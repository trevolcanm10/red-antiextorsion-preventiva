from datetime import datetime, timezone
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.security import dummy_password_hash, verify_password
from app.models import User
from app.models.enums import GeneralStatus
from app.repositories.user import get_user_by_email


def user_is_active(user: User | None) -> bool:
    return bool(user is not None and user.status == GeneralStatus.ACTIVE
                and user.organization is not None
                and user.organization.status == GeneralStatus.ACTIVE)


@dataclass(frozen=True)
class AuthenticatedPrincipal:
    """Pin the verified version; never upgrade it through an ORM refresh after commit."""
    id: UUID
    organization_id: UUID
    auth_version: int


def authenticate_user(db: Session, email: str, password: str) -> AuthenticatedPrincipal | None:
    user = get_user_by_email(db, email)
    stored_hash = user.password_hash if user is not None else dummy_password_hash()
    valid, updated_hash = verify_password(password, stored_hash)
    if not valid or not user_is_active(user):
        return None
    assert user is not None
    principal = AuthenticatedPrincipal(user.id, user.organization_id, user.auth_version)
    if updated_hash is not None:
        user.password_hash = updated_hash
    user.last_login = datetime.now(timezone.utc)
    db.commit()
    return principal
