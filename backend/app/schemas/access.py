"""Safe projections for future resource endpoints, separate from internal schemas."""
from uuid import UUID

from app.models.enums import AlertStatus, RiskLevel
from app.schemas.base import Schema, UTCDateTime


class AlertPreventiveRead(Schema):
    id: UUID
    level: RiskLevel
    status: AlertStatus
    generated_at: UTCDateTime


class AlertAuthorizedDetailRead(AlertPreventiveRead):
    organization_id: UUID
    analysis_id: UUID
    closed_at: UTCDateTime | None
    # No reporter, coordinates, evidence path, raw title or free-text message.


class AnalysisSummaryRead(Schema):
    id: UUID
    report_id: UUID
    risk_level: RiskLevel
    analyzed_at: UTCDateTime
