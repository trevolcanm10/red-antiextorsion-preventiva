from __future__ import annotations

from typing import TYPE_CHECKING

from decimal import Decimal
from uuid import UUID, uuid4
from sqlalchemy import Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base
from app.models._types import enum_type
from app.models.enums import GeneralStatus


if TYPE_CHECKING:
    from app.models.analysis_indicator import AnalysisIndicator
    from app.models.report_indicator import ReportIndicator


class Indicator(Base):
    __tablename__ = "indicators"
    __table_args__ = (
        UniqueConstraint("name"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    category: Mapped[str | None] = mapped_column(String(100), nullable=True)
    weight: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    status: Mapped[GeneralStatus] = mapped_column(enum_type(GeneralStatus, "estado_general"), nullable=False)

    report_links: Mapped[list["ReportIndicator"]] = relationship("ReportIndicator", back_populates="indicator", passive_deletes="all")
    analysis_links: Mapped[list["AnalysisIndicator"]] = relationship("AnalysisIndicator", back_populates="indicator", passive_deletes="all")
