"""Local password and short-lived JWT authentication helpers."""

import base64
import hashlib
import hmac
import json
import os
import time
from dataclasses import dataclass

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer


ROLES = {
    "learner",
    "instructor",
    "academic_administrator",
    "support_staff",
    "platform_administrator",
}
REQUESTER_AUTHORIZATION_ROLES = {
    "support_staff",
    "platform_administrator",
}
TOKEN_TTL_SECONDS = 900
MAX_TOKEN_TTL_SECONDS = 3600
PBKDF2_ITERATIONS = 310_000
_bearer = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class Principal:
    username: str
    role: str
    student_id: str | None = None


def _b64url_encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _b64url_decode(value: str) -> bytes:
    return base64.b64decode(
        value + "=" * (-len(value) % 4),
        altchars=b"-_",
        validate=True,
    )


def get_jwt_secret() -> bytes:
    secret = os.getenv("AUTH_JWT_SECRET")
    if not secret:
        raise RuntimeError("AUTH_JWT_SECRET is required.")
    secret_bytes = secret.encode("utf-8")
    if len(secret_bytes) < 32:
        raise RuntimeError("AUTH_JWT_SECRET must contain at least 32 bytes.")
    return secret_bytes


def get_token_ttl() -> int:
    value = os.getenv("AUTH_JWT_TTL_SECONDS", str(TOKEN_TTL_SECONDS))
    try:
        ttl = int(value)
    except ValueError as exc:
        raise RuntimeError("AUTH_JWT_TTL_SECONDS must be an integer.") from exc
    if not 60 <= ttl <= MAX_TOKEN_TTL_SECONDS:
        raise RuntimeError(
            "AUTH_JWT_TTL_SECONDS must be between 60 and 3600."
        )
    return ttl


def hash_password(password: str) -> str:
    if not isinstance(password, str) or not password:
        raise ValueError("Password must not be empty.")
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        PBKDF2_ITERATIONS,
    )
    return "$".join(
        (
            "pbkdf2_sha256",
            str(PBKDF2_ITERATIONS),
            _b64url_encode(salt),
            _b64url_encode(digest),
        )
    )


def verify_password(password: str, encoded_hash: str) -> bool:
    try:
        algorithm, rounds_text, salt_text, digest_text = encoded_hash.split("$")
        rounds = int(rounds_text)
        if algorithm != "pbkdf2_sha256" or not 10_000 <= rounds <= 2_000_000:
            return False
        salt = _b64url_decode(salt_text)
        expected = _b64url_decode(digest_text)
        actual = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            salt,
            rounds,
        )
        return hmac.compare_digest(actual, expected)
    except (AttributeError, TypeError, ValueError):
        return False


def issue_token(
    username: str,
    role: str,
    student_id: str | None = None,
    now: int | None = None,
) -> tuple[str, int]:
    if role not in ROLES or not username:
        raise ValueError("A valid username and role are required.")
    if role == "learner" and not student_id:
        raise ValueError("Learner tokens require a student identity.")

    issued_at = int(time.time() if now is None else now)
    expires_at = issued_at + get_token_ttl()
    header = {"alg": "HS256", "typ": "JWT"}
    payload = {
        "sub": username,
        "role": role,
        "iat": issued_at,
        "exp": expires_at,
    }
    if student_id is not None:
        payload["student_id"] = student_id
    signing_input = ".".join(
        (
            _b64url_encode(json.dumps(header, separators=(",", ":")).encode()),
            _b64url_encode(json.dumps(payload, separators=(",", ":")).encode()),
        )
    )
    signature = hmac.new(
        get_jwt_secret(),
        signing_input.encode("ascii"),
        hashlib.sha256,
    ).digest()
    return f"{signing_input}.{_b64url_encode(signature)}", expires_at - issued_at


def decode_token(token: str, now: int | None = None) -> Principal:
    try:
        header_part, payload_part, signature_part = token.split(".")
        signing_input = f"{header_part}.{payload_part}"
        signature = _b64url_decode(signature_part)
        expected = hmac.new(
            get_jwt_secret(),
            signing_input.encode("ascii"),
            hashlib.sha256,
        ).digest()
        if not hmac.compare_digest(signature, expected):
            raise ValueError("Invalid token signature.")

        header = json.loads(_b64url_decode(header_part))
        payload = json.loads(_b64url_decode(payload_part))
        if header != {"alg": "HS256", "typ": "JWT"}:
            raise ValueError("Unsupported token header.")

        username = payload.get("sub")
        role = payload.get("role")
        issued_at = payload.get("iat")
        expires_at = payload.get("exp")
        student_id = payload.get("student_id")
        current_time = int(time.time() if now is None else now)
        if (
            not isinstance(username, str)
            or not username
            or role not in ROLES
            or not isinstance(issued_at, int)
            or not isinstance(expires_at, int)
            or expires_at <= current_time
            or issued_at > current_time + 60
            or expires_at <= issued_at
            or expires_at - issued_at > MAX_TOKEN_TTL_SECONDS
            or (role == "learner" and not isinstance(student_id, str))
        ):
            raise ValueError("Invalid token claims.")
        return Principal(username, role, student_id)
    except RuntimeError:
        raise
    except (
        AttributeError,
        TypeError,
        ValueError,
        UnicodeDecodeError,
        json.JSONDecodeError,
    ):
        raise ValueError("Invalid or expired token.") from None


def current_principal(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> Principal:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=401,
            detail="Bearer token required.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        return decode_token(credentials.credentials)
    except RuntimeError as exc:
        raise HTTPException(
            status_code=503,
            detail="Authentication is not configured.",
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=401,
            detail="Invalid or expired bearer token.",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


def require_roles(*allowed_roles: str):
    def dependency(principal: Principal = Depends(current_principal)) -> Principal:
        if principal.role not in allowed_roles:
            raise HTTPException(status_code=403, detail="Insufficient role.")
        return principal

    return dependency


def authorize_student_access(principal: Principal, student_id: str) -> None:
    if principal.role == "platform_administrator":
        return
    if principal.role != "learner" or principal.student_id != student_id:
        raise HTTPException(status_code=403, detail="Student access denied.")


def requester_is_authorized(role: str) -> bool:
    return role in REQUESTER_AUTHORIZATION_ROLES


def has_instructor_route_scope(cursor, username: str, route_id: str) -> bool:
    cursor.execute(
        """
        SELECT 1
        FROM instructor_route_scope
        WHERE username = %s AND route_id = %s AND is_active = TRUE
        """,
        (username, route_id),
    )
    return cursor.fetchone() is not None


def authenticate_user(username: str, password: str) -> dict | None:
    from app.db import get_connection

    connection = get_connection()
    cursor = connection.cursor(dictionary=True)
    try:
        cursor.execute(
            """
            SELECT username, password_hash, role, student_id, is_active
            FROM app_user
            WHERE username = %s
            """,
            (username,),
        )
        user = cursor.fetchone()
        if (
            user is None
            or not user["is_active"]
            or not verify_password(password, user["password_hash"])
        ):
            return None
        return user
    finally:
        cursor.close()
        connection.close()


def bootstrap_platform_admin(username: str, password: str) -> None:
    """Create the first platform administrator while serializing bootstraps."""
    from uuid import uuid4

    from app.db import get_connection, record_audit_event

    if not username.strip():
        raise ValueError("Username must not be empty.")
    if len(username.strip()) > 80 or username != username.strip():
        raise ValueError("Username must be at most 80 characters without padding.")
    if len(password) < 12:
        raise ValueError("Password must contain at least 12 characters.")
    if len(password) > 1024:
        raise ValueError("Password must not exceed 1024 characters.")

    connection = get_connection()
    cursor = connection.cursor(dictionary=True)
    lock_acquired = False
    try:
        cursor.execute(
            "SELECT GET_LOCK('yottaflex_bootstrap_admin', 10) AS acquired"
        )
        lock_acquired = cursor.fetchone()["acquired"] == 1
        if not lock_acquired:
            raise RuntimeError("Could not acquire the bootstrap lock.")

        connection.start_transaction()
        cursor.execute("SELECT COUNT(*) AS user_count FROM app_user")
        if cursor.fetchone()["user_count"] != 0:
            raise RuntimeError(
                "Bootstrap is allowed only when no user accounts exist."
            )
        safe_user = {
            "username": username.strip(),
            "role": "platform_administrator",
            "student_id": None,
            "is_active": True,
        }
        cursor.execute(
            """
            INSERT INTO app_user (
                username, password_hash, role, student_id, is_active
            )
            VALUES (%s, %s, 'platform_administrator', NULL, TRUE)
            """,
            (safe_user["username"], hash_password(password)),
        )
        record_audit_event(
            cursor,
            "app_user",
            safe_user["username"],
            "CREATED",
            after=safe_user,
            correlation_id=str(uuid4()),
        )
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        if lock_acquired:
            cursor.execute("SELECT RELEASE_LOCK('yottaflex_bootstrap_admin')")
            cursor.fetchone()
        cursor.close()
        connection.close()
