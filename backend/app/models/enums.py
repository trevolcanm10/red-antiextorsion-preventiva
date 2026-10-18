from enum import StrEnum


class GeneralStatus(StrEnum):
    ACTIVE = "ACTIVO"
    INACTIVE = "INACTIVO"


class UserRole(StrEnum):
    USER = "USUARIO"
    MODERATOR = "MODERADOR"
    ADMINISTRATOR = "ADMINISTRADOR"


class ReportStatus(StrEnum):
    REGISTERED = "REGISTRADO"
    IN_ANALYSIS = "EN_ANALISIS"
    ANALYZED = "ANALIZADO"
    CLOSED = "CERRADO"


class RiskLevel(StrEnum):
    LOW = "BAJO"
    MODERATE = "MODERADO"
    HIGH = "ALTO"
    CRITICAL = "CRITICO"


class AlertStatus(StrEnum):
    ACTIVE = "ACTIVA"
    ATTENDED = "ATENDIDA"
    CLOSED = "CERRADA"
