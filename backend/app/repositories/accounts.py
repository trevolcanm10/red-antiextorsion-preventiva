"""All HTTP account lookups are explicitly scoped to the actor organization."""
from uuid import UUID

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session, joinedload

from app.models import Organization, User
from app.models.enums import GeneralStatus, UserRole


def users_query(organization_id: UUID) -> Select:
    return select(User).where(User.organization_id == organization_id)


def organization_for_update(db: Session, organization_id: UUID) -> Organization | None:
    return db.scalar(select(Organization).where(Organization.id == organization_id)
                     .with_for_update().execution_options(populate_existing=True))


def user_in_organization(
    db: Session, organization_id: UUID, user_id: UUID, *, lock: bool = False,
) -> User | None:
    query = users_query(organization_id).where(User.id == user_id)
    if lock:
        query = query.options(joinedload(User.organization, innerjoin=True)).with_for_update(of=User)
    return db.scalar(query.execution_options(populate_existing=True))


def active_administrator_count(db: Session, organization_id: UUID) -> int:
    return db.scalar(select(func.count()).select_from(User).where(
        User.organization_id == organization_id, User.role == UserRole.ADMINISTRATOR,
        User.status == GeneralStatus.ACTIVE,
    )) or 0
