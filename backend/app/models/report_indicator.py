from __future__ import annotations

from typing import TYPE_CHECKING

from datetime import datetime
from decimal import Decimal
from uuid import UUID
from sqlalchemy import CheckConstraint, DateTime, Numeric, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base
from app.models._types import fk


if TYPE_CHECKING:
    from app.models.indicator import Indicator
    from app.models.report import Report


class ReportIndicator(Base):
    """One detection per report/indicator pair.

    value: optional textual observation, category or numeric representation;
        it is never implicitly interpreted as a number.
    confidence: optional confidence in the detection, from 0 to 1;
        NULL means unknown or not calculated, not zero confidence.
    detected_at: explicitly supplied, timezone-aware instant of detection.
    """
    __tablename__ = "report_indicators"
    __table_args__ = (
        CheckConstraint("confidence BETWEEN 0 AND 1", name="confidence_range"),
    )
    report_id: Mapped[UUID] = mapped_column(fk("reports.id"), primary_key=True, nullable=False)
    indicator_id: Mapped[UUID] = mapped_column(fk("indicators.id"), primary_key=True, index=True, nullable=False)
    value: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(5, 4), nullable=True)
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    report: Mapped["Report"] = relationship("Report", back_populates="indicator_links")
    indicator: Mapped["Indicator"] = relationship("Indicator", back_populates="report_links")
