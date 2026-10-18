from decimal import Decimal
from uuid import UUID

from pydantic import Field

from app.schemas.base import Schema


class AnalysisIndicatorCreate(Schema):
    analysis_id: UUID
    indicator_id: UUID
    applied_weight: Decimal | None = Field(default=None, max_digits=5, decimal_places=2)
    contribution: Decimal | None = Field(default=None, max_digits=6, decimal_places=2)


class AnalysisIndicatorInternal(AnalysisIndicatorCreate):
    pass


class AnalysisIndicatorRead(Schema):
    analysis_id: UUID
    indicator_id: UUID
    applied_weight: Decimal | None = Field(default=None, max_digits=5, decimal_places=2)
    contribution: Decimal | None = Field(default=None, max_digits=6, decimal_places=2)
