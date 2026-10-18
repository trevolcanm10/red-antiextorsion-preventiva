from collections.abc import Callable
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Annotated
from uuid import UUID

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import InvalidTokenError
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.core.config import AuthSettings, get_auth_settings
from app.core.permissions import Permission
from app.core.security import decode_access_token
from app.db.dependencies import get_db
from app.models import User
from app.models.enums import UserRole
from app.repositories.user import get_user_by_id
from app.services.auth import user_is_active
from app.services.authorization import AuthorizationError, ensure_permission

bearer = HTTPBearer(auto_error=False)
Database = Annotated[Session, Depends(get_db)]
AuthConfig = Annotated[AuthSettings, Depends(get_auth_settings)]


def unauthorized() -> HTTPException:
    return HTTPException(
        status_code=401, detail="Authentication required or invalid credentials",
        headers={"WWW-Authenticate": "Bearer", "Cache-Control": "no-store"},
    )


def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    db: Database, settings: AuthConfig,
) -> User:
    if credentials is None:
        raise unauthorized()
    try:
        claims = decode_access_token(credentials.credentials, settings)
    except (InvalidTokenError, ValidationError, ValueError):
        raise unauthorized() from None
    user = get_user_by_id(db, claims.sub)
    if not user_is_active(user):
        raise unauthorized()
    assert user is not None
    if user.organization_id != claims.organization_id:
        raise unauthorized()
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


@contextmanager
def authorization_errors() -> Iterator[None]:
    """Keep reusable domain policies independent of FastAPI exceptions."""
    try:
        yield
    except AuthorizationError as exc:
        headers = {"WWW-Authenticate": "Bearer"} if exc.status_code == 401 else None
        raise HTTPException(exc.status_code, detail=exc.detail, headers=headers) from None


def require_permission(permission: Permission) -> Callable[..., User]:
    def dependency(user: CurrentUser) -> User:
        with authorization_errors():
            ensure_permission(user, permission)
        return user
    return dependency


def require_roles(*allowed_roles: UserRole) -> Callable[..., User]:
    """Exact allowlist: ADMINISTRADOR has no implicit superuser privilege."""
    def dependency(user: CurrentUser) -> User:
        if user.role not in allowed_roles:
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        return user
    return dependency


def require_organization(user: User, organization_id: UUID) -> None:
    """Future organization-scoped operations must also filter their SQL queries."""
    if user.organization_id != organization_id:
        raise HTTPException(status_code=403, detail="Insufficient permissions")
