"""The broken uploads: locked, corrupt, unsupported, duplicate and degraded scans."""

from __future__ import annotations

import csv
import hashlib
import io

import pdfplumber
import pypdfium2 as pdfium
import pytest
from PIL import Image, ImageFilter

from tests.data.conftest import Rendered
from tests.data.helpers import D, read_pages

ACCEPTED_UPLOADS = {".pdf", ".png", ".jpg", ".jpeg"}  # contracts/openapi.yaml uploadDocuments


def detail(image: Image.Image) -> int:
    """How strong the strongest 0.5% of edges are, after a light blur that ignores film grain.

    Text and rules give strong edges; a blurred page does not. Compare a scan with the clean
    page it came from, at the scan's native resolution, so page content cancels out.
    """
    edges = image.convert("L").filter(ImageFilter.GaussianBlur(1.2)).filter(ImageFilter.FIND_EDGES)
    histogram, total, seen = edges.histogram(), edges.width * edges.height, 0
    for value, count in enumerate(histogram):
        seen += count
        if seen >= total * 0.995:
            return value
    return 255


def render(path, index: int, scale: float) -> Image.Image:
    document = pdfium.PdfDocument(str(path))
    try:
        return document[index].render(scale=scale).to_pil()
    finally:
        document.close()


def test_the_broken_set_is_six_files_with_a_reason_each(rendered: Rendered) -> None:
    broken = [f for f in rendered.manifest["files"] if f["role"] == "broken"]
    assert sorted(f["path"] for f in broken) == [
        "broken/bank_transactions_export.csv",
        "broken/corrupt_bank_statement.pdf",
        "broken/duplicate_pay_stub.pdf",
        "broken/locked_w2_2025.pdf",
        "broken/scan_mortgage_statement.jpg",
        "broken/scan_pay_stub_photo.pdf",
    ]
    assert sorted(f["kind"] for f in broken) == [
        "corrupt",
        "duplicate",
        "password_protected",
        "scan",
        "scan",
        "unsupported_type",
    ]
    assert all(f["expected_behaviour"] for f in broken)


def test_locked_pdf_needs_its_password(rendered: Rendered) -> None:
    path = rendered.path("broken/locked_w2_2025.pdf")
    with pytest.raises(pdfium.PdfiumError, match="password"):
        pdfium.PdfDocument(str(path))
    with pytest.raises(Exception):  # noqa: B017 (pdfminer wraps it in its own error)
        pdfplumber.open(str(path)).pages[0].extract_text()
    password = rendered.entry("broken/locked_w2_2025.pdf")["password"]
    pages = read_pages(path, password=password)
    assert "Form W-2" in pages[0][0] and "74,298.60" in "\n".join(pages[0])
    assert len(pdfium.PdfDocument(str(path), password=password)) == 1


def test_corrupt_pdf_cannot_be_read(rendered: Rendered) -> None:
    path = rendered.path("broken/corrupt_bank_statement.pdf")
    data = path.read_bytes()
    assert data.startswith(b"%PDF-")  # it looks like a PDF but is truncated
    clean = rendered.path("daniel_reyes/bank_statement_2026-08.pdf").read_bytes()
    assert len(data) < len(clean) * 0.5
    with pytest.raises(pdfium.PdfiumError):
        pdfium.PdfDocument(str(path))
    with pytest.raises(Exception):  # noqa: B017
        pdfplumber.open(str(path))


def test_unsupported_type_is_a_csv_of_the_september_transactions(
    rendered: Rendered, daniel
) -> None:
    path = rendered.path("broken/bank_transactions_export.csv")
    assert path.suffix not in ACCEPTED_UPLOADS
    rows = list(csv.reader(io.StringIO(path.read_text(encoding="utf-8"))))
    assert rows[0] == ["date", "description", "amount", "balance"]
    statement = daniel.document("bank_statement_2026-09").facts
    assert len(rows) - 1 == len(statement.transactions)
    assert D(rows[-1][3]) == statement.closing_balance == D("9226.32")
    assert rows[next(i for i, r in enumerate(rows) if r[0] == "2026-09-22" and r[2] == "2000.00")][
        :3
    ] == ["2026-09-22", "ZELLE FROM PATRICIA OWENS REF 8841", "2000.00"]


def test_duplicate_is_byte_identical_under_a_different_name(rendered: Rendered) -> None:
    original = rendered.path("daniel_reyes/pay_stub_2026-09-27.pdf")
    duplicate = rendered.path("broken/duplicate_pay_stub.pdf")
    assert original.name != duplicate.name
    assert (
        hashlib.sha256(original.read_bytes()).hexdigest()
        == hashlib.sha256(duplicate.read_bytes()).hexdigest()
    )
    a, b = (
        rendered.entry(p)
        for p in ("daniel_reyes/pay_stub_2026-09-27.pdf", "broken/duplicate_pay_stub.pdf")
    )
    assert a["sha256"] == b["sha256"]


def test_photographed_stub_is_image_only_with_a_blurrier_second_page(rendered: Rendered) -> None:
    path = rendered.path("broken/scan_pay_stub_photo.pdf")
    with pdfplumber.open(str(path)) as pdf:
        assert len(pdf.pages) == 2  # FSD T-04: a photographed pay stub with a blurred second page
        assert [(page.extract_text() or "").strip() for page in pdf.pages] == ["", ""]
        assert [len(page.images) for page in pdf.pages] == [1, 1]
    clean = rendered.path("daniel_reyes/pay_stub_2026-09-27.pdf")
    kept = [detail(render(path, i, 1.5)) / detail(render(clean, i, 1.5)) for i in range(2)]
    assert kept[0] > 0.3  # page 1 is degraded but still legible
    assert kept[1] < kept[0] * 0.6  # page 2 lost far more detail


def test_scanned_statement_is_a_poor_grey_jpeg(rendered: Rendered) -> None:
    path = rendered.path("broken/scan_mortgage_statement.jpg")
    image = Image.open(path)
    assert image.format == "JPEG" and image.mode == "L"
    assert image.size[0] < 900  # low resolution
    reference = render(rendered.path("angela_whitfield/mortgage_statement_2026-10.pdf"), 0, 1.3)
    assert image.size == reference.size
    assert detail(image) < detail(reference) * 0.8
    assert rendered.entry("broken/scan_mortgage_statement.jpg")["page_count"] == 1
