
from datetime import time
from uuid import uuid4

from app.db import get_connection, record_audit_event


def register_student_with_guardian(
    student_id: str,
    zone_id: str,
    address_id: str,
    pickup_window_start: time,
    pickup_window_end: time,
    guardian_id: str,
    synthetic_phone: str,
    synthetic_email: str,
    consent_status: str,
    accessibility_required: bool = False,
) -> dict:
    """Register a student and guardian atomically."""

    consent_status = consent_status.upper()

    if pickup_window_start >= pickup_window_end:
        raise ValueError(
            "Pickup window start must be earlier than pickup window end."
        )

    if consent_status not in {"GRANTED", "DENIED"}:
        raise ValueError("Consent status must be GRANTED or DENIED.")

    if not synthetic_phone.strip():
        raise ValueError("Synthetic phone must not be empty.")

    if not synthetic_email.strip() or "@" not in synthetic_email:
        raise ValueError("A valid synthetic email format is required.")

    connection = get_connection()
    cursor = connection.cursor(dictionary=True)
    correlation_id = str(uuid4())

    try:
        connection.start_transaction()

        # Confirm the selected zone is approved.
        cursor.execute(
            """
            SELECT zone_id
            FROM address_zone
            WHERE zone_id = %s
              AND approved_status = 'APPROVED'
            FOR UPDATE
            """,
            (zone_id,),
        )
        if cursor.fetchone() is None:
            raise ValueError("Zone does not exist or is not approved.")

        # Confirm the address is approved and belongs to that zone.
        cursor.execute(
            """
            SELECT address_id
            FROM address
            WHERE address_id = %s
              AND zone_id = %s
              AND approval_status = 'APPROVED'
            FOR UPDATE
            """,
            (address_id, zone_id),
        )
        if cursor.fetchone() is None:
            raise ValueError(
                "Address does not exist, is not approved, "
                "or does not belong to the selected zone."
            )

        # Reject duplicate student IDs.
        cursor.execute(
            "SELECT student_id FROM student WHERE student_id = %s",
            (student_id,),
        )
        if cursor.fetchone() is not None:
            raise ValueError("Student ID already exists.")

        # Reject duplicate guardian IDs.
        cursor.execute(
            "SELECT guardian_id FROM guardian_contact WHERE guardian_id = %s",
            (guardian_id,),
        )
        if cursor.fetchone() is not None:
            raise ValueError("Guardian ID already exists.")

        # Insert the student.
        cursor.execute(
            """
            INSERT INTO student (
                student_id,
                zone_id,
                address_id,
                accessibility_required,
                pickup_window_start,
                pickup_window_end,
                status
            )
            VALUES (%s, %s, %s, %s, %s, %s, 'ACTIVE')
            """,
            (
                student_id,
                zone_id,
                address_id,
                accessibility_required,
                pickup_window_start,
                pickup_window_end,
            ),
        )
        record_audit_event(
            cursor,
            "student",
            student_id,
            "CREATED",
            after={
                "student_id": student_id,
                "zone_id": zone_id,
                "address_id": address_id,
                "accessibility_required": accessibility_required,
                "pickup_window_start": pickup_window_start,
                "pickup_window_end": pickup_window_end,
                "status": "ACTIVE",
            },
            correlation_id=correlation_id,
        )

        # Insert the linked guardian in the same transaction.
        cursor.execute(
            """
            INSERT INTO guardian_contact (
                guardian_id,
                student_id,
                synthetic_phone,
                synthetic_email,
                is_valid,
                consent_status
            )
            VALUES (%s, %s, %s, %s, TRUE, %s)
            """,
            (
                guardian_id,
                student_id,
                synthetic_phone.strip(),
                synthetic_email.strip(),
                consent_status,
            ),
        )
        record_audit_event(
            cursor,
            "guardian_contact",
            guardian_id,
            "CREATED",
            after={
                "guardian_id": guardian_id,
                "student_id": student_id,
                "is_valid": True,
                "consent_status": consent_status,
            },
            correlation_id=correlation_id,
        )

        # Both records succeed together.
        connection.commit()

        return {
            "status": "REGISTERED",
            "correlation_id": correlation_id,
            "student": {
                "student_id": student_id,
                "zone_id": zone_id,
                "address_id": address_id,
                "accessibility_required": accessibility_required,
                "pickup_window_start": str(pickup_window_start),
                "pickup_window_end": str(pickup_window_end),
            },
            "guardian": {
                "guardian_id": guardian_id,
                "consent_status": consent_status,
                "is_valid": True,
            },
            "message": (
                "Student and guardian registered successfully. "
                "No notification was sent."
            ),
        }

    except Exception:
        connection.rollback()
        raise

    finally:
        cursor.close()
        connection.close()
