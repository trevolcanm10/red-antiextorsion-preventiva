"""Private account operations; caller sessions belong to this unit of work.

Every management writer locks Organization first, then reloads actor and target under
READ COMMITTED. No API/CLI account writer may bypass this protocol. Transaction commit
or rollback belongs to this service, including when authentication already autobegan it.
"""
from collections.abc import Iterator
from contextlib import contextmanager
from uuid import UUID

from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.permissions import Permission
from app.core.security import hash_password, verify_password
from app.db.base import Base
from app.models import Organization, User
from app.models.enums import GeneralStatus, UserRole
from app.repositories.accounts import (
    active_administrator_count, organization_for_update, user_in_organization, users_query,
)
from app.schemas.accounts import (
    BootstrapRequest, BootstrapResult, OrganizationSelfRead, UserManagementRead,
    UserPage, UserProvisionRequest, UserRoleChangeRequest, UserStatusChangeRequest,
)
from app.services.authorization import (
    AuthorizationError, InactiveActor, ResourceNotFound, ensure_permission,
)


class AccountConflict(AuthorizationError):
    status_code = 409
    detail = "Account operation conflicts with current state"


class LastAdministrator(AccountConflict):
    detail = "At least one active administrator must remain"


class BootstrapConflict(AccountConflict):
    detail = "Bootstrap requires an empty installation at revision 0002"


@contextmanager
def account_transaction(db: Session) -> Iterator[None]:
    try:
        # Subsequent reads must see commits made while waiting for our row/advisory lock.
        if db.connection().get_isolation_level() != "READ COMMITTED":
            raise AccountConflict()
        yield
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        if getattr(exc.orig, "sqlstate", None) == "23505":
            raise AccountConflict() from None  # No email/constraint/tenant details.
        raise
    except BaseException:
        db.rollback()
        raise


def locked_administrator(
    db: Session, principal: User, permission: Permission, current_password: str,
) -> User:
    # Capture JWT-authenticated organization before refreshing the identity map.
    actor_id, organization_id = principal.id, principal.organization_id
    expected_version = principal.auth_version
    organization = organization_for_update(db, organization_id)
    if organization is None or organization.status != GeneralStatus.ACTIVE:
        raise InactiveActor()
    actor = user_in_organization(db, organization_id, actor_id, lock=True)
    if actor is None or actor.auth_version != expected_version:
        raise InactiveActor()
    ensure_permission(actor, permission)  # Recheck role/status AFTER waiting for the lock.
    if actor.role != UserRole.ADMINISTRATOR:
        raise AuthorizationError()
    valid, _ = verify_password(current_password, actor.password_hash)
    if not valid:
        raise InactiveActor()
    return actor


def scoped_target(db: Session, actor: User, target_id: UUID, *, lock: bool = False) -> User:
    target = user_in_organization(db, actor.organization_id, target_id, lock=lock)
    if target is None:
        raise ResourceNotFound()
    return target


def ensure_admin_survives(
    db: Session, target: User, *, new_role: UserRole, new_status: GeneralStatus,
) -> None:
    if (target.role == UserRole.ADMINISTRATOR and target.status == GeneralStatus.ACTIVE
            and (new_role != UserRole.ADMINISTRATOR or new_status != GeneralStatus.ACTIVE)
            and active_administrator_count(db, target.organization_id) <= 1):
        raise LastAdministrator()


def get_own_organization(db: Session, actor: User) -> OrganizationSelfRead:
    ensure_permission(actor, Permission.ORGANIZATION_READ_SELF)
    organization = db.get(Organization, actor.organization_id)
    if organization is None:
        raise ResourceNotFound()
    return OrganizationSelfRead.model_validate(organization)


def list_users(
    db: Session, actor: User, *, offset: int = 0, limit: int = 50,
    role: UserRole | None = None, status: GeneralStatus | None = None,
) -> UserPage:
    ensure_permission(actor, Permission.USER_READ_OTHERS)
    if offset < 0 or not 1 <= limit <= 100:
        raise ValueError("Invalid pagination")
    query = users_query(actor.organization_id)
    if role is not None:
        query = query.where(User.role == role)
    if status is not None:
        query = query.where(User.status == status)
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    users = db.scalars(query.order_by(User.created_at, User.id).offset(offset).limit(limit))
    return UserPage(items=[UserManagementRead.model_validate(user) for user in users],
                    total=total, offset=offset, limit=limit)


def read_user(db: Session, actor: User, target_id: UUID) -> UserManagementRead:
    ensure_permission(actor, Permission.USER_READ_OTHERS)
    return UserManagementRead.model_validate(scoped_target(db, actor, target_id))


def provision_user(db: Session, principal: User, payload: UserProvisionRequest) -> UserManagementRead:
    with account_transaction(db):
        actor = locked_administrator(db, principal, Permission.USER_CREATE,
                                     payload.current_password.get_secret_value())
        user = User(organization_id=actor.organization_id, name=payload.name, email=payload.email,
                    password_hash=hash_password(payload.password.get_secret_value()),
                    role=payload.role, status=payload.status)
        db.add(user)
        db.flush()
        return UserManagementRead.model_validate(user)


def change_user_role(
    db: Session, principal: User, target_id: UUID, payload: UserRoleChangeRequest,
) -> UserManagementRead:
    with account_transaction(db):
        actor = locked_administrator(db, principal, Permission.USER_ROLE_CHANGE,
                                     payload.current_password.get_secret_value())
        target = scoped_target(db, actor, target_id, lock=True)
        if actor.id == target.id:
            raise AuthorizationError()
        ensure_admin_survives(db, target, new_role=payload.role, new_status=target.status)
        target.role = payload.role
        db.flush()
        return UserManagementRead.model_validate(target)


def status_permission(status: GeneralStatus) -> Permission:
    if status == GeneralStatus.ACTIVE:
        return Permission.USER_ACTIVATE
    if status == GeneralStatus.INACTIVE:
        return Permission.USER_DEACTIVATE
    raise AuthorizationError()


def change_user_status(
    db: Session, principal: User, target_id: UUID, payload: UserStatusChangeRequest,
) -> UserManagementRead:
    permission = status_permission(payload.status)
    with account_transaction(db):
        actor = locked_administrator(db, principal, permission,
                                     payload.current_password.get_secret_value())
        target = scoped_target(db, actor, target_id, lock=True)
        if actor.id == target.id:
            raise AuthorizationError()  # Includes self-activation; inactive actors fail earlier.
        ensure_admin_survives(db, target, new_role=target.role, new_status=payload.status)
        if target.status == GeneralStatus.ACTIVE and payload.status == GeneralStatus.INACTIVE:
            target.auth_version += 1  # Row + organization locked; same commit as deactivation.
        target.status = payload.status
        db.flush()
        return UserManagementRead.model_validate(target)


def bootstrap_empty_installation(db: Session, payload: BootstrapRequest) -> BootstrapResult:
    with account_transaction(db):
        # No row exists to lock initially: serialize all bootstrap executions instead.
        db.execute(text("SELECT pg_advisory_xact_lock(173341, 33)"))
        versions = list(db.scalars(text("SELECT version_num FROM alembic_version")))
        if versions != ["0002"]:
            raise BootstrapConflict()
        # Empty means ALL ten domain tables, not just organizations and users.
        for table in Base.metadata.sorted_tables:
            if db.scalar(select(select(table).exists())):
                raise BootstrapConflict()
        organization = Organization(name=payload.organization_name,
                                    type=payload.organization_type, status=GeneralStatus.ACTIVE)
        db.add(organization)
        db.flush()
        administrator = User(organization_id=organization.id, name=payload.admin_name,
                             email=payload.admin_email, role=UserRole.ADMINISTRATOR,
                             status=GeneralStatus.ACTIVE,
                             password_hash=hash_password(payload.password.get_secret_value()))
        db.add(administrator)
        db.flush()
        return BootstrapResult(organization_id=organization.id, administrator_id=administrator.id)

