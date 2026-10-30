
"""Create one synthetic attendance event for local API testing."""

from datetime import datetime

from app.db import get_connection, record_audit_event


def main():
    connection = get_connection()
    cursor = connection.cursor(dictionary=True)

    try:
        # Reuse an existing student and one of their assigned routes.
        cursor.execute(
            """
            SELECT a.student_id, a.route_id
            FROM assignment a
            WHERE a.status = 'ASSIGNED'
            ORDER BY a.student_id
            LIMIT 1
            """
        )
        assignment = cursor.fetchone()

        if assignment is None:
            raise RuntimeError("No assigned student-route pair is available")

        event_id = "EVT-API-TEST-001"

        cursor.execute(
            "SELECT event_id FROM attendance_event WHERE event_id = %s",
            (event_id,),
        )
        if cursor.fetchone():
            print(f"Test event already exists: {event_id}")
            return

        event_time = datetime.now()
        cursor.execute(
            """
            INSERT INTO attendance_event (
                event_id, student_id, route_id,
                event_type, event_time, reason
            )
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (
                event_id,
                assignment["student_id"],
                assignment["route_id"],
                "PRESENT",
                event_time,
                "Synthetic event for local API testing",
            ),
        )
        record_audit_event(
            cursor,
            "attendance_event",
            event_id,
            "CREATED",
            after={
                "event_id": event_id,
                "student_id": assignment["student_id"],
                "route_id": assignment["route_id"],
                "event_type": "PRESENT",
                "event_time": event_time,
                "reason": "Synthetic event for local API testing",
            },
        )
        connection.commit()
        print(f"Created synthetic attendance event: {event_id}")

    except Exception:
        connection.rollback()
        raise
    finally:
        cursor.close()
        connection.close()


if __name__ == "__main__":
    main()
