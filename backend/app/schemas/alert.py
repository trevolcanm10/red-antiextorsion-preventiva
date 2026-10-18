from uuid import UUID

from pydantic import Field, model_validator

from app.schemas.base import Schema, UTCDateTime
from app.models.enums import RiskLevel, AlertStatus


class AlertCreate(Schema):
    analysis_id: UUID
    organization_id: UUID
    type: str = Field(max_length=100)
    level: RiskLevel
    title: str = Field(max_length=200)
    message: str
    status: AlertStatus
    generated_at: UTCDateTime
    closed_at: UTCDateTime | None = Field(default=None)

    @model_validator(mode="after")
    def closure_order(self) -> "AlertCreate":
        if self.closed_at is not None and self.closed_at < self.generated_at:
            raise ValueError("closed_at must be at or after generated_at")
        return self


class AlertInternal(AlertCreate):
    id: UUID


class AlertRead(Schema):
    id: UUID
    analysis_id: UUID
    organization_id: UUID
    type: str = Field(max_length=100)
    level: RiskLevel
    title: str = Field(max_length=200)
    message: str
    status: AlertStatus
    generated_at: UTCDateTime
    closed_at: UTCDateTime | None = Field(default=None)
