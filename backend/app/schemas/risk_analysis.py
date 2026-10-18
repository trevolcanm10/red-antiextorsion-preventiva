from decimal import Decimal
from uuid import UUID

from pydantic import Field

from app.schemas.base import Schema, UTCDateTime
from app.models.enums import RiskLevel


class RiskAnalysisCreate(Schema):
    report_id: UUID
    risk_level: RiskLevel
    score: Decimal = Field(max_digits=6, decimal_places=2)
    justification: str | None = Field(default=None)
    model_version: str | None = Field(default=None, max_length=50)
    analyzed_at: UTCDateTime


class RiskAnalysisInternal(RiskAnalysisCreate):
    id: UUID


class RiskAnalysisRead(Schema):
    id: UUID
    report_id: UUID
    risk_level: RiskLevel
    score: Decimal = Field(max_digits=6, decimal_places=2)
    justification: str | None = Field(default=None)
    model_version: str | None = Field(default=None, max_length=50)
    analyzed_at: UTCDateTime
