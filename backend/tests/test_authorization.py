"""Pure policies plus isolated PostgreSQL/HTTP probes. No production CRUD routes."""
import os
import secrets
import unittest
from datetime import datetime, timezone
from decimal import Decimal
from typing import Annotated
from uuid import UUID, uuid4

from alembic import command
from alembic.config import Config
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, inspect, select, update
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.api.access import (require_alert, require_alert_transition, require_analysis,
                            require_evidence, require_report)
from app.api.dependencies import CurrentUser, authorization_errors, require_permission
from app.core.config import AuthSettings, get_auth_settings
from app.core.permissions import Permission, ROLE_PERMISSIONS, has_permission
from app.core.security import create_access_token
from app.db.dependencies import get_db
from app.models import Alert, Evidence, Organization, Report, RiskAnalysis, User
from app.models.enums import AlertStatus, GeneralStatus, ReportStatus, RiskLevel, UserRole
from app.repositories.access import alerts_query, reports_query
from app.services.access_views import (authorized_alert_detail_view, preventive_alert_view,
                                       analysis_summary_view)
from app.services.authorization import (AuthorizationError, InactiveActor, InvalidResourceState,
    ResourceNotFound, authorize_alert, authorize_alert_transition, authorize_report, ensure_permission)


class PolicyTests(unittest.TestCase):
    def actor(self, role=UserRole.USER):
        organization = Organization(id=uuid4(), name="Synthetic", status=GeneralStatus.ACTIVE)
        return User(id=uuid4(), organization_id=organization.id, organization=organization,
                    role=role, status=GeneralStatus.ACTIVE)

    def report(self, user, *, owner=True, status=ReportStatus.REGISTERED, cross=False):
        return Report(id=uuid4(), user_id=user.id if owner else uuid4(),
                      organization_id=uuid4() if cross else user.organization_id, status=status)

    def test_explicit_role_grants_and_default_denial(self):
        staff_actions = {Permission.REPORT_REVIEW, Permission.REPORT_CLOSE,
                         Permission.ANALYSIS_READ_DETAIL, Permission.ALERT_READ_DETAIL,
                         Permission.ALERT_ATTEND, Permission.ALERT_CLOSE}
        common_actions = {Permission.PROFILE_READ, Permission.REPORT_CREATE, Permission.REPORT_READ,
                          Permission.REPORT_EDIT, Permission.EVIDENCE_ATTACH, Permission.EVIDENCE_READ,
                          Permission.ANALYSIS_READ_SUMMARY, Permission.ALERT_READ_PREVENTIVE}
        administrative_actions = {Permission.ORGANIZATION_READ_SELF, Permission.USER_READ_OTHERS,
                                  Permission.USER_CREATE, Permission.USER_ROLE_CHANGE, Permission.USER_DEACTIVATE, Permission.USER_ACTIVATE}
        for role in UserRole:
            for permission in Permission:
                expected = (permission in common_actions
                            or (role != UserRole.USER and permission in staff_actions)
                            or (role == UserRole.ADMINISTRATOR and permission in administrative_actions))
                with self.subTest(role=role, action=permission):
                    self.assertEqual(has_permission(role, permission), expected)
            self.assertFalse(has_permission(role, "unknown.action"))
            self.assertFalse(has_permission(role, "report.read"))
        self.assertFalse(has_permission("UNKNOWN", Permission.REPORT_READ))
        self.assertFalse(has_permission("ADMINISTRADOR", Permission.REPORT_REVIEW))
        with self.assertRaises(TypeError):
            ROLE_PERMISSIONS[UserRole.USER] = frozenset()

    def test_report_read_matrix_and_cross_organization(self):
        for role in UserRole:
            user = self.actor(role)
            for permission in (Permission.REPORT_READ, Permission.EVIDENCE_READ, Permission.ANALYSIS_READ_SUMMARY):
                for owner in (True, False):
                    report = self.report(user, owner=owner)
                    if role == UserRole.USER and not owner:
                        with self.assertRaises(ResourceNotFound):
                            authorize_report(user, report, permission)
                    else:
                        authorize_report(user, report, permission)
                    report.organization_id = uuid4()
                    with self.assertRaises(ResourceNotFound):
                        authorize_report(user, report, permission)

    def test_content_and_evidence_changes_require_owner_and_registered(self):
        for role in UserRole:
            user = self.actor(role)
            for permission in (Permission.REPORT_EDIT, Permission.EVIDENCE_ATTACH):
                for status in ReportStatus:
                    report = self.report(user, status=status)
                    if status == ReportStatus.REGISTERED:
                        authorize_report(user, report, permission)
                    else:
                        with self.assertRaises(InvalidResourceState):
                            authorize_report(user, report, permission)
                    report.user_id = uuid4()
                    with self.assertRaises(ResourceNotFound):
                        authorize_report(user, report, permission)
                    self.assertEqual(report.status, status)

    def test_review_is_eligibility_only_and_never_self_review(self):
        for role in UserRole:
            user = self.actor(role)
            for status in ReportStatus:
                report = self.report(user, owner=False, status=status)
                if role == UserRole.USER:
                    with self.assertRaises(AuthorizationError):
                        authorize_report(user, report, Permission.REPORT_REVIEW)
                else:
                    authorize_report(user, report, Permission.REPORT_REVIEW)
                self.assertEqual(report.status, status)
                report.user_id = user.id
                with self.assertRaises(AuthorizationError):
                    authorize_report(user, report, Permission.REPORT_REVIEW)
                for action in (Permission.REPORT_VALIDATE, Permission.REPORT_OBSERVE):
                    with self.assertRaises(AuthorizationError):
                        authorize_report(user, report, action)

    def test_administrative_report_closure_matrix(self):
        for role in UserRole:
            user = self.actor(role)
            for state in ReportStatus:
                report = self.report(user, owner=False, status=state)
                if role == UserRole.USER:
                    with self.assertRaises(AuthorizationError):
                        authorize_report(user, report, Permission.REPORT_CLOSE)
                elif state == ReportStatus.ANALYZED:
                    authorize_report(user, report, Permission.REPORT_CLOSE)
                else:
                    with self.assertRaises(InvalidResourceState):
                        authorize_report(user, report, Permission.REPORT_CLOSE)
                self.assertEqual(report.status, state)
            with self.assertRaises(AuthorizationError):
                authorize_report(user, self.report(user, status=ReportStatus.ANALYZED), Permission.REPORT_CLOSE)

    def test_all_alert_transitions_no_skips_or_reopening(self):
        for role in UserRole:
            user = self.actor(role)
            for source in AlertStatus:
                for target in AlertStatus:
                    alert = Alert(id=uuid4(), organization_id=user.organization_id, status=source)
                    allowed = role != UserRole.USER and (source, target) in {
                        (AlertStatus.ACTIVE, AlertStatus.ATTENDED),
                        (AlertStatus.ATTENDED, AlertStatus.CLOSED),
                    }
                    with self.subTest(role=role, source=source, target=target):
                        if allowed:
                            authorize_alert_transition(user, alert, target)
                        elif role == UserRole.USER:
                            with self.assertRaises(AuthorizationError):
                                authorize_alert_transition(user, alert, target)
                        else:
                            with self.assertRaises(InvalidResourceState):
                                authorize_alert_transition(user, alert, target)
                        self.assertEqual(alert.status, source)

    def test_sensitive_and_account_actions_disabled_for_every_role(self):
        disabled = (Permission.REPORTER_IDENTITY_READ, Permission.PRECISE_LOCATION_READ,
                    Permission.EVIDENCE_PATH_READ, Permission.ORGANIZATION_MANAGE,
                    Permission.RESOURCE_DELETE, Permission.ANALYSIS_WRITE, Permission.ALERT_CREATE)
        for role in UserRole:
            user = self.actor(role)
            for action in disabled:
                with self.subTest(role=role, action=action), self.assertRaises(AuthorizationError):
                    ensure_permission(user, action)

    def test_analysis_summary_requires_visible_parent_and_correct_relationship(self):
        user = self.actor()
        report = self.report(user)
        analysis = RiskAnalysis(
            id=uuid4(), report_id=report.id, risk_level=RiskLevel.HIGH,
            analyzed_at=datetime.now(timezone.utc), justification="Synthetic private details",
        )
        view = analysis_summary_view(user, report, analysis).model_dump()
        self.assertEqual(set(view), {"id", "report_id", "risk_level", "analyzed_at"})
        self.assertNotIn("justification", view)
        analysis.report_id = uuid4()
        with self.assertRaises(ResourceNotFound):
            analysis_summary_view(user, report, analysis)
        analysis.report_id = report.id
        report.user_id = uuid4()
        with self.assertRaises(ResourceNotFound):
            analysis_summary_view(user, report, analysis)

    def test_inactive_actors_and_wrong_resource_action_fail_closed(self):
        user = self.actor(UserRole.ADMINISTRATOR)
        report = self.report(user)
        with self.assertRaises(AuthorizationError):
            authorize_report(user, report, Permission.ALERT_READ_DETAIL)
        for obj in (user, user.organization):
            obj.status = GeneralStatus.INACTIVE
            with self.assertRaises(InactiveActor):
                ensure_permission(user, Permission.REPORT_READ)
            obj.status = GeneralStatus.ACTIVE

    def test_alert_projections_exclude_identity_and_unreviewed_free_text(self):
        user = self.actor()
        alert = Alert(id=uuid4(), organization_id=user.organization_id, analysis_id=uuid4(),
                      level=RiskLevel.HIGH, status=AlertStatus.ACTIVE,
                      generated_at=datetime.now(timezone.utc), closed_at=None,
                      title="Synthetic private reporter name", message="Synthetic private evidence path")
        view = preventive_alert_view(user, alert).model_dump()
        self.assertEqual(set(view), {"id", "level", "status", "generated_at"})
        with self.assertRaises(AuthorizationError):
            authorized_alert_detail_view(user, alert)
        for role in (UserRole.MODERATOR, UserRole.ADMINISTRATOR):
            user.role = role
            detail = authorized_alert_detail_view(user, alert).model_dump()
            self.assertEqual(set(detail), {"id", "level", "status", "generated_at", "organization_id", "analysis_id", "closed_at"})
            self.assertNotIn(alert.title, str(detail))
            self.assertNotIn(alert.message, str(detail))
        alert.organization_id = uuid4()
        with self.assertRaises(ResourceNotFound):
            preventive_alert_view(user, alert)


@unittest.skipUnless(os.getenv("AUTHORIZATION_TEST_DATABASE_URL"), "explicit isolated authorization DB required")
class AuthorizationHTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        url = make_url(os.environ["AUTHORIZATION_TEST_DATABASE_URL"])
        if url.get_backend_name() != "postgresql" or not (url.database or "").startswith("persistence_test"):
            raise RuntimeError("Refusing non-test database")
        cls.engine = create_engine(url, connect_args={"options": "-c timezone=UTC"})
        with cls.engine.connect() as connection:
            if set(inspect(connection).get_table_names()) - {"alembic_version"}:
                raise RuntimeError("Authorization DB must initially contain no domain tables")
        cls.config = Config("alembic.ini")
        cls.config.set_main_option("sqlalchemy.url", url.render_as_string(hide_password=False).replace("%", "%%"))
        command.upgrade(cls.config, "head")
        cls.settings = AuthSettings(_env_file=None, JWT_SECRET=secrets.token_urlsafe(48))
        cls.probe = FastAPI()  # All routes below exist only in tests.
        def report_read(report: Annotated[Report, Depends(require_report(Permission.REPORT_READ))]):
            return {"id": str(report.id)}
        def report_edit(report: Annotated[Report, Depends(require_report(Permission.REPORT_EDIT))]):
            return {"allowed": True}
        def report_attach(report: Annotated[Report, Depends(require_report(Permission.EVIDENCE_ATTACH))]):
            return {"allowed": True}
        def report_review(report: Annotated[Report, Depends(require_report(Permission.REPORT_REVIEW))]):
            return {"allowed": True}
        def report_close(report: Annotated[Report, Depends(require_report(Permission.REPORT_CLOSE))]):
            return {"allowed": True}
        def evidence_read(evidence: Annotated[Evidence, Depends(require_evidence())]):
            return {"id": str(evidence.id)}
        def analysis_read(analysis: Annotated[RiskAnalysis, Depends(require_analysis(Permission.ANALYSIS_READ_SUMMARY))]):
            return {"id": str(analysis.id)}
        def analysis_detail(analysis: Annotated[RiskAnalysis, Depends(require_analysis(Permission.ANALYSIS_READ_DETAIL))]):
            return {"id": str(analysis.id)}
        def alert_read(user: CurrentUser, alert: Annotated[Alert, Depends(require_alert(Permission.ALERT_READ_PREVENTIVE))]):
            return preventive_alert_view(user, alert)
        def alert_detail(user: CurrentUser, alert: Annotated[Alert, Depends(require_alert(Permission.ALERT_READ_DETAIL))]):
            return authorized_alert_detail_view(user, alert)
        def attend(alert: Annotated[Alert, Depends(require_alert_transition(AlertStatus.ATTENDED))]):
            return {"allowed": True}
        def close(alert: Annotated[Alert, Depends(require_alert_transition(AlertStatus.CLOSED))]):
            return {"allowed": True}
        def disabled(user: Annotated[User, Depends(require_permission(Permission.ORGANIZATION_MANAGE))]):
            return {"allowed": True}
        for path, endpoint in (
            ("/reports/{report_id}", report_read), ("/reports/{report_id}/edit", report_edit),
            ("/reports/{report_id}/attach", report_attach), ("/reports/{report_id}/review", report_review),
            ("/reports/{report_id}/close", report_close),
            ("/reports/{report_id}/evidence/{evidence_id}", evidence_read),
            ("/reports/{report_id}/analysis/{analysis_id}", analysis_read),
            ("/reports/{report_id}/analysis/{analysis_id}/detail", analysis_detail),
            ("/alerts/{alert_id}", alert_read), ("/alerts/{alert_id}/detail", alert_detail),
            ("/alerts/{alert_id}/attend", attend), ("/alerts/{alert_id}/close", close),
            ("/disabled", disabled),
        ):
            cls.probe.add_api_route(path, endpoint)

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
        self.db.add_all([self.o1, self.o2]); self.db.flush()
        self.actors = {}
        for role in UserRole:
            self.actors[role] = User(organization_id=self.o1.id, name="Synthetic " + role.value,
                email=role.value + "@example.invalid", password_hash="synthetic-unused-hash",
                status=GeneralStatus.ACTIVE, role=role)
        self.outsider = User(organization_id=self.o2.id, name="Synthetic other organization",
            email="other@example.invalid", password_hash="synthetic-unused-hash",
            status=GeneralStatus.ACTIVE, role=UserRole.ADMINISTRATOR)
        self.db.add_all([*self.actors.values(), self.outsider]); self.db.flush()
        self.reports = {}
        for role, actor in self.actors.items():
            self.reports[role] = Report(user_id=actor.id, organization_id=self.o1.id, type="synthetic",
                                      description="Synthetic", status=ReportStatus.REGISTERED)
        self.foreign = Report(user_id=self.outsider.id, organization_id=self.o2.id, type="synthetic",
                              description="Synthetic", status=ReportStatus.REGISTERED)
        self.db.add_all([*self.reports.values(), self.foreign]); self.db.flush()
        self.analysis = RiskAnalysis(report_id=self.reports[UserRole.USER].id, risk_level=RiskLevel.HIGH, score=Decimal("1.00"))
        self.other_analysis = RiskAnalysis(report_id=self.reports[UserRole.MODERATOR].id, risk_level=RiskLevel.HIGH, score=Decimal("2.00"))
        self.foreign_analysis = RiskAnalysis(report_id=self.foreign.id, risk_level=RiskLevel.HIGH, score=Decimal("3.00"))
        self.db.add_all([self.analysis, self.other_analysis, self.foreign_analysis]); self.db.flush()
        self.evidence = Evidence(report_id=self.reports[UserRole.USER].id, file_path="private/synthetic")
        self.foreign_evidence = Evidence(report_id=self.foreign.id, file_path="private/foreign")
        self.alert = Alert(analysis_id=self.other_analysis.id, organization_id=self.o1.id, type="synthetic",
                           level=RiskLevel.HIGH, title="Synthetic private title", message="Synthetic private message", status=AlertStatus.ACTIVE)
        self.foreign_alert = Alert(analysis_id=self.foreign_analysis.id, organization_id=self.o2.id, type="synthetic",
                           level=RiskLevel.HIGH, title="Foreign", message="Synthetic", status=AlertStatus.ACTIVE)
        self.db.add_all([self.evidence, self.foreign_evidence, self.alert, self.foreign_alert]); self.db.commit()
        def database():
            yield self.db
        self.probe.dependency_overrides[get_db] = database
        self.probe.dependency_overrides[get_auth_settings] = lambda: self.settings
        self.client = TestClient(self.probe).__enter__()

    def tearDown(self):
        self.client.__exit__(None, None, None)
        self.probe.dependency_overrides.clear()
        self.db.close(); self.outer.rollback(); self.connection.close()

    def request(self, path, role=UserRole.USER, actor=None, token=None):
        user = actor or self.actors[role]
        token = token or create_access_token(user.id, user.organization_id, self.settings, auth_version=user.auth_version)
        return self.client.get(path, headers={"Authorization": "Bearer " + token})

    def test_report_reads_and_lists_follow_role_and_ownership(self):
        for role in UserRole:
            own = self.reports[role]
            self.assertEqual(self.request(f"/reports/{own.id}", role).status_code, 200)
            for report in self.reports.values():
                expected = 200 if role != UserRole.USER or report.user_id == self.actors[role].id else 404
                self.assertEqual(self.request(f"/reports/{report.id}", role).status_code, expected)
            ids = set(self.db.scalars(reports_query(self.actors[role])).all())
            expected_reports = {own} if role == UserRole.USER else set(self.reports.values())
            self.assertEqual(ids, expected_reports)
            count = self.db.scalar(select(func.count()).select_from(reports_query(self.actors[role]).subquery()))
            self.assertEqual(count, len(expected_reports))

    def test_foreign_uuid_matches_missing_resource_and_filter_cannot_expand_scope(self):
        for role in UserRole:
            foreign = self.request(f"/reports/{self.foreign.id}", role)
            absent = self.request(f"/reports/{uuid4()}", role)
            self.assertEqual(foreign.status_code, 404)
            self.assertEqual(foreign.json(), absent.json())
            response = self.request(f"/reports/{self.foreign.id}?organization_id={self.o2.id}&user_id={self.outsider.id}", role)
            self.assertEqual(response.status_code, 404)
            self.assertEqual(self.request(f"/alerts/{self.foreign_alert.id}", role).status_code, 404)
            for action in ("edit", "attach", "review", "close"):
                expected = 403 if role == UserRole.USER and action in {"review", "close"} else 404
                self.assertEqual(self.request(f"/reports/{self.foreign.id}/{action}", role).status_code, expected)

    def test_edit_and_attachment_require_owner_and_state_even_for_admin(self):
        for role in UserRole:
            report = self.reports[role]
            for state in ReportStatus:
                report.status = state; self.db.commit()
                for action in ("edit", "attach"):
                    self.assertEqual(self.request(f"/reports/{report.id}/{action}", role).status_code,
                                     200 if state == ReportStatus.REGISTERED else 409)
            other = self.reports[UserRole.MODERATOR if role == UserRole.USER else UserRole.USER]
            for action in ("edit", "attach"):
                self.assertEqual(self.request(f"/reports/{other.id}/{action}", role).status_code, 404)

    def test_review_and_close_checks_do_not_mutate_resources(self):
        report = self.reports[UserRole.USER]
        for role in (UserRole.MODERATOR, UserRole.ADMINISTRATOR):
            own = self.reports[role]
            self.assertEqual(self.request(f"/reports/{own.id}/review", role).status_code, 403)
            self.assertEqual(self.request(f"/reports/{report.id}/review", role).status_code, 200)
            self.assertEqual(self.request(f"/reports/{report.id}/close", role).status_code, 409)
        report.status = ReportStatus.ANALYZED; self.db.commit()
        self.assertEqual(self.request(f"/reports/{report.id}/close", UserRole.ADMINISTRATOR).status_code, 200)
        self.db.refresh(report)
        self.assertEqual(report.status, ReportStatus.ANALYZED)
        self.assertEqual(self.request(f"/reports/{report.id}/review").status_code, 403)

    def test_nested_evidence_and_analysis_match_authorized_parent(self):
        user_report = self.reports[UserRole.USER]
        for role in UserRole:
            self.assertEqual(self.request(f"/reports/{user_report.id}/evidence/{self.evidence.id}", role).status_code, 200)
            self.assertEqual(self.request(f"/reports/{user_report.id}/evidence/{self.foreign_evidence.id}", role).status_code, 404)
            self.assertEqual(self.request(f"/reports/{self.foreign.id}/evidence/{self.foreign_evidence.id}", role).status_code, 404)
            self.assertEqual(self.request(f"/reports/{user_report.id}/analysis/{self.analysis.id}", role).status_code, 200)
            self.assertEqual(self.request(f"/reports/{user_report.id}/analysis/{self.other_analysis.id}", role).status_code, 404)
            self.assertEqual(self.request(f"/reports/{self.foreign.id}/analysis/{self.foreign_analysis.id}", role).status_code, 404)
            expected = 403 if role == UserRole.USER else 200
            self.assertEqual(self.request(f"/reports/{user_report.id}/analysis/{self.analysis.id}/detail", role).status_code, expected)

    def test_preventive_alert_access_does_not_grant_linked_report_access(self):
        for role in UserRole:
            response = self.request(f"/alerts/{self.alert.id}", role)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(set(response.json()), {"id", "level", "status", "generated_at"})
            self.assertEqual(list(self.db.scalars(alerts_query(self.actors[role]))), [self.alert])
            detail = self.request(f"/alerts/{self.alert.id}/detail", role)
            self.assertEqual(detail.status_code, 403 if role == UserRole.USER else 200)
            self.assertNotIn(self.alert.title, response.text + detail.text)
            self.assertNotIn(self.alert.message, response.text + detail.text)
        parent = self.reports[UserRole.MODERATOR]
        self.assertEqual(self.request(f"/reports/{parent.id}").status_code, 404)
        self.assertEqual(self.request(f"/reports/{parent.id}/analysis/{self.other_analysis.id}").status_code, 404)

    def test_alert_transition_dependencies_check_but_do_not_update(self):
        self.assertEqual(self.request(f"/alerts/{self.alert.id}/attend").status_code, 403)
        for role in (UserRole.MODERATOR, UserRole.ADMINISTRATOR):
            self.assertEqual(self.request(f"/alerts/{self.alert.id}/attend", role).status_code, 200)
            self.assertEqual(self.request(f"/alerts/{self.alert.id}/close", role).status_code, 409)
        self.alert.status = AlertStatus.ATTENDED; self.db.commit()
        self.assertEqual(self.request(f"/alerts/{self.alert.id}/close", UserRole.MODERATOR).status_code, 200)
        self.assertEqual(self.request(f"/alerts/{self.alert.id}/attend", UserRole.ADMINISTRATOR).status_code, 409)
        self.db.refresh(self.alert)
        self.assertEqual(self.alert.status, AlertStatus.ATTENDED)

    def test_role_change_with_same_token_and_disabled_actions(self):
        user = self.actors[UserRole.USER]
        token = create_access_token(user.id, user.organization_id, self.settings, auth_version=user.auth_version)
        other = self.reports[UserRole.MODERATOR]
        self.assertEqual(self.request(f"/reports/{other.id}/review", token=token).status_code, 403)
        for role, expected in ((UserRole.MODERATOR, 200), (UserRole.ADMINISTRATOR, 200), (UserRole.USER, 403)):
            self.db.execute(update(User).where(User.id == user.id).values(role=role)); self.db.commit()
            self.assertEqual(self.request(f"/reports/{other.id}/review", token=token).status_code, expected)
            self.assertEqual(self.request("/disabled", token=token).status_code, 403)

    def test_inactive_accounts_organizations_and_missing_token(self):
        self.assertEqual(self.client.get(f"/reports/{self.foreign.id}").status_code, 401)
        for role in UserRole:
            user = self.actors[role]
            token = create_access_token(user.id, user.organization_id, self.settings, auth_version=user.auth_version)
            for instance in (user, self.o1):
                instance.status = GeneralStatus.INACTIVE; self.db.commit()
                response = self.request(f"/reports/{self.reports[role].id}", token=token)
                self.assertEqual(response.status_code, 401)
                self.assertEqual(response.headers["www-authenticate"], "Bearer")
                instance.status = GeneralStatus.ACTIVE; self.db.commit()


if __name__ == "__main__":
    unittest.main()
