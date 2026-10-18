from decimal import Decimal
from uuid import UUID

from pydantic import Field

from app.schemas.base import Schema
from app.models.enums import GeneralStatus


class IndicatorCreate(Schema):
    name: str = Field(max_length=150)
    description: str | None = Field(default=None)
    category: str | None = Field(default=None, max_length=100)
    weight: Decimal | None = Field(default=None, max_digits=5, decimal_places=2)
    status: GeneralStatus


class IndicatorInternal(IndicatorCreate):
    id: UUID


class IndicatorRead(Schema):
    id: UUID
    name: str = Field(max_length=150)
    description: str | None = Field(default=None)
    category: str | None = Field(default=None, max_length=100)
    weight: Decimal | None = Field(default=None, max_digits=5, decimal_places=2)
    status: GeneralStatus
