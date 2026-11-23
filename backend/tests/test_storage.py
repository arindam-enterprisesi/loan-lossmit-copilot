from collections.abc import Iterator
from typing import Any
from urllib.parse import parse_qs, urlparse

import boto3
import pytest
from botocore.exceptions import EndpointConnectionError, NoCredentialsError
from moto import mock_aws

from app.settings import Settings
from app.storage import ObjectNotFoundError, Storage, StorageError

BUCKET = "test-bucket"
PREFIX = "dev/abhay/"


@pytest.fixture
def storage(monkeypatch: pytest.MonkeyPatch) -> Iterator[Storage]:
    for name in ("AWS_PROFILE", "AWS_SESSION_TOKEN"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    with mock_aws():
        boto3.client("s3", region_name="us-east-1").create_bucket(Bucket=BUCKET)
        settings = Settings(
            _env_file=None, s3_bucket=BUCKET, s3_prefix=PREFIX, aws_region="us-east-1"
        )
        yield Storage(settings)


def test_put_get_round_trip_under_prefix(storage: Storage) -> None:
    full = storage.put("cases/1/doc.pdf", b"original bytes", "application/pdf")
    assert full == f"{PREFIX}cases/1/doc.pdf"
    assert storage.get("cases/1/doc.pdf") == b"original bytes"

    raw = boto3.client("s3", region_name="us-east-1")
    keys = [o["Key"] for o in raw.list_objects_v2(Bucket=BUCKET)["Contents"]]
    assert keys == [full]
    assert raw.head_object(Bucket=BUCKET, Key=full)["ContentType"] == "application/pdf"


def test_delete(storage: Storage) -> None:
    storage.put("a.txt", b"x")
    storage.delete("a.txt")
    with pytest.raises(ObjectNotFoundError):
        storage.get("a.txt")


def test_get_missing_raises(storage: Storage) -> None:
    with pytest.raises(ObjectNotFoundError):
        storage.get("nope.txt")


def test_presigned_get_is_prefixed_and_valid_five_minutes(storage: Storage) -> None:
    storage.put("cases/1/page-1.png", b"png")
    url = urlparse(storage.presigned_get("cases/1/page-1.png"))
    assert f"{PREFIX}cases/1/page-1.png" in url.path
    assert parse_qs(url.query)["X-Amz-Expires"] == ["300"]


@pytest.mark.parametrize("bad", ["", "/abs", "../escape", "a/../b", "a//b", "a/./b", "a\\b"])
def test_keys_cannot_escape_prefix(storage: Storage, bad: str) -> None:
    with pytest.raises(StorageError):
        storage.put(bad, b"x")
    with pytest.raises(StorageError):
        storage.presigned_get(bad)


def test_client_builds_with_blank_profile_from_env_example(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # `cp .env.example .env` leaves AWS_PROFILE= and AWS_REGION= blank.
    monkeypatch.setenv("AWS_PROFILE", "")
    monkeypatch.setenv("AWS_REGION", "")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    store = Storage(Settings(_env_file=None, s3_bucket=BUCKET))
    assert store._get_client() is not None


class _Unreachable:
    """An S3 client whose network is down: botocore raises EndpointConnectionError."""

    def put_object(self, **_: Any) -> Any:
        raise EndpointConnectionError(endpoint_url="https://s3.example.invalid/secret-key")

    def get_object(self, **_: Any) -> Any:
        raise EndpointConnectionError(endpoint_url="https://s3.example.invalid/secret-key")

    def delete_object(self, **_: Any) -> Any:
        raise EndpointConnectionError(endpoint_url="https://s3.example.invalid/secret-key")

    def generate_presigned_url(self, *_: Any, **__: Any) -> Any:
        # Signing is local, so what fails here is the credentials, not the network.
        raise NoCredentialsError()


def test_presigning_without_credentials_is_a_storage_error() -> None:
    store = Storage(Settings(_env_file=None, s3_bucket=BUCKET), client=_Unreachable())  # type: ignore[arg-type]
    with pytest.raises(StorageError, match="NoCredentialsError"):
        store.presigned_get("cases/1/page-1.png")


def test_a_connection_error_is_a_storage_error_that_names_no_url() -> None:
    store = Storage(Settings(_env_file=None, s3_bucket=BUCKET), client=_Unreachable())  # type: ignore[arg-type]
    for call in (
        lambda: store.put("a.txt", b"x"),
        lambda: store.get("a.txt"),
        lambda: store.delete("a.txt"),
    ):
        with pytest.raises(StorageError, match="EndpointConnectionError") as caught:
            call()
        assert not isinstance(caught.value, ObjectNotFoundError)
        assert "secret-key" not in str(caught.value)


def test_missing_bucket_is_an_error() -> None:
    with pytest.raises(StorageError, match="S3_BUCKET"):
        Storage(Settings(_env_file=None, s3_bucket="")).put("a", b"x")
