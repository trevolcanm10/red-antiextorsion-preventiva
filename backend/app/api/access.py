"""Dependency factories for future routes; this module registers no endpoints.

Return values are internal ORM instances. Routes must select an authorized response
projection explicitly. A dependency is not permission to serialize all attributes.
"""
from collections.abc import Callable
from uuid import UUID

from app.api.dependencies import CurrentUser, Database, authorization_errors
from app.core.permissions import Permission
from app.models import Alert, Evidence, Report, RiskAnalysis
from app.models.enums import AlertStatus
from app.repositories.access import load_alert, load_analysis, load_evidence, load_report
from app.services.authorization import authorize_alert_transition


def require_report(permission: Permission) -> Callable[..., Report]:
    def dependency(report_id: UUID, user: CurrentUser, db: Database) -> Report:
        with authorization_errors():
            return load_report(db, user, report_id, permission)
    return dependency


def require_alert(permission: Permission) -> Callable[..., Alert]:
    def dependency(alert_id: UUID, user: CurrentUser, db: Database) -> Alert:
        with authorization_errors():
            return load_alert(db, user, alert_id, permission)
    return dependency


def require_alert_transition(target: AlertStatus) -> Callable[..., Alert]:
    if not isinstance(target, AlertStatus) or target not in {AlertStatus.ATTENDED, AlertStatus.CLOSED}:
        raise ValueError("Only attending or closing alerts is supported")
    permission = Permission.ALERT_ATTEND if target == AlertStatus.ATTENDED else Permission.ALERT_CLOSE

    def dependency(alert_id: UUID, user: CurrentUser, db: Database) -> Alert:
        with authorization_errors():
            alert = load_alert(db, user, alert_id, permission)
            authorize_alert_transition(user, alert, target)
            return alert
    return dependency


def require_evidence() -> Callable[..., Evidence]:
    def dependency(
        report_id: UUID, evidence_id: UUID, user: CurrentUser, db: Database,
    ) -> Evidence:
        with authorization_errors():
            return load_evidence(db, user, report_id, evidence_id)
    return dependency


def require_analysis(permission: Permission) -> Callable[..., RiskAnalysis]:
    def dependency(
        report_id: UUID, analysis_id: UUID, user: CurrentUser, db: Database,
    ) -> RiskAnalysis:
        with authorization_errors():
            return load_analysis(db, user, report_id, analysis_id, permission)
    return dependency
