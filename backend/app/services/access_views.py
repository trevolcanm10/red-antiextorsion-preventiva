"""Authorize first, project second. Never serialize raw ORM objects to clients."""
from app.core.permissions import Permission
from app.models import Alert, Report, RiskAnalysis, User
from app.schemas.access import AlertAuthorizedDetailRead, AlertPreventiveRead, AnalysisSummaryRead
from app.services.authorization import ResourceNotFound, authorize_alert, authorize_report


def preventive_alert_view(user: User, alert: Alert) -> AlertPreventiveRead:
    authorize_alert(user, alert, Permission.ALERT_READ_PREVENTIVE)
    return AlertPreventiveRead.model_validate(alert)


def authorized_alert_detail_view(user: User, alert: Alert) -> AlertAuthorizedDetailRead:
    authorize_alert(user, alert, Permission.ALERT_READ_DETAIL)
    return AlertAuthorizedDetailRead.model_validate(alert)


def analysis_summary_view(user: User, report: Report, analysis: RiskAnalysis) -> AnalysisSummaryRead:
    authorize_report(user, report, Permission.ANALYSIS_READ_SUMMARY)
    if analysis.report_id != report.id:
        raise ResourceNotFound()
    return AnalysisSummaryRead.model_validate(analysis)
