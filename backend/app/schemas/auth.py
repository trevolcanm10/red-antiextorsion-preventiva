from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, SecretStr, StringConstraints

from app.models.enums import GeneralStatus, UserRole


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    # Provisional exact match: never lowercase/casefold/normalize the address.
    email: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)]
    password: SecretStr = Field(min_length=1, max_length=1024)


class TokenResponse(BaseModel):
    access_token: str = Field(repr=False)
    token_type: Literal["bearer"] = "bearer"
    expires_in: int


class CurrentUserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    organization_id: UUID
    name: str
    email: str
    role: UserRole
    status: GeneralStatus
