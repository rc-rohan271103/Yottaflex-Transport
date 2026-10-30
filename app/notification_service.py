
"""Record simulated notification decisions; never send real messages."""

from datetime import datetime, timezone
from uuid import uuid4

from app.db import get_connection, record_audit_event
from app.auth import requester_is_authorized


def record_notification(guardian_id, student_id, event_id, requester_role):
    """Validate against MySQL, then record a simulated decision."""

    connection = get_connection()
    cursor = connection.cursor(dictionary=True)
    correlation_id = str(uuid4())

    try:
        connection.start_transaction()

        cursor.execute(
            """
            SELECT student_id, is_valid, consent_status
            FROM guardian_contact
            WHERE guardian_id = %s
            FOR UPDATE
            """,
            (guardian_id,),
        )
        guardian = cursor.fetchone()

        if guardian is None:
            raise ValueError("Guardian contact does not exist")

        if guardian["student_id"] != student_id:
            raise ValueError("Guardian does not belong to this student")

        # Verify the attendance event exists and belongs to this student
        cursor.execute(
            """
            SELECT student_id
            FROM attendance_event
            WHERE event_id = %s
            FOR UPDATE
            """,
            (event_id,),
        )
        event = cursor.fetchone()

        if event is None:
            raise ValueError("Attendance event does not exist")

        if event["student_id"] != student_id:
            raise ValueError("Attendance event does not belong to this student")

        cursor.execute(
            """
            SELECT notification_id
            FROM notification
            WHERE event_id = %s
            FOR UPDATE
            """,
            (event_id,),
        )
        if cursor.fetchone() is not None:
            raise ValueError(
                "A notification decision already exists for this event."
            )

        if not guardian["is_valid"]:
            status = "BLOCKED_INVALID_CONTACT"
            reason = "Guardian contact is marked invalid"
        elif guardian["consent_status"] != "GRANTED":
            status = "BLOCKED_CONSENT"
            reason = "Guardian consent is not granted"
        elif not requester_is_authorized(requester_role):
            status = "BLOCKED_AUTHORIZATION"
            reason = "Requester is not authorized"
        else:
            status = "SIMULATED_SENT"
            reason = "Checks passed; no real message was sent"

        notification_id = f"NTF-{uuid4().hex[:20]}"
        created_at = datetime.now(timezone.utc).replace(tzinfo=None)

        cursor.execute(
            """
            INSERT INTO notification (
                notification_id, guardian_id, student_id, event_id,
                status, reason, created_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (
                notification_id,
                guardian_id,
                student_id,
                event_id,
                status,
                reason,
                created_at,
            ),
        )
        record_audit_event(
            cursor,
            "notification",
            notification_id,
            "CREATED",
            after={
                "notification_id": notification_id,
                "guardian_id": guardian_id,
                "student_id": student_id,
                "event_id": event_id,
                "status": status,
                "reason": reason,
            },
            correlation_id=correlation_id,
        )
        connection.commit()

        return {
            "notification_id": notification_id,
            "status": status,
            "reason": reason,
            "correlation_id": correlation_id,
        }

    except Exception:
        connection.rollback()
        raise
    finally:
        cursor.close()
        connection.close()
