"""Tesseract OCR for pages with no text layer (``app.services.ocr``).

The helpers that turn Tesseract's output into numbered lines with boxes and confidences, and the
image preparation (scale, denoise, straighten, threshold), are plain functions tested here with no
Tesseract program. Tests that run the real engine are skipped when ``tesseract`` is not installed
(CI installs it; so does the worker image).
"""

from __future__ import annotations

import io
import shutil
from typing import Any

import cv2
import numpy as np
import pytesseract
import pytest
from PIL import Image, ImageDraw, ImageFont

from app.db.enums import ReadBy
from app.services import ocr
from app.services.ingestion import BBox, NotImplementedOcr
from app.services.ingestion_config import OcrSettings, get_ingestion_config

SETTINGS = get_ingestion_config().ocr
NEEDS_TESSERACT = pytest.mark.skipif(
    shutil.which("tesseract") is None, reason="the tesseract program is not installed"
)


# --- what tesseract returns -------------------------------------------------------------------


# (level, block, paragraph, line, word, left, top, width, height, conf, text)
Row = tuple[int, int, int, int, int, int, int, int, int, float, str]
COLUMNS = [
    "level",
    "block_num",
    "par_num",
    "line_num",
    "word_num",
    "left",
    "top",
    "width",
    "height",
    "conf",
    "text",
]


def data(*rows: Row) -> dict[str, list[Any]]:
    """pytesseract's ``image_to_data`` output. Level 5 is a word; other levels have conf -1."""
    out: dict[str, list[Any]] = {name: [] for name in COLUMNS}
    for row in rows:
        for name, value in zip(COLUMNS, row, strict=True):
            out[name].append(value)
    return out


def word(text: str, left: int, top: int, *, conf: float = 90, line: int = 1, block: int = 1) -> Row:
    return (5, block, 1, line, 1, left, top, 100, 30, conf, text)


def test_only_real_words_are_kept() -> None:
    rows = data(
        (1, 0, 0, 0, 0, 0, 0, 1000, 2000, -1, ""),  # the page
        (4, 1, 1, 1, 0, 10, 10, 300, 30, -1, ""),  # a line
        word("Net", 10, 10),
        word("   ", 120, 10),  # blank
        word("pay", 230, 10, conf=-1),  # no confidence: not a word
        word("2,033.61", 340, 10),
    )

    assert [w.text for w in ocr.words_from_data(rows)] == ["Net", "2,033.61"]


def test_the_words_of_a_line_join_in_reading_order_and_the_box_is_their_union() -> None:
    rows = data(word("pay", 130, 12), word("Net", 10, 10), word("2,033.61", 250, 8))

    [line] = ocr.lines_from_words(ocr.words_from_data(rows))

    assert line.text == "Net pay 2,033.61"
    assert (line.x0, line.y0, line.x1, line.y1) == (10, 8, 350, 42)


def test_a_lines_confidence_is_its_mean_word_confidence_as_a_fraction() -> None:
    rows = data(word("Net", 10, 10, conf=90), word("pay", 130, 10, conf=70))

    [line] = ocr.lines_from_words(ocr.words_from_data(rows))

    assert line.confidence == pytest.approx(0.80)  # lines.confidence is 0 to 1


def test_lines_are_grouped_by_block_paragraph_and_line_and_come_out_top_to_bottom() -> None:
    rows = data(
        word("Gross", 10, 200, line=2),
        word("3,070.50", 130, 200, line=2),
        word("Pay", 10, 50, line=1, block=2),  # listed later but higher up on the page
        word("stub", 130, 50, line=1, block=2),
    )

    lines = ocr.lines_from_words(ocr.words_from_data(rows))

    assert [ln.text for ln in lines] == ["Pay stub", "Gross 3,070.50"]


def test_a_line_whose_words_are_all_unreadable_is_dropped() -> None:
    rows = data(word("   ", 10, 10), word("x", 130, 10, conf=-1))

    assert ocr.lines_from_words(ocr.words_from_data(rows)) == []


# --- boxes as fractions of the page ------------------------------------------------------------


def test_boxes_are_fractions_of_the_image_with_the_origin_top_left() -> None:
    line = ocr.PixelLine("Net pay", 100, 200, 300, 260, 0.9)

    [out] = ocr.to_ocr_lines([line], size=(1000, 2000))

    assert out.text == "Net pay" and out.confidence == pytest.approx(0.9)
    assert out.bbox == BBox(0.1, 0.1, 0.3, 0.13)


def test_a_box_outside_the_image_is_clamped_to_it() -> None:
    line = ocr.PixelLine("edge", -5, -5, 1010, 2010, 0.9)

    [out] = ocr.to_ocr_lines([line], size=(1000, 2000))

    assert out.bbox == BBox(0.0, 0.0, 1.0, 1.0)


def test_boxes_are_mapped_back_through_the_straightening_turn() -> None:
    width, height = 1000, 2000
    turn = cv2.getRotationMatrix2D((width / 2, height / 2), 3.0, 1.0)
    # A box on the original page, turned the way the page was turned, as OCR would see it.
    original = np.array([[200, 400], [600, 400], [600, 440], [200, 440]], dtype=np.float64)
    seen = cv2.transform(original[None, :, :], turn)[0]
    line = ocr.PixelLine("x", *seen.min(axis=0), *seen.max(axis=0), 0.9)

    [out] = ocr.to_ocr_lines([line], size=(width, height), matrix=turn)

    # Mapped back, the box contains the original (it is the bounds of a slightly turned box).
    assert out.bbox.x0 <= 200 / width + 1e-6 and out.bbox.x1 >= 600 / width - 1e-6
    assert out.bbox.y0 <= 400 / height + 1e-6 and out.bbox.y1 >= 440 / height - 1e-6
    assert out.bbox.x0 > 0.15 and out.bbox.x1 < 0.65  # and stays close to it


def test_a_page_that_was_not_turned_keeps_its_boxes_exactly() -> None:
    identity = np.array([[1, 0, 0], [0, 1, 0]], dtype=np.float64)
    line = ocr.PixelLine("x", 100, 200, 300, 260, 0.9)

    assert ocr.to_ocr_lines([line], (1000, 2000), identity) == ocr.to_ocr_lines(
        [line], (1000, 2000)
    )


# --- preparing the image ----------------------------------------------------------------------


def text_page(
    lines: list[str], *, tilt: float = 0.0, size: tuple[int, int] = (1650, 2200)
) -> Image.Image:
    """Black text on white, like a printed page, optionally tilted (degrees, counter-clockwise)."""
    image = Image.new("L", size, 255)
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default(size=44)
    for number, text in enumerate(lines):
        draw.text((150, 200 + number * 110), text, fill=0, font=font)
    return image.rotate(tilt, resample=Image.Resampling.BICUBIC, fillcolor=255) if tilt else image


def as_png(image: Image.Image) -> bytes:
    out = io.BytesIO()
    image.save(out, format="PNG")
    return out.getvalue()


LINES = ["Pay stub 2026-09-27", "Gross pay 3,070.50", "Net pay 2,033.61", "Employer Cedar Valley"]


@pytest.mark.parametrize("tilt", [3.0, -2.0, 6.0])
def test_a_tilted_page_is_straightened(tilt: float) -> None:
    gray = np.array(text_page(LINES, tilt=tilt))

    angle = ocr.estimate_skew(gray, max_degrees=10)

    turned = cv2.warpAffine(
        gray,
        cv2.getRotationMatrix2D((gray.shape[1] / 2, gray.shape[0] / 2), angle, 1.0),
        (gray.shape[1], gray.shape[0]),
        borderValue=255,
    )
    assert abs(angle + tilt) <= 1.0  # undoes the tilt (OpenCV and Pillow agree on the direction)
    assert abs(ocr.estimate_skew(turned, max_degrees=10)) <= 0.5


def test_an_upright_page_is_left_alone() -> None:
    assert ocr.estimate_skew(np.array(text_page(LINES)), max_degrees=10) == 0.0


def test_a_blank_page_is_left_alone() -> None:
    assert ocr.estimate_skew(np.full((800, 600), 255, dtype=np.uint8), max_degrees=10) == 0.0


def test_the_search_for_a_tilt_stops_at_the_configured_maximum() -> None:
    gray = np.array(text_page(LINES, tilt=14.0))

    assert abs(ocr.estimate_skew(gray, max_degrees=5)) <= 5.0


def test_preparing_a_page_scales_it_and_leaves_pure_black_and_white() -> None:
    gray = np.array(text_page(LINES))

    prepared = ocr.preprocess(gray, SETTINGS, scale=1.5)

    assert prepared.image.shape == (int(2200 * 1.5), int(1650 * 1.5))
    assert set(np.unique(prepared.image)) <= {0, 255}
    assert (prepared.image == 0).any()  # the text is still there


def test_a_page_that_needs_no_scaling_keeps_its_size() -> None:
    gray = np.array(text_page(LINES, size=(800, 1000)))

    assert ocr.preprocess(gray, SETTINGS, scale=1.0).image.shape == (1000, 800)


# --- the adapter, without the program -----------------------------------------------------------


def test_a_missing_tesseract_program_is_unavailable_not_a_crash(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def gone(*_: Any, **__: Any) -> Any:
        raise pytesseract.TesseractNotFoundError()

    monkeypatch.setattr(ocr.pytesseract, "image_to_data", gone)
    adapter = ocr.TesseractOcr(SETTINGS, scale=1.0)

    with pytest.raises(NotImplementedError, match="not installed"):
        adapter.read_page(as_png(text_page(LINES, size=(300, 300))), 300, 300)


def test_an_image_that_cannot_be_decoded_has_no_lines() -> None:
    assert ocr.TesseractOcr(SETTINGS, scale=1.0).read_page(b"not an image", 10, 10) == []


def test_the_adapter_records_pages_as_read_by_tesseract() -> None:
    assert ocr.TesseractOcr(SETTINGS, scale=1.0).read_by is ReadBy.TESSERACT


def test_the_adapter_turns_tesseracts_words_into_lines_with_boxes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows = data(word("Net", 100, 300), word("pay", 230, 300), word("2,033.61", 340, 300, conf=80))
    monkeypatch.setattr(ocr.pytesseract, "image_to_data", lambda *_, **__: rows)
    gray = text_page(LINES, size=(1000, 1400))

    [line] = ocr.TesseractOcr(SETTINGS, scale=1.0).read_page(as_png(gray), 1000, 1400)

    assert line.text == "Net pay 2,033.61"
    assert line.confidence == pytest.approx((0.9 + 0.9 + 0.8) / 3)
    assert 0 <= line.bbox.x0 < line.bbox.x1 <= 1 and 0 <= line.bbox.y0 < line.bbox.y1 <= 1


# --- choosing the engine --------------------------------------------------------------------------


def test_engine_none_never_uses_tesseract() -> None:
    assert isinstance(ocr.default_ocr(get_ingestion_config(), "none"), NotImplementedOcr)


def test_without_the_program_the_default_is_the_unavailable_stub(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(ocr.shutil, "which", lambda _: None)

    assert isinstance(ocr.default_ocr(get_ingestion_config(), "tesseract"), NotImplementedOcr)


def test_with_the_program_the_default_is_tesseract_at_the_configured_scale(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(ocr.shutil, "which", lambda _: "/usr/bin/tesseract")
    config = get_ingestion_config()

    adapter = ocr.default_ocr(config, "tesseract")

    assert isinstance(adapter, ocr.TesseractOcr)
    assert adapter.scale == config.ocr.target_dpi / config.render_dpi == 1.5


# --- the settings ---------------------------------------------------------------------------------


def test_the_ocr_settings_are_in_the_labelled_versioned_config() -> None:
    config = get_ingestion_config()

    assert config.label == "illustrative" and config.version
    assert (config.ocr.target_dpi, config.ocr.tesseract_config) == (300, "--oem 1 --psm 6")
    assert config.ocr_scale == 1.5


@pytest.mark.parametrize("field", ["denoise_kernel", "threshold_block_size"])
def test_the_image_windows_must_be_odd(field: str) -> None:
    with pytest.raises(ValueError, match="odd"):
        OcrSettings.model_validate({**SETTINGS.model_dump(), field: 4})


# --- the real engine (skipped without the program) ---------------------------------------------


@NEEDS_TESSERACT
def test_it_reads_a_printed_page_into_lines_with_boxes_and_confidence() -> None:
    adapter = ocr.TesseractOcr(SETTINGS, scale=1.0)

    lines = adapter.read_page(as_png(text_page(LINES)), 1650, 2200)

    text = "\n".join(line.text for line in lines)
    for expected in ("2026-09-27", "3,070.50", "2,033.61", "Cedar Valley"):
        assert expected in text
    assert [ln.bbox.y0 for ln in lines] == sorted(ln.bbox.y0 for ln in lines)  # top to bottom
    for line in lines:
        assert 0 < line.confidence <= 1  # type: ignore[operator]
        assert 0 <= line.bbox.x0 < line.bbox.x1 <= 1 and 0 <= line.bbox.y0 < line.bbox.y1 <= 1
    net = next(ln for ln in lines if "2,033.61" in ln.text)
    assert 0.08 < net.bbox.x0 < 0.12  # drawn at x = 150 of 1650
    assert 0.17 < net.bbox.y0 < 0.23  # third line: y = 420 of 2200


@NEEDS_TESSERACT
def test_a_tilted_page_is_read_and_its_boxes_stay_on_the_page_image() -> None:
    adapter = ocr.TesseractOcr(SETTINGS, scale=1.5)

    lines = adapter.read_page(as_png(text_page(LINES, tilt=3.0)), 1650, 2200)

    text = "\n".join(line.text for line in lines)
    assert "3,070.50" in text and "2,033.61" in text
    for line in lines:
        assert 0 <= line.bbox.x0 < line.bbox.x1 <= 1 and 0 <= line.bbox.y0 < line.bbox.y1 <= 1


@NEEDS_TESSERACT
def test_the_adapter_reports_its_version() -> None:
    version = ocr.TesseractOcr(SETTINGS, scale=1.0).version

    assert version[0].isdigit()
