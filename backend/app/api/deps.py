"""Who is calling, and may they? Used by every router.

The user and role come only from the bearer token: no endpoint takes them from the
request. Roles are checked per router and nothing is implicitly all-powerful, so
``admin`` must be listed wherever an administrator is allowed.

    router = APIRouter(dependencies=[Depends(require_roles(Role.UNDERWRITER, Role.ADMIN))])
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Annotated

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.api.errors import forbidden, unauthorized
from app.db.enums import Role
from app.services.security import CurrentUser, TokenError, decode_access_token

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
