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


def test_the_worker_limits_allow_for_slow_model_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    # arq's own default is 300 s, which a job of several real model calls overruns.
    defaults = Settings(_env_file=None)
    assert (defaults.worker_job_timeout, defaults.worker_max_jobs) == (1800, 4)
    monkeypatch.setenv("WORKER_JOB_TIMEOUT", "600")
    monkeypatch.setenv("WORKER_MAX_JOBS", "2")
    changed = Settings(_env_file=None)
    assert (changed.worker_job_timeout, changed.worker_max_jobs) == (600, 2)


@pytest.mark.parametrize("name", ["WORKER_JOB_TIMEOUT", "WORKER_MAX_JOBS"])
def test_a_zero_worker_limit_is_rejected(monkeypatch: pytest.MonkeyPatch, name: str) -> None:
    monkeypatch.setenv(name, "0")
    with pytest.raises(ValueError):
        Settings(_env_file=None)


def test_the_worker_uses_the_settings() -> None:
    from app.settings import get_settings
    from app.worker import WorkerSettings

    assert WorkerSettings.job_timeout == get_settings().worker_job_timeout
    assert WorkerSettings.max_jobs == get_settings().worker_max_jobs
