"""Who is calling, and may they? Used by every router.

The user and role come only from the bearer token: no endpoint takes them from the
request. Roles are checked per router and nothing is implicitly all-powerful, so
``admin`` must be listed wherever an administrator is allowed.

    router = APIRouter(dependencies=[Depends(require_roles(Role.UNDERWRITER, Role.ADMIN))])
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from functools import lru_cache
from typing import Annotated

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.api.errors import ApiError, forbidden, unauthorized
from app.db.enums import Role
from app.services.security import CurrentUser, TokenError, decode_access_token
from app.storage import Storage

# auto_error=False so a missing token gives our contract-shaped 401, not FastAPI's default.
_bearer = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> CurrentUser:
    if credentials is None:
        raise unauthorized()
    try:
        return decode_access_token(credentials.credentials)
    except TokenError:
        raise unauthorized() from None


def require_roles(*roles: Role) -> Callable[[CurrentUser], Awaitable[CurrentUser]]:
    """A dependency that allows only the listed roles (403 otherwise) and returns the user."""
    allowed = frozenset(roles)

    async def dependency(user: Annotated[CurrentUser, Depends(get_current_user)]) -> CurrentUser:
        if user.role not in allowed:
            raise forbidden()
        return user

    return dependency


def case_not_found() -> ApiError:
    return ApiError(404, "not_found", "Case not found")


def _case_id(case_id: str) -> uuid.UUID:
    """A malformed ID is a 404, like an unknown one (the contract lists no 422 here)."""
    try:
        return uuid.UUID(case_id)
    except ValueError:
        raise case_not_found() from None


CaseIdPath = Annotated[uuid.UUID, Depends(_case_id)]


@lru_cache
def get_storage() -> Storage:
    """The S3 wrapper (tests override this with a moto-backed one)."""
    return Storage()
