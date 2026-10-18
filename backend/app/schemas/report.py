from uuid import UUID

from pydantic import Field

from app.schemas.base import Schema, UTCDateTime
from app.models.enums import ReportStatus


class ReportCreate(Schema):
    user_id: UUID
    organization_id: UUID
    location_id: UUID | None = Field(default=None)
    type: str = Field(max_length=100)
    description: str
    incident_at: UTCDateTime | None = Field(default=None)
    registered_at: UTCDateTime
    status: ReportStatus


class ReportInternal(ReportCreate):
    id: UUID


class ReportRead(Schema):
    id: UUID
    organization_id: UUID
    location_id: UUID | None = Field(default=None)
    type: str = Field(max_length=100)
    description: str
    incident_at: UTCDateTime | None = Field(default=None)
    registered_at: UTCDateTime
    status: ReportStatus
