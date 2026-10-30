import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.auth import (
    Principal,
    authorize_student_access,
    decode_token,
    bootstrap_platform_admin,
    hash_password,
    has_instructor_route_scope,
    issue_token,
    verify_password,
)
from app import main
from app.main import app


def test_pbkdf2_password_hash_verifies_without_storing_plaintext():
    encoded = hash_password("a sufficiently long local password")

    assert encoded.startswith("pbkdf2_sha256$310000$")
    assert "a sufficiently long local password" not in encoded
    assert verify_password("a sufficiently long local password", encoded)
    assert not verify_password("wrong password", encoded)


def test_jwt_contains_signed_short_lived_identity_claims(monkeypatch):
    monkeypatch.setenv("AUTH_JWT_SECRET", "test-secret-value-that-is-at-least-32-bytes")
    token, expires_in = issue_token(
        "learner1",
        "learner",
        student_id="STU-000001",
        now=1000,
    )

    principal = decode_token(token, now=1001)

    assert expires_in == 900
    assert principal == Principal("learner1", "learner", "STU-000001")
    with pytest.raises(ValueError, match="Invalid or expired"):
        decode_token(token, now=1900)
    with pytest.raises(ValueError, match="Invalid or expired"):
        decode_token(token[:-1] + ("A" if token[-1] != "A" else "B"), now=1001)


def test_jwt_requires_configured_secret(monkeypatch):
    monkeypatch.delenv("AUTH_JWT_SECRET", raising=False)

    with pytest.raises(RuntimeError, match="AUTH_JWT_SECRET is required"):
        issue_token("admin", "platform_administrator", now=1000)


def test_bootstrap_consumes_mysql_lock_release_result(monkeypatch):
    class Cursor:
        def __init__(self):
            self.result = None
            self.queries = []
            self.closed = False

        def execute(self, query, params=None):
            self.queries.append(query)
            if "GET_LOCK" in query:
                self.result = {"acquired": 1}
            elif "COUNT(*)" in query:
                self.result = {"user_count": 0}
            elif "RELEASE_LOCK" in query:
                self.result = {"released": 1}
            else:
                self.result = None

        def fetchone(self):
            result = self.result
            self.result = None
            return result

        def close(self):
            assert self.result is None
            self.closed = True

    class Connection:
        def __init__(self):
            self.cursor_instance = Cursor()
            self.committed = False
            self.closed = False

        def cursor(self, dictionary=False):
            return self.cursor_instance

        def start_transaction(self):
            pass

        def commit(self):
            self.committed = True

        def rollback(self):
            pass

        def close(self):
            self.closed = True

    connection = Connection()
    monkeypatch.setattr(
        "app.db.get_connection",
        lambda: connection,
    )
    monkeypatch.setattr("app.db.record_audit_event", lambda *args, **kwargs: None)

    bootstrap_platform_admin("admin", "a sufficiently long password")

    assert connection.committed
    assert connection.cursor_instance.closed
    assert connection.closed
    assert any("RELEASE_LOCK" in query for query in connection.cursor_instance.queries)


def test_login_is_public_and_returns_a_bearer_token(monkeypatch):
    monkeypatch.setattr(
        main,
        "authenticate_user",
        lambda username, password: {
            "username": username,
            "role": "platform_administrator",
            "student_id": None,
        },
    )
    monkeypatch.setattr(main, "issue_token", lambda **kwargs: ("signed-token", 900))
    client = TestClient(app)

    response = client.post(
        "/auth/login",
        json={"username": "admin", "password": "local-password"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "access_token": "signed-token",
        "token_type": "bearer",
        "expires_in": 900,
    }


def test_root_and_health_remain_public():
    client = TestClient(app)

    assert client.get("/").status_code == 200
    assert client.get("/health").status_code == 200


def test_learner_scope_is_limited_to_own_student():
    learner = Principal("learner1", "learner", "STU-000001")

    authorize_student_access(learner, "STU-000001")
    with pytest.raises(HTTPException) as exc_info:
        authorize_student_access(learner, "STU-000002")
    assert exc_info.value.status_code == 403


class ScopeCursor:
    def __init__(self, active):
        self.active = active
        self.query = None
        self.params = None

    def execute(self, query, params):
        self.query = query
        self.params = params

    def fetchone(self):
        return {"1": 1} if self.active else None


def test_instructor_route_scope_requires_active_matching_scope():
    scoped_cursor = ScopeCursor(active=True)
    unscoped_cursor = ScopeCursor(active=False)

    assert has_instructor_route_scope(
        scoped_cursor,
        "teacher1",
        "R-20261030-001",
    )
    assert not has_instructor_route_scope(
        unscoped_cursor,
        "teacher1",
        "R-20261030-002",
    )
    assert "is_active = TRUE" in scoped_cursor.query
    assert scoped_cursor.params == ("teacher1", "R-20261030-001")


def test_role_denial_protects_routes_and_anomaly_summary(monkeypatch):
    monkeypatch.setenv("AUTH_JWT_SECRET", "test-secret-value-that-is-at-least-32-bytes")
    token, _ = issue_token("learner1", "learner", "STU-000001")
    client = TestClient(app)
    headers = {"Authorization": f"Bearer {token}"}

    route_response = client.post(
        "/routes/generate",
        json={"service_date": "2026-10-30"},
        headers=headers,
    )
    summary_response = client.get("/anomalies/summary", headers=headers)

    assert route_response.status_code == 403
    assert summary_response.status_code == 403


def test_client_cannot_supply_requester_authorization_boolean(monkeypatch):
    monkeypatch.setenv("AUTH_JWT_SECRET", "test-secret-value-that-is-at-least-32-bytes")
    token, _ = issue_token("support1", "support_staff")
    client = TestClient(app)

    response = client.post(
        "/notifications/simulate",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "guardian_id": "GUA-000001",
            "student_id": "STU-000001",
            "event_id": "EVT-000001",
            "requester_is_authorized": False,
        },
    )

    assert response.status_code == 422
    assert "requester_is_authorized" in response.text
