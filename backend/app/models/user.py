from __future__ import annotations

from typing import TYPE_CHECKING

from datetime import datetime
from uuid import UUID, uuid4
from sqlalchemy import DateTime, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base
from app.models._types import enum_type, fk
from app.models.enums import GeneralStatus, UserRole


if TYPE_CHECKING:
    from app.models.organization import Organization
    from app.models.report import Report


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("email"),
        UniqueConstraint("id", "organization_id"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    organization_id: Mapped[UUID] = mapped_column(fk("organizations.id"), index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[UserRole] = mapped_column(enum_type(UserRole, "rol_usuario"), nullable=False)
    status: Mapped[GeneralStatus] = mapped_column(enum_type(GeneralStatus, "estado_general"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    last_login: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    organization: Mapped["Organization"] = relationship("Organization", back_populates="users")
    reports: Mapped[list["Report"]] = relationship("Report", back_populates="user", foreign_keys="Report.user_id", passive_deletes="all")
