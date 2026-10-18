from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.api.dependencies import CurrentUser, Database, authorization_errors, require_permission
from app.core.permissions import Permission
from app.models import User
from app.models.enums import GeneralStatus, UserRole
from app.schemas.accounts import (OrganizationSelfRead, UserManagementRead, UserPage,
    UserProvisionRequest, UserRoleChangeRequest, UserStatusChangeRequest)
from app.services import accounts
from app.services.authorization import ensure_permission

router = APIRouter(prefix="/api/v1", tags=["private accounts"])
AccountReader = Annotated[User, Depends(require_permission(Permission.USER_READ_OTHERS))]
AccountCreator = Annotated[User, Depends(require_permission(Permission.USER_CREATE))]
RoleManager = Annotated[User, Depends(require_permission(Permission.USER_ROLE_CHANGE))]
OrganizationReader = Annotated[User, Depends(require_permission(Permission.ORGANIZATION_READ_SELF))]


@router.get("/organizations/me", response_model=OrganizationSelfRead)
def own_organization(actor: OrganizationReader, db: Database) -> OrganizationSelfRead:
    with authorization_errors():
        return accounts.get_own_organization(db, actor)


@router.get("/users", response_model=UserPage)
def list_users(
    actor: AccountReader, db: Database,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    role: UserRole | None = None, status: GeneralStatus | None = None,
) -> UserPage:
    with authorization_errors():
        return accounts.list_users(db, actor, offset=offset, limit=limit, role=role, status=status)


@router.get("/users/{user_id}", response_model=UserManagementRead)
def read_user(user_id: UUID, actor: AccountReader, db: Database) -> UserManagementRead:
    with authorization_errors():
        return accounts.read_user(db, actor, user_id)


@router.post("/users", response_model=UserManagementRead, status_code=201)
def create_user(payload: UserProvisionRequest, actor: AccountCreator, db: Database) -> UserManagementRead:
    with authorization_errors():
        return accounts.provision_user(db, actor, payload)


@router.patch("/users/{user_id}/role", response_model=UserManagementRead)
def change_role(
    user_id: UUID, payload: UserRoleChangeRequest, actor: RoleManager, db: Database,
) -> UserManagementRead:
    with authorization_errors():
        return accounts.change_user_role(db, actor, user_id, payload)


@router.patch("/users/{user_id}/status", response_model=UserManagementRead)
def change_status(
    user_id: UUID, payload: UserStatusChangeRequest, actor: CurrentUser, db: Database,
) -> UserManagementRead:
    with authorization_errors():
        ensure_permission(actor, accounts.status_permission(payload.status))
        return accounts.change_user_status(db, actor, user_id, payload)
