
from datetime import date, datetime, time, timedelta
import uuid
from typing import Any

from app.db import get_connection, record_audit_event


def candidate_rank(
    candidate_and_load: tuple[dict[str, Any], int],
) -> tuple[float, int, float, str, int]:
    candidate, passenger_count = candidate_and_load
    arrival = candidate["arrival_time"]
    if isinstance(arrival, timedelta):
        arrival_seconds = arrival.total_seconds()
    elif isinstance(arrival, time):
        arrival_seconds = (
            arrival.hour * 3600
            + arrival.minute * 60
            + arrival.second
            + arrival.microsecond / 1_000_000
        )
    else:
        raise TypeError("Route candidate arrival_time must be a MySQL TIME.")
    return (
        passenger_count / int(candidate["capacity"]),
        int(candidate["travel_minutes"]),
        arrival_seconds,
        candidate["route_id"],
        int(candidate["sequence_no"]),
    )


def _format_arrival_time(value: Any) -> str:
    if isinstance(value, time):
        return value.isoformat()
    if isinstance(value, timedelta):
        converted = datetime.combine(date.min, time.min) + value
        if converted.date() != date.min:
            raise ValueError("Route candidate arrival is outside one day.")
        return converted.time().isoformat()
    raise TypeError("Route candidate arrival_time must be a MySQL TIME.")


def _record_assignment_decision(
    cursor,
    student_id: str,
    decision: str,
    reason_code: str,
    explanation: str,
    candidate_count: int = 0,
    correlation_id: str | None = None,
) -> str:
    decision_id = "DEC-" + uuid.uuid4().hex[:24]
    cursor.execute(
        """
        INSERT INTO assignment_decision (
            decision_id, student_id, decision, reason_code,
            explanation, candidate_count, created_at
        )
        VALUES (%s, %s, %s, %s, %s, %s, NOW())
        """,
        (
            decision_id,
            student_id,
            decision,
            reason_code,
            explanation,
            candidate_count,
        ),
    )
    record_audit_event(
        cursor,
        "assignment_decision",
        decision_id,
        "CREATED",
        after={
            "decision_id": decision_id,
            "student_id": student_id,
            "decision": decision,
            "reason_code": reason_code,
            "candidate_count": candidate_count,
        },
        correlation_id=correlation_id,
    )
    return decision_id


def assign_new_student(student_id: str, service_date: date) -> dict:
    """Assign an active student to a safe, eligible route when capacity allows."""

    connection = get_connection()
    cursor = connection.cursor(dictionary=True)
    correlation_id = str(uuid.uuid4())

    try:
        connection.start_transaction()

        # Lock the student to serialize concurrent assignment requests.
        cursor.execute(
            """
            SELECT student_id, zone_id, accessibility_required,
                   pickup_window_start, pickup_window_end, status
            FROM student
            WHERE student_id = %s
            FOR UPDATE
            """,
            (student_id,),
        )
        student = cursor.fetchone()

        if student is None:
            connection.rollback()
            return {
                "status": "NOT_FOUND",
                "student_id": student_id,
                "message": "Student is not registered.",
            }

        if student["status"] != "ACTIVE":
            message = "Only active students can be assigned."
            decision_id = _record_assignment_decision(
                cursor,
                student_id,
                "REJECTED",
                "STUDENT_INACTIVE",
                message,
                correlation_id=correlation_id,
            )
            connection.commit()
            return {
                "status": "REJECTED",
                "student_id": student_id,
                "reason_code": "STUDENT_INACTIVE",
                "message": message,
                "decision_id": decision_id,
                "correlation_id": correlation_id,
            }

        # Prevent a second assignment covering the same service date.
        cursor.execute(
            """
            SELECT assignment_id
            FROM assignment
            WHERE student_id = %s
              AND status = 'ASSIGNED'
              AND effective_from <= %s
              AND (effective_to IS NULL OR effective_to >= %s)
            LIMIT 1
            FOR UPDATE
            """,
            (student_id, service_date, service_date),
        )
        existing = cursor.fetchone()

        if existing:
            message = (
                "Student already has an assignment covering this date."
            )
            decision_id = _record_assignment_decision(
                cursor,
                student_id,
                "REJECTED",
                "ALREADY_ASSIGNED",
                message,
                correlation_id=correlation_id,
            )
            connection.commit()
            return {
                "status": "REJECTED",
                "student_id": student_id,
                "reason_code": "ALREADY_ASSIGNED",
                "message": message,
                "existing_assignment_id": existing["assignment_id"],
                "decision_id": decision_id,
                "correlation_id": correlation_id,
            }

        # Find routes with an approved stop in the student's zone,
        # a compatible pickup time, an active bus/driver, and exactly
        # one effective capacity-history record for the service date.
        cursor.execute(
            """
            SELECT
                r.route_id,
                r.bus_id,
                rs.stop_id,
                rs.arrival_time,
                rs.travel_minutes,
                rs.sequence_no,
                ch.capacity
            FROM route AS r
            JOIN bus AS b
              ON b.bus_id = r.bus_id
            JOIN driver AS d
              ON d.driver_id = r.driver_id
            JOIN route_stop AS rs
              ON rs.route_id = r.route_id
            JOIN stop AS st
              ON st.stop_id = rs.stop_id
            JOIN address_zone AS az
              ON az.zone_id = st.zone_id
            JOIN bus_capacity_history AS ch
              ON ch.bus_id = b.bus_id
             AND ch.effective_from <= r.service_date
             AND (
                 ch.effective_to IS NULL
                 OR ch.effective_to >= r.service_date
             )
            WHERE r.service_date = %s
              AND r.status IN ('PLANNED', 'ACTIVE')
              AND b.status = 'ACTIVE'
              AND d.status = 'ACTIVE'
              AND st.active_status = TRUE
              AND st.approval_status = 'APPROVED'
              AND az.approved_status = 'APPROVED'
              AND st.zone_id = %s
              AND rs.arrival_time >= %s
              AND rs.arrival_time <= %s
              AND (%s = FALSE OR b.is_accessible = TRUE)
              AND (
                  SELECT COUNT(*)
                  FROM bus_capacity_history AS ch2
                  WHERE ch2.bus_id = b.bus_id
                    AND ch2.effective_from <= r.service_date
                    AND (
                        ch2.effective_to IS NULL
                        OR ch2.effective_to >= r.service_date
                    )
              ) = 1
            ORDER BY r.route_id
            """,
            (
                service_date,
                student["zone_id"],
                student["pickup_window_start"],
                student["pickup_window_end"],
                bool(student["accessibility_required"]),
            ),
        )
        candidates = cursor.fetchall()

        route_loads = {}
        for route_id in sorted({row["route_id"] for row in candidates}):
            # Lock routes in a stable order to serialize capacity checks
            # without acquiring route locks in different candidate orders.
            cursor.execute(
                """
                SELECT route_id
                FROM route
                WHERE route_id = %s
                FOR UPDATE
                """,
                (route_id,),
            )
            if cursor.fetchone() is None:
                continue

            cursor.execute(
                """
                SELECT assignment_id
                FROM assignment
                WHERE route_id = %s
                  AND status = 'ASSIGNED'
                  AND effective_from <= %s
                  AND (effective_to IS NULL OR effective_to >= %s)
                FOR UPDATE
                """,
                (route_id, service_date, service_date),
            )
            route_loads[route_id] = len(cursor.fetchall())

        available_candidates = [
            (candidate, route_loads[candidate["route_id"]])
            for candidate in candidates
            if candidate["route_id"] in route_loads
            and route_loads[candidate["route_id"]]
            < int(candidate["capacity"])
        ]
        ranked_candidates = sorted(
            available_candidates,
            key=candidate_rank,
        )
        selected = ranked_candidates[0][0] if ranked_candidates else None
        passenger_count = ranked_candidates[0][1] if ranked_candidates else None

        if selected is None:
            reason_code = (
                "NO_ELIGIBLE_ROUTE"
                if not candidates
                else "NO_AVAILABLE_CAPACITY"
            )
            explanation = (
                "No route meets the zone, stop, schedule, accessibility, "
                "status, and capacity-history requirements."
                if not candidates
                else
                "Eligible routes were found, but none has sufficient "
                "available capacity."
            )

            decision_id = _record_assignment_decision(
                cursor,
                student_id,
                "UNASSIGNED",
                reason_code,
                explanation,
                len(candidates),
                correlation_id,
            )

            connection.commit()

            return {
                "status": "UNASSIGNED",
                "student_id": student_id,
                "service_date": service_date.isoformat(),
                "reason_code": reason_code,
                "message": explanation,
                "eligible_candidates_checked": len(candidates),
                "assignment_created": False,
                "decision_id": decision_id,
                "correlation_id": correlation_id,
            }

        # Use a unique ID so a previous ended assignment cannot cause
        # a primary-key collision for this student and service date.
        assignment_id = (
            f"ASG-{student_id}-{service_date.strftime('%Y%m%d')}-"
            f"{uuid.uuid4().hex[:8]}"
        )

        cursor.execute(
            """
            INSERT INTO assignment (
                assignment_id, student_id, route_id, stop_id,
                effective_from, effective_to, status
            )
            VALUES (%s, %s, %s, %s, %s, %s, 'ASSIGNED')
            """,
            (
                assignment_id,
                student_id,
                selected["route_id"],
                selected["stop_id"],
                service_date,
                service_date,
            ),
        )
        record_audit_event(
            cursor,
            "assignment",
            assignment_id,
            "CREATED",
            after={
                "assignment_id": assignment_id,
                "student_id": student_id,
                "route_id": selected["route_id"],
                "stop_id": selected["stop_id"],
                "effective_from": service_date,
                "effective_to": service_date,
                "status": "ASSIGNED",
            },
            correlation_id=correlation_id,
        )

        decision_id = _record_assignment_decision(
            cursor,
            student_id,
            "ACCEPTED",
            "ASSIGNMENT_CREATED",
            (
                f"Assigned to route {selected['route_id']} "
                f"and stop {selected['stop_id']}."
            ),
            len(candidates),
            correlation_id,
        )

        connection.commit()

        return {
            "status": "ASSIGNED",
            "student_id": student_id,
            "service_date": service_date.isoformat(),
            "assignment_id": assignment_id,
            "route_id": selected["route_id"],
            "bus_id": selected["bus_id"],
            "stop_id": selected["stop_id"],
            "arrival_time": _format_arrival_time(selected["arrival_time"]),
            "bus_capacity": int(selected["capacity"]),
            "passengers_before_assignment": passenger_count,
            "candidate_score": {
                "route_utilization": round(
                    passenger_count / int(selected["capacity"]),
                    4,
                ),
                "travel_minutes": int(selected["travel_minutes"]),
                "arrival_time": _format_arrival_time(selected["arrival_time"]),
            },
            "remaining_capacity_after_assignment": (
                int(selected["capacity"]) - passenger_count - 1
            ),
            "decision_id": decision_id,
            "correlation_id": correlation_id,
        }

    except Exception:
        connection.rollback()
        raise

    finally:
        cursor.close()
        connection.close()
