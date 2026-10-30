
"""Read-only inspection of database fields needed for anomaly checks."""

from app.db import get_connection


QUERIES = {
    "bus": """
        SELECT bus_id, capacity, is_accessible
        FROM bus
        LIMIT 5
    """,
    "student": """
        SELECT student_id, accessibility_required, zone_id
        FROM student
        LIMIT 5
    """,
    "route_stop": """
        SELECT route_stop_id, route_id, stop_id, travel_minutes
        FROM route_stop
        LIMIT 5
    """,
    "guardian_contact": """
        SELECT guardian_id, student_id, is_valid
        FROM guardian_contact
        LIMIT 5
    """,
    "address": """
        SELECT address_id, disclosure_authorized
        FROM address
        LIMIT 5
    """,
}


def main():
    connection = get_connection()
    cursor = connection.cursor(dictionary=True)

    try:
        for table, query in QUERIES.items():
            print(f"\n--- {table} ---")
            cursor.execute(query)
            rows = cursor.fetchall()

            if not rows:
                print("(no rows)")
                continue

            for row in rows:
                print(row)

    finally:
        cursor.close()
        connection.close()


if __name__ == "__main__":
    main()
