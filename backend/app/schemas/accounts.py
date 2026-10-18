"""Private account-management contracts, never persistence-wide update schemas."""
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, SecretStr, StringConstraints

from app.models.enums import GeneralStatus, UserRole
from app.schemas.base import UTCDateTime

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=150)]
ExactEmail = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)]
NewPassword = Annotated[SecretStr, Field(min_length=15, max_length=1024)]


class PrivateInput(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class UserProvisionRequest(PrivateInput):
    name: Name
    email: ExactEmail
    password: NewPassword
    role: UserRole
    status: GeneralStatus
    current_password: SecretStr = Field(min_length=1, max_length=1024)


class UserRoleChangeRequest(PrivateInput):
    role: UserRole
    current_password: SecretStr = Field(min_length=1, max_length=1024)


class UserStatusChangeRequest(PrivateInput):
    status: GeneralStatus
    current_password: SecretStr = Field(min_length=1, max_length=1024)


class UserManagementRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    organization_id: UUID
    name: str
    email: str
    role: UserRole
    status: GeneralStatus
    created_at: UTCDateTime
    last_login: UTCDateTime | None


class UserPage(BaseModel):
    items: list[UserManagementRead]
    total: int
    offset: int
    limit: int


class OrganizationSelfRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    name: str
    type: str | None
    status: GeneralStatus
    created_at: UTCDateTime


class BootstrapRequest(PrivateInput):
    organization_name: Name
    organization_type: Annotated[str, StringConstraints(strip_whitespace=True, max_length=50)] | None = None
    admin_name: Name
    admin_email: ExactEmail
    password: NewPassword


class BootstrapResult(BaseModel):
    organization_id: UUID
    administrator_id: UUID
