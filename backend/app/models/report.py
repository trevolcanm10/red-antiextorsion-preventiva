from __future__ import annotations

from typing import TYPE_CHECKING

from datetime import datetime
from uuid import UUID, uuid4
from sqlalchemy import DateTime, ForeignKeyConstraint, Index, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base
from app.models._types import enum_type, fk
from app.models.enums import ReportStatus


if TYPE_CHECKING:
    from app.models.evidence import Evidence
    from app.models.location import Location
    from app.models.organization import Organization
    from app.models.report_indicator import ReportIndicator
    from app.models.risk_analysis import RiskAnalysis
    from app.models.user import User


class Report(Base):
    __tablename__ = "reports"
    __table_args__ = (
        ForeignKeyConstraint(["user_id", "organization_id"], ["users.id", "users.organization_id"], ondelete="RESTRICT", onupdate="RESTRICT", name="fk_reports_user_organization"),
        Index("ix_reports_user_id_organization_id", "user_id", "organization_id"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(nullable=False)
    organization_id: Mapped[UUID] = mapped_column(fk("organizations.id"), index=True, nullable=False)
    location_id: Mapped[UUID | None] = mapped_column(fk("locations.id"), index=True, nullable=True)
    type: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    incident_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    registered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    status: Mapped[ReportStatus] = mapped_column(enum_type(ReportStatus, "estado_reporte"), nullable=False)

    user: Mapped["User"] = relationship("User", back_populates="reports", foreign_keys=[user_id])
    organization: Mapped["Organization"] = relationship("Organization", back_populates="reports", foreign_keys=[organization_id])
    location: Mapped["Location | None"] = relationship("Location", back_populates="reports")
    evidence: Mapped[list["Evidence"]] = relationship("Evidence", back_populates="report", passive_deletes="all")
    risk_analyses: Mapped[list["RiskAnalysis"]] = relationship("RiskAnalysis", back_populates="report", passive_deletes="all")
    indicator_links: Mapped[list["ReportIndicator"]] = relationship("ReportIndicator", back_populates="report", passive_deletes="all")
