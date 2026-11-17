"""S3 file storage (CPS-01, file side). Originals are stored unchanged.

Every key a caller passes is relative; ``Storage`` puts it under ``S3_PREFIX`` so
one developer's (or tenant's) files can never touch another's. Only the S3
client is used here; model providers stay inside ``app.llm``.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from app.settings import Settings, get_settings

if TYPE_CHECKING:
    from mypy_boto3_s3 import S3Client

PRESIGN_SECONDS = 300  # presigned GET links are valid for 5 minutes


class StorageError(Exception):
    """A storage call failed or a key was rejected."""


class ObjectNotFoundError(StorageError):
    pass


class Storage:
    def __init__(self, settings: Settings | None = None, client: S3Client | None = None) -> None:
        self._settings = settings or get_settings()
        self._client = client

    @property
    def prefix(self) -> str:
        return self._settings.s3_prefix

    @property
    def bucket(self) -> str:
        if not self._settings.s3_bucket:
            raise StorageError("S3_BUCKET is not set")
        return self._settings.s3_bucket

    def _get_client(self) -> S3Client:
        if self._client is None:
            _drop_blank_aws_env()
            s = self._settings
            session = boto3.Session(
                profile_name=s.aws_profile,
                region_name=s.aws_region,
                aws_access_key_id=s.aws_access_key_id.get_secret_value()
                if s.aws_access_key_id
                else None,
                aws_secret_access_key=s.aws_secret_access_key.get_secret_value()
                if s.aws_secret_access_key
                else None,
                aws_session_token=s.aws_session_token.get_secret_value()
                if s.aws_session_token
                else None,
            )
            # SigV4 is required by newer regions and gives presigned links X-Amz-Expires.
            self._client = session.client("s3", config=Config(signature_version="s3v4"))
        return self._client

    def full_key(self, key: str) -> str:
        """The key under ``S3_PREFIX``. Rejects anything that could escape it."""
        if not key or key.startswith("/") or "\\" in key:
            raise StorageError(f"invalid storage key {key!r}")
        if any(part in {"", ".", ".."} for part in key.split("/")):
            raise StorageError(f"invalid storage key {key!r}")
        return f"{self.prefix}{key}"

    def put(self, key: str, data: bytes, content_type: str | None = None) -> str:
        """Store ``data`` and return the full key."""
        full = self.full_key(key)
        extra: dict[str, Any] = {"ContentType": content_type} if content_type else {}
        try:
            self._get_client().put_object(Bucket=self.bucket, Key=full, Body=data, **extra)
        except ClientError as exc:
            raise StorageError(f"put failed: {_code(exc)}") from exc
        return full

    def get(self, key: str) -> bytes:
        full = self.full_key(key)
        try:
            response = self._get_client().get_object(Bucket=self.bucket, Key=full)
        except ClientError as exc:
            if _code(exc) in {"NoSuchKey", "404"}:
                raise ObjectNotFoundError(f"no object at {key!r}") from exc
            raise StorageError(f"get failed: {_code(exc)}") from exc
        return response["Body"].read()

    def delete(self, key: str) -> None:
        full = self.full_key(key)
        try:
            self._get_client().delete_object(Bucket=self.bucket, Key=full)
        except ClientError as exc:
            raise StorageError(f"delete failed: {_code(exc)}") from exc

    def presigned_get(self, key: str, expires: int = PRESIGN_SECONDS) -> str:
        """A one-time-style link to read one object, valid for 5 minutes by default."""
        full = self.full_key(key)
        return self._get_client().generate_presigned_url(
            "get_object",
            Params={"Bucket": self.bucket, "Key": full},
            ExpiresIn=expires,
        )


def _drop_blank_aws_env() -> None:
    """Remove blank ``AWS_*`` variables from the process environment.

    boto3 reads ``AWS_PROFILE`` itself, so a blank ``AWS_PROFILE=`` (what
    ``cp .env.example .env`` and docker compose's ``env_file`` produce) would be
    treated as a profile named "". A blank value means "not set".
    """
    for name in [n for n, v in os.environ.items() if n.startswith("AWS_") and not v.strip()]:
        del os.environ[name]


def _code(exc: ClientError) -> str:
    return str(exc.response.get("Error", {}).get("Code", "unknown"))
