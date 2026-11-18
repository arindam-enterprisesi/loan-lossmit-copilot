"""Password hashing and tokens. No database needed."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from jose import jwt

from app.db.enums import Role
from app.services.auth_config import get_auth_config, load_auth_config
from app.services.security import (
    CurrentUser,
    TokenError,
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)

USER = CurrentUser(id="11111111-2222-3333-4444-555555555555", name="Demo", role=Role.UNDERWRITER)


def test_hash_verifies_and_is_not_the_password() -> None:
    stored = hash_password("correct horse")
    assert "correct horse" not in stored
    assert verify_password("correct horse", stored)
    assert not verify_password("wrong", stored)


def test_each_hash_gets_its_own_salt() -> None:
    assert hash_password("same") != hash_password("same")


@pytest.mark.parametrize(
    "stored", ["", "plain", "scrypt$1$2$3", "bcrypt$1$2$3$a$b", "scrypt$x$y$z$!!$??"]
)
def test_malformed_stored_hash_is_a_failed_check_not_an_error(stored: str) -> None:
    assert verify_password("anything", stored) is False


def test_tampered_hash_fails() -> None:
    stored = hash_password("secret")
    head, digest = stored.rsplit("$", 1)
    flipped = ("A" if digest[0] != "A" else "B") + digest[1:]
    assert not verify_password("secret", f"{head}${flipped}")


def test_token_round_trip_carries_user_and_role() -> None:
    token = create_access_token(USER, secret="s3cret")
    assert decode_access_token(token, secret="s3cret") == USER


def test_token_claims() -> None:
    now = datetime(2026, 11, 17, 9, 0, tzinfo=UTC)
    token = create_access_token(USER, secret="s3cret", expires_minutes=30, now=now)
    claims = jwt.get_unverified_claims(token)
    assert claims["sub"] == USER.id
    assert claims["role"] == "underwriter"
    assert claims["iat"] == int(now.timestamp())
    assert claims["exp"] == int((now + timedelta(minutes=30)).timestamp())


def test_expired_token_rejected() -> None:
    old = datetime.now(UTC) - timedelta(hours=2)
    token = create_access_token(USER, secret="s3cret", expires_minutes=30, now=old)
    with pytest.raises(TokenError):
        decode_access_token(token, secret="s3cret")


def test_token_signed_with_another_secret_rejected() -> None:
    token = create_access_token(USER, secret="someone-else")
    with pytest.raises(TokenError):
        decode_access_token(token, secret="s3cret")


def test_unsigned_token_rejected() -> None:
    # alg "none" must never be accepted.
    claims = {"sub": USER.id, "name": "Demo", "role": "admin", "exp": 9999999999}
    forged = jwt.encode(claims, "", algorithm="HS256").rsplit(".", 1)[0] + "."
    with pytest.raises(TokenError):
        decode_access_token(forged, secret="s3cret")


@pytest.mark.parametrize("token", ["", "abc", "a.b.c"])
def test_garbage_token_rejected(token: str) -> None:
    with pytest.raises(TokenError):
        decode_access_token(token, secret="s3cret")


def test_token_with_unknown_role_rejected() -> None:
    forged = jwt.encode(
        {"sub": "1", "name": "X", "role": "superuser", "exp": 9999999999}, "s3cret", "HS256"
    )
    with pytest.raises(TokenError):
        decode_access_token(forged, secret="s3cret")


def test_token_without_subject_rejected() -> None:
    forged = jwt.encode({"name": "X", "role": "admin", "exp": 9999999999}, "s3cret", "HS256")
    with pytest.raises(TokenError):
        decode_access_token(forged, secret="s3cret")


def test_auth_config_is_versioned_and_labelled() -> None:
    config = get_auth_config()
    assert config.version
    assert config.label in {"illustrative", "authoritative"}
    assert config.access_token_minutes > 0
    assert load_auth_config() == config
