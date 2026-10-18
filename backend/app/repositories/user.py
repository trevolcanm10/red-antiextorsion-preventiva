from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.models import User


def get_user_by_email(db: Session, email: str) -> User | None:
    return db.scalar(
        select(User).options(joinedload(User.organization, innerjoin=True))
        .where(User.email == email).execution_options(populate_existing=True)
    )


def get_user_by_id(db: Session, user_id: UUID) -> User | None:
    return db.scalar(
        select(User).options(joinedload(User.organization, innerjoin=True))
        .where(User.id == user_id).execution_options(populate_existing=True)
    )
