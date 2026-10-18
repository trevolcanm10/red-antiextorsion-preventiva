"""Reusable policies. These functions never change or persist resource state."""
from types import MappingProxyType
from uuid import UUID

from app.core.permissions import Permission, has_permission
from app.models import Alert, Report, User
from app.models.enums import AlertStatus, ReportStatus, UserRole
from app.services.auth import user_is_active


class AuthorizationError(Exception):
    status_code = 403
    detail = "Insufficient permissions"


class InactiveActor(AuthorizationError):
    status_code = 401
    detail = "Authentication required or invalid credentials"


class ResourceNotFound(AuthorizationError):
    status_code = 404
    detail = "Resource not found"


class InvalidResourceState(AuthorizationError):
    status_code = 409
    detail = "Operation is not allowed in the current state"


REPORT_ACTIONS = frozenset({
    Permission.REPORT_READ, Permission.REPORT_EDIT, Permission.EVIDENCE_ATTACH,
    Permission.EVIDENCE_READ, Permission.REPORT_REVIEW, Permission.REPORT_CLOSE,
    Permission.ANALYSIS_READ_SUMMARY, Permission.ANALYSIS_READ_DETAIL,
})
ALERT_ACTIONS = frozenset({
    Permission.ALERT_READ_PREVENTIVE, Permission.ALERT_READ_DETAIL,
    Permission.ALERT_ATTEND, Permission.ALERT_CLOSE,
})
ALERT_TRANSITIONS = MappingProxyType({
    AlertStatus.ACTIVE: AlertStatus.ATTENDED,
    AlertStatus.ATTENDED: AlertStatus.CLOSED,
})


def ensure_permission(user: User, permission: Permission) -> None:
    if not user_is_active(user):
        raise InactiveActor()
    if not has_permission(user.role, permission):
        raise AuthorizationError()


def ensure_resource_organization(user: User, organization_id: UUID) -> None:
    if user.organization_id != organization_id:
        raise ResourceNotFound()


def report_requires_owner(user: User, permission: Permission) -> bool:
    return (permission in {Permission.REPORT_EDIT, Permission.EVIDENCE_ATTACH}
            or (user.role == UserRole.USER and permission in {
                Permission.REPORT_READ, Permission.EVIDENCE_READ,
                Permission.ANALYSIS_READ_SUMMARY,
            }))


def authorize_report(user: User, report: Report, permission: Permission) -> None:
    ensure_permission(user, permission)
    if permission not in REPORT_ACTIONS:
        raise AuthorizationError()
    ensure_resource_organization(user, report.organization_id)
    if report_requires_owner(user, permission) and report.user_id != user.id:
        raise ResourceNotFound()
    if permission in {Permission.REPORT_REVIEW, Permission.REPORT_CLOSE}:
        if report.user_id == user.id:
            raise AuthorizationError()  # No self-review or administrative self-closure.
    if permission in {Permission.REPORT_EDIT, Permission.EVIDENCE_ATTACH}:
        if report.status != ReportStatus.REGISTERED:
            raise InvalidResourceState()
    if permission == Permission.REPORT_CLOSE and report.status != ReportStatus.ANALYZED:
        raise InvalidResourceState()
    # REPORT_REVIEW is eligibility only, never validation/observation of a report.


def authorize_alert(user: User, alert: Alert, permission: Permission) -> None:
    ensure_permission(user, permission)
    if permission not in ALERT_ACTIONS:
        raise AuthorizationError()
    ensure_resource_organization(user, alert.organization_id)
    if permission == Permission.ALERT_ATTEND and alert.status != AlertStatus.ACTIVE:
        raise InvalidResourceState()
    if permission == Permission.ALERT_CLOSE and alert.status != AlertStatus.ATTENDED:
        raise InvalidResourceState()


def authorize_alert_transition(user: User, alert: Alert, target: AlertStatus) -> None:
    # Check eligibility and organization before revealing workflow-state information.
    ensure_permission(user, Permission.ALERT_ATTEND)
    ensure_resource_organization(user, alert.organization_id)
    if not isinstance(target, AlertStatus) or ALERT_TRANSITIONS.get(alert.status) != target:
        raise InvalidResourceState()
    permission = (Permission.ALERT_ATTEND if target == AlertStatus.ATTENDED
                  else Permission.ALERT_CLOSE)
    authorize_alert(user, alert, permission)
