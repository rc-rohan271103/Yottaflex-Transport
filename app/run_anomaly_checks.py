
"""Read-only database checks for Yottaflex transport anomalies."""

from app.db import get_connection

MINIMUM_PLAUSIBLE_TRAVEL_MINUTES = 10


def main():
    connection = get_connection()
    cursor = connection.cursor(dictionary=True)

    checks = [
        (
            "GT-001",
            "CAPACITY_EXCEEDED",
            """
            SELECT a.assignment_id AS record_id,
                   r.route_id,
                   COUNT(a.assignment_id) AS passenger_count,
                   COALESCE(
                       MAX(bch.capacity),
                       MAX(b.capacity)
                   ) AS bus_capacity
            FROM assignment a
            JOIN route r ON r.route_id = a.route_id
            JOIN bus b ON b.bus_id = r.bus_id
            LEFT JOIN bus_capacity_history bch
              ON bch.bus_id = b.bus_id
             AND r.service_date >= bch.effective_from
             AND (bch.effective_to IS NULL
                  OR r.service_date <= bch.effective_to)
            WHERE a.status = 'ASSIGNED'
            GROUP BY a.assignment_id, r.route_id
            HAVING passenger_count > bus_capacity
            """,
        ),
        (
            "GT-002",
            "ACCESSIBILITY_MISMATCH",
            """
            SELECT a.assignment_id AS record_id,
                   s.student_id,
                   b.bus_id
            FROM assignment a
            JOIN student s ON s.student_id = a.student_id
            JOIN route r ON r.route_id = a.route_id
            JOIN bus b ON b.bus_id = r.bus_id
            WHERE a.status = 'ASSIGNED'
              AND s.accessibility_required = TRUE
              AND b.is_accessible = FALSE
            """,
        ),
        (
            "GT-003",
            "IMPOSSIBLE_TRAVEL_TIME",
            """
            SELECT route_stop_id AS record_id,
                   route_id,
                   stop_id,
                   travel_minutes
            FROM route_stop
            WHERE travel_minutes > 0
              AND travel_minutes < %s
            """,
        ),
        (
            "GT-004",
            "INVALID_GUARDIAN_CONTACT",
            """
            SELECT gc.guardian_id AS record_id,
                   gc.student_id
            FROM guardian_contact gc
            WHERE gc.is_valid = FALSE
            """,
        ),
        (
            "GT-005",
            "UNAUTHORIZED_ADDRESS_DISCLOSURE",
            """
            SELECT a.address_id AS record_id,
                   a.approval_status,
                   a.disclosure_authorized
            FROM address a
            WHERE a.disclosure_authorized = FALSE
               OR a.approval_status <> 'APPROVED'
            """,
        ),
    ]

    try:
        total_findings = 0

        print("Yottaflex database anomaly report")
        print("=" * 48)

        for case_id, anomaly_type, query in checks:
            if case_id == "GT-003":
                cursor.execute(
                    query, (MINIMUM_PLAUSIBLE_TRAVEL_MINUTES,)
                )
            else:
                cursor.execute(query)

            findings = cursor.fetchall()
            total_findings += len(findings)

            print(f"\n{case_id} — {anomaly_type}")
            print(f"Findings: {len(findings)}")

            for finding in findings[:10]:
                # Show synthetic IDs and relevant fields only.
                print(f"  {finding}")

            if len(findings) > 10:
                print(f"  ... and {len(findings) - 10} more")

        print("\n" + "=" * 48)
        print(f"Total findings: {total_findings}")
        print("Report only: no database records were changed.")
        print(
            "Note: GT-003 uses an illustrative 10-minute threshold; "
            "configure and justify this threshold for the project."
        )
        print(
            "Note: GT-005 identifies addresses that are not eligible "
            "for disclosure; it does not attempt to disclose them."
        )

    finally:
        cursor.close()
        connection.close()


if __name__ == "__main__":
    main()
