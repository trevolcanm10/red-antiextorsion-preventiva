from uuid import UUID

from pydantic import Field

from app.schemas.base import Schema, UTCDateTime


class EvidenceCreate(Schema):
    report_id: UUID
    file_type: str | None = Field(default=None, max_length=50)
    file_path: str = Field(max_length=500)
    file_name: str | None = Field(default=None, max_length=255)
    created_at: UTCDateTime


class EvidenceInternal(EvidenceCreate):
    id: UUID


class EvidenceRead(Schema):
    id: UUID
    report_id: UUID
    file_type: str | None = Field(default=None, max_length=50)
    file_name: str | None = Field(default=None, max_length=255)
    created_at: UTCDateTime
