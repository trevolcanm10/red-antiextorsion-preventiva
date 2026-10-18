from uuid import UUID

from pydantic import Field

from app.schemas.base import Schema, UTCDateTime
from app.models.enums import GeneralStatus


class OrganizationCreate(Schema):
    name: str = Field(max_length=150)
    type: str | None = Field(default=None, max_length=50)
    status: GeneralStatus
    created_at: UTCDateTime


class OrganizationInternal(OrganizationCreate):
    id: UUID


class OrganizationRead(Schema):
    id: UUID
    name: str = Field(max_length=150)
    type: str | None = Field(default=None, max_length=50)
    status: GeneralStatus
    created_at: UTCDateTime
