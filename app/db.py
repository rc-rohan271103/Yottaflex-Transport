
import json
import os
from uuid import uuid4

import mysql.connector
from dotenv import load_dotenv

load_dotenv()


def get_connection():
    password = os.getenv("DB_PASSWORD")

    if not password:
        raise RuntimeError(
            "DB_PASSWORD is missing from your .env file"
        )

    return mysql.connector.connect(
        host=os.getenv("DB_HOST", "localhost"),
        port=int(os.getenv("DB_PORT", "3306")),
        database=os.getenv(
            "DB_NAME", "yottaflex_transport"
        ),
        user=os.getenv("DB_USER", "yottaflex_app"),
        password=password,
    )


def record_audit_event(
    cursor,
    entity_type,
    entity_id,
    action,
    before=None,
    after=None,
    correlation_id=None,
):
    """Append a minimized entity change record in the caller's transaction."""
    cursor.execute(
        """
        INSERT INTO audit_event (
            audit_id, entity_type, entity_id, action, before_json,
            after_json, created_at, correlation_id
        )
        VALUES (%s, %s, %s, %s, %s, %s, NOW(), %s)
        """,
        (
            "AUD-" + uuid4().hex[:24],
            entity_type,
            entity_id,
            action,
            json.dumps(before, default=str) if before is not None else None,
            json.dumps(after, default=str) if after is not None else None,
            correlation_id or str(uuid4()),
        ),
    )


def record_audit_events(cursor, events):
    """Append a batch of minimized entity changes in one transaction."""
    cursor.executemany(
        """
        INSERT INTO audit_event (
            audit_id, entity_type, entity_id, action, before_json,
            after_json, created_at, correlation_id
        )
        VALUES (%s, %s, %s, %s, %s, %s, NOW(), %s)
        """,
        [
            (
                "AUD-" + uuid4().hex[:24],
                event["entity_type"],
                event["entity_id"],
                event["action"],
                json.dumps(event["before"], default=str)
                if event.get("before") is not None
                else None,
                json.dumps(event["after"], default=str)
                if event.get("after") is not None
                else None,
                event["correlation_id"],
            )
            for event in events
        ],
    )


def record_import_audit_events(cursor, table_name, records, correlation_id):
    """Audit imported rows without copying synthetic contact/address details."""
    primary_keys = {
        "address_zone": "zone_id",
        "address": "address_id",
        "bus": "bus_id",
        "driver": "driver_id",
        "student": "student_id",
        "guardian_contact": "guardian_id",
        "stop": "stop_id",
        "bus_capacity_history": "capacity_history_id",
        "route": "route_id",
        "route_stop": "route_stop_id",
        "assignment": "assignment_id",
    }
    tracked_fields = {
        "address_zone": ("zone_name", "approved_status"),
        "address": (
            "zone_id",
            "approval_status",
            "disclosure_authorized",
        ),
        "bus": ("capacity", "is_accessible", "status"),
        "driver": ("status",),
        "student": (
            "zone_id",
            "address_id",
            "accessibility_required",
            "pickup_window_start",
            "pickup_window_end",
            "status",
        ),
        "guardian_contact": ("student_id", "is_valid", "consent_status"),
        "stop": ("zone_id", "approval_status", "active_status"),
        "bus_capacity_history": (
            "bus_id",
            "capacity",
            "effective_from",
            "effective_to",
        ),
        "route": ("bus_id", "driver_id", "service_date", "status"),
        "route_stop": (
            "route_id",
            "stop_id",
            "sequence_no",
            "arrival_time",
            "travel_minutes",
        ),
        "assignment": (
            "student_id",
            "route_id",
            "stop_id",
            "effective_from",
            "effective_to",
            "status",
        ),
    }
    if table_name not in primary_keys:
        raise ValueError(f"No import audit mapping for table {table_name!r}.")

    events = []
    for record in records:
        key = record.get(primary_keys[table_name])
        if key is None:
            raise ValueError(
                f"Imported {table_name} row has no primary key "
                f"{primary_keys[table_name]!r}."
            )
        events.append(
            {
                "entity_type": table_name,
                "entity_id": str(key),
                "action": "IMPORTED",
                "after": {
                    field: record[field]
                    for field in tracked_fields[table_name]
                    if field in record
                },
                "correlation_id": correlation_id,
            }
        )
    record_audit_events(cursor, events)


if __name__ == "__main__":
    connection = get_connection()
    cursor = connection.cursor()

    try:
        cursor.execute(
            "SELECT DATABASE(), VERSION()"
        )
        database, version = cursor.fetchone()

        print(f"Connected database: {database}")
        print(f"MySQL version: {version}")

    finally:
        cursor.close()
        connection.close()
