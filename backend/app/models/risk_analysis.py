from __future__ import annotations

from typing import TYPE_CHECKING

from datetime import datetime
from decimal import Decimal
from uuid import UUID, uuid4
from sqlalchemy import DateTime, Numeric, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base
from app.models._types import enum_type, fk
from app.models.enums import RiskLevel


if TYPE_CHECKING:
    from app.models.alert import Alert
    from app.models.analysis_indicator import AnalysisIndicator
    from app.models.report import Report


class RiskAnalysis(Base):
    __tablename__ = "risk_analyses"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    report_id: Mapped[UUID] = mapped_column(fk("reports.id"), index=True, nullable=False)
    risk_level: Mapped[RiskLevel] = mapped_column(enum_type(RiskLevel, "nivel_riesgo"), nullable=False)
    score: Mapped[Decimal] = mapped_column(Numeric(6, 2), nullable=False)
    justification: Mapped[str | None] = mapped_column(Text, nullable=True)
    model_version: Mapped[str | None] = mapped_column(String(50), nullable=True)
    analyzed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    report: Mapped["Report"] = relationship("Report", back_populates="risk_analyses")
    indicator_links: Mapped[list["AnalysisIndicator"]] = relationship("AnalysisIndicator", back_populates="analysis", passive_deletes="all")
    alerts: Mapped[list["Alert"]] = relationship("Alert", back_populates="analysis", passive_deletes="all")
