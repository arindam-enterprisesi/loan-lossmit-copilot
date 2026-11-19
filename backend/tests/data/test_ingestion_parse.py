"""Reading the generated documents: pages, numbered lines, boxes and the broken set (no database).

The nth line of page p is the line ``p<p>-L<n>`` of the Feature Design, so the lines read from a
PDF must be exactly the text rows the generator drew, in order.
"""

from __future__ import annotations

import io

import pytest
from PIL import Image

from app.services.ingestion import (
    NotImplementedOcr,
    ParsedDocument,
    PasswordProtectedError,
    UnreadableFileError,
    parse_file,
    parse_image,
    parse_pdf,
)
from tests.conftest import Rendered
from tests.data.helpers import read_pages

DPI = 200
LETTER_AT_200_DPI = (1700, 2200)  # 612 x 792 points


def clean_pdfs(rendered: Rendered) -> list[dict[str, object]]:
    return [
        f
        for f in rendered.manifest["files"]
        if f["role"] in {"case", "withheld"} and str(f["path"]).endswith(".pdf")
    ]


@pytest.fixture(scope="module")
def parsed(rendered: Rendered) -> dict[str, ParsedDocument]:
    """Every clean generated PDF, read once."""
    return {
        str(f["path"]): parse_pdf(rendered.read(str(f["path"])), DPI) for f in clean_pdfs(rendered)
    }


def test_there_are_seventeen_clean_pdfs(rendered: Rendered) -> None:
    assert len(clean_pdfs(rendered)) == 17  # 15 in the cases and 2 withheld


def test_page_counts_match_the_manifest(
    rendered: Rendered, parsed: dict[str, ParsedDocument]
) -> None:
    for f in clean_pdfs(rendered):
        assert len(parsed[str(f["path"])].pages) == f["page_count"], f["path"]


def test_lines_are_the_rows_the_generator_drew_in_order(
    rendered: Rendered, parsed: dict[str, ParsedDocument]
) -> None:
    for f in clean_pdfs(rendered):
        path = str(f["path"])
        expected = read_pages(rendered.path(path))
        got = [[line.text for line in page.lines] for page in parsed[path].pages]
        assert got == expected, path
        assert all(
            page.read_by is not None and page.read_by.value == "text_layer"
            for page in parsed[path].pages
        )


def test_net_pay_is_on_line_31_of_the_stub(parsed: dict[str, ParsedDocument]) -> None:
    stub = parsed["daniel_reyes/pay_stub_2026-09-27.pdf"]
    line_31 = stub.pages[0].lines[31 - 1]
    assert "2,083.61" in line_31.text  # the printed value; the true net pay is 2,033.61


def test_hardship_quotes_are_on_lines_6_and_14(
    rendered: Rendered, parsed: dict[str, ParsedDocument]
) -> None:
    [letter] = [str(f["path"]) for f in clean_pdfs(rendered) if f["doc_type"] == "hardship_letter"]
    lines = parsed[letter].pages[0].lines
    assert "cut my hours from 40 to 30 a week in July" in lines[6 - 1].text
    assert "I want to keep my home" in lines[14 - 1].text


def test_august_statement_has_two_pages_but_a_footer_that_says_three(
    parsed: dict[str, ParsedDocument],
) -> None:
    statement = parsed["daniel_reyes/bank_statement_2026-08.pdf"]
    assert len(statement.pages) == 2
    assert any("Page 1 of 3" in line.text for line in statement.pages[0].lines)


def test_boxes_are_fractions_of_the_page_and_run_top_to_bottom(
    parsed: dict[str, ParsedDocument],
) -> None:
    for path, document in parsed.items():
        for page in document.pages:
            tops = [line.bbox.y0 for line in page.lines]
            assert tops == sorted(tops), (path, page.page_no)
            for line in page.lines:
                b = line.bbox
                assert 0 <= b.x0 < b.x1 <= 1 and 0 <= b.y0 < b.y1 <= 1, (path, line.text)
                assert line.confidence is None  # text-layer lines have no OCR confidence


def test_line_box_matches_where_the_text_is_drawn(parsed: dict[str, ParsedDocument]) -> None:
    # The generator starts the first row 54 pt from the left and about 50 pt from the top.
    first = parsed["daniel_reyes/pay_stub_2026-09-27.pdf"].pages[0].lines[0].bbox
    assert first.x0 == pytest.approx(54 / 612, abs=0.002)
    assert first.y0 == pytest.approx(50.5 / 792, abs=0.002)


def test_pages_are_rendered_at_200_dpi(parsed: dict[str, ParsedDocument]) -> None:
    for document in parsed.values():
        for page in document.pages:
            assert (page.width, page.height) == LETTER_AT_200_DPI
            with Image.open(io.BytesIO(page.png)) as image:
                assert image.format == "PNG" and image.size == LETTER_AT_200_DPI


def test_dpi_comes_from_the_argument(rendered: Rendered) -> None:
    data = rendered.read("daniel_reyes/pay_stub_2026-09-27.pdf")
    page = parse_pdf(data, 100).pages[0]
    assert (page.width, page.height) == (850, 1100)


# --- the broken set -------------------------------------------------------------------------


def test_a_password_protected_pdf_is_recognised(rendered: Rendered) -> None:
    with pytest.raises(PasswordProtectedError) as info:
        parse_pdf(rendered.read("broken/locked_w2_2025.pdf"), DPI)
    assert info.value.code == "password_protected"
    assert info.value.reason == "the file is password protected"


@pytest.mark.parametrize(
    "data",
    [
        pytest.param(None, id="truncated-pdf"),
        pytest.param(b"%PDF-1.4\nnot really a pdf", id="header-only"),
        pytest.param(b"", id="empty"),
    ],
)
def test_a_corrupt_pdf_is_unreadable(rendered: Rendered, data: bytes | None) -> None:
    if data is None:
        data = rendered.read("broken/corrupt_bank_statement.pdf")
    with pytest.raises(UnreadableFileError) as info:
        parse_pdf(data, DPI)
    assert (info.value.code, info.value.reason) == ("unreadable", "the file cannot be read")


def test_a_photographed_pdf_has_page_images_but_no_text_layer(rendered: Rendered) -> None:
    document = parse_pdf(rendered.read("broken/scan_pay_stub_photo.pdf"), DPI)
    assert len(document.pages) == 2
    for page in document.pages:
        assert page.lines == [] and page.read_by is None
        assert (page.width, page.height) == LETTER_AT_200_DPI


def test_a_jpeg_scan_is_one_page_with_no_text(rendered: Rendered) -> None:
    data = rendered.read("broken/scan_mortgage_statement.jpg")
    document = parse_file(data, "image/jpeg", DPI)
    [page] = document.pages
    assert page.page_no == 1 and page.lines == [] and page.read_by is None
    with Image.open(rendered.path("broken/scan_mortgage_statement.jpg")) as original:
        assert (page.width, page.height) == original.size
    with Image.open(io.BytesIO(page.png)) as image:
        assert image.format == "PNG"


def test_a_png_is_one_page_too() -> None:
    buffer = io.BytesIO()
    Image.new("RGBA", (120, 80), (255, 255, 255, 0)).save(buffer, format="PNG")
    [page] = parse_image(buffer.getvalue()).pages
    assert (page.width, page.height) == (120, 80)


@pytest.mark.parametrize("data", [b"", b"\x89PNG\r\n\x1a\nnot an image", b"\xff\xd8\xffjunk"])
def test_a_broken_image_is_unreadable(data: bytes) -> None:
    with pytest.raises(UnreadableFileError):
        parse_image(data)


def test_a_truncated_jpeg_is_unreadable(rendered: Rendered) -> None:
    data = rendered.read("broken/scan_mortgage_statement.jpg")
    with pytest.raises(UnreadableFileError):
        parse_image(data[: len(data) // 2])


# --- the OCR seam ---------------------------------------------------------------------------


def test_the_default_ocr_adapter_is_a_not_implemented_stub() -> None:
    with pytest.raises(NotImplementedError, match="OCR is not implemented"):
        NotImplementedOcr().read_page(b"png", 10, 10)
    assert NotImplementedOcr().read_by.value == "tesseract"
