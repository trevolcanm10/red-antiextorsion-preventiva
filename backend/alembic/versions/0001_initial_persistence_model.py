"""initial persistence model

Revision ID: 0001
Revises: 
Create Date: 2026-10-17 20:08:28.989928

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '0001'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


ENUMS = (
    postgresql.ENUM("ACTIVO", "INACTIVO", name="estado_general"),
    postgresql.ENUM("USUARIO", "MODERADOR", "ADMINISTRADOR", name="rol_usuario"),
    postgresql.ENUM("REGISTRADO", "EN_ANALISIS", "ANALIZADO", "CERRADO", name="estado_reporte"),
    postgresql.ENUM("BAJO", "MODERADO", "ALTO", "CRITICO", name="nivel_riesgo"),
    postgresql.ENUM("ACTIVA", "ATENDIDA", "CERRADA", name="estado_alerta"),
)


def upgrade() -> None:
    """Upgrade schema."""
    for enum in ENUMS:
        enum.create(op.get_bind(), checkfirst=False)
    op.create_table('indicators',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('name', sa.String(length=150), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('category', sa.String(length=100), nullable=True),
    sa.Column('weight', sa.Numeric(precision=5, scale=2), nullable=True),
    sa.Column('status', postgresql.ENUM('ACTIVO', 'INACTIVO', name='estado_general', create_type=False), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_indicators')),
    sa.UniqueConstraint('name', name=op.f('uq_indicators_name'))
    )
    op.create_table('locations',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('department', sa.String(length=100), nullable=True),
    sa.Column('province', sa.String(length=100), nullable=True),
    sa.Column('district', sa.String(length=100), nullable=True),
    sa.Column('zone_reference', sa.String(length=255), nullable=True),
    sa.Column('latitude', sa.Numeric(precision=9, scale=6), nullable=True),
    sa.Column('longitude', sa.Numeric(precision=9, scale=6), nullable=True),
    sa.CheckConstraint('latitude BETWEEN -90 AND 90', name=op.f('ck_locations_latitude_range')),
    sa.CheckConstraint('longitude BETWEEN -180 AND 180', name=op.f('ck_locations_longitude_range')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_locations'))
    )
    op.create_table('organizations',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('name', sa.String(length=150), nullable=False),
    sa.Column('type', sa.String(length=50), nullable=True),
    sa.Column('status', postgresql.ENUM('ACTIVO', 'INACTIVO', name='estado_general', create_type=False), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_organizations'))
    )
    op.create_table('users',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('organization_id', sa.Uuid(), nullable=False),
    sa.Column('name', sa.String(length=150), nullable=False),
    sa.Column('email', sa.String(length=255), nullable=False),
    sa.Column('password_hash', sa.String(length=255), nullable=False),
    sa.Column('role', postgresql.ENUM('USUARIO', 'MODERADOR', 'ADMINISTRADOR', name='rol_usuario', create_type=False), nullable=False),
    sa.Column('status', postgresql.ENUM('ACTIVO', 'INACTIVO', name='estado_general', create_type=False), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('last_login', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], name=op.f('fk_users_organization_id_organizations'), onupdate='RESTRICT', ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_users')),
    sa.UniqueConstraint('email', name=op.f('uq_users_email')),
    sa.UniqueConstraint('id', 'organization_id', name=op.f('uq_users_id'))
    )
    op.create_index(op.f('ix_users_organization_id'), 'users', ['organization_id'], unique=False)
    op.create_table('reports',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('organization_id', sa.Uuid(), nullable=False),
    sa.Column('location_id', sa.Uuid(), nullable=True),
    sa.Column('type', sa.String(length=100), nullable=False),
    sa.Column('description', sa.Text(), nullable=False),
    sa.Column('incident_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('registered_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('status', postgresql.ENUM('REGISTRADO', 'EN_ANALISIS', 'ANALIZADO', 'CERRADO', name='estado_reporte', create_type=False), nullable=False),
    sa.ForeignKeyConstraint(['location_id'], ['locations.id'], name=op.f('fk_reports_location_id_locations'), onupdate='RESTRICT', ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], name=op.f('fk_reports_organization_id_organizations'), onupdate='RESTRICT', ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['user_id', 'organization_id'], ['users.id', 'users.organization_id'], name='fk_reports_user_organization', onupdate='RESTRICT', ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_reports'))
    )
    op.create_index(op.f('ix_reports_location_id'), 'reports', ['location_id'], unique=False)
    op.create_index(op.f('ix_reports_organization_id'), 'reports', ['organization_id'], unique=False)
    op.create_index('ix_reports_user_id_organization_id', 'reports', ['user_id', 'organization_id'], unique=False)
    op.create_table('evidence',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('report_id', sa.Uuid(), nullable=False),
    sa.Column('file_type', sa.String(length=50), nullable=True),
    sa.Column('file_path', sa.String(length=500), nullable=False),
    sa.Column('file_name', sa.String(length=255), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['report_id'], ['reports.id'], name=op.f('fk_evidence_report_id_reports'), onupdate='RESTRICT', ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_evidence'))
    )
    op.create_index(op.f('ix_evidence_report_id'), 'evidence', ['report_id'], unique=False)
    op.create_table('report_indicators',
    sa.Column('report_id', sa.Uuid(), nullable=False),
    sa.Column('indicator_id', sa.Uuid(), nullable=False),
    sa.Column('value', sa.Text(), nullable=True),
    sa.Column('confidence', sa.Numeric(precision=5, scale=4), nullable=True),
    sa.Column('detected_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint('confidence BETWEEN 0 AND 1', name=op.f('ck_report_indicators_confidence_range')),
    sa.ForeignKeyConstraint(['indicator_id'], ['indicators.id'], name=op.f('fk_report_indicators_indicator_id_indicators'), onupdate='RESTRICT', ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['report_id'], ['reports.id'], name=op.f('fk_report_indicators_report_id_reports'), onupdate='RESTRICT', ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('report_id', 'indicator_id', name=op.f('pk_report_indicators'))
    )
    op.create_index(op.f('ix_report_indicators_indicator_id'), 'report_indicators', ['indicator_id'], unique=False)
    op.create_table('risk_analyses',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('report_id', sa.Uuid(), nullable=False),
    sa.Column('risk_level', postgresql.ENUM('BAJO', 'MODERADO', 'ALTO', 'CRITICO', name='nivel_riesgo', create_type=False), nullable=False),
    sa.Column('score', sa.Numeric(precision=6, scale=2), nullable=False),
    sa.Column('justification', sa.Text(), nullable=True),
    sa.Column('model_version', sa.String(length=50), nullable=True),
    sa.Column('analyzed_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['report_id'], ['reports.id'], name=op.f('fk_risk_analyses_report_id_reports'), onupdate='RESTRICT', ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_risk_analyses'))
    )
    op.create_index(op.f('ix_risk_analyses_report_id'), 'risk_analyses', ['report_id'], unique=False)
    op.create_table('alerts',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('analysis_id', sa.Uuid(), nullable=False),
    sa.Column('organization_id', sa.Uuid(), nullable=False),
    sa.Column('type', sa.String(length=100), nullable=False),
    sa.Column('level', postgresql.ENUM('BAJO', 'MODERADO', 'ALTO', 'CRITICO', name='nivel_riesgo', create_type=False), nullable=False),
    sa.Column('title', sa.String(length=200), nullable=False),
    sa.Column('message', sa.Text(), nullable=False),
    sa.Column('status', postgresql.ENUM('ACTIVA', 'ATENDIDA', 'CERRADA', name='estado_alerta', create_type=False), nullable=False),
    sa.Column('generated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('closed_at', sa.DateTime(timezone=True), nullable=True),
    sa.CheckConstraint('closed_at >= generated_at', name=op.f('ck_alerts_closure_order')),
    sa.ForeignKeyConstraint(['analysis_id'], ['risk_analyses.id'], name=op.f('fk_alerts_analysis_id_risk_analyses'), onupdate='RESTRICT', ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], name=op.f('fk_alerts_organization_id_organizations'), onupdate='RESTRICT', ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_alerts'))
    )
    op.create_index(op.f('ix_alerts_analysis_id'), 'alerts', ['analysis_id'], unique=False)
    op.create_index(op.f('ix_alerts_organization_id'), 'alerts', ['organization_id'], unique=False)
    op.create_table('analysis_indicators',
    sa.Column('analysis_id', sa.Uuid(), nullable=False),
    sa.Column('indicator_id', sa.Uuid(), nullable=False),
    sa.Column('applied_weight', sa.Numeric(precision=5, scale=2), nullable=True),
    sa.Column('contribution', sa.Numeric(precision=6, scale=2), nullable=True),
    sa.ForeignKeyConstraint(['analysis_id'], ['risk_analyses.id'], name=op.f('fk_analysis_indicators_analysis_id_risk_analyses'), onupdate='RESTRICT', ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['indicator_id'], ['indicators.id'], name=op.f('fk_analysis_indicators_indicator_id_indicators'), onupdate='RESTRICT', ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('analysis_id', 'indicator_id', name=op.f('pk_analysis_indicators'))
    )
    op.create_index(op.f('ix_analysis_indicators_indicator_id'), 'analysis_indicators', ['indicator_id'], unique=False)
    # Ownership is immutable, so alert validation cannot be invalidated later.
    op.execute("""
        CREATE FUNCTION prevent_report_organization_change() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF NEW.organization_id IS DISTINCT FROM OLD.organization_id THEN
                RAISE EXCEPTION 'report organization is immutable' USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END;
        $$
    """)
    op.execute("""
        CREATE TRIGGER reports_immutable_organization
        BEFORE UPDATE OF organization_id ON reports
        FOR EACH ROW EXECUTE FUNCTION prevent_report_organization_change()
    """)
    op.execute("""
        CREATE FUNCTION prevent_analysis_report_change() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF NEW.report_id IS DISTINCT FROM OLD.report_id THEN
                RAISE EXCEPTION 'analysis report is immutable' USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END;
        $$
    """)
    op.execute("""
        CREATE TRIGGER analyses_immutable_report
        BEFORE UPDATE OF report_id ON risk_analyses
        FOR EACH ROW EXECUTE FUNCTION prevent_analysis_report_change()
    """)
    op.execute("""
        CREATE FUNCTION validate_alert_organization() RETURNS trigger
        LANGUAGE plpgsql AS $$
        DECLARE expected_organization uuid;
        BEGIN
            SELECT r.organization_id INTO expected_organization
            FROM risk_analyses a JOIN reports r ON r.id = a.report_id
            WHERE a.id = NEW.analysis_id;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'analysis does not exist' USING ERRCODE = '23503';
            END IF;
            IF NEW.organization_id IS DISTINCT FROM expected_organization THEN
                RAISE EXCEPTION 'alert organization must match report organization'
                    USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END;
        $$
    """)
    op.execute("""
        CREATE TRIGGER alerts_validate_organization
        BEFORE INSERT OR UPDATE OF analysis_id, organization_id ON alerts
        FOR EACH ROW EXECUTE FUNCTION validate_alert_organization()
    """)



def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DROP TRIGGER alerts_validate_organization ON alerts")
    op.execute("DROP FUNCTION validate_alert_organization()")
    op.execute("DROP TRIGGER analyses_immutable_report ON risk_analyses")
    op.execute("DROP FUNCTION prevent_analysis_report_change()")
    op.execute("DROP TRIGGER reports_immutable_organization ON reports")
    op.execute("DROP FUNCTION prevent_report_organization_change()")
    op.drop_index(op.f('ix_analysis_indicators_indicator_id'), table_name='analysis_indicators')
    op.drop_table('analysis_indicators')
    op.drop_index(op.f('ix_alerts_organization_id'), table_name='alerts')
    op.drop_index(op.f('ix_alerts_analysis_id'), table_name='alerts')
    op.drop_table('alerts')
    op.drop_index(op.f('ix_risk_analyses_report_id'), table_name='risk_analyses')
    op.drop_table('risk_analyses')
    op.drop_index(op.f('ix_report_indicators_indicator_id'), table_name='report_indicators')
    op.drop_table('report_indicators')
    op.drop_index(op.f('ix_evidence_report_id'), table_name='evidence')
    op.drop_table('evidence')
    op.drop_index('ix_reports_user_id_organization_id', table_name='reports')
    op.drop_index(op.f('ix_reports_organization_id'), table_name='reports')
    op.drop_index(op.f('ix_reports_location_id'), table_name='reports')
    op.drop_table('reports')
    op.drop_index(op.f('ix_users_organization_id'), table_name='users')
    op.drop_table('users')
    op.drop_table('organizations')
    op.drop_table('locations')
    op.drop_table('indicators')
    for enum in reversed(ENUMS):
        enum.drop(op.get_bind(), checkfirst=False)
