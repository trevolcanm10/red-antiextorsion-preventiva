from __future__ import annotations

from typing import TYPE_CHECKING

from datetime import datetime
from uuid import UUID, uuid4
from sqlalchemy import DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base
from app.models._types import enum_type
from app.models.enums import GeneralStatus


if TYPE_CHECKING:
    from app.models.alert import Alert
    from app.models.report import Report
    from app.models.user import User


class Organization(Base):
    __tablename__ = "organizations"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    status: Mapped[GeneralStatus] = mapped_column(enum_type(GeneralStatus, "estado_general"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    users: Mapped[list["User"]] = relationship("User", back_populates="organization", passive_deletes="all")
    reports: Mapped[list["Report"]] = relationship("Report", back_populates="organization", foreign_keys="Report.organization_id", passive_deletes="all")
    alerts: Mapped[list["Alert"]] = relationship("Alert", back_populates="organization", passive_deletes="all")
