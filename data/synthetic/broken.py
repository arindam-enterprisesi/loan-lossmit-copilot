"""The deliberately broken uploads: locked, corrupt, unsupported, duplicate and degraded 'scans'.

All of them are made from the clean documents, and all are reproducible (fixed seeds and
JPEG settings), so the same scenario always produces the same bytes.
"""

from __future__ import annotations

import csv
import io
import random

import pypdfium2 as pdfium
from PIL import Image, ImageChops, ImageEnhance, ImageFilter

from synthetic.layout import build_pdf, image_pdf
from synthetic.renderers import render_pages
from synthetic.schema import BankStatementDoc, Document, running_balances

LOCK_PASSWORD = "demo-locked"  # not a secret: synthetic demo data, and it is in the manifest


def locked_pdf(doc: Document) -> bytes:
    """The document as a PDF that needs a password to open."""
    return build_pdf(render_pages(doc), title=doc.file_name, password=LOCK_PASSWORD)


def corrupt_pdf(clean: bytes) -> bytes:
    """Keep the header and the first part of the file; the page tree and trailer are lost."""
    broken = clean[: int(len(clean) * 0.4)]
    # Cut mid-object so a repair pass cannot find a complete structure.
    return broken[: broken.rfind(b"endobj")] + b"\n%% truncated in transfer"


def csv_export(doc: BankStatementDoc) -> bytes:
    """A transaction export: a file type the upload does not accept (PDF, PNG and JPEG only)."""
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(["date", "description", "amount", "balance"])
    for txn, balance in zip(doc.facts.transactions, running_balances(doc.facts), strict=True):
        writer.writerow(
            [txn.date.isoformat(), txn.description, f"{txn.amount:.2f}", f"{balance:.2f}"]
        )
    return out.getvalue().encode("utf-8")


def _page_images(pdf_bytes: bytes, scale: float) -> list[Image.Image]:
    document = pdfium.PdfDocument(pdf_bytes)
    try:
        return [document[i].render(scale=scale).to_pil() for i in range(len(document))]
    finally:
        document.close()


def _degrade(
    image: Image.Image,
    *,
    angle: float,
    blur: float,
    contrast: float,
    brightness: float,
    noise: int,
    seed: int,
    quality: int,
) -> bytes:
    """Make a clean page look scanned or photographed, and return it as JPEG bytes."""
    grey = image.convert("L")
    grey = grey.rotate(angle, resample=Image.Resampling.BICUBIC, fillcolor=228)
    grey = ImageEnhance.Contrast(grey).enhance(contrast)
    grey = ImageEnhance.Brightness(grey).enhance(brightness)
    if blur:
        grey = grey.filter(ImageFilter.GaussianBlur(blur))
    grain = Image.frombytes(
        "L", grey.size, random.Random(seed).randbytes(grey.size[0] * grey.size[1])
    )
    grain = grain.point(lambda v: v * 2 * noise // 255)
    grey = ImageChops.add(grey, grain, 1.0, -noise)
    out = io.BytesIO()
    grey.save(out, format="JPEG", quality=quality)
    return out.getvalue()


def photographed_pdf(clean_pdf: bytes, *, title: str) -> bytes:
    """A phone photo of a two-page stub, as an image-only PDF: page 2 is much blurrier."""
    first, second = _page_images(clean_pdf, scale=1.5)[:2]
    pages = [
        _degrade(
            first, angle=1.2, blur=0.8, contrast=0.85, brightness=0.93, noise=14, seed=1, quality=55
        ),
        _degrade(
            second,
            angle=-0.9,
            blur=2.8,
            contrast=0.75,
            brightness=0.9,
            noise=18,
            seed=2,
            quality=45,
        ),
    ]
    return image_pdf(pages, title=title)


def scanned_jpeg(clean_pdf: bytes) -> bytes:
    """A poor flatbed scan of a one-page document, as a JPEG."""
    page = _page_images(clean_pdf, scale=1.3)[0]
    return _degrade(
        page, angle=1.8, blur=1.1, contrast=0.8, brightness=0.88, noise=20, seed=3, quality=38
    )
