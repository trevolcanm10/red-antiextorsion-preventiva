"""Private provisioning tests. Uses only an explicit disposable PostgreSQL database."""
import io
import os
import secrets
import threading
import unittest
import warnings
from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stdout, redirect_stderr
from typing import Callable
from unittest.mock import patch
from uuid import uuid4

from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import create_engine, func, inspect, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.cli.bootstrap import main as bootstrap_main
from app.core.config import AuthSettings, get_auth_settings
from app.core.permissions import Permission, has_permission
from app.core.security import create_access_token, decode_access_token, hash_password, verify_password
from app.db.base import Base
from app.db.dependencies import get_db
from app.main import app
from app.models import Location, Organization, User
from app.models.enums import GeneralStatus, UserRole
from app.schemas.accounts import (BootstrapRequest, BootstrapResult, UserProvisionRequest,
                                 UserRoleChangeRequest, UserStatusChangeRequest)
from app.services.accounts import (AccountConflict, BootstrapConflict, LastAdministrator,
    bootstrap_empty_installation, change_user_role, change_user_status, ensure_admin_survives, provision_user)
from app.services.authorization import AuthorizationError

PASSWORD = "Synthetic-private-password-123!"


def bootstrap_payload():
    return BootstrapRequest(organization_name="Synthetic initial organization", admin_name="Synthetic admin",
                            admin_email="initial@example.invalid", password=PASSWORD)


class AccountContractTests(unittest.TestCase):
    def test_new_password_bounds_and_exact_email(self):
        for size in (14, 1025):
            with self.subTest(size=size), self.assertRaises(ValidationError):
                BootstrapRequest(**{**bootstrap_payload().model_dump(), "password": "a" * size})
        for size in (15, 1024):
            payload = BootstrapRequest(**{**bootstrap_payload().model_dump(), "password": "a" * size})
            self.assertEqual(len(payload.password.get_secret_value()), size)
        payload = BootstrapRequest(**{**bootstrap_payload().model_dump(), "admin_email": " MixedCase@example.invalid ",
                                     "password": " leading trailing "})
        self.assertEqual(payload.admin_email, "MixedCase@example.invalid")
        self.assertEqual(payload.password.get_secret_value(), " leading trailing ")
        self.assertNotIn(PASSWORD, repr(bootstrap_payload()))

    def test_cli_never_prints_credentials_and_does_not_accept_password_argument(self):
        output = io.StringIO()
        result = BootstrapResult(organization_id=uuid4(), administrator_id=uuid4())
        args = ["--organization-name", "Synthetic", "--admin-name", "Synthetic", "--admin-email", "a@example.invalid"]
        with redirect_stdout(output), redirect_stderr(output), patch("sys.stdin.isatty", return_value=True),              patch("app.cli.bootstrap.getpass.getpass", side_effect=[PASSWORD, PASSWORD]),              patch("app.cli.bootstrap.session_factory"),              patch("app.cli.bootstrap.bootstrap_empty_installation", return_value=result):
            self.assertEqual(bootstrap_main(args), 0)
        self.assertNotIn(PASSWORD, output.getvalue())
        self.assertIn(str(result.organization_id), output.getvalue())
        with redirect_stdout(output), redirect_stderr(output), self.assertRaises(SystemExit):
            bootstrap_main([*args, "--password", "not-accepted"])

    def test_cli_refuses_noninteractive_mismatch_and_echo_fallback(self):
        args = ["--organization-name", "Synthetic", "--admin-name", "Synthetic", "--admin-email", "a@example.invalid"]
        output = io.StringIO()
        with redirect_stderr(output), patch("sys.stdin.isatty", return_value=False),              patch("app.cli.bootstrap.session_factory") as factory:
            self.assertEqual(bootstrap_main(args), 2)
            factory.assert_not_called()
        with redirect_stderr(output), patch("sys.stdin.isatty", return_value=True),              patch("app.cli.bootstrap.getpass.getpass", side_effect=[PASSWORD, "different"]),              patch("app.cli.bootstrap.session_factory") as factory:
            self.assertEqual(bootstrap_main(args), 2)
            factory.assert_not_called()
        def cannot_hide(prompt):
            from getpass import GetPassWarning
            warnings.warn("Cannot hide input", GetPassWarning)
        with redirect_stderr(output), patch("sys.stdin.isatty", return_value=True),              patch("app.cli.bootstrap.getpass.getpass", side_effect=cannot_hide),              patch("app.cli.bootstrap.session_factory") as factory:
            self.assertEqual(bootstrap_main(args), 2)
            factory.assert_not_called()
        self.assertNotIn(PASSWORD, output.getvalue())


@unittest.skipUnless(os.getenv("ACCOUNTS_TEST_DATABASE_URL"), "explicit isolated account test DB required")
class AccountDatabaseCase(unittest.TestCase):
    seed = False

    @classmethod
    def setUpClass(cls):
        url = make_url(os.environ["ACCOUNTS_TEST_DATABASE_URL"])
        if url.get_backend_name() != "postgresql" or not (url.database or "").startswith("persistence_test"):
            raise RuntimeError("Refusing non-test database")
        cls.engine = create_engine(url, connect_args={"options": "-c timezone=UTC -c lock_timeout=5000 -c statement_timeout=15000"})
        with cls.engine.connect() as connection:
            if set(inspect(connection).get_table_names()) - {"alembic_version"}:
                raise RuntimeError("Account test database must start with no domain tables")
        cls.config = Config("alembic.ini")
        cls.config.set_main_option("sqlalchemy.url", url.render_as_string(hide_password=False).replace("%", "%%"))
        command.upgrade(cls.config, "head")
        cls.settings = AuthSettings(_env_file=None, JWT_SECRET=secrets.token_urlsafe(48))
        cls.stored_hash = hash_password(PASSWORD)

    @classmethod
    def tearDownClass(cls):
        command.downgrade(cls.config, "base")
        cls.engine.dispose()

    def setUp(self):
        # All tables are on the guarded, disposable test engine. No application URL fallback.
        tables = ", ".join('"' + table.name + '"' for table in Base.metadata.sorted_tables)
        with self.engine.begin() as connection:
            connection.execute(text("TRUNCATE TABLE " + tables))
        if self.seed:
            with Session(self.engine, expire_on_commit=False) as db:
                self.org = Organization(name="Synthetic A", status=GeneralStatus.ACTIVE)
                self.other_org = Organization(name="Synthetic B", status=GeneralStatus.ACTIVE)
                db.add_all([self.org, self.other_org]); db.flush()
                self.actors = {}
                for role in UserRole:
                    self.actors[role] = User(organization_id=self.org.id, name="Synthetic " + role.value,
                        email=role.value + "@example.invalid", password_hash=self.stored_hash,
                        role=role, status=GeneralStatus.ACTIVE)
                self.admin2 = User(organization_id=self.org.id, name="Synthetic second admin",
                    email="admin2@example.invalid", password_hash=self.stored_hash,
                    role=UserRole.ADMINISTRATOR, status=GeneralStatus.ACTIVE)
                self.foreign = User(organization_id=self.other_org.id, name="Synthetic foreign admin",
                    email="foreign@example.invalid", password_hash=self.stored_hash,
                    role=UserRole.ADMINISTRATOR, status=GeneralStatus.ACTIVE)
                db.add_all([*self.actors.values(), self.admin2, self.foreign]); db.commit()

    def scalar(self, query):
        with Session(self.engine) as db:
            return db.scalar(query)


class BootstrapTests(AccountDatabaseCase):
    def test_account_writes_refuse_an_isolation_level_with_stale_snapshots(self):
        with Session(self.engine.execution_options(isolation_level="REPEATABLE READ")) as db:
            with self.assertRaises(AccountConflict):
                bootstrap_empty_installation(db, bootstrap_payload())
        self.assertEqual(self.scalar(select(func.count()).select_from(Organization)), 0)

    def test_bootstrap_creates_one_org_and_admin_without_exposing_hash(self):
        with Session(self.engine) as db:
            result = bootstrap_empty_installation(db, bootstrap_payload())
        self.assertEqual(set(result.model_dump()), {"organization_id", "administrator_id"})
        with Session(self.engine) as db:
            user = db.get(User, result.administrator_id)
            self.assertEqual(user.organization_id, result.organization_id)
            self.assertEqual(user.role, UserRole.ADMINISTRATOR)
            self.assertEqual(user.status, GeneralStatus.ACTIVE)
            self.assertEqual(user.organization.status, GeneralStatus.ACTIVE)
            self.assertTrue(user.password_hash.startswith("$argon2id$"))
            self.assertEqual(verify_password(PASSWORD, user.password_hash), (True, None))
            self.assertEqual(user.id.version, 4)
            self.assertEqual(user.auth_version, 1)
        with Session(self.engine) as db, self.assertRaises(BootstrapConflict):
            bootstrap_empty_installation(db, bootstrap_payload())
        self.assertEqual(self.scalar(select(func.count()).select_from(Organization)), 1)
        self.assertEqual(self.scalar(select(func.count()).select_from(User)), 1)

    def test_bootstrap_checks_all_domain_tables(self):
        with Session(self.engine) as db:
            db.add(Location(zone_reference="Synthetic preexisting")); db.commit()
        with Session(self.engine) as db, self.assertRaises(BootstrapConflict):
            bootstrap_empty_installation(db, bootstrap_payload())
        self.assertEqual(self.scalar(select(func.count()).select_from(Organization)), 0)
        self.assertEqual(self.scalar(select(func.count()).select_from(User)), 0)

    def test_bootstrap_is_atomic_on_failure_after_organization_flush(self):
        with Session(self.engine) as db, patch("app.services.accounts.hash_password", side_effect=RuntimeError("synthetic failure")):
            with self.assertRaises(RuntimeError):
                bootstrap_empty_installation(db, bootstrap_payload())
        self.assertEqual(self.scalar(select(func.count()).select_from(Organization)), 0)
        self.assertEqual(self.scalar(select(func.count()).select_from(User)), 0)

    def test_simultaneous_bootstraps_only_one_succeeds(self):
        barrier = threading.Barrier(2, timeout=10)
        def worker():
            with Session(self.engine) as db:
                barrier.wait()
                try:
                    return bootstrap_empty_installation(db, bootstrap_payload())
                except BootstrapConflict:
                    return "conflict"
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(worker) for _ in range(2)]
            outcomes = [future.result(timeout=20) for future in futures]
        self.assertEqual(sum(isinstance(value, BootstrapResult) for value in outcomes), 1)
        self.assertEqual(outcomes.count("conflict"), 1)
        self.assertEqual(self.scalar(select(func.count()).select_from(Organization)), 1)
        self.assertEqual(self.scalar(select(func.count()).select_from(User)), 1)


class AccountHTTPTests(AccountDatabaseCase):
    seed = True

    def setUp(self):
        super().setUp()
        def database():
            with Session(self.engine) as db:
                yield db
        app.dependency_overrides[get_db] = database
        app.dependency_overrides[get_auth_settings] = lambda: self.settings
        self.startup = patch("app.main.get_auth_settings", return_value=self.settings)
        self.startup.start()
        self.client = TestClient(app).__enter__()

    def tearDown(self):
        self.client.__exit__(None, None, None)
        self.startup.stop()
        app.dependency_overrides.clear()

    def headers(self, actor=None):
        actor = actor or self.actors[UserRole.ADMINISTRATOR]
        return {"Authorization": "Bearer " + create_access_token(actor.id, actor.organization_id, self.settings, auth_version=actor.auth_version)}

    def payload(self, **changes):
        return {"name": "Synthetic new account", "email": "NewCase@example.invalid", "password": PASSWORD,
                "current_password": PASSWORD, "role": "USUARIO", "status": "ACTIVO", **changes}

    def test_admin_reads_only_own_organization_and_accounts(self):
        org = self.client.get("/api/v1/organizations/me", headers=self.headers())
        self.assertEqual(org.status_code, 200)
        self.assertEqual(org.json()["id"], str(self.org.id))
        users = self.client.get("/api/v1/users", headers=self.headers()).json()
        self.assertEqual(users["total"], 4)
        self.assertEqual({user["organization_id"] for user in users["items"]}, {str(self.org.id)})
        for target in (*self.actors.values(), self.admin2):
            self.assertEqual(self.client.get(f"/api/v1/users/{target.id}", headers=self.headers()).status_code, 200)
        missing = self.client.get(f"/api/v1/users/{uuid4()}", headers=self.headers())
        foreign = self.client.get(f"/api/v1/users/{self.foreign.id}", headers=self.headers())
        self.assertEqual(foreign.status_code, 404)
        self.assertEqual(foreign.json(), missing.json())
        injected = self.client.get(f"/api/v1/users?organization_id={self.other_org.id}", headers=self.headers()).json()
        self.assertEqual(injected["total"], 4)

    def test_pagination_and_filters(self):
        page = self.client.get("/api/v1/users?role=ADMINISTRADOR&status=ACTIVO&offset=1&limit=1", headers=self.headers()).json()
        self.assertEqual(page["total"], 2)
        self.assertEqual(len(page["items"]), 1)
        for query in ("limit=101", "limit=0", "offset=-1", "role=SUPERADMIN"):
            self.assertEqual(self.client.get("/api/v1/users?" + query, headers=self.headers()).status_code, 422)

    def test_all_non_admin_roles_and_anonymous_access_denied(self):
        for role in (UserRole.USER, UserRole.MODERATOR):
            headers = self.headers(self.actors[role])
            for path in ("/api/v1/users", f"/api/v1/users/{self.admin2.id}", "/api/v1/organizations/me"):
                self.assertEqual(self.client.get(path, headers=headers).status_code, 403)
            self.assertEqual(self.client.post("/api/v1/users", json=self.payload(), headers=headers).status_code, 403)
            self.assertEqual(self.client.patch(f"/api/v1/users/{self.admin2.id}/role", json={"role": "USUARIO", "current_password": PASSWORD}, headers=headers).status_code, 403)
            self.assertEqual(self.client.patch(f"/api/v1/users/{self.admin2.id}/status", json={"status": "INACTIVO", "current_password": PASSWORD}, headers=headers).status_code, 403)
        self.assertEqual(self.client.post("/api/v1/users", json=self.payload()).status_code, 401)
        self.assertEqual(self.client.get("/api/v1/users").status_code, 401)

    def test_admin_can_create_every_role_but_not_another_organization(self):
        for role in UserRole:
            payload = self.payload(email=role.value + "-created@example.invalid", role=role.value)
            response = self.client.post("/api/v1/users", json=payload, headers=self.headers())
            self.assertEqual(response.status_code, 201)
            self.assertEqual(response.json()["organization_id"], str(self.org.id))
            self.assertEqual(response.json()["role"], role.value)
            self.assertEqual(response.headers["cache-control"], "no-store")
            with Session(self.engine) as db:
                user = db.get(User, response.json()["id"])
                self.assertEqual(verify_password(PASSWORD, user.password_hash), (True, None))
            self.assertNotIn(PASSWORD, response.text)
            self.assertNotIn("password_hash", response.json())
        for field, value in (("organization_id", str(self.other_org.id)), ("id", str(uuid4())),
                             ("password_hash", "synthetic"), ("auth_version", 9), ("created_at", "2026-01-01T00:00:00Z")):
            response = self.client.post("/api/v1/users", json=self.payload(**{field: value}), headers=self.headers())
            self.assertEqual(response.status_code, 422)
        self.assertEqual(self.client.post("/api/v1/organizations", json={}, headers=self.headers()).status_code, 404)

    def test_password_confirmation_and_lengths_never_leak_input(self):
        for size in (14, 1025):
            response = self.client.post("/api/v1/users", json=self.payload(password="s" * size), headers=self.headers())
            self.assertEqual(response.status_code, 422)
            self.assertEqual(response.json(), {"detail": "Invalid request data"})
        response = self.client.post("/api/v1/users", json=self.payload(current_password="synthetic-wrong"), headers=self.headers())
        self.assertEqual(response.status_code, 401)
        self.assertNotIn("synthetic-wrong", response.text)
        self.assertEqual(self.scalar(select(func.count()).select_from(User)), 5)
        for route, body in (("role", {"role": "MODERADOR"}), ("status", {"status": "INACTIVO"})):
            response = self.client.patch(f"/api/v1/users/{self.actors[UserRole.USER].id}/{route}",
                json={**body, "current_password": "synthetic-wrong"}, headers=self.headers())
            self.assertEqual(response.status_code, 401)

    def test_password_1024_is_not_truncated_and_case_matching_is_exact(self):
        password = "long-private-synthetic-" + "x" * (1024 - len("long-private-synthetic-"))
        response = self.client.post("/api/v1/users", json=self.payload(password=password, email=" MixedCase@example.invalid "), headers=self.headers())
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["email"], "MixedCase@example.invalid")
        with Session(self.engine) as db:
            user = db.get(User, response.json()["id"])
            self.assertEqual(verify_password(password, user.password_hash), (True, None))
            self.assertEqual(verify_password(password[:-1], user.password_hash), (False, None))
        self.assertEqual(self.client.post("/api/v1/auth/login", json={"email": " MixedCase@example.invalid ", "password": password}).status_code, 200)
        self.assertEqual(self.client.post("/api/v1/auth/login", json={"email": "mixedcase@example.invalid", "password": password}).status_code, 401)

    def test_duplicate_email_conflict_is_generic_and_does_not_poison_following_requests(self):
        for email in (self.admin2.email, self.foreign.email):
            response = self.client.post("/api/v1/users", json=self.payload(email=email), headers=self.headers())
            self.assertEqual(response.status_code, 409)
            self.assertNotIn(email, response.text)
            self.assertNotIn(str(self.other_org.id), response.text)
            self.assertNotIn("uq_", response.text)
        self.assertEqual(self.client.post("/api/v1/users", json=self.payload(), headers=self.headers()).status_code, 201)

    def test_role_changes_are_explicit_and_self_changes_are_forbidden(self):
        user = self.actors[UserRole.USER]
        token = self.headers(user)
        for role in UserRole:
            response = self.client.patch(f"/api/v1/users/{user.id}/role", json={"role": role.value, "current_password": PASSWORD}, headers=self.headers())
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["role"], role.value)
            profile = self.client.get("/api/v1/auth/me", headers=token)
            self.assertEqual(profile.json()["role"], role.value)
        actor = self.actors[UserRole.ADMINISTRATOR]
        for role in UserRole:
            self.assertEqual(self.client.patch(f"/api/v1/users/{actor.id}/role", json={"role": role.value, "current_password": PASSWORD}, headers=self.headers()).status_code, 403)

    def test_deactivation_is_idempotent_and_reactivation_never_restores_old_tokens(self):
        user = self.actors[UserRole.USER]
        old_headers = self.headers(user)
        for _ in range(2):
            response = self.client.patch(f"/api/v1/users/{user.id}/status", json={"status": "INACTIVO", "current_password": PASSWORD}, headers=self.headers())
            self.assertEqual(response.status_code, 200)
        self.assertEqual(self.client.get("/api/v1/auth/me", headers=old_headers).status_code, 401)
        self.assertEqual(self.client.post("/api/v1/auth/login", json={"email": user.email, "password": PASSWORD}).status_code, 401)
        response = self.client.patch(f"/api/v1/users/{user.id}/status", json={"status": "ACTIVO", "current_password": PASSWORD}, headers=self.headers())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.client.get("/api/v1/auth/me", headers=old_headers).status_code, 401)
        response = self.client.post("/api/v1/users", json=self.payload(status="INACTIVO"), headers=self.headers())
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["status"], "INACTIVO")

    def test_reactivation_keeps_old_tokens_revoked_across_multiple_cycles(self):
        user = self.actors[UserRole.USER]
        old = self.headers(user)
        def change(status):
            response = self.client.patch(f"/api/v1/users/{user.id}/status",
                json={"status": status, "current_password": PASSWORD}, headers=self.headers())
            self.assertEqual(response.status_code, 200)
        def version():
            return self.scalar(select(User.auth_version).where(User.id == user.id))
        self.assertEqual(version(), 1)
        change("INACTIVO")
        self.assertEqual(version(), 2)
        change("INACTIVO")  # Idempotent: no second transition and no counter increase.
        self.assertEqual(version(), 2)
        change("ACTIVO")
        change("ACTIVO")
        self.assertEqual(version(), 2)
        self.assertEqual(self.client.get("/api/v1/auth/me", headers=old).status_code, 401)
        fresh = self.client.post("/api/v1/auth/login", json={"email": user.email, "password": PASSWORD}).json()["access_token"]
        self.assertEqual(decode_access_token(fresh, self.settings).ver, 2)
        self.assertEqual(self.client.get("/api/v1/auth/me", headers={"Authorization": "Bearer " + fresh}).status_code, 200)
        change("INACTIVO")
        self.assertEqual(version(), 3)
        change("ACTIVO")
        self.assertEqual(self.client.get("/api/v1/auth/me", headers=old).status_code, 401)
        self.assertEqual(self.client.get("/api/v1/auth/me", headers={"Authorization": "Bearer " + fresh}).status_code, 401)
        newest = self.client.post("/api/v1/auth/login", json={"email": user.email, "password": PASSWORD}).json()["access_token"]
        self.assertEqual(decode_access_token(newest, self.settings).ver, 3)

    def test_activation_requires_admin_password_same_organization_and_no_self_activation(self):
        user = self.actors[UserRole.USER]
        body = {"status": "ACTIVO", "current_password": PASSWORD}
        self.client.patch(f"/api/v1/users/{user.id}/status", json={"status": "INACTIVO", "current_password": PASSWORD}, headers=self.headers())
        for actor in (self.actors[UserRole.MODERATOR], user):
            response = self.client.patch(f"/api/v1/users/{user.id}/status", json=body, headers=self.headers(actor))
            self.assertEqual(response.status_code, 401 if actor.id == user.id else 403)
        wrong = self.client.patch(f"/api/v1/users/{user.id}/status", json={**body, "current_password": "wrong"}, headers=self.headers())
        self.assertEqual(wrong.status_code, 401)
        self.assertEqual(self.scalar(select(User.status).where(User.id == user.id)), GeneralStatus.INACTIVE)
        foreign = self.client.patch(f"/api/v1/users/{self.foreign.id}/status", json=body, headers=self.headers())
        self.assertEqual(foreign.status_code, 404)
        own = self.client.patch(f"/api/v1/users/{self.actors[UserRole.ADMINISTRATOR].id}/status", json=body, headers=self.headers())
        self.assertEqual(own.status_code, 403)
        admin_headers = self.headers(self.admin2)
        self.client.patch(f"/api/v1/users/{self.admin2.id}/status", json={"status": "INACTIVO", "current_password": PASSWORD}, headers=self.headers())
        self.assertEqual(self.client.patch(f"/api/v1/users/{self.admin2.id}/status", json=body, headers=admin_headers).status_code, 401)
        self.assertEqual(self.client.patch(f"/api/v1/users/{self.admin2.id}/status", json=body, headers=self.headers()).status_code, 200)
        self.assertEqual(self.client.get("/api/v1/users", headers=admin_headers).status_code, 401)

    def test_cannot_deactivate_self_or_access_foreign_targets(self):
        actor = self.actors[UserRole.ADMINISTRATOR]
        self.assertEqual(self.client.patch(f"/api/v1/users/{actor.id}/status", json={"status": "INACTIVO", "current_password": PASSWORD}, headers=self.headers()).status_code, 403)
        for route, body in (("role", {"role": "USUARIO"}), ("status", {"status": "INACTIVO"})):
            self.assertEqual(self.client.patch(f"/api/v1/users/{self.foreign.id}/{route}", json={**body, "current_password": PASSWORD}, headers=self.headers()).status_code, 404)

    def test_last_admin_guard_and_only_admin_cannot_disable_itself(self):
        with Session(self.engine) as db:
            second = db.get(User, self.admin2.id)
            second.status = GeneralStatus.INACTIVE
            db.commit()
            target = db.get(User, self.actors[UserRole.ADMINISTRATOR].id)
            for new_role, new_status in ((UserRole.USER, GeneralStatus.ACTIVE), (UserRole.ADMINISTRATOR, GeneralStatus.INACTIVE)):
                with self.assertRaises(LastAdministrator):
                    ensure_admin_survives(db, target, new_role=new_role, new_status=new_status)
        actor = self.actors[UserRole.ADMINISTRATOR]
        self.assertEqual(self.client.patch(f"/api/v1/users/{actor.id}/status", json={"status": "INACTIVO", "current_password": PASSWORD}, headers=self.headers()).status_code, 403)
        self.assertEqual(self.client.patch(f"/api/v1/users/{actor.id}/role", json={"role": "MODERADOR", "current_password": PASSWORD}, headers=self.headers()).status_code, 403)

    def test_inactive_actor_and_organization_cannot_manage_accounts(self):
        headers = self.headers()
        for model, target_id in ((User, self.actors[UserRole.ADMINISTRATOR].id), (Organization, self.org.id)):
            with Session(self.engine) as db:
                target = db.get(model, target_id); target.status = GeneralStatus.INACTIVE; db.commit()
            self.assertEqual(self.client.get("/api/v1/users", headers=headers).status_code, 401)
            self.assertEqual(self.client.post("/api/v1/users", json=self.payload(), headers=headers).status_code, 401)
            with Session(self.engine) as db:
                target = db.get(model, target_id); target.status = GeneralStatus.ACTIVE; db.commit()

    def test_queries_and_errors_contain_no_hash_password_or_signing_secret(self):
        for path in ("/api/v1/users", f"/api/v1/users/{self.admin2.id}", "/api/v1/organizations/me"):
            response = self.client.get(path, headers=self.headers())
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.headers["cache-control"], "no-store")
            for secret in (PASSWORD, self.stored_hash, self.settings.JWT_SECRET.get_secret_value()):
                self.assertNotIn(secret, response.text)
        invalid = self.client.post("/api/v1/users", json=self.payload(current_password=[PASSWORD]), headers=self.headers())
        self.assertEqual(invalid.status_code, 422)
        self.assertNotIn(PASSWORD, invalid.text)


class AccountConcurrencyTests(AccountDatabaseCase):
    seed = True

    def test_failed_commit_rolls_back_status_and_version_together(self):
        target_id = self.actors[UserRole.USER].id
        with Session(self.engine) as db:
            actor = db.get(User, self.actors[UserRole.ADMINISTRATOR].id)
            with patch.object(db, "commit", side_effect=RuntimeError("Synthetic failed commit")):
                with self.assertRaises(RuntimeError):
                    change_user_status(db, actor, target_id,
                        UserStatusChangeRequest(status=GeneralStatus.INACTIVE, current_password=PASSWORD))
        self.assertEqual(self.scalar(select(User.status).where(User.id == target_id)), GeneralStatus.ACTIVE)
        self.assertEqual(self.scalar(select(User.auth_version).where(User.id == target_id)), 1)

    def cross_action(self, operation: str):
        barrier = threading.Barrier(2, timeout=10)
        first_id, second_id = self.actors[UserRole.ADMINISTRATOR].id, self.admin2.id
        def worker(actor_id, target_id):
            with Session(self.engine) as db:
                principal = db.get(User, actor_id)  # Both requests capture their initial admin role.
                barrier.wait()
                try:
                    if operation == "deactivate":
                        result = change_user_status(db, principal, target_id, UserStatusChangeRequest(status=GeneralStatus.INACTIVE, current_password=PASSWORD))
                    else:
                        result = change_user_role(db, principal, target_id, UserRoleChangeRequest(role=UserRole.USER, current_password=PASSWORD))
                    return result
                except AuthorizationError as exc:
                    return exc.status_code
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(worker, first_id, second_id), executor.submit(worker, second_id, first_id)]
            outcomes = [future.result(timeout=20) for future in futures]
        self.assertEqual(sum(not isinstance(value, int) for value in outcomes), 1)
        self.assertEqual(sum(isinstance(value, int) and value in (401, 403, 409) for value in outcomes), 1)
        count = self.scalar(select(func.count()).select_from(User).where(User.organization_id == self.org.id,
                            User.role == UserRole.ADMINISTRATOR, User.status == GeneralStatus.ACTIVE))
        self.assertEqual(count, 1)

    def test_two_admins_cannot_deactivate_each_other_concurrently(self):
        self.cross_action("deactivate")

    def test_two_admins_cannot_demote_each_other_concurrently(self):
        self.cross_action("demote")

    def test_concurrent_duplicate_creates_one_account(self):
        barrier = threading.Barrier(2, timeout=10)
        def worker(actor_id):
            with Session(self.engine) as db:
                principal = db.get(User, actor_id)
                barrier.wait()
                try:
                    return provision_user(db, principal, UserProvisionRequest(name="Synthetic duplicate",
                        email="duplicate@example.invalid", password=PASSWORD, current_password=PASSWORD,
                        role=UserRole.USER, status=GeneralStatus.ACTIVE))
                except AccountConflict:
                    return "conflict"
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(worker, actor.id) for actor in (self.actors[UserRole.ADMINISTRATOR], self.admin2)]
            outcomes = [future.result(timeout=20) for future in futures]
        self.assertEqual(outcomes.count("conflict"), 1)
        self.assertEqual(self.scalar(select(func.count()).select_from(User).where(User.email == "duplicate@example.invalid")), 1)

    def test_concurrent_deactivations_increment_once_and_concurrent_activations_preserve_version(self):
        target_id = self.actors[UserRole.USER].id
        def simultaneous(status):
            barrier = threading.Barrier(2, timeout=10)
            def worker(actor_id):
                with Session(self.engine) as db:
                    actor = db.get(User, actor_id)
                    barrier.wait()
                    return change_user_status(db, actor, target_id,
                        UserStatusChangeRequest(status=status, current_password=PASSWORD))
            with ThreadPoolExecutor(max_workers=2) as executor:
                futures = [executor.submit(worker, actor.id) for actor in (self.actors[UserRole.ADMINISTRATOR], self.admin2)]
                return [future.result(timeout=20) for future in futures]
        self.assertTrue(all(value.status == GeneralStatus.INACTIVE for value in simultaneous(GeneralStatus.INACTIVE)))
        self.assertEqual(self.scalar(select(User.auth_version).where(User.id == target_id)), 2)
        self.assertTrue(all(value.status == GeneralStatus.ACTIVE for value in simultaneous(GeneralStatus.ACTIVE)))
        self.assertEqual(self.scalar(select(User.auth_version).where(User.id == target_id)), 2)

    def test_simultaneous_activation_and_deactivation_never_restore_the_old_version(self):
        target_id = self.actors[UserRole.USER].id
        barrier = threading.Barrier(2, timeout=10)
        def worker(actor_id, status):
            with Session(self.engine) as db:
                actor = db.get(User, actor_id)
                barrier.wait()
                return change_user_status(db, actor, target_id,
                    UserStatusChangeRequest(status=status, current_password=PASSWORD))
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(worker, self.actors[UserRole.ADMINISTRATOR].id, GeneralStatus.INACTIVE),
                       executor.submit(worker, self.admin2.id, GeneralStatus.ACTIVE)]
            [future.result(timeout=20) for future in futures]
        self.assertEqual(self.scalar(select(User.auth_version).where(User.id == target_id)), 2)

    def test_waiting_writer_rejects_revoked_version_even_if_actor_is_active_again(self):
        ready = threading.Event()
        actor_id, target_id = self.admin2.id, self.actors[UserRole.USER].id
        with Session(self.engine) as blocker:
            blocker.scalar(select(Organization).where(Organization.id == self.org.id).with_for_update())
            def worker():
                with Session(self.engine) as db:
                    principal = db.get(User, actor_id)
                    self.assertEqual(principal.auth_version, 1)
                    ready.set()
                    try:
                        return change_user_status(db, principal, target_id,
                            UserStatusChangeRequest(status=GeneralStatus.INACTIVE, current_password=PASSWORD))
                    except AuthorizationError as exc:
                        return exc.status_code
            with ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(worker)
                self.assertTrue(ready.wait(timeout=10))
                # Final state of a revocation/reactivation while the previous request waits.
                actor = blocker.get(User, actor_id)
                actor.auth_version += 1
                blocker.commit()
                self.assertEqual(future.result(timeout=20), 401)
        self.assertEqual(self.scalar(select(User.status).where(User.id == target_id)), GeneralStatus.ACTIVE)

    def test_waiting_writer_rechecks_permission_after_lock_is_released(self):
        ready = threading.Event()
        actor_id, target_id = self.admin2.id, self.actors[UserRole.USER].id
        with Session(self.engine) as blocker:
            blocker.scalar(select(Organization).where(Organization.id == self.org.id).with_for_update())
            def worker():
                with Session(self.engine) as db:
                    principal = db.get(User, actor_id)
                    ready.set()
                    try:
                        return change_user_status(db, principal, target_id,
                            UserStatusChangeRequest(status=GeneralStatus.INACTIVE, current_password=PASSWORD))
                    except AuthorizationError as exc:
                        return exc.status_code
            with ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(worker)
                self.assertTrue(ready.wait(timeout=10))
                # Commit a role change while the waiting actor still holds a stale identity map.
                other = blocker.get(User, actor_id)
                other.role = UserRole.USER
                blocker.commit()
                self.assertEqual(future.result(timeout=20), 403)
        self.assertEqual(self.scalar(select(User.status).where(User.id == target_id)), GeneralStatus.ACTIVE)


if __name__ == "__main__":
    unittest.main()
