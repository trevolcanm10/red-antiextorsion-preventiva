from decimal import Decimal
from uuid import UUID

from pydantic import Field

from app.schemas.base import Schema, UTCDateTime


class ReportIndicatorCreate(Schema):
    report_id: UUID
    indicator_id: UUID
    value: str | None = Field(default=None, description="Textual observation or value; not necessarily numeric")
    confidence: Decimal | None = Field(default=None, max_digits=5, decimal_places=4, ge=0, le=1, description="Detection confidence in [0, 1]; null means unknown")
    detected_at: UTCDateTime = Field(description="Explicit detection instant, normalized to UTC")


class ReportIndicatorInternal(ReportIndicatorCreate):
    pass


class ReportIndicatorRead(Schema):
    report_id: UUID
    indicator_id: UUID
    confidence: Decimal | None = Field(default=None, max_digits=5, decimal_places=4, ge=0, le=1, description="Detection confidence in [0, 1]; null means unknown")
    detected_at: UTCDateTime = Field(description="Explicit detection instant, normalized to UTC")
