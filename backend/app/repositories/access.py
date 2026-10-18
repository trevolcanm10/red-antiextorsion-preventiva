"""Read-only authorization scopes/loaders; no CRUD endpoints or mutations.

Future writes must use a transaction plus row locks or conditional updates to prevent
state changes between authorization and persistence. These loaders grant no write by themselves.
"""
from uuid import UUID

from sqlalchemy import Select, and_, select
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from app.core.permissions import Permission
from app.models import Alert, Evidence, Report, RiskAnalysis, User
from app.services.authorization import (
    ALERT_ACTIONS, REPORT_ACTIONS, AuthorizationError, ResourceNotFound,
    authorize_alert, authorize_report, ensure_permission, report_requires_owner,
)


def report_scope(user: User, permission: Permission) -> ColumnElement[bool]:
    ensure_permission(user, permission)
    if permission not in REPORT_ACTIONS:
        raise AuthorizationError()
    scope = Report.organization_id == user.organization_id
    if report_requires_owner(user, permission):
        scope = and_(scope, Report.user_id == user.id)
    return scope


def reports_query(user: User, permission: Permission = Permission.REPORT_READ) -> Select:
    return select(Report).where(report_scope(user, permission))


def alerts_query(user: User, permission: Permission = Permission.ALERT_READ_PREVENTIVE) -> Select:
    ensure_permission(user, permission)
    if permission not in ALERT_ACTIONS:
        raise AuthorizationError()
    return select(Alert).where(Alert.organization_id == user.organization_id)


def load_report(db: Session, user: User, report_id: UUID, permission: Permission) -> Report:
    report = db.scalar(reports_query(user, permission).where(Report.id == report_id)
                       .execution_options(populate_existing=True))
    if report is None:
        raise ResourceNotFound()
    authorize_report(user, report, permission)
    return report


def load_alert(db: Session, user: User, alert_id: UUID, permission: Permission) -> Alert:
    alert = db.scalar(alerts_query(user, permission).where(Alert.id == alert_id)
                      .execution_options(populate_existing=True))
    if alert is None:
        raise ResourceNotFound()
    authorize_alert(user, alert, permission)
    return alert


def load_evidence(db: Session, user: User, report_id: UUID, evidence_id: UUID) -> Evidence:
    result = db.execute(
        select(Evidence, Report).join(Report, Evidence.report_id == Report.id)
        .where(report_scope(user, Permission.EVIDENCE_READ),
               Report.id == report_id, Evidence.id == evidence_id)
        .execution_options(populate_existing=True)
    ).one_or_none()
    if result is None:
        raise ResourceNotFound()
    evidence, report = result
    authorize_report(user, report, Permission.EVIDENCE_READ)
    return evidence


def load_analysis(
    db: Session, user: User, report_id: UUID, analysis_id: UUID,
    permission: Permission = Permission.ANALYSIS_READ_SUMMARY,
) -> RiskAnalysis:
    if permission not in {Permission.ANALYSIS_READ_SUMMARY, Permission.ANALYSIS_READ_DETAIL}:
        raise AuthorizationError()
    result = db.execute(
        select(RiskAnalysis, Report).join(Report, RiskAnalysis.report_id == Report.id)
        .where(report_scope(user, permission), Report.id == report_id,
               RiskAnalysis.id == analysis_id)
        .execution_options(populate_existing=True)
    ).one_or_none()
    if result is None:
        raise ResourceNotFound()
    analysis, report = result
    authorize_report(user, report, permission)
    return analysis
