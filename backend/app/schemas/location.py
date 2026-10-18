from decimal import Decimal
from uuid import UUID

from pydantic import Field

from app.schemas.base import Schema


class LocationCreate(Schema):
    department: str | None = Field(default=None, max_length=100)
    province: str | None = Field(default=None, max_length=100)
    district: str | None = Field(default=None, max_length=100)
    zone_reference: str | None = Field(default=None, max_length=255)
    latitude: Decimal | None = Field(default=None, max_digits=9, decimal_places=6, ge=-90, le=90)
    longitude: Decimal | None = Field(default=None, max_digits=9, decimal_places=6, ge=-180, le=180)


class LocationInternal(LocationCreate):
    id: UUID


class LocationRead(Schema):
    id: UUID
    department: str | None = Field(default=None, max_length=100)
    province: str | None = Field(default=None, max_length=100)
    district: str | None = Field(default=None, max_length=100)
    zone_reference: str | None = Field(default=None, max_length=255)
