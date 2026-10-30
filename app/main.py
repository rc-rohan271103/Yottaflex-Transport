
"""Yottaflex transport API."""

from fastapi import Depends, FastAPI, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field

from app.auth import (
    Principal,
    authenticate_user,
    authorize_student_access,
    hash_password,
    has_instructor_route_scope,
    issue_token,
    require_roles,
)
from app.db import get_connection, record_audit_event
from app.notification_service import record_notification
from app.address_service import check_address_access
from datetime import date
from app.assignment_service import assign_new_student
from app.registration_service import register_student_with_guardian
from app.route_service import RouteGenerationError, create_routes_for_date
from datetime import datetime
from enum import Enum
from uuid import uuid4

app = FastAPI(
    title="Yottaflex Transport API",
    description="School transport assignments, safety checks, and notifications.",
    version="1.0.0",
)


class StrictRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LoginRequest(StrictRequest):
    username: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=1, max_length=1024)


class UserRole(str, Enum):
    LEARNER = "learner"
    INSTRUCTOR = "instructor"
    ACADEMIC_ADMINISTRATOR = "academic_administrator"
    SUPPORT_STAFF = "support_staff"
    PLATFORM_ADMINISTRATOR = "platform_administrator"


class UserCreateRequest(StrictRequest):
    username: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=12, max_length=1024)
    role: UserRole
    student_id: str | None = Field(default=None, max_length=20)


class UserUpdateRequest(StrictRequest):
    password: str | None = Field(default=None, min_length=12, max_length=1024)
    role: UserRole | None = None
    student_id: str | None = Field(default=None, max_length=20)
    is_active: bool | None = None


class RouteScopeRequest(StrictRequest):
    route_id: str = Field(min_length=1, max_length=30)


class NotificationRequest(StrictRequest):
    guardian_id: str
    student_id: str
    event_id: str


class AddressAccessRequest(StrictRequest):
    address_id: str


@app.post("/auth/login")
def login(request: LoginRequest):
    """Exchange local credentials for a short-lived signed bearer token."""
    try:
        user = authenticate_user(request.username, request.password)
    except RuntimeError as exc:
        raise HTTPException(
            status_code=503,
            detail="Authentication is not available.",
        ) from exc
    if user is None:
        raise HTTPException(
            status_code=401,
            detail="Invalid username or password.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        token, expires_in = issue_token(
            username=user["username"],
            role=user["role"],
            student_id=user["student_id"],
        )
    except RuntimeError as exc:
        raise HTTPException(
            status_code=503,
            detail="Authentication is not configured.",
        ) from exc
    return {
        "access_token": token,
        "token_type": "bearer",
        "expires_in": expires_in,
    }


@app.post("/auth/users", status_code=status.HTTP_201_CREATED)
def create_user(
    request: UserCreateRequest,
    principal: Principal = Depends(
        require_roles("platform_administrator")
    ),
):
    """Provision a local account without exposing credentials in audit data."""
    del principal
    username = request.username.strip()
    if username != request.username:
        raise HTTPException(status_code=400, detail="Invalid username.")
    if (request.role == UserRole.LEARNER) != (request.student_id is not None):
        raise HTTPException(
            status_code=400,
            detail="Learners require a student_id; other roles must omit it.",
        )

    safe_user = {
        "username": username,
        "role": request.role.value,
        "student_id": request.student_id,
        "is_active": True,
    }
    connection = get_connection()
    cursor = connection.cursor(dictionary=True)
    correlation_id = str(uuid4())
    try:
        connection.start_transaction()
        cursor.execute(
            """
            INSERT INTO app_user (
                username, password_hash, role, student_id, is_active
            )
            VALUES (%s, %s, %s, %s, TRUE)
            """,
            (
                username,
                hash_password(request.password),
                request.role.value,
                request.student_id,
            ),
        )
        record_audit_event(
            cursor,
            "app_user",
            username,
            "CREATED",
            after=safe_user,
            correlation_id=correlation_id,
        )
        connection.commit()
        return {**safe_user, "correlation_id": correlation_id}
    except Exception as exc:
        connection.rollback()
        raise HTTPException(
            status_code=409,
            detail="Unable to create user; username or student may exist.",
        ) from exc
    finally:
        cursor.close()
        connection.close()


@app.patch("/auth/users/{username}")
def update_user(
    username: str,
    request: UserUpdateRequest,
    principal: Principal = Depends(
        require_roles("platform_administrator")
    ),
):
    """Update an account and audit only non-secret identity fields."""
    del principal
    updates = request.model_dump(exclude_unset=True)
    if not updates:
        raise HTTPException(status_code=400, detail="No user changes supplied.")

    connection = get_connection()
    cursor = connection.cursor(dictionary=True)
    correlation_id = str(uuid4())
    try:
        connection.start_transaction()
        cursor.execute(
            """
            SELECT username, role, student_id, is_active
            FROM app_user
            WHERE username = %s
            FOR UPDATE
            """,
            (username,),
        )
        current = cursor.fetchone()
        if current is None:
            raise HTTPException(status_code=404, detail="User not found.")

        updated = dict(current)
        if "role" in updates and updates["role"] is not None:
            updated["role"] = updates["role"].value
        if "student_id" in updates:
            updated["student_id"] = updates["student_id"]
        if "is_active" in updates and updates["is_active"] is not None:
            updated["is_active"] = updates["is_active"]
        if (updated["role"] == "learner") != (updated["student_id"] is not None):
            raise HTTPException(
                status_code=400,
                detail="Learners require a student_id; other roles must omit it.",
            )

        assignments = []
        values = []
        if "role" in updates and updates["role"] is not None:
            assignments.append("role = %s")
            values.append(updated["role"])
        if "student_id" in updates:
            assignments.append("student_id = %s")
            values.append(updated["student_id"])
        if "is_active" in updates and updates["is_active"] is not None:
            assignments.append("is_active = %s")
            values.append(updated["is_active"])
        if updates.get("password") is not None:
            assignments.append("password_hash = %s")
            values.append(hash_password(updates["password"]))
        if not assignments:
            raise HTTPException(status_code=400, detail="No user changes supplied.")
        values.append(username)
        cursor.execute(
            f"UPDATE app_user SET {', '.join(assignments)} WHERE username = %s",
            values,
        )

        safe_before = {
            "username": current["username"],
            "role": current["role"],
            "student_id": current["student_id"],
            "is_active": bool(current["is_active"]),
        }
        safe_after = {
            "username": updated["username"],
            "role": updated["role"],
            "student_id": updated["student_id"],
            "is_active": bool(updated["is_active"]),
        }
        if updates.get("password") is not None:
            safe_after["password_changed"] = True
        record_audit_event(
            cursor,
            "app_user",
            username,
            "UPDATED",
            before=safe_before,
            after=safe_after,
            correlation_id=correlation_id,
        )
        if current["role"] == "instructor" and updated["role"] != "instructor":
            cursor.execute(
                """
                SELECT scope_id, route_id
                FROM instructor_route_scope
                WHERE username = %s AND is_active = TRUE
                FOR UPDATE
                """,
                (username,),
            )
            for scope in cursor.fetchall():
                cursor.execute(
                    """
                    UPDATE instructor_route_scope
                    SET is_active = FALSE
                    WHERE scope_id = %s
                    """,
                    (scope["scope_id"],),
                )
                scope_before = {
                    "username": username,
                    "route_id": scope["route_id"],
                    "is_active": True,
                }
                record_audit_event(
                    cursor,
                    "instructor_route_scope",
                    scope["scope_id"],
                    "UPDATED",
                    before=scope_before,
                    after={**scope_before, "is_active": False},
                    correlation_id=correlation_id,
                )
        connection.commit()
        return {**safe_after, "correlation_id": correlation_id}
    except HTTPException:
        connection.rollback()
        raise
    except Exception as exc:
        connection.rollback()
        raise HTTPException(
            status_code=409,
            detail="Unable to update user.",
        ) from exc
    finally:
        cursor.close()
        connection.close()


@app.post("/auth/users/{username}/route-scopes", status_code=201)
def grant_route_scope(
    username: str,
    request: RouteScopeRequest,
    principal: Principal = Depends(
        require_roles("platform_administrator")
    ),
):
    """Grant or reactivate one instructor route scope."""
    del principal
    connection = get_connection()
    cursor = connection.cursor(dictionary=True)
    correlation_id = str(uuid4())
    try:
        connection.start_transaction()
        cursor.execute(
            "SELECT role FROM app_user WHERE username = %s FOR UPDATE",
            (username,),
        )
        user = cursor.fetchone()
        if user is None:
            raise HTTPException(status_code=404, detail="User not found.")
        if user["role"] != "instructor":
            raise HTTPException(
                status_code=409,
                detail="Route scopes may be assigned only to instructors.",
            )

        cursor.execute(
            """
            SELECT scope_id, is_active
            FROM instructor_route_scope
            WHERE username = %s AND route_id = %s
            FOR UPDATE
            """,
            (username, request.route_id),
        )
        existing = cursor.fetchone()
        if existing and existing["is_active"]:
            raise HTTPException(
                status_code=409,
                detail="Instructor already has this active route scope.",
            )
        if existing:
            cursor.execute(
                """
                UPDATE instructor_route_scope
                SET is_active = TRUE
                WHERE scope_id = %s
                """,
                (existing["scope_id"],),
            )
            action = "UPDATED"
            before = {
                "username": username,
                "route_id": request.route_id,
                "is_active": False,
            }
        else:
            scope_id = "SCP-" + uuid4().hex[:24]
            cursor.execute(
                """
                INSERT INTO instructor_route_scope (
                    scope_id, username, route_id, is_active
                )
                VALUES (%s, %s, %s, TRUE)
                """,
                (scope_id, username, request.route_id),
            )
            action = "CREATED"
            before = None
        after = {
            "username": username,
            "route_id": request.route_id,
            "is_active": True,
        }
        record_audit_event(
            cursor,
            "instructor_route_scope",
            existing["scope_id"] if existing else scope_id,
            action,
            before=before,
            after=after,
            correlation_id=correlation_id,
        )
        connection.commit()
        return {**after, "correlation_id": correlation_id}
    except HTTPException:
        connection.rollback()
        raise
    except Exception as exc:
        connection.rollback()
        raise HTTPException(
            status_code=409,
            detail="Unable to grant route scope; route may not exist.",
        ) from exc
    finally:
        cursor.close()
        connection.close()


@app.delete("/auth/users/{username}/route-scopes/{route_id}")
def revoke_route_scope(
    username: str,
    route_id: str,
    principal: Principal = Depends(
        require_roles("platform_administrator")
    ),
):
    """Deactivate an instructor route scope without deleting its audit trail."""
    del principal
    connection = get_connection()
    cursor = connection.cursor(dictionary=True)
    correlation_id = str(uuid4())
    try:
        connection.start_transaction()
        cursor.execute(
            """
            SELECT scope_id, is_active
            FROM instructor_route_scope
            WHERE username = %s AND route_id = %s
            FOR UPDATE
            """,
            (username, route_id),
        )
        scope = cursor.fetchone()
        if scope is None or not scope["is_active"]:
            raise HTTPException(status_code=404, detail="Active scope not found.")
        cursor.execute(
            "UPDATE instructor_route_scope SET is_active = FALSE WHERE scope_id = %s",
            (scope["scope_id"],),
        )
        safe_before = {
            "username": username,
            "route_id": route_id,
            "is_active": True,
        }
        safe_after = {**safe_before, "is_active": False}
        record_audit_event(
            cursor,
            "instructor_route_scope",
            scope["scope_id"],
            "UPDATED",
            before=safe_before,
            after=safe_after,
            correlation_id=correlation_id,
        )
        connection.commit()
        return {**safe_after, "correlation_id": correlation_id}
    except HTTPException:
        connection.rollback()
        raise
    except Exception as exc:
        connection.rollback()
        raise HTTPException(
            status_code=500,
            detail="Unable to revoke route scope.",
        ) from exc
    finally:
        cursor.close()
        connection.close()


class RouteGenerationRequest(BaseModel):
    service_date: date


@app.post("/routes/generate", status_code=201)
def generate_routes_endpoint(
    request: RouteGenerationRequest,
    principal: Principal = Depends(
        require_roles("academic_administrator", "platform_administrator")
    ),
):
    """Create routes and approved-stop schedules for a service date."""
    del principal
    try:
        return create_routes_for_date(request.service_date)
    except RouteGenerationError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail="Unable to create routes for the service date.",
        ) from exc


@app.get("/")
def root():
    return {
        "message": "Yottaflex Transport API is running",
        "status": "ok",
    }


@app.get("/health")
def health():
    return {"status": "healthy"}


@app.get("/students/{student_id}/transport")
def read_student_transport(
    student_id: str,
    principal: Principal = Depends(
        require_roles("learner", "platform_administrator")
    ),
):
    """Return assignment and scheduled-stop data for the authenticated learner."""
    authorize_student_access(principal, student_id)
    connection = get_connection()
    cursor = connection.cursor(dictionary=True)
    try:
        cursor.execute(
            """
            SELECT
                a.assignment_id,
                a.route_id,
                r.service_date,
                r.status AS route_status,
                a.stop_id,
                a.status AS assignment_status,
                rs.sequence_no,
                rs.arrival_time
            FROM assignment AS a
            JOIN route AS r ON r.route_id = a.route_id
            LEFT JOIN route_stop AS rs
              ON rs.route_id = a.route_id
             AND rs.stop_id = a.stop_id
            WHERE a.student_id = %s
            ORDER BY r.service_date DESC, a.assignment_id
            """,
            (student_id,),
        )
        return {"student_id": student_id, "assignments": cursor.fetchall()}
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail="Unable to read student transport.",
        ) from exc
    finally:
        cursor.close()
        connection.close()


@app.get("/students/{student_id}/attendance")
def read_student_attendance(
    student_id: str,
    principal: Principal = Depends(
        require_roles("learner", "platform_administrator")
    ),
):
    """Return attendance history for the authenticated learner."""
    authorize_student_access(principal, student_id)
    connection = get_connection()
    cursor = connection.cursor(dictionary=True)
    try:
        cursor.execute(
            """
            SELECT event_id, route_id, event_type, event_time, reason
            FROM attendance_event
            WHERE student_id = %s
            ORDER BY event_time DESC, event_id
            """,
            (student_id,),
        )
        return {"student_id": student_id, "attendance": cursor.fetchall()}
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail="Unable to read student attendance.",
        ) from exc
    finally:
        cursor.close()
        connection.close()


@app.get("/anomalies/summary")
def anomaly_summary(
    principal: Principal = Depends(
        require_roles("academic_administrator", "platform_administrator")
    ),
):
    """Return counts of detected anomalies without exposing record details."""
    del principal
    checks = {
        "GT-001": """
            SELECT COUNT(*) AS total
            FROM (
                SELECT a.route_id
                FROM assignment a
                JOIN route r ON r.route_id = a.route_id
                JOIN bus_capacity_history h ON h.bus_id = r.bus_id
                  AND h.effective_from <= r.service_date
                  AND (
                      h.effective_to IS NULL
                      OR h.effective_to >= r.service_date
                  )
                WHERE a.status = 'ASSIGNED'
                GROUP BY a.route_id, h.capacity
                HAVING COUNT(a.assignment_id) > h.capacity
            ) AS findings
        """,
        "GT-002": """
            SELECT COUNT(*) AS total
            FROM assignment a
            JOIN student s ON s.student_id = a.student_id
            JOIN route r ON r.route_id = a.route_id
            JOIN bus b ON b.bus_id = r.bus_id
            WHERE a.status = 'ASSIGNED'
              AND s.accessibility_required = TRUE
              AND b.is_accessible = FALSE
        """,
        "GT-003": """
            SELECT COUNT(*) AS total
            FROM route_stop
            WHERE travel_minutes > 0
              AND travel_minutes < 10
        """,
        "GT-004": """
            SELECT COUNT(*) AS total
            FROM guardian_contact
            WHERE is_valid = FALSE
        """,
        "GT-005": """
            SELECT COUNT(*) AS total
            FROM address
            WHERE disclosure_authorized = FALSE
               OR approval_status <> 'APPROVED'
        """,
    }

    connection = get_connection()
    cursor = connection.cursor(dictionary=True)

    try:
        results = {}

        for case_id, query in checks.items():
            cursor.execute(query)
            results[case_id] = cursor.fetchone()["total"]

        return {
            "status": "ok",
            "threshold_note": (
                "GT-003 uses an illustrative 10-minute threshold."
            ),
            "findings": results,
            "total_findings": sum(results.values()),
        }

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail="Unable to calculate anomaly summary.",
        ) from exc

    finally:
        cursor.close()
        connection.close()

@app.post("/notifications/simulate")
def simulate_notification(
    request: NotificationRequest,
    principal: Principal = Depends(
        require_roles("support_staff", "platform_administrator")
    ),
):
    """Record a simulated notification decision; never send a real message."""
    try:
        return record_notification(
            guardian_id=request.guardian_id,
            student_id=request.student_id,
            event_id=request.event_id,
            requester_role=principal.role,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail="Unable to record notification decision.",
        ) from exc
@app.get("/notifications/readiness")
def notification_readiness(
    principal: Principal = Depends(
        require_roles("platform_administrator")
    ),
):
    """Check whether notification simulation has required database records."""
    del principal
    connection = get_connection()
    cursor = connection.cursor(dictionary=True)

    try:
        cursor.execute("SELECT COUNT(*) AS total FROM attendance_event")
        event_count = cursor.fetchone()["total"]

        cursor.execute("SELECT COUNT(*) AS total FROM guardian_contact")
        guardian_count = cursor.fetchone()["total"]

        return {
            "ready": event_count > 0 and guardian_count > 0,
            "attendance_events_available": event_count > 0,
            "guardian_contacts_available": guardian_count > 0,
            "message": (
                "Ready for notification simulation"
                if event_count > 0 and guardian_count > 0
                else "Attendance events must be generated before testing"
            ),
        }
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail="Unable to check notification readiness.",
        ) from exc
    finally:
        cursor.close()
        connection.close()


@app.post("/addresses/check-access")
def check_address_access_endpoint(
    request: AddressAccessRequest,
    principal: Principal = Depends(
        require_roles("support_staff", "platform_administrator")
    ),
):
    """Check address permissions without returning address details."""
    try:
        return check_address_access(
            address_id=request.address_id,
            requester_role=principal.role,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail="Unable to check address access.",
        ) from exc
class NewStudentAssignmentRequest(BaseModel):
    student_id: str
    service_date: date


@app.post("/assignments/assign-new-student")
def assign_new_student_endpoint(
    request: NewStudentAssignmentRequest,
    principal: Principal = Depends(
        require_roles("academic_administrator", "platform_administrator")
    ),
):
    """Assign a registered student to an eligible route and stop."""
    del principal
    try:
        result = assign_new_student(
            student_id=request.student_id,
            service_date=request.service_date,
        )

        if result["status"] == "NOT_FOUND":
            raise HTTPException(status_code=404, detail=result)

        if result["status"] in {"REJECTED", "UNASSIGNED"}:
            raise HTTPException(status_code=409, detail=result)

        return result

    except HTTPException:
        raise
    except Exception as exc:
        import traceback
        traceback.print_exc()
        raise HTTPException(
             status_code=500,
             detail="Unable to process student assignment.",
        ) from exc



from datetime import time
from pydantic import Field


class StudentRegistrationRequest(BaseModel):
    student_id: str = Field(min_length=1, max_length=20)
    zone_id: str = Field(min_length=1, max_length=20)
    address_id: str = Field(min_length=1, max_length=20)
    pickup_window_start: time
    pickup_window_end: time
    accessibility_required: bool = False

    guardian_id: str = Field(min_length=1, max_length=20)
    synthetic_phone: str = Field(min_length=1, max_length=30)
    synthetic_email: str = Field(min_length=3, max_length=150)
    consent_status: str


@app.post("/students/register")
def register_student_endpoint(
    request: StudentRegistrationRequest,
    principal: Principal = Depends(
        require_roles("academic_administrator", "platform_administrator")
    ),
):
    """Register a student and guardian in one transaction."""
    del principal
    try:
        return register_student_with_guardian(
            student_id=request.student_id,
            zone_id=request.zone_id,
            address_id=request.address_id,
            pickup_window_start=request.pickup_window_start,
            pickup_window_end=request.pickup_window_end,
            accessibility_required=request.accessibility_required,
            guardian_id=request.guardian_id,
            synthetic_phone=request.synthetic_phone,
            synthetic_email=request.synthetic_email,
            consent_status=request.consent_status,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail="Unable to register student and guardian.",
        ) from exc


class AttendanceEventType(str, Enum):
    PRESENT = "PRESENT"
    ABSENT = "ABSENT"
    BOARDED = "BOARDED"
    MISSED_PICKUP = "MISSED_PICKUP"
    DISRUPTION_REASSIGNED = "DISRUPTION_REASSIGNED"


class AttendanceEventRequest(BaseModel):
    student_id: str = Field(min_length=1, max_length=20)
    route_id: str = Field(min_length=1, max_length=30)
    event_type: AttendanceEventType
    reason: str = Field(min_length=1, max_length=255)
    event_time: datetime | None = None


@app.post("/attendance/events", status_code=201)
def record_attendance_event(
    request: AttendanceEventRequest,
    principal: Principal = Depends(
        require_roles("instructor", "platform_administrator")
    ),
):
    """Append an attendance event without overwriting previous history."""

    connection = get_connection()
    cursor = connection.cursor(dictionary=True)

    try:
        if principal.role == "instructor" and not has_instructor_route_scope(
            cursor,
            principal.username,
            request.route_id,
        ):
            raise HTTPException(
                status_code=403,
                detail="Instructor is not scoped to this route.",
            )
        event_time = request.event_time or datetime.now()
        cursor.execute(
            """
            SELECT r.service_date
            FROM route AS r
            JOIN assignment AS a
              ON a.route_id = r.route_id
             AND a.student_id = %s
             AND a.status = 'ASSIGNED'
             AND a.effective_from <= r.service_date
             AND (
                 a.effective_to IS NULL
                 OR a.effective_to >= r.service_date
             )
            WHERE r.route_id = %s
            """,
            (request.student_id, request.route_id),
        )
        route_assignment = cursor.fetchone()
        if route_assignment is None:
            raise HTTPException(
                status_code=409,
                detail=(
                    "Student must have an active assignment to the route "
                    "before recording attendance."
                ),
            )

        service_date = route_assignment["service_date"]
        if isinstance(service_date, datetime):
            service_date = service_date.date()
        if event_time.date() != service_date:
            raise HTTPException(
                status_code=400,
                detail="Attendance event date must match the route service date.",
            )

        event_id = f"EVT-{uuid4().hex[:20]}"
        correlation_id = str(uuid4())

        cursor.execute(
            """
            INSERT INTO attendance_event
                (event_id, student_id, route_id, event_type, event_time, reason)
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (
                event_id,
                request.student_id,
                request.route_id,
                request.event_type.value,
                event_time,
                request.reason,
            ),
        )
        record_audit_event(
            cursor,
            "attendance_event",
            event_id,
            "CREATED",
            after={
                "event_id": event_id,
                "student_id": request.student_id,
                "route_id": request.route_id,
                "event_type": request.event_type.value,
                "event_time": event_time,
            },
            correlation_id=correlation_id,
        )

        connection.commit()

        return {
            "status": "RECORDED",
            "correlation_id": correlation_id,
            "event_id": event_id,
            "student_id": request.student_id,
            "route_id": request.route_id,
            "event_type": request.event_type.value,
            "event_time": event_time.isoformat(),
            "reason": request.reason,
        }

    except HTTPException:
        connection.rollback()
        raise
    except Exception as exc:
        connection.rollback()
        raise HTTPException(
            status_code=500,
            detail="Unable to record attendance event.",
        ) from exc
    finally:
        cursor.close()
        connection.close()
