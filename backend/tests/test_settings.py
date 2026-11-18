import pytest

from app.settings import Settings


def test_s3_prefix_is_normalised(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("S3_PREFIX", "/dev/abhay")
    assert Settings(_env_file=None).s3_prefix == "dev/abhay/"


def test_env_overrides_and_unknown_vars_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("S3_BUCKET", "demo-bucket")
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "not-a-setting")
    settings = Settings(_env_file=None)
    assert settings.s3_bucket == "demo-bucket"
    assert settings.aws_region == "us-east-1"


def test_blank_aws_values_are_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AWS_PROFILE", "")
    monkeypatch.setenv("AWS_REGION", "  ")
    settings = Settings(_env_file=None)
    assert settings.aws_profile is None
    assert settings.aws_region is None


def test_secrets_are_not_echoed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JWT_SECRET", "hunter2")
    assert "hunter2" not in repr(Settings(_env_file=None))
