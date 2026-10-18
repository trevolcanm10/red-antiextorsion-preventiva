from __future__ import annotations

from typing import TYPE_CHECKING

from decimal import Decimal
from uuid import UUID
from sqlalchemy import Numeric
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base
from app.models._types import fk


if TYPE_CHECKING:
    from app.models.indicator import Indicator
    from app.models.risk_analysis import RiskAnalysis


class AnalysisIndicator(Base):
    __tablename__ = "analysis_indicators"
    analysis_id: Mapped[UUID] = mapped_column(fk("risk_analyses.id"), primary_key=True, nullable=False)
    indicator_id: Mapped[UUID] = mapped_column(fk("indicators.id"), primary_key=True, index=True, nullable=False)
    applied_weight: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    contribution: Mapped[Decimal | None] = mapped_column(Numeric(6, 2), nullable=True)

    analysis: Mapped["RiskAnalysis"] = relationship("RiskAnalysis", back_populates="indicator_links")
    indicator: Mapped["Indicator"] = relationship("Indicator", back_populates="analysis_links")
