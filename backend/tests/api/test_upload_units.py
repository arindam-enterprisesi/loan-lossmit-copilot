"""Upload validation, ingestion settings, S3 keys and the job queue (no database, no Redis)."""

from __future__ import annotations

import hashlib
import uuid
from pathlib import Path
from typing import Any

import pytest
import yaml
from pydantic import ValidationError

from app.services import queue as queue_module
from app.services.documents import (
    UploadRejectedError,
    safe_file_name,
    sniff_mime,
    validate_file,
)
from app.services.ingestion_config import (
    DEFAULT_INGESTION_CONFIG_PATH,
    IngestionConfig,
    get_ingestion_config,
    load_ingestion_config,
)
from app.services.queue import PROCESS_FUNCTION, ArqQueue
from app.services.storage_keys import original_key, page_image_key
from app.worker import WorkerSettings

MIB = 1024 * 1024
PDF = b"%PDF-1.7\n%rest of a pdf"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 16


# --- type and size --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("data", "mime"),
    [
        (PDF, "application/pdf"),
        (PNG, "image/png"),
        (JPEG, "image/jpeg"),
        (b"date,description,amount\n2026-09-22,ZELLE,2000.00\n", None),  # the broken-set CSV
        (b"", None),
        (b"GIF89a", None),
        (b" %PDF-1.7", None),  # must start with the signature
        (b"PK\x03\x04", None),  # a zip, or a docx
    ],
)
def test_the_type_comes_from_the_bytes(data: bytes, mime: str | None) -> None:
    assert sniff_mime(data) == mime


def test_validate_returns_the_hash_size_and_sniffed_type() -> None:
    file = validate_file("stub.pdf", PDF, 25 * MIB)
    assert (file.file_name, file.mime, file.size_bytes) == ("stub.pdf", "application/pdf", len(PDF))
    assert file.sha256 == hashlib.sha256(PDF).hexdigest()


def test_the_extension_and_client_type_do_not_matter() -> None:
    assert validate_file("statement.csv", PDF, MIB).mime == "application/pdf"
    with pytest.raises(UploadRejectedError) as info:
        validate_file("statement.pdf", b"a,b,c\n1,2,3\n", MIB)
    assert info.value.kind == "unsupported_media"


def test_a_file_at_the_limit_is_accepted_and_one_byte_over_is_not() -> None:
    at_limit = PDF + b"\x00" * (MIB - len(PDF))
    assert validate_file("a.pdf", at_limit, MIB).size_bytes == MIB
    with pytest.raises(UploadRejectedError) as info:
        validate_file("a.pdf", at_limit + b"\x00", MIB)
    assert info.value.kind == "too_large"
    assert "1 MB" in info.value.message and "a.pdf" in info.value.message


def test_size_is_checked_before_type() -> None:
    with pytest.raises(UploadRejectedError) as info:
        validate_file("big.csv", b"x" * (MIB + 1), MIB)
    assert info.value.kind == "too_large"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("stub.pdf", "stub.pdf"),
        ("../../etc/passwd", "passwd"),
        ("C:\\Users\\daniel\\stub.pdf", "stub.pdf"),
        ("/tmp/uploads/stub.pdf", "stub.pdf"),
        ("pay\x00st\nub.pdf", "paystub.pdf"),
        ("  spaced.pdf  ", "spaced.pdf"),
        ("", "upload"),
        (None, "upload"),
        ("folder/", "upload"),
        ("x" * 400 + ".pdf", "x" * 255),
    ],
)
def test_file_names_are_reduced_to_a_safe_base_name(raw: str | None, expected: str) -> None:
    assert safe_file_name(raw) == expected


# --- S3 keys --------------------------------------------------------------------------------


def test_keys_are_made_of_ids_only() -> None:
    case, document = uuid.uuid4(), uuid.uuid4()
    assert original_key(case, document) == f"cases/{case}/documents/{document}/original"
    assert page_image_key(case, document, 3) == f"cases/{case}/documents/{document}/pages/3.png"


# --- ingestion settings ---------------------------------------------------------------------


def test_the_shipped_settings_are_versioned_labelled_and_say_25_mib_at_200_dpi() -> None:
    config = get_ingestion_config()
    assert config.label in {"illustrative", "authoritative"}
    assert config.version
    assert config.max_file_mb == 25 and config.max_file_bytes == 26_214_400
    assert config.render_dpi == 200


def _write(tmp_path: Path, **overrides: Any) -> Path:
    values: dict[str, Any] = {
        "version": "t",
        "label": "illustrative",
        "max_file_mb": 25,
        "render_dpi": 200,
        "ocr": get_ingestion_config().ocr.model_dump(),
    }
    values.update(overrides)
    path = tmp_path / "ingestion.yaml"
    path.write_text(yaml.safe_dump(values), encoding="utf-8")
    return path


def test_settings_are_loaded_from_a_file(tmp_path: Path) -> None:
    config = load_ingestion_config(_write(tmp_path, max_file_mb=5))
    assert config.max_file_bytes == 5 * MIB


@pytest.mark.parametrize(
    "bad",
    [
        {"label": "approved"},  # only illustrative or authoritative
        {"max_file_mb": 0},
        {"render_dpi": -1},
        {"surprise": True},  # unknown settings are rejected, not ignored
        {"ocr": {"surprise": True}},
        {"ocr": {**get_ingestion_config().ocr.model_dump(), "denoise_kernel": 4}},  # must be odd
        {"ocr": {**get_ingestion_config().ocr.model_dump(), "min_text_chars": 0}},
    ],
)
def test_bad_settings_are_rejected(tmp_path: Path, bad: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        load_ingestion_config(_write(tmp_path, **bad))


@pytest.mark.parametrize("name", ["version", "label", "max_file_mb", "render_dpi", "ocr"])
def test_a_setting_cannot_be_left_out(tmp_path: Path, name: str) -> None:
    path = _write(tmp_path)
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    del data[name]
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    with pytest.raises(ValidationError):
        load_ingestion_config(path)


def test_the_settings_file_is_where_the_loader_looks() -> None:
    assert DEFAULT_INGESTION_CONFIG_PATH.name == "ingestion.yaml"
    assert DEFAULT_INGESTION_CONFIG_PATH.parent.name == "config"
    assert isinstance(load_ingestion_config(), IngestionConfig)


# --- the queue ------------------------------------------------------------------------------


class FakePool:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...], str]] = []
        self.closed = False

    async def enqueue_job(self, function: str, *args: Any, _job_id: str) -> None:
        self.calls.append((function, args, _job_id))

    async def aclose(self) -> None:
        self.closed = True


async def test_the_arq_queue_connects_on_first_use_and_names_the_job(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pool, opened = FakePool(), []

    async def fake_create_pool(settings: Any) -> FakePool:
        opened.append(settings)
        return pool

    monkeypatch.setattr(queue_module, "create_pool", fake_create_pool)
    queue = ArqQueue("redis://example.invalid:6379/3")
    assert opened == []  # nothing is opened until something is queued

    await queue.enqueue(PROCESS_FUNCTION, "job-1", ["d1", "d2"], job_id="job-1")
    await queue.enqueue(PROCESS_FUNCTION, "job-2", ["d3"], job_id="job-2")

    assert len(opened) == 1 and opened[0].host == "example.invalid" and opened[0].database == 3
    assert opened[0].conn_retries == 1  # fail fast inside a request
    assert pool.calls == [
        ("process_documents", ("job-1", ["d1", "d2"]), "job-1"),
        ("process_documents", ("job-2", ["d3"]), "job-2"),
    ]
    await queue.close()
    assert pool.closed


def test_the_worker_runs_the_function_the_api_queues() -> None:
    names = {fn.__name__ for fn in WorkerSettings.functions}
    assert PROCESS_FUNCTION in names
