"""Synthetic HTTP/auth tests. Never use or migrate the application's database.

AUTH_TEST_DATABASE_URL must explicitly name a disposable persistence_test* DB.
"""
import os
import secrets
import unittest
from datetime import datetime, timedelta, timezone
from typing import Annotated
from unittest.mock import patch
from uuid import UUID, uuid4

import jwt
from alembic import command
from alembic.config import Config
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError
from pwdlib import PasswordHash
from pwdlib.hashers.argon2 import Argon2Hasher
from sqlalchemy import create_engine, inspect, select, update
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.api.dependencies import CurrentUser, require_organization, require_roles
from app.core.config import AuthSettings, get_auth_settings
from app.core.security import (create_access_token, decode_access_token, hash_password,
                               verify_password, dummy_password_hash)
from app.db.dependencies import get_db
from app.main import app
from app.models import Organization, User
from app.models.enums import GeneralStatus, UserRole
from app.schemas.auth import LoginRequest


class SecurityTests(unittest.TestCase):
    def setUp(self):
        self.settings = AuthSettings(_env_file=None, JWT_SECRET=secrets.token_urlsafe(48))

    def test_argon2_salts_verification_and_upgrade(self):
        password = "synthetic-password-with-spaces "
        first, second = hash_password(password), hash_password(password)
        self.assertTrue(first.startswith("$argon2id$"))
        self.assertLessEqual(len(first), 255)
        self.assertNotEqual(first, second)
        self.assertEqual(verify_password(password, first), (True, None))
        self.assertEqual(verify_password(password.strip(), first), (False, None))
        self.assertEqual(verify_password(password, "unrecognized-hash"), (False, None))
        old = PasswordHash((Argon2Hasher(time_cost=2, memory_cost=19456, parallelism=1),)).hash(password)
        valid, replacement = verify_password(password, old)
        self.assertTrue(valid)
        self.assertIsNotNone(replacement)
        self.assertEqual(verify_password(password, replacement), (True, None))

    def test_secret_and_expiry_validation(self):
        weak = "short-synthetic-secret"
        with self.assertRaises(ValidationError) as error:
            AuthSettings(_env_file=None, JWT_SECRET=weak)
        self.assertNotIn(weak, str(error.exception))
        with self.assertRaises(ValidationError):
            AuthSettings(_env_file=None, JWT_SECRET=secrets.token_urlsafe(48), JWT_ACCESS_TOKEN_MINUTES=0)
        with patch.dict(os.environ):
            os.environ.pop("JWT_SECRET", None)
            with self.assertRaises(ValidationError):
                AuthSettings(_env_file=None)
        settings = self.settings.model_copy(update={"JWT_ACCESS_TOKEN_MINUTES": 3})
        token = create_access_token(uuid4(), uuid4(), settings, auth_version=1)
        claims = decode_access_token(token, settings)
        self.assertEqual(claims.exp - claims.iat, 180)

    def test_api_startup_fails_without_valid_auth_config(self):
        with patch("app.main.get_auth_settings", side_effect=RuntimeError("auth configuration unavailable")):
            with self.assertRaises(RuntimeError):
                with TestClient(app):
                    pass

    def test_token_issuer_requires_explicit_positive_integer_version(self):
        for version in (0, -1, True, 1.0, "1", None):
            with self.subTest(version=version), self.assertRaises(ValueError):
                create_access_token(uuid4(), uuid4(), self.settings, auth_version=version)
        token = create_access_token(uuid4(), uuid4(), self.settings, auth_version=1)
        self.assertEqual(decode_access_token(token, self.settings).ver, 1)

    def test_input_exact_email_and_password_privacy(self):
        payload = LoginRequest(email="  MixedCase@example.invalid  ", password=" leading and trailing ")
        self.assertEqual(payload.email, "MixedCase@example.invalid")
        self.assertEqual(payload.password.get_secret_value(), " leading and trailing ")
        self.assertNotIn("leading and trailing", repr(payload))


@unittest.skipUnless(os.getenv("AUTH_TEST_DATABASE_URL"), "explicit isolated auth test DB required")
class AuthHTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        url = make_url(os.environ["AUTH_TEST_DATABASE_URL"])
        if url.get_backend_name() != "postgresql" or not (url.database or "").startswith("persistence_test"):
            raise RuntimeError("Refusing to migrate a non-test database")
        cls.engine = create_engine(url, connect_args={"options": "-c timezone=UTC"})
        with cls.engine.connect() as connection:
            if set(inspect(connection).get_table_names()) - {"alembic_version"}:
                raise RuntimeError("Auth test DB must initially contain no domain tables")
        cls.config = Config("alembic.ini")
        cls.config.set_main_option("sqlalchemy.url", url.render_as_string(hide_password=False).replace("%", "%%"))
        command.upgrade(cls.config, "head")
        cls.settings = AuthSettings(_env_file=None, JWT_SECRET=secrets.token_urlsafe(48))
        cls.password = "Synthetic-auth-password-123!"
        cls.stored_hash = hash_password(cls.password)
        dummy_password_hash()
        # Authorization probes exist exclusively in this test application.
        cls.probe_app = FastAPI()
        def moderator(user: Annotated[User, Depends(require_roles(UserRole.MODERATOR))]):
            return {"role": user.role}
        def organization(organization_id: UUID, user: CurrentUser):
            require_organization(user, organization_id)
            return {"organization_id": str(user.organization_id)}
        cls.probe_app.add_api_route("/moderator", moderator)
        cls.probe_app.add_api_route("/organizations/{organization_id}", organization)

    @classmethod
    def tearDownClass(cls):
        command.downgrade(cls.config, "base")
        cls.engine.dispose()

    def setUp(self):
        self.connection = self.engine.connect()
        self.outer = self.connection.begin()
        self.db = Session(self.connection, join_transaction_mode="create_savepoint")
        self.o1 = Organization(name="Synthetic A", status=GeneralStatus.ACTIVE)
        self.o2 = Organization(name="Synthetic B", status=GeneralStatus.ACTIVE)
        self.db.add_all([self.o1, self.o2])
        self.db.flush()
        self.u1 = User(organization_id=self.o1.id, name="Synthetic A user", email="MixedCase@example.invalid",
                       password_hash=self.stored_hash, role=UserRole.USER, status=GeneralStatus.ACTIVE)
        self.u2 = User(organization_id=self.o2.id, name="Synthetic B admin", email="admin@example.invalid",
                       password_hash=self.stored_hash, role=UserRole.ADMINISTRATOR, status=GeneralStatus.ACTIVE)
        self.db.add_all([self.u1, self.u2])
        self.db.commit()
        def database_override():
            yield self.db
        for application in (app, self.probe_app):
            application.dependency_overrides[get_db] = database_override
            application.dependency_overrides[get_auth_settings] = lambda: self.settings
        self.startup = patch("app.main.get_auth_settings", return_value=self.settings)
        self.startup.start()
        self.client = TestClient(app).__enter__()
        self.probe_client = TestClient(self.probe_app).__enter__()

    def tearDown(self):
        self.probe_client.__exit__(None, None, None)
        self.client.__exit__(None, None, None)
        self.startup.stop()
        for application in (app, self.probe_app):
            application.dependency_overrides.clear()
        self.db.close()
        self.outer.rollback()
        self.connection.close()

    def login(self, email="MixedCase@example.invalid", password=None, **extra):
        return self.client.post("/api/v1/auth/login", json={"email": email, "password": self.password if password is None else password, **extra})

    def token(self, user=None):
        user = user or self.u1
        return create_access_token(user.id, user.organization_id, self.settings, auth_version=user.auth_version)

    def me(self, token=None):
        headers = {"Authorization": "Bearer " + token} if token is not None else {}
        return self.client.get("/api/v1/auth/me", headers=headers)

    def signed(self, claims):
        return jwt.encode(claims, self.settings.JWT_SECRET.get_secret_value(), algorithm="HS256")

    def test_login_and_current_user_contracts(self):
        before = datetime.now(timezone.utc)
        response = self.login(email="  MixedCase@example.invalid  ")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(set(data), {"access_token", "token_type", "expires_in"})
        self.assertEqual(data["expires_in"], 900)
        self.assertEqual(data["token_type"], "bearer")
        self.assertEqual(response.headers["cache-control"], "no-store")
        claims = decode_access_token(data["access_token"], self.settings)
        self.assertEqual(claims.sub, self.u1.id)
        self.assertEqual(claims.organization_id, self.o1.id)
        self.assertEqual(claims.exp - claims.iat, 900)
        self.db.refresh(self.u1)
        self.assertGreaterEqual(self.u1.last_login, before)
        profile = self.me(data["access_token"])
        self.assertEqual(profile.status_code, 200)
        self.assertEqual(profile.json(), {"id": str(self.u1.id), "organization_id": str(self.o1.id),
                         "name": self.u1.name, "email": self.u1.email, "role": "USUARIO", "status": "ACTIVO"})
        for secret in (self.password, self.stored_hash, self.settings.JWT_SECRET.get_secret_value()):
            self.assertNotIn(secret, response.text)
            self.assertNotIn(secret, profile.text)
        self.assertNotIn(data["access_token"], profile.text)
        self.assertEqual(profile.headers["cache-control"], "no-store")

    def test_invalid_credentials_and_case_sensitive_email(self):
        responses = [self.login(password="wrong"), self.login(email="absent@example.invalid"),
                     self.login(email="mixedcase@example.invalid")]
        for response in responses:
            self.assertEqual(response.status_code, 401)
            self.assertEqual(response.headers["www-authenticate"], "Bearer")
            self.assertEqual(response.headers["cache-control"], "no-store")
            self.assertEqual(response.json(), responses[0].json())
        self.db.refresh(self.u1)
        self.assertIsNone(self.u1.last_login)

    def test_disabled_user_and_organization_at_login(self):
        baseline = self.login(password="wrong").json()
        for instance in (self.u1, self.o1):
            instance.status = GeneralStatus.INACTIVE
            self.db.commit()
            response = self.login()
            self.assertEqual(response.status_code, 401)
            self.assertEqual(response.json(), baseline)
            self.db.refresh(self.u1)
            self.assertIsNone(self.u1.last_login)
            instance.status = GeneralStatus.ACTIVE
            self.db.commit()

    def test_token_rechecks_user_and_organization_status(self):
        token = self.token()
        for instance in (self.u1, self.o1):
            instance.status = GeneralStatus.INACTIVE
            self.db.commit()
            self.assertEqual(self.me(token).status_code, 401)
            instance.status = GeneralStatus.ACTIVE
            self.db.commit()
            self.assertEqual(self.me(token).status_code, 200)

    def test_missing_malformed_altered_and_expired_tokens(self):
        self.assertEqual(self.me().status_code, 401)
        token = self.token()
        payload = jwt.decode(token, options={"verify_signature": False})
        altered = dict(payload, sub=str(self.u2.id))
        encoded = self.signed(altered).split(".")
        encoded[2] = ("A" if encoded[2][0] != "A" else "B") + encoded[2][1:]
        expired = dict(payload, iat=payload["iat"] - 120, exp=payload["iat"] - 60)
        invalid = ["not-a-jwt", ".".join(encoded), self.signed(expired),
                   jwt.encode(payload, secrets.token_urlsafe(48), algorithm="HS256"),
                   jwt.encode(payload, self.settings.JWT_SECRET.get_secret_value(), algorithm="HS384"),
                   jwt.encode(payload, key="", algorithm="none")]
        for field in ("sub", "organization_id", "iat", "exp", "iss", "aud", "ver"):
            incomplete = payload.copy()
            del incomplete[field]
            invalid.append(self.signed(incomplete))
        for changes in ({"iss": "other"}, {"aud": "other"}, {"sub": "not-a-uuid"},
                        {"organization_id": "not-a-uuid"}, {"iat": payload["iat"] + 3600},
                        {"iat": str(payload["iat"])}, {"exp": payload["iat"] - 1}):
            invalid.append(self.signed({**payload, **changes}))
        for candidate in invalid:
            with self.subTest(case=len(candidate)):
                response = self.me(candidate)
                self.assertEqual(response.status_code, 401)
                self.assertNotIn(candidate, response.text)
        self.assertEqual(self.client.get("/api/v1/auth/me", headers={"Authorization": "Basic fake"}).status_code, 401)
        self.assertEqual(self.client.get("/api/v1/auth/me", params={"access_token": token}).status_code, 401)

    def test_legacy_missing_and_incorrect_versions_are_rejected(self):
        token = self.token()
        payload = jwt.decode(token, options={"verify_signature": False})
        self.assertEqual(payload["ver"], 1)
        legacy = payload.copy()
        del legacy["ver"]
        self.assertEqual(self.me(self.signed(legacy)).status_code, 401)
        for version in (0, -1, True, 1.0, "1", None, [], {}, 2, 1000):
            with self.subTest(version=version):
                response = self.me(self.signed({**payload, "ver": version}))
                self.assertEqual(response.status_code, 401)
                self.assertEqual(response.headers["www-authenticate"], "Bearer")
        self.assertEqual(self.me(token).status_code, 200)

    def test_login_does_not_upgrade_its_verified_version_after_a_concurrent_revocation(self):
        original_commit = self.db.commit
        def commit_after_version_change():
            # Simulate the final state of a deactivation/reactivation after verification.
            self.db.execute(update(User).where(User.id == self.u1.id)
                            .values(auth_version=User.auth_version + 1))
            original_commit()
        with patch.object(self.db, "commit", side_effect=commit_after_version_change):
            response = self.login()
        self.assertEqual(response.status_code, 200)
        stale = response.json()["access_token"]
        self.assertEqual(decode_access_token(stale, self.settings).ver, 1)
        self.assertEqual(self.me(stale).status_code, 401)
        fresh = self.login().json()["access_token"]
        self.assertEqual(decode_access_token(fresh, self.settings).ver, 2)
        self.assertEqual(self.me(fresh).status_code, 200)

    def test_role_changes_are_loaded_from_database_without_hierarchy(self):
        token = self.token()
        headers = {"Authorization": "Bearer " + token}
        self.assertEqual(self.probe_client.get("/moderator", headers=headers).status_code, 403)
        for role, expected in ((UserRole.MODERATOR, 200), (UserRole.ADMINISTRATOR, 403), (UserRole.USER, 403)):
            self.db.execute(update(User).where(User.id == self.u1.id).values(role=role))
            self.db.commit()
            self.assertEqual(self.me(token).json()["role"], role.value)
            self.assertEqual(self.probe_client.get("/moderator", headers=headers).status_code, expected)
        payload = jwt.decode(token, options={"verify_signature": False})
        payload["role"] = "ADMINISTRADOR"
        self.assertEqual(self.me(self.signed(payload)).json()["role"], "USUARIO")

    def test_organization_scope_applies_to_administrators(self):
        for user, own, other in ((self.u1, self.o1, self.o2), (self.u2, self.o2, self.o1)):
            headers = {"Authorization": "Bearer " + self.token(user)}
            self.assertEqual(self.probe_client.get(f"/organizations/{own.id}", headers=headers).status_code, 200)
            self.assertEqual(self.probe_client.get(f"/organizations/{other.id}", headers=headers).status_code, 403)
        payload = jwt.decode(self.token(), options={"verify_signature": False})
        payload["organization_id"] = str(self.o2.id)
        self.assertEqual(self.me(self.signed(payload)).status_code, 401)

    def test_old_token_rejected_after_organization_change_or_user_deletion(self):
        token = self.token()
        self.u1.organization_id = self.o2.id  # No reports attached to this synthetic user.
        self.db.commit()
        self.assertEqual(self.me(token).status_code, 401)
        fresh = self.token()
        self.assertEqual(self.me(fresh).status_code, 200)
        self.db.delete(self.u1)
        self.db.commit()
        self.assertEqual(self.me(fresh).status_code, 401)

    def test_validation_never_echoes_passwords_or_unknown_inputs(self):
        private = "synthetic-private-input"
        bodies = [{"email": private, "password": [private]},
                  {"email": "x", "password": private, "role": private},
                  {"email": None, "password": private},
                  {"email": "x", "password": "z" * 1025}]
        for body in bodies:
            response = self.client.post("/api/v1/auth/login", json=body)
            self.assertEqual(response.status_code, 422)
            self.assertEqual(response.json(), {"detail": "Invalid request data"})
            self.assertNotIn(private, response.text)
            self.assertEqual(response.headers["cache-control"], "no-store")
        malformed = self.client.post("/api/v1/auth/login", content='{"password":"'+private+'",', headers={"Content-Type": "application/json"})
        self.assertEqual(malformed.status_code, 422)
        self.assertNotIn(private, malformed.text)

    def test_successful_login_upgrades_old_hash(self):
        old = PasswordHash((Argon2Hasher(time_cost=2, memory_cost=19456, parallelism=1),)).hash(self.password)
        self.u1.password_hash = old
        self.db.commit()
        self.assertEqual(self.login().status_code, 200)
        self.db.refresh(self.u1)
        self.assertNotEqual(self.u1.password_hash, old)
        self.assertEqual(verify_password(self.password, self.u1.password_hash), (True, None))

    def test_no_public_registration_routes_or_sensitive_openapi_fields(self):
        paths = app.openapi()["paths"]
        self.assertEqual(set(paths), {"/health", "/api/v1/auth/login", "/api/v1/auth/me",
                         "/api/v1/organizations/me", "/api/v1/users", "/api/v1/users/{user_id}",
                         "/api/v1/users/{user_id}/role", "/api/v1/users/{user_id}/status"})
        for path in ("/api/v1/auth/register", "/api/v1/organizations"):
            self.assertEqual(self.client.post(path, json={"role": "ADMINISTRADOR"}).status_code, 404)
        self.assertEqual(self.client.post("/api/v1/users", json={"role": "ADMINISTRADOR"}).status_code, 401)
        profile_schema = app.openapi()["components"]["schemas"]["CurrentUserResponse"]["properties"]
        self.assertNotIn("password_hash", profile_schema)
        self.assertNotIn("password", profile_schema)
        self.assertEqual(self.client.get("/health").json(), {"status": "ok"})


if __name__ == "__main__":
    unittest.main()
