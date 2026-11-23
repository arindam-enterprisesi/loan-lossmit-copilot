"""OCR with Tesseract for pages that have no text layer (CPS-08, FSD error DI-E301).

``app.services.ingestion`` sends a page here when its text layer is missing or too short (and for
every PNG or JPEG upload). The page image is prepared (scaled to about 300 dpi, lightly denoised,
straightened, thresholded), Tesseract reads it, and its words become the same numbered lines the
text layer produces: a text, a box as fractions of the page image (origin top left) and a confidence
from 0 to 1. Everything after the Tesseract call is a plain function, tested without the program.

A line read below ``min_line_confidence`` (``validation.yaml``) lowers the certainty of the fields
cited from it, so a reviewer sees them first (FSD 4.4). That rule already exists and is not repeated
here. Document text is data and is never logged.
"""

from __future__ import annotations

import logging
import shutil
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import cv2
import numpy as np
import numpy.typing as npt
import pytesseract

from app.db.enums import ReadBy
from app.services.ingestion import BBox, NotImplementedOcr, OcrAdapter, OcrLine
from app.services.ingestion_config import IngestionConfig, OcrSettings

logger = logging.getLogger(__name__)

# OpenCV returns arrays whose dtype its stubs only know loosely, so the aliases do not narrow it.
Image = npt.NDArray[Any]
Matrix = npt.NDArray[Any]

SKEW_STEP_DEGREES = 0.5  # how finely the tilt is searched; Tesseract copes with less than this
SKEW_SEARCH_PIXELS = 1000  # the tilt is found on a copy no larger than this on its longest side
MIN_SKEW_DEGREES = 0.25  # a tilt smaller than this is noise: the page is left as it is


# --- Tesseract's words, as lines ---------------------------------------------------------------


@dataclass(frozen=True)
class Word:
    text: str
    left: int
    top: int
    width: int
    height: int
    confidence: float  # 0 to 100, as Tesseract reports it
    group: tuple[int, int, int]  # block, paragraph and line number: words of one line share it


@dataclass(frozen=True)
class PixelLine:
    """A line in pixels of the image Tesseract read, with its confidence as a fraction (0 to 1)."""

    text: str
    x0: float
    y0: float
    x1: float
    y1: float
    confidence: float


def words_from_data(data: dict[str, list[Any]]) -> list[Word]:
    """The words in ``pytesseract.image_to_data`` output. Blocks, lines and blanks are skipped."""
    words: list[Word] = []
    for index, text in enumerate(data["text"]):
        confidence = float(data["conf"][index])
        if confidence < 0 or not str(text).strip():
            continue  # a layout row (page, block, line), or nothing readable
        words.append(
            Word(
                text=str(text).strip(),
                left=int(data["left"][index]),
                top=int(data["top"][index]),
                width=int(data["width"][index]),
                height=int(data["height"][index]),
                confidence=confidence,
                group=(
                    int(data["block_num"][index]),
                    int(data["par_num"][index]),
                    int(data["line_num"][index]),
                ),
            )
        )
    return words


def lines_from_words(words: Sequence[Word]) -> list[PixelLine]:
    """Group words into lines, left to right, and the lines top to bottom.

    A line's box is the union of its words' boxes; its confidence is their mean, as a fraction.
    """
    by_line: dict[tuple[int, int, int], list[Word]] = defaultdict(list)
    for word in words:
        by_line[word.group].append(word)
    lines: list[PixelLine] = []
    for members in by_line.values():
        members = sorted(members, key=lambda w: w.left)
        lines.append(
            PixelLine(
                text=" ".join(w.text for w in members),
                x0=min(w.left for w in members),
                y0=min(w.top for w in members),
                x1=max(w.left + w.width for w in members),
                y1=max(w.top + w.height for w in members),
                confidence=sum(w.confidence for w in members) / len(members) / 100,
            )
        )
    return sorted(lines, key=lambda ln: (ln.y0, ln.x0))


def _fraction(value: float, size: int) -> float:
    return min(max(value / size, 0.0), 1.0)


def to_ocr_lines(
    lines: Sequence[PixelLine], size: tuple[int, int], matrix: Matrix | None = None
) -> list[OcrLine]:
    """Lines as ``OcrLine``: boxes as fractions of the page image, back in its original orientation.

    ``size`` is the (width, height) of the image Tesseract read. ``matrix`` is the 2x3 turn that
    straightened it; a box found on the straightened page is turned back, and the bounds of the
    turned box are kept, so the box lands on the page image the reviewer sees.
    """
    width, height = size
    inverse = cv2.invertAffineTransform(matrix) if matrix is not None else None
    out: list[OcrLine] = []
    for line in lines:
        corners = np.array(
            [[line.x0, line.y0], [line.x1, line.y0], [line.x1, line.y1], [line.x0, line.y1]],
            dtype=np.float64,
        )
        if inverse is not None:
            corners = cv2.transform(corners[None, :, :], inverse)[0]
        x0, y0 = corners.min(axis=0)
        x1, y1 = corners.max(axis=0)
        box = BBox(
            _fraction(float(x0), width),
            _fraction(float(y0), height),
            _fraction(float(x1), width),
            _fraction(float(y1), height),
        )
        out.append(OcrLine(line.text, box, line.confidence))
    return out


# --- preparing the image -----------------------------------------------------------------------


def _turn(image: Image, angle: float) -> tuple[Image, Matrix]:
    """Turn ``image`` by ``angle`` degrees about its centre (positive is counter-clockwise)."""
    height, width = image.shape[:2]
    matrix = cv2.getRotationMatrix2D((width / 2, height / 2), angle, 1.0)
    turned = cv2.warpAffine(
        image, matrix, (width, height), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE
    )
    return turned, matrix


def estimate_skew(gray: Image, max_degrees: float, step: float = SKEW_STEP_DEGREES) -> float:
    """The angle, in degrees, to turn a page by to make its text lines horizontal.

    Tries every angle within ``max_degrees`` either way on a small black-and-white copy and keeps
    the one whose rows are most unevenly filled (text lines make crisp ink-and-gap stripes only
    when the page is level). Returns 0.0 for a page that is level, blank or tilted by less than
    a quarter of a degree.
    """
    longest = max(gray.shape[:2])
    if longest > SKEW_SEARCH_PIXELS:
        factor = SKEW_SEARCH_PIXELS / longest
        gray = cv2.resize(gray, None, fx=factor, fy=factor, interpolation=cv2.INTER_AREA)
    _, ink = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU)
    if not ink.any():
        return 0.0
    steps = int(max_degrees / step)
    # Nearest to level first, so a tie is decided in favour of leaving the page alone.
    candidates = sorted(
        (i * step for i in range(-steps, steps + 1)), key=lambda angle: (abs(angle), angle)
    )
    best_angle, best_score = 0.0, -1.0
    for angle in candidates:
        turned, _ = _turn(ink, angle)
        score = float(np.var(turned.sum(axis=1, dtype=np.float64)))
        if score > best_score * 1.0001:  # strictly better, beyond rounding
            best_angle, best_score = angle, score
    return best_angle if abs(best_angle) >= MIN_SKEW_DEGREES else 0.0


@dataclass(frozen=True)
class Prepared:
    image: Image  # black and white, what Tesseract reads
    matrix: Matrix  # the 2x3 turn that straightened it (the identity when it was level)


def preprocess(gray: Image, settings: OcrSettings, scale: float) -> Prepared:
    """Scale, lightly denoise, straighten and threshold a grey page image."""
    scaled = (
        gray
        if scale == 1
        else cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    )
    denoised = cv2.medianBlur(scaled, settings.denoise_kernel)
    angle = estimate_skew(denoised, settings.max_skew_degrees)
    level, matrix = _turn(denoised, angle)
    binary = cv2.adaptiveThreshold(
        level,
        255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY,
        settings.threshold_block_size,
        settings.threshold_c,
    )
    return Prepared(binary, matrix)


# --- the engine --------------------------------------------------------------------------------


class TesseractOcr:
    """Reads a page image with Tesseract (LSTM engine, one block of text per page)."""

    read_by = ReadBy.TESSERACT

    def __init__(self, settings: OcrSettings, scale: float) -> None:
        self.settings = settings
        self.scale = scale
        self._version: str | None = None

    @property
    def version(self) -> str:
        """The Tesseract version, recorded with the pages it read."""
        if self._version is None:
            try:
                self._version = str(pytesseract.get_tesseract_version())
            except pytesseract.TesseractNotFoundError:
                return "unknown"
        return self._version

    def read_page(self, png: bytes, width: int, height: int) -> list[OcrLine]:
        gray = cv2.imdecode(np.frombuffer(png, dtype=np.uint8), cv2.IMREAD_GRAYSCALE)
        if gray is None:
            return []
        prepared = preprocess(gray, self.settings, self.scale)
        try:
            data = pytesseract.image_to_data(
                prepared.image,
                lang=self.settings.language,
                config=self.settings.tesseract_config,
                output_type=pytesseract.Output.DICT,
            )
        except pytesseract.TesseractNotFoundError as exc:
            raise NotImplementedError("the tesseract program is not installed") from exc
        rows, columns = prepared.image.shape[:2]
        return to_ocr_lines(
            lines_from_words(words_from_data(data)), (columns, rows), prepared.matrix
        )


def default_ocr(config: IngestionConfig, engine: str) -> OcrAdapter:
    """The OCR the worker uses: Tesseract when asked for and installed, otherwise the stub.

    The stub leaves image-only pages unread, and they fail with the DI-E301 flag and a reason.
    """
    if engine != "tesseract":
        return NotImplementedOcr()
    if shutil.which("tesseract") is None:
        logger.warning("OCR_ENGINE=tesseract but the tesseract program was not found")
        return NotImplementedOcr()
    return TesseractOcr(config.ocr, config.ocr_scale)
