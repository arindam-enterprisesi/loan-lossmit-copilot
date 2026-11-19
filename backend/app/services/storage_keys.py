"""Where a document's files live in S3, relative to ``S3_PREFIX`` (``Storage`` adds the prefix).

Keys hold IDs only: never a file name or anything about the borrower (FSD 5.3).
"""

from __future__ import annotations

import uuid


def document_folder(case_id: uuid.UUID, document_id: uuid.UUID) -> str:
    return f"cases/{case_id}/documents/{document_id}"


def original_key(case_id: uuid.UUID, document_id: uuid.UUID) -> str:
    """The uploaded file, byte for byte, with no extension and no name."""
    return f"{document_folder(case_id, document_id)}/original"


def page_image_key(case_id: uuid.UUID, document_id: uuid.UUID, page_no: int) -> str:
    return f"{document_folder(case_id, document_id)}/pages/{page_no}.png"
