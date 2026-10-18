"""Explicit action grants. Permissions are code constants, not database roles."""
from enum import StrEnum
from types import MappingProxyType

from app.models.enums import UserRole


class Permission(StrEnum):
    PROFILE_READ = "profile.read"
    REPORT_CREATE = "report.create"
    REPORT_READ = "report.read"
    REPORT_EDIT = "report.edit"
    EVIDENCE_ATTACH = "evidence.attach"
    EVIDENCE_READ = "evidence.read"
    REPORT_REVIEW = "report.review"
    REPORT_CLOSE = "report.close"
    ANALYSIS_READ_SUMMARY = "analysis.read_summary"
    ANALYSIS_READ_DETAIL = "analysis.read_detail"
    ALERT_READ_PREVENTIVE = "alert.read_preventive"
    ALERT_READ_DETAIL = "alert.read_detail"
    ALERT_ATTEND = "alert.attend"
    ALERT_CLOSE = "alert.close"
    # Only explicitly granted actions below are enabled; no implicit role inheritance.
    REPORT_VALIDATE = "report.validate"
    REPORT_OBSERVE = "report.observe"
    REPORTER_IDENTITY_READ = "reporter_identity.read"
    PRECISE_LOCATION_READ = "precise_location.read"
    EVIDENCE_PATH_READ = "evidence_path.read"
    USER_READ_OTHERS = "user.read_others"
    USER_CREATE = "user.create"
    USER_ROLE_CHANGE = "user.change_role"
    USER_DEACTIVATE = "user.deactivate"
    ORGANIZATION_READ_SELF = "organization.read_self"
    USER_ACTIVATE = "user.activate"
    ORGANIZATION_MANAGE = "organization.manage"
    RESOURCE_DELETE = "resource.delete"
    ANALYSIS_WRITE = "analysis.write"
    ALERT_CREATE = "alert.create"


ROLE_PERMISSIONS = MappingProxyType({
    UserRole.USER: frozenset({
        Permission.PROFILE_READ, Permission.REPORT_CREATE, Permission.REPORT_READ,
        Permission.REPORT_EDIT, Permission.EVIDENCE_ATTACH, Permission.EVIDENCE_READ,
        Permission.ANALYSIS_READ_SUMMARY, Permission.ALERT_READ_PREVENTIVE,
    }),
    UserRole.MODERATOR: frozenset({
        Permission.PROFILE_READ, Permission.REPORT_CREATE, Permission.REPORT_READ,
        Permission.REPORT_EDIT, Permission.EVIDENCE_ATTACH, Permission.EVIDENCE_READ,
        Permission.REPORT_REVIEW, Permission.REPORT_CLOSE,
        Permission.ANALYSIS_READ_SUMMARY, Permission.ANALYSIS_READ_DETAIL,
        Permission.ALERT_READ_PREVENTIVE, Permission.ALERT_READ_DETAIL,
        Permission.ALERT_ATTEND, Permission.ALERT_CLOSE,
    }),
    UserRole.ADMINISTRATOR: frozenset({
        Permission.PROFILE_READ, Permission.REPORT_CREATE, Permission.REPORT_READ,
        Permission.REPORT_EDIT, Permission.EVIDENCE_ATTACH, Permission.EVIDENCE_READ,
        Permission.REPORT_REVIEW, Permission.REPORT_CLOSE,
        Permission.ANALYSIS_READ_SUMMARY, Permission.ANALYSIS_READ_DETAIL,
        Permission.ALERT_READ_PREVENTIVE, Permission.ALERT_READ_DETAIL,
        Permission.ALERT_ATTEND, Permission.ALERT_CLOSE,
        Permission.ORGANIZATION_READ_SELF, Permission.USER_READ_OTHERS, Permission.USER_CREATE,
        Permission.USER_ROLE_CHANGE, Permission.USER_DEACTIVATE, Permission.USER_ACTIVATE,
    }),
})


def has_permission(role: UserRole, permission: Permission) -> bool:
    # No implicit conversion of unknown strings and no role hierarchy.
    return (isinstance(role, UserRole) and isinstance(permission, Permission)
            and permission in ROLE_PERMISSIONS.get(role, frozenset()))
