from __future__ import annotations

from typing import TYPE_CHECKING

from datetime import datetime
from uuid import UUID, uuid4
from sqlalchemy import CheckConstraint, DateTime, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base
from app.models._types import enum_type, fk
from app.models.enums import AlertStatus, RiskLevel


if TYPE_CHECKING:
    from app.models.organization import Organization
    from app.models.risk_analysis import RiskAnalysis


class Alert(Base):
    __tablename__ = "alerts"
    __table_args__ = (
        CheckConstraint("closed_at >= generated_at", name="closure_order"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    analysis_id: Mapped[UUID] = mapped_column(fk("risk_analyses.id"), index=True, nullable=False)
    organization_id: Mapped[UUID] = mapped_column(fk("organizations.id"), index=True, nullable=False)
    type: Mapped[str] = mapped_column(String(100), nullable=False)
    level: Mapped[RiskLevel] = mapped_column(enum_type(RiskLevel, "nivel_riesgo"), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[AlertStatus] = mapped_column(enum_type(AlertStatus, "estado_alerta"), nullable=False)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    analysis: Mapped["RiskAnalysis"] = relationship("RiskAnalysis", back_populates="alerts")
    organization: Mapped["Organization"] = relationship("Organization", back_populates="alerts")
