from uuid import UUID

from pydantic import Field

from app.schemas.base import Schema, UTCDateTime
from app.models.enums import GeneralStatus, UserRole


class UserCreate(Schema):
    """Account metadata input; credential handling is outside this phase."""
    organization_id: UUID
    name: str = Field(max_length=150)
    email: str = Field(max_length=255)
    role: UserRole
    status: GeneralStatus
    created_at: UTCDateTime
    last_login: UTCDateTime | None = Field(default=None)


class UserInternal(UserCreate):
    """Trusted persistence data; never use as a general API response."""
    id: UUID
    password_hash: str = Field(max_length=255, repr=False)


class UserRead(Schema):
    id: UUID
    organization_id: UUID
    name: str = Field(max_length=150)
    email: str = Field(max_length=255)
    role: UserRole
    status: GeneralStatus
    created_at: UTCDateTime
    last_login: UTCDateTime | None = Field(default=None)
