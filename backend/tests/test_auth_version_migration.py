"""Incremental migration verification with a complete synthetic v0001 graph."""
import os
import unittest
from uuid import uuid4

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError


@unittest.skipUnless(os.getenv("AUTH_VERSION_TEST_DATABASE_URL"), "explicit isolated migration DB required")
class AuthVersionMigrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        url = make_url(os.environ["AUTH_VERSION_TEST_DATABASE_URL"])
        if url.get_backend_name() != "postgresql" or not (url.database or "").startswith("persistence_test"):
            raise RuntimeError("Refusing non-test database")
        cls.engine = create_engine(url, hide_parameters=True)
        with cls.engine.connect() as connection:
            if set(inspect(connection).get_table_names()) - {"alembic_version"}:
                raise RuntimeError("Migration test DB must initially contain no domain tables")
        cls.config = Config("alembic.ini")
        cls.config.set_main_option("sqlalchemy.url", url.render_as_string(hide_password=False).replace("%", "%%"))

    @classmethod
    def tearDownClass(cls):
        cls.engine.dispose()

    def setUp(self):
        command.upgrade(self.config, "0001")
        self.ids = {name: uuid4() for name in ("org", "user", "inactive", "location", "report", "evidence", "indicator", "analysis", "alert")}
        params = self.ids
        # SQL rather than current ORM: the new column does not exist yet.
        statements = [
            "INSERT INTO organizations(id,name,status) VALUES (:org,'Synthetic legacy','ACTIVO')",
            "INSERT INTO users(id,organization_id,name,email,password_hash,role,status) VALUES (:user,:org,'Synthetic legacy admin','legacy@example.invalid','synthetic-unused-hash','ADMINISTRADOR','ACTIVO')",
            "INSERT INTO users(id,organization_id,name,email,password_hash,role,status) VALUES (:inactive,:org,'Synthetic legacy inactive','inactive@example.invalid','synthetic-unused-hash','USUARIO','INACTIVO')",
            "INSERT INTO locations(id,department,latitude,longitude) VALUES (:location,'Synthetic',-12.0,-77.0)",
            "INSERT INTO reports(id,user_id,organization_id,location_id,type,description,status) VALUES (:report,:user,:org,:location,'Synthetic','Synthetic legacy description','ANALIZADO')",
            "INSERT INTO evidence(id,report_id,file_path) VALUES (:evidence,:report,'private/synthetic-legacy')",
            "INSERT INTO indicators(id,name,weight,status) VALUES (:indicator,'Synthetic legacy signal',1.25,'ACTIVO')",
            "INSERT INTO report_indicators(report_id,indicator_id,value,confidence,detected_at) VALUES (:report,:indicator,'synthetic text',0.5,now())",
            "INSERT INTO risk_analyses(id,report_id,risk_level,score,justification) VALUES (:analysis,:report,'ALTO',1.25,'Synthetic justification')",
            "INSERT INTO analysis_indicators(analysis_id,indicator_id,applied_weight,contribution) VALUES (:analysis,:indicator,1.25,1.25)",
            "INSERT INTO alerts(id,analysis_id,organization_id,type,level,title,message,status) VALUES (:alert,:analysis,:org,'Synthetic','ALTO','Synthetic title','Synthetic message','ACTIVA')",
        ]
        with self.engine.begin() as connection:
            for statement in statements:
                connection.execute(text(statement), params)
        self.before = self.snapshot()

    def tearDown(self):
        command.downgrade(self.config, "base")

    def snapshot(self):
        with self.engine.connect() as connection:
            tables = set(inspect(connection).get_table_names()) - {"alembic_version"}
            return {table: list(connection.scalars(text(
                f"SELECT to_jsonb(t) - 'auth_version' FROM \"{table}\" t "
                "ORDER BY (to_jsonb(t) - 'auth_version')::text"
            ))) for table in sorted(tables)}

    def test_incremental_upgrade_preserves_all_ten_tables_and_initializes_every_user(self):
        command.upgrade(self.config, "head")
        self.assertEqual(self.snapshot(), self.before)
        self.assertEqual(len(self.before), 10)
        with self.engine.connect() as connection:
            users = connection.execute(text("SELECT status,auth_version FROM users ORDER BY status")).all()
            self.assertEqual(users, [("ACTIVO", 1), ("INACTIVO", 1)])
            columns = {col["name"]: col for col in inspect(connection).get_columns("users")}
            self.assertFalse(columns["auth_version"]["nullable"])
            self.assertEqual(str(columns["auth_version"]["default"]), "1")
        with self.engine.begin() as connection:
            connection.execute(text("INSERT INTO users(id,organization_id,name,email,password_hash,role,status) VALUES (:id,:org,'Synthetic new','new@example.invalid','synthetic-unused-hash','USUARIO','ACTIVO')"), {"id": uuid4(), "org": self.ids["org"]})
            self.assertEqual(connection.scalar(text("SELECT auth_version FROM users WHERE email='new@example.invalid'")), 1)
        for invalid in (0, -1, None):
            with self.subTest(invalid=invalid), self.assertRaises(IntegrityError):
                with self.engine.begin() as connection:
                    connection.execute(text("UPDATE users SET auth_version=:invalid WHERE id=:user"), {"invalid": invalid, "user": self.ids["user"]})
        command.check(self.config)

    def test_downgrade_and_upgrade_preserve_original_records(self):
        command.upgrade(self.config, "head")
        with self.engine.begin() as connection:
            connection.execute(text("UPDATE users SET auth_version=3 WHERE id=:user"), self.ids)
        command.downgrade(self.config, "0001")
        self.assertEqual(self.snapshot(), self.before)
        command.upgrade(self.config, "head")
        self.assertEqual(self.snapshot(), self.before)
        # A downgrade intentionally loses the new revocation counter, not existing data.
        with self.engine.connect() as connection:
            self.assertEqual(connection.scalar(text("SELECT min(auth_version) FROM users")), 1)
