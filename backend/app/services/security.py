"""Password hashing and login tokens.

Passwords use the standard library's scrypt, so there is no extra dependency.
Tokens are HS256 JWTs carrying the user and role, the same claims Amazon Cognito
will issue later. No endpoint takes a user ID from the request: it comes from here.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from jose import JWTError, jwt

from app.db.enums import Role
from app.services.auth_config import get_auth_config
from app.settings import get_settings

JWT_ALGORITHM = "HS256"

# scrypt cost parameters (about 16 MiB of memory per hash). Cryptographic settings,
# not mortgage thresholds; stored in each hash so they can change without breaking logins.
SCRYPT_N = 2**14
SCRYPT_R = 8
SCRYPT_P = 1
SCRYPT_KEY_LENGTH = 32
SALT_BYTES = 16


class TokenError(Exception):
    """The token is missing a claim, expired, malformed or not signed by us."""


@dataclass(frozen=True)
class CurrentUser:
    id: str
    name: str
    role: Role


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def _scrypt(password: str, salt: bytes, n: int, r: int, p: int, length: int) -> bytes:
    return hashlib.scrypt(
        password.encode("utf-8"), salt=salt, n=n, r=r, p=p, dklen=length, maxmem=128 * n * r * 2
    )


def hash_password(password: str) -> str:
    """``scrypt$n$r$p$salt$hash``, with a fresh random salt each time."""
    salt = os.urandom(SALT_BYTES)
    digest = _scrypt(password, salt, SCRYPT_N, SCRYPT_R, SCRYPT_P, SCRYPT_KEY_LENGTH)
    return f"scrypt${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}${_b64(salt)}${_b64(digest)}"


def verify_password(password: str, stored: str) -> bool:
    """Constant-time check. A malformed stored hash is simply a failed check."""
    try:
        scheme, n, r, p, salt_b64, digest_b64 = stored.split("$")
        if scheme != "scrypt":
            return False
        salt, expected = base64.b64decode(salt_b64), base64.b64decode(digest_b64)
        actual = _scrypt(password, salt, int(n), int(r), int(p), len(expected))
    except ValueError:
        return False
    return hmac.compare_digest(actual, expected)


def create_access_token(
    user: CurrentUser,
    *,
    secret: str | None = None,
    expires_minutes: int | None = None,
    now: datetime | None = None,
) -> str:
    issued = now or datetime.now(UTC)
    minutes = (
        expires_minutes if expires_minutes is not None else get_auth_config().access_token_minutes
    )
    claims = {
        "sub": user.id,
        "name": user.name,
        "role": user.role.value,
        "iat": int(issued.timestamp()),
        "exp": int((issued + timedelta(minutes=minutes)).timestamp()),
    }
    key = secret if secret is not None else get_settings().jwt_secret.get_secret_value()
    return jwt.encode(claims, key, algorithm=JWT_ALGORITHM)


def decode_access_token(token: str, *, secret: str | None = None) -> CurrentUser:
    key = secret if secret is not None else get_settings().jwt_secret.get_secret_value()
    try:
        claims = jwt.decode(
            token,
            key,
            algorithms=[JWT_ALGORITHM],
            options={"require_exp": True, "require_sub": True},
        )
        return CurrentUser(
            id=str(claims["sub"]), name=str(claims["name"]), role=Role(claims["role"])
        )
    except (JWTError, KeyError, ValueError) as exc:
        raise TokenError("invalid token") from exc
