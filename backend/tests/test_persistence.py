"""Run only against an explicitly supplied, disposable PostgreSQL test database.

PERSISTENCE_TEST_DATABASE_URL must end in a database name prefixed persistence_test.
This suite never falls back to the application database or reads its credentials.
"""
import os
import importlib
from io import StringIO
from pathlib import Path
import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, select, text, update
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session
from pydantic import ValidationError

from app.db.base import Base
from app.models import (Organization, User, Location, Report, Evidence, Indicator,
                        ReportIndicator, RiskAnalysis, AnalysisIndicator, Alert)
from app.models.enums import GeneralStatus, UserRole, ReportStatus, RiskLevel, AlertStatus
from app.schemas.report_indicator import ReportIndicatorCreate, ReportIndicatorRead
from app.schemas.report import ReportRead
from app.schemas.user import UserRead, UserCreate
from app.schemas.evidence import EvidenceRead
from app.schemas.location import LocationRead


class SchemaTests(unittest.TestCase):
    def test_confidence_text_and_utc(self):
        timestamp = datetime(2026, 1, 1, 12, tzinfo=timezone(timedelta(hours=-5)))
        value = ReportIndicatorCreate(report_id=uuid4(), indicator_id=uuid4(),
                                     value="llamada reiterada", confidence="0.7500",
                                     detected_at=timestamp)
        self.assertEqual(value.value, "llamada reiterada")
        self.assertEqual(value.confidence, Decimal("0.7500"))
        self.assertEqual(value.detected_at.hour, 17)
        self.assertEqual(value.detected_at.utcoffset(), timedelta(0))
        for confidence in (-0.1, 1.1):
            with self.subTest(confidence=confidence), self.assertRaises(ValidationError):
                ReportIndicatorCreate(**{**value.model_dump(), "confidence": confidence})
        with self.assertRaises(ValidationError):
            ReportIndicatorCreate(**{**value.model_dump(), "detected_at": timestamp.replace(tzinfo=None)})

    def test_all_schema_modules_import(self):
        for path in Path("app/schemas").glob("*.py"):
            if path.stem not in ("__init__", "base"):
                module = importlib.import_module("app.schemas." + path.stem)
                for name, cls in vars(module).items():
                    if name.endswith(("Create", "Read", "Internal")) and hasattr(cls, "model_json_schema"):
                        with self.subTest(schema=name):
                            cls.model_json_schema()

    def test_offline_migration_sql(self):
        output = StringIO()
        config = Config("alembic.ini", output_buffer=output)
        config.set_main_option("sqlalchemy.url", "postgresql+psycopg://unused/unused")
        command.upgrade(config, "head", sql=True)
        sql = output.getvalue()
        self.assertEqual(sql.count("CREATE TYPE "), 5)
        self.assertEqual(sql.count("CREATE TRIGGER "), 3)
        self.assertIn("TIMESTAMP WITH TIME ZONE", sql)
        output.truncate(0); output.seek(0)
        command.downgrade(config, "0001:base", sql=True)
        self.assertEqual(output.getvalue().count("DROP TYPE "), 5)
        self.assertEqual(output.getvalue().count("DROP FUNCTION "), 3)

    def test_sensitive_fields_are_absent(self):
        for schema, hidden in [(UserRead, {"password_hash"}), (ReportRead, {"user_id"}),
                               (EvidenceRead, {"file_path"}),
                               (LocationRead, {"latitude", "longitude"}),
                               (ReportIndicatorRead, {"value"})]:
            with self.subTest(schema=schema.__name__):
                self.assertTrue(hidden.isdisjoint(schema.model_fields))
        self.assertNotIn("password_hash", UserCreate.model_fields)


@unittest.skipUnless(os.getenv("PERSISTENCE_TEST_DATABASE_URL"), "explicit disposable test database required")
class PostgreSQLTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        url = make_url(os.environ["PERSISTENCE_TEST_DATABASE_URL"])
        if url.get_backend_name() != "postgresql" or not (url.database or "").startswith("persistence_test"):
            raise RuntimeError("Refusing to migrate a non-test database")
        cls.engine = create_engine(url, connect_args={"options": "-c timezone=UTC"})
        cls.config = Config("alembic.ini")
        cls.config.set_main_option("sqlalchemy.url", url.render_as_string(hide_password=False).replace("%", "%%"))
        with cls.engine.connect() as c:
            tables = set(inspect(c).get_table_names())
            if tables - {"alembic_version"}:
                raise RuntimeError("Test database must initially contain no domain tables")
        # Exercise every object lifecycle, including shared enums and functions.
        command.upgrade(cls.config, "head")
        command.downgrade(cls.config, "base")
        with cls.engine.connect() as c:
            assert set(inspect(c).get_table_names()) <= {"alembic_version"}
            assert not inspect(c).get_enums()
            assert c.scalar(text("SELECT count(*) FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname='public' AND p.proname IN ('validate_alert_organization','prevent_report_organization_change','prevent_analysis_report_change')")) == 0
        command.upgrade(cls.config, "head")
        command.check(cls.config)

    @classmethod
    def tearDownClass(cls):
        command.downgrade(cls.config, "base")
        cls.engine.dispose()

    def setUp(self):
        self.connection = self.engine.connect()
        self.transaction = self.connection.begin()
        self.session = Session(self.connection)
        self.o1 = Organization(name="Synthetic A", status=GeneralStatus.ACTIVE)
        self.o2 = Organization(name="Synthetic B", status=GeneralStatus.ACTIVE)
        self.session.add_all([self.o1, self.o2]); self.session.flush()
        self.u1 = User(organization_id=self.o1.id, name="Synthetic user A", email="a@example.invalid",
                       password_hash="synthetic-not-a-credential", role=UserRole.USER, status=GeneralStatus.ACTIVE)
        self.u2 = User(organization_id=self.o2.id, name="Synthetic user B", email="b@example.invalid",
                       password_hash="synthetic-not-a-credential", role=UserRole.USER, status=GeneralStatus.ACTIVE)
        self.session.add_all([self.u1, self.u2]); self.session.flush()
        self.r1 = Report(user_id=self.u1.id, organization_id=self.o1.id, type="synthetic", description="synthetic", status=ReportStatus.REGISTERED)
        self.r2 = Report(user_id=self.u2.id, organization_id=self.o2.id, type="synthetic", description="synthetic", status=ReportStatus.REGISTERED)
        self.session.add_all([self.r1, self.r2]); self.session.flush()
        self.a1 = RiskAnalysis(report_id=self.r1.id, risk_level=RiskLevel.LOW, score=Decimal("1.00"))
        self.a2 = RiskAnalysis(report_id=self.r2.id, risk_level=RiskLevel.LOW, score=Decimal("2.00"))
        self.session.add_all([self.a1, self.a2]); self.session.flush()

    def tearDown(self):
        self.session.close()
        self.transaction.rollback()
        self.connection.close()

    def rejects(self, operation, sqlstate):
        with self.assertRaises(DBAPIError) as error:
            with self.session.begin_nested():
                operation()
                self.session.flush()
        self.assertEqual(error.exception.orig.sqlstate, sqlstate)

    def alert(self, analysis=None, organization=None):
        return Alert(analysis_id=analysis or self.a1.id, organization_id=organization or self.o1.id,
                     type="synthetic", level=RiskLevel.LOW, title="Synthetic", message="Synthetic", status=AlertStatus.ACTIVE)

    def test_metadata_and_types(self):
        inspector = inspect(self.connection)
        self.assertEqual(set(inspector.get_table_names()) - {"alembic_version"}, set(Base.metadata.tables))
        self.assertEqual(len(Base.metadata.tables), 10)
        self.assertEqual(len(inspector.get_enums()), 5)
        for table in Base.metadata.sorted_tables:
            for fk in inspector.get_foreign_keys(table.name):
                self.assertEqual(fk["options"]["ondelete"], "RESTRICT")
                self.assertEqual(fk["options"]["onupdate"], "RESTRICT")
            for col in inspector.get_columns(table.name):
                if col["name"] in {"status", "role", "risk_level", "level"}:
                    self.assertIsNone(col["default"])
                if "TIMESTAMP" in str(col["type"]):
                    self.assertTrue(col["type"].timezone)
        self.assertEqual(self.r1.id.version, 4)
        self.assertIsNotNone(self.r1.registered_at.tzinfo)

    def test_report_rejects_other_organization_user(self):
        self.rejects(lambda: self.session.execute(update(Report).where(Report.id == self.r1.id).values(user_id=self.u2.id)), "23503")
        self.rejects(lambda: self.session.add(Report(user_id=self.u2.id, organization_id=self.o1.id, type="x", description="x", status=ReportStatus.REGISTERED)), "23503")

    def test_user_organization_update_is_restricted(self):
        self.rejects(lambda: self.session.execute(update(User).where(User.id == self.u1.id).values(organization_id=self.o2.id)), "23503")

    def test_ownership_is_immutable(self):
        self.rejects(lambda: self.session.execute(update(Report).where(Report.id == self.r1.id).values(organization_id=self.o2.id, user_id=self.u2.id)), "23514")
        self.rejects(lambda: self.session.execute(update(RiskAnalysis).where(RiskAnalysis.id == self.a1.id).values(report_id=self.r2.id)), "23514")
        # Writing the same ownership value remains valid.
        self.session.execute(update(Report).where(Report.id == self.r1.id).values(organization_id=self.o1.id))
        self.session.execute(update(RiskAnalysis).where(RiskAnalysis.id == self.a1.id).values(report_id=self.r1.id))

    def test_alert_insert_and_updates(self):
        self.rejects(lambda: self.session.add(self.alert(organization=self.o2.id)), "23514")
        self.rejects(lambda: self.session.add(self.alert(analysis=uuid4())), "23503")
        alert = self.alert(); self.session.add(alert); self.session.flush()
        self.rejects(lambda: self.session.execute(update(Alert).where(Alert.id == alert.id).values(analysis_id=self.a2.id)), "23514")
        self.rejects(lambda: self.session.execute(update(Alert).where(Alert.id == alert.id).values(organization_id=self.o2.id)), "23514")
        self.session.execute(update(Alert).where(Alert.id == alert.id).values(analysis_id=self.a2.id, organization_id=self.o2.id))
        self.session.expire_all()
        self.assertEqual(alert.analysis.report.organization_id, self.o2.id)

    def test_history_and_bidirectional_relationships(self):
        analysis = RiskAnalysis(report=self.r1, risk_level=RiskLevel.HIGH, score=Decimal("9.00"))
        indicator = Indicator(name="Synthetic signal", status=GeneralStatus.ACTIVE)
        self.session.add_all([analysis, indicator]); self.session.flush()
        self.session.add_all([
            Evidence(report=self.r1, file_path="private/synthetic"),
            ReportIndicator(report=self.r1, indicator=indicator, value="texto", confidence=Decimal("0.5"), detected_at=datetime.now(timezone.utc)),
            AnalysisIndicator(analysis=analysis, indicator=indicator, applied_weight=Decimal("1")),
            self.alert(),
        ]); self.session.flush(); self.session.expire_all()
        self.assertEqual(len(self.r1.risk_analyses), 2)
        self.assertEqual(self.r1.user.organization, self.o1)
        self.assertEqual(self.r1.organization, self.o1)
        self.assertEqual(self.r1.indicator_links[0].indicator, indicator)
        self.assertEqual(indicator.analysis_links[0].analysis, analysis)
        self.assertEqual(self.a1.alerts[0].organization, self.o1)
        self.assertEqual(len(self.r1.evidence), 1)
        self.assertNotIn("user_id", ReportRead.model_validate(self.r1).model_dump())

    def test_duplicate_association_and_confidence(self):
        indicator = Indicator(name="Synthetic signal", status=GeneralStatus.ACTIVE)
        self.session.add(indicator); self.session.flush()
        for confidence in (Decimal("-0.1"), Decimal("1.1")):
            self.rejects(lambda: self.session.add(ReportIndicator(report_id=self.r1.id, indicator_id=indicator.id, confidence=confidence, detected_at=datetime.now(timezone.utc))), "23514")
        def insert_link():
            self.session.execute(ReportIndicator.__table__.insert().values(report_id=self.r1.id, indicator_id=indicator.id, value="texto", detected_at=datetime.now(timezone.utc)))
        insert_link()
        self.rejects(insert_link, "23505")
        def insert_analysis_link():
            self.session.execute(AnalysisIndicator.__table__.insert().values(analysis_id=self.a1.id, indicator_id=indicator.id))
        insert_analysis_link()
        self.rejects(insert_analysis_link, "23505")

    def test_restrict_delete_including_loaded_children(self):
        self.assertEqual(len(self.u1.reports), 1)
        self.rejects(lambda: self.session.delete(self.u1), "23503")
        self.assertEqual(len(self.r1.risk_analyses), 1)
        self.rejects(lambda: self.session.delete(self.r1), "23503")
        self.rejects(lambda: self.session.delete(self.o1), "23503")

    def test_optional_location_and_coordinate_checks(self):
        self.assertIsNone(self.r1.location_id)
        for values in ({"latitude": 91}, {"longitude": -181}):
            self.rejects(lambda: self.session.add(Location(**values)), "23514")
        location = Location(latitude=Decimal("-12.046400"), longitude=Decimal("-77.042800"))
        self.r1.location = location; self.session.add(location); self.session.flush()
        self.assertEqual(location.reports, [self.r1])

    def test_required_states_uniques_and_fks(self):
        self.rejects(lambda: self.session.execute(Organization.__table__.insert().values(id=uuid4(), name="No status")), "23502")
        self.rejects(lambda: self.session.execute(Organization.__table__.insert().values(id=uuid4(), name="Bad status", status="BAD")), "22P02")
        self.rejects(lambda: self.session.add(User(organization_id=self.o1.id, name="duplicate", email=self.u1.email, password_hash="synthetic", role=UserRole.USER, status=GeneralStatus.ACTIVE)), "23505")
        self.rejects(lambda: self.session.add(Evidence(report_id=uuid4(), file_path="synthetic")), "23503")
        self.session.add(Indicator(name="unique", status=GeneralStatus.ACTIVE)); self.session.flush()
        self.rejects(lambda: self.session.add(Indicator(name="unique", status=GeneralStatus.ACTIVE)), "23505")

    def test_alert_closure_order(self):
        alert = self.alert()
        alert.generated_at = datetime.now(timezone.utc)
        alert.closed_at = alert.generated_at - timedelta(seconds=1)
        self.rejects(lambda: self.session.add(alert), "23514")


if __name__ == "__main__":
    unittest.main()
