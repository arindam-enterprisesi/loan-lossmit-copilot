"""Text-row page layout and PDF writing.

A page is a list of rows and one row is one line of text, so the *n*th row on a page
is its line ``p<page>-L<n>`` once the document is read back in reading order. Rows
are drawn at a fixed pitch, which keeps the numbering predictable and the text layer
clean. Footers are rows pinned to the bottom, so they come last.
"""

from __future__ import annotations

import io
from dataclasses import dataclass, field
from typing import Literal

from reportlab.lib.pagesizes import letter
from reportlab.lib.pdfencrypt import StandardEncryption
from reportlab.pdfgen import canvas

PAGE_WIDTH, PAGE_HEIGHT = letter
LEFT, RIGHT = 54.0, PAGE_WIDTH - 54.0
TOP = PAGE_HEIGHT - 60.0
PITCH = 15.5
FOOTER_Y = 46.0
NOTICE = "SYNTHETIC SAMPLE - invented data, not a real document"

Align = Literal["l", "r"]


@dataclass(frozen=True)
class Seg:
    x: float
    text: str
    align: Align = "l"


@dataclass
class Row:
    segs: list[Seg]
    bold: bool = False
    size: float = 9.5
    footer_slot: int | None = None  # 0 = lowest footer line, 1 = the one above
    rule_below: bool = False


@dataclass
class Page:
    rows: list[Row] = field(default_factory=list)

    def line(self, text: str, *, bold: bool = False, size: float = 9.5, rule: bool = False) -> None:
        self.rows.append(Row([Seg(LEFT, text)], bold, size, rule_below=rule))

    def cols(self, *segs: Seg, bold: bool = False, size: float = 9.5, rule: bool = False) -> None:
        self.rows.append(Row(list(segs), bold, size, rule_below=rule))

    def footer(self, text: str) -> None:
        self.rows.append(Row([Seg(LEFT, text)], False, 8.0, footer_slot=1))
        self.rows.append(Row([Seg(LEFT, NOTICE)], False, 7.0, footer_slot=0))

    def body_rows(self) -> list[Row]:
        return [r for r in self.rows if r.footer_slot is None]


def build_pdf(pages: list[Page], *, title: str, password: str | None = None) -> bytes:
    """Render pages to a text-layer PDF. Output is byte-for-byte reproducible.

    ``password`` makes the PDF require it to open (RC4 128-bit; AES needs an extra library).
    """
    buffer = io.BytesIO()
    encrypt = (
        StandardEncryption(password, ownerPassword=password + "-owner", strength=128)
        if password
        else None
    )
    pdf = canvas.Canvas(buffer, pagesize=letter, invariant=1, pageCompression=0, encrypt=encrypt)
    pdf.setTitle(title)
    pdf.setAuthor("Synthetic data generator")
    pdf.setSubject(NOTICE)
    for page in pages:
        y = TOP
        for row in page.rows:
            row_y = FOOTER_Y + 12.0 * (row.footer_slot or 0) if row.footer_slot is not None else y
            pdf.setFont("Helvetica-Bold" if row.bold else "Helvetica", row.size)
            for seg in row.segs:
                if seg.align == "r":
                    pdf.drawRightString(seg.x, row_y, seg.text)
                else:
                    pdf.drawString(seg.x, row_y, seg.text)
            if row.rule_below:
                pdf.setLineWidth(0.5)
                pdf.line(LEFT, row_y - 4, RIGHT, row_y - 4)
            if row.footer_slot is None:
                y -= PITCH
        pdf.showPage()
    pdf.save()
    return buffer.getvalue()


def image_pdf(jpeg_pages: list[bytes], *, title: str) -> bytes:
    """An image-only PDF (no text layer): one full-page JPEG per page."""
    from reportlab.lib.utils import ImageReader

    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=letter, invariant=1, pageCompression=0)
    pdf.setTitle(title)
    for data in jpeg_pages:
        pdf.drawImage(ImageReader(io.BytesIO(data)), 0, 0, width=PAGE_WIDTH, height=PAGE_HEIGHT)
        pdf.showPage()
    pdf.save()
    return buffer.getvalue()
