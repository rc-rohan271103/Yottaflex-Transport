import sys
from datetime import date, datetime, time, timedelta

import pytest

from app import assignment_service, notification_service, route_service
from app.assignment_service import candidate_rank
from app.route_service import (
    RouteGenerationError,
    _as_time,
    build_route_plan,
    create_routes_for_date,
)


SERVICE_DATE = date(2026, 10, 30)


def master_rows():
    return {
        "buses": [
            {"bus_id": "BUS-000001", "is_accessible": False},
            {"bus_id": "BUS-000002", "is_accessible": True},
        ],
        "drivers": [
            {"driver_id": "DRV-000001"},
            {"driver_id": "DRV-000002"},
        ],
        "stops": [
            {"stop_id": "STOP-000001", "zone_id": "ZONE-001"},
            {"stop_id": "STOP-000002", "zone_id": "ZONE-002"},
        ],
        "students": [
            {
                "zone_id": "ZONE-001",
                "accessibility_required": True,
                "pickup_window_start": time(7, 30),
                "pickup_window_end": time(8, 0),
            },
            {
                "zone_id": "ZONE-002",
                "accessibility_required": False,
                "pickup_window_start": time(7, 0),
                "pickup_window_end": time(8, 30),
            },
        ],
    }


def test_route_plan_covers_approved_zones_and_respects_accessibility():
    plan = master_rows()

    routes, route_stops = build_route_plan(SERVICE_DATE, **plan)

    assert len(routes) == 2
    assert {row["stop_id"] for row in route_stops} == {
        "STOP-000001",
        "STOP-000002",
    }
    accessible_bus_id = next(
        row["bus_id"] for row in routes
        if row["route_id"]
        == next(
            stop["route_id"] for stop in route_stops
            if stop["stop_id"] == "STOP-000001"
        )
    )
    assert accessible_bus_id == "BUS-000002"

    accessible_stop = next(
        row for row in route_stops if row["stop_id"] == "STOP-000001"
    )
    assert accessible_stop["arrival_time"] == "07:30:00"


def test_route_plan_rejects_student_zone_without_approved_stop():
    plan = master_rows()
    plan["stops"] = plan["stops"][:1]

    with pytest.raises(RouteGenerationError, match="ZONE-002"):
        build_route_plan(SERVICE_DATE, **plan)


def test_route_plan_rejects_missing_accessible_bus():
    plan = master_rows()
    plan["buses"] = [plan["buses"][0]]
    plan["drivers"] = [plan["drivers"][0]]

    with pytest.raises(RouteGenerationError, match="accessible bus"):
        build_route_plan(SERVICE_DATE, **plan)


def test_route_plan_rejects_stops_that_cannot_fit_pickup_windows():
    plan = master_rows()
    plan["buses"] = [plan["buses"][1]]
    plan["drivers"] = [plan["drivers"][0]]
    plan["students"] = plan["students"][:1]
    plan["stops"] = [
        {"stop_id": f"STOP-{index:06d}", "zone_id": "ZONE-001"}
        for index in range(1, 12)
    ]

    with pytest.raises(RouteGenerationError, match="pickup window"):
        build_route_plan(SERVICE_DATE, **plan)


def test_route_plan_does_not_wrap_travel_time_past_midnight():
    plan = master_rows()
    plan["buses"] = [plan["buses"][1]]
    plan["drivers"] = [plan["drivers"][0]]
    plan["students"] = [
        {
            "zone_id": "ZONE-001",
            "accessibility_required": True,
            "pickup_window_start": time(23, 50),
            "pickup_window_end": time(23, 59),
        }
    ]
    plan["stops"] = [
        {"stop_id": f"STOP-{index:06d}", "zone_id": "ZONE-001"}
        for index in range(1, 3)
    ]

    with pytest.raises(RouteGenerationError, match="pickup window"):
        build_route_plan(SERVICE_DATE, **plan)


def test_candidate_rank_uses_derived_utilization_then_travel_and_arrival():
    less_loaded = {
        "capacity": 20,
        "travel_minutes": 10,
        "arrival_time": time(7, 20),
        "route_id": "R-20261030-002",
        "sequence_no": 2,
    }
    earlier_arrival = {
        "capacity": 20,
        "travel_minutes": 0,
        "arrival_time": time(7, 0),
        "route_id": "R-20261030-001",
        "sequence_no": 1,
    }
    longer_travel = {
        "capacity": 20,
        "travel_minutes": 10,
        "arrival_time": time(7, 20),
        "route_id": "R-20261030-002",
        "sequence_no": 2,
    }

    assert candidate_rank((less_loaded, 2)) < candidate_rank(
        (earlier_arrival, 10)
    )
    assert candidate_rank((earlier_arrival, 10)) < candidate_rank(
        (longer_travel, 10)
    )
    mysql_time_candidate = {
        **longer_travel,
        "arrival_time": timedelta(hours=7, minutes=20),
    }
    assert candidate_rank((longer_travel, 10)) == candidate_rank(
        (mysql_time_candidate, 10)
    )


def test_mysql_time_values_convert_to_daily_pickup_times():
    assert _as_time(timedelta(hours=7, minutes=30)) == time(7, 30)

    with pytest.raises(RouteGenerationError, match="Invalid pickup time"):
        _as_time(timedelta(days=1))


class AssignmentCursor:
    def __init__(self):
        self.results = []
        self.inserted_assignment = None
        self.audit_events = []

    def execute(self, query, params=None):
        normalized = " ".join(query.split())
        if normalized.startswith("SELECT student_id, zone_id"):
            self.results = [{
                "student_id": "STU-000001",
                "zone_id": "ZONE-001",
                "accessibility_required": False,
                "pickup_window_start": time(7, 0),
                "pickup_window_end": time(8, 30),
                "status": "ACTIVE",
            }]
        elif normalized.startswith(
            "SELECT assignment_id FROM assignment WHERE student_id"
        ):
            self.results = []
        elif normalized.startswith("SELECT r.route_id"):
            self.results = [
                {
                    "route_id": "R-20261030-001",
                    "bus_id": "BUS-000001",
                    "stop_id": "STOP-000001",
                    "arrival_time": time(7, 10),
                    "travel_minutes": 5,
                    "sequence_no": 2,
                    "capacity": 20,
                },
                {
                    "route_id": "R-20261030-002",
                    "bus_id": "BUS-000002",
                    "stop_id": "STOP-000002",
                    "arrival_time": time(7, 20),
                    "travel_minutes": 10,
                    "sequence_no": 2,
                    "capacity": 20,
                },
            ]
        elif normalized.startswith("SELECT route_id FROM route"):
            self.results = [{"route_id": params[0]}]
        elif normalized.startswith(
            "SELECT assignment_id FROM assignment WHERE route_id"
        ):
            load = 10 if params[0] == "R-20261030-001" else 2
            self.results = [
                {"assignment_id": f"EXISTING-{index}"}
                for index in range(load)
            ]
        elif normalized.startswith("INSERT INTO assignment ("):
            self.inserted_assignment = params
            self.results = []
        elif normalized.startswith("INSERT INTO assignment_decision"):
            self.results = []
        elif normalized.startswith("INSERT INTO audit_event"):
            self.audit_events.append(params)
            self.results = []
        else:
            raise AssertionError(f"Unexpected assignment query: {normalized}")

    def fetchall(self):
        return self.results

    def fetchone(self):
        return self.results[0] if self.results else None

    def close(self):
        pass


class AssignmentConnection:
    def __init__(self):
        self.cursor_instance = AssignmentCursor()
        self.committed = False
        self.rolled_back = False

    def cursor(self, dictionary=False):
        return self.cursor_instance

    def start_transaction(self):
        pass

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True

    def close(self):
        pass


def test_assignment_uses_derived_rank_capacity_and_service_dates(monkeypatch):
    connection = AssignmentConnection()
    monkeypatch.setattr(
        assignment_service,
        "get_connection",
        lambda: connection,
    )

    result = assignment_service.assign_new_student(
        "STU-000001",
        SERVICE_DATE,
    )

    assert result["status"] == "ASSIGNED"
    assert result["route_id"] == "R-20261030-002"
    assert result["candidate_score"] == {
        "route_utilization": 0.1,
        "travel_minutes": 10,
        "arrival_time": "07:20:00",
    }
    assert result["remaining_capacity_after_assignment"] == 17
    assert connection.cursor_instance.inserted_assignment[4:] == (
        SERVICE_DATE,
        SERVICE_DATE,
    )
    assert connection.committed
    assert not connection.rolled_back
    assert connection.cursor_instance.inserted_assignment is not None
    assert len(connection.cursor_instance.audit_events) == 2
    assert len({event[6] for event in connection.cursor_instance.audit_events}) == 1
    assert result["correlation_id"] == connection.cursor_instance.audit_events[0][6]


class AttendanceCursor:
    def __init__(self, service_date):
        self.service_date = service_date
        self.results = []
        self.inserted_event = None
        self.audit_events = []

    def execute(self, query, params=None):
        normalized = " ".join(query.split())
        if normalized.startswith("SELECT r.service_date"):
            self.results = (
                [{"service_date": self.service_date}]
                if self.service_date is not None
                else []
            )
        elif normalized.startswith("INSERT INTO attendance_event"):
            self.inserted_event = params
            self.results = []
        elif normalized.startswith("INSERT INTO audit_event"):
            self.audit_events.append(params)
            self.results = []
        else:
            raise AssertionError(f"Unexpected attendance query: {normalized}")

    def fetchone(self):
        return self.results[0] if self.results else None

    def close(self):
        pass


class AttendanceConnection:
    def __init__(self, service_date):
        self.cursor_instance = AttendanceCursor(service_date)
        self.committed = False
        self.rolled_back = False

    def cursor(self, dictionary=False):
        return self.cursor_instance

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True

    def close(self):
        pass


def test_attendance_requires_assignment_and_matching_service_date(monkeypatch):
    from fastapi import HTTPException

    from app.auth import Principal
    from app import main

    connection = AttendanceConnection(None)
    monkeypatch.setattr(main, "get_connection", lambda: connection)
    request = main.AttendanceEventRequest(
        student_id="STU-000001",
        route_id="R-20261030-001",
        event_type=main.AttendanceEventType.PRESENT,
        reason="Test attendance",
        event_time=datetime(2026, 10, 30, 7, 0),
    )

    with pytest.raises(HTTPException) as exc_info:
        main.record_attendance_event(
            request,
            Principal("admin", "platform_administrator"),
        )

    assert exc_info.value.status_code == 409
    assert connection.rolled_back
    assert connection.cursor_instance.inserted_event is None

    connection = AttendanceConnection(SERVICE_DATE)
    monkeypatch.setattr(main, "get_connection", lambda: connection)
    result = main.record_attendance_event(
        request,
        Principal("admin", "platform_administrator"),
    )

    assert result["status"] == "RECORDED"
    assert connection.cursor_instance.inserted_event[1:4] == (
        "STU-000001",
        "R-20261030-001",
        "PRESENT",
    )
    assert connection.committed
    assert not connection.rolled_back
    assert len(connection.cursor_instance.audit_events) == 1
    assert result["correlation_id"] == connection.cursor_instance.audit_events[0][6]


def test_attendance_rejects_event_from_a_different_service_date(monkeypatch):
    from fastapi import HTTPException

    from app.auth import Principal
    from app import main

    connection = AttendanceConnection(SERVICE_DATE)
    monkeypatch.setattr(main, "get_connection", lambda: connection)
    request = main.AttendanceEventRequest(
        student_id="STU-000001",
        route_id="R-20261030-001",
        event_type=main.AttendanceEventType.PRESENT,
        reason="Test attendance",
        event_time=datetime(2026, 10, 31, 7, 0),
    )

    with pytest.raises(HTTPException) as exc_info:
        main.record_attendance_event(
            request,
            Principal("admin", "platform_administrator"),
        )

    assert exc_info.value.status_code == 400
    assert connection.rolled_back
    assert connection.cursor_instance.inserted_event is None


def test_full_scale_generator_refuses_to_replace_history(
    monkeypatch,
    tmp_path,
):
    from generator import generate_full_scale_operations

    existing_output = tmp_path / "route.csv"
    existing_output.write_text("existing-history\n", encoding="utf-8")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "generate_full_scale_operations",
            "--output",
            str(tmp_path),
        ],
    )

    with pytest.raises(FileExistsError, match="Refusing to overwrite"):
        generate_full_scale_operations.main()

    assert existing_output.read_text(encoding="utf-8") == "existing-history\n"


class FakeCursor:
    def __init__(self, rows, existing_route=False):
        self.rows = rows
        self.existing_route = existing_route
        self.results = []
        self.inserted = []
        self.audit_events = []
        self.closed = False

    def execute(self, query, params=None):
        normalized = " ".join(query.split())
        if normalized.startswith("SELECT b.bus_id"):
            self.results = self.rows["buses"]
        elif normalized.startswith("SELECT route_id FROM route"):
            self.results = (
                [{"route_id": "R-20261030-001"}]
                if self.existing_route
                else []
            )
        elif normalized.startswith("SELECT driver_id"):
            self.results = self.rows["drivers"]
        elif normalized.startswith("SELECT st.stop_id"):
            self.results = self.rows["stops"]
        elif normalized.startswith("SELECT zone_id"):
            self.results = self.rows["students"]
        elif normalized.startswith("INSERT INTO audit_event"):
            self.audit_events.append(params)
            self.results = []
        else:
            raise AssertionError(f"Unexpected query: {normalized}")

    def fetchall(self):
        return self.results

    def fetchone(self):
        return self.results[0] if self.results else None

    def executemany(self, query, rows):
        self.inserted.append((query, list(rows)))

    def close(self):
        self.closed = True


class FakeConnection:
    def __init__(self, rows, existing_route=False):
        self.cursor_instance = FakeCursor(rows, existing_route)
        self.committed = False
        self.rolled_back = False
        self.closed = False

    def cursor(self, dictionary=False):
        return self.cursor_instance

    def start_transaction(self):
        pass

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True

    def close(self):
        self.closed = True


def test_create_routes_inserts_plan_in_one_transaction(monkeypatch):
    connection = FakeConnection(master_rows())
    monkeypatch.setattr(route_service, "get_connection", lambda: connection)

    result = create_routes_for_date(SERVICE_DATE)

    assert result["status"] == "CREATED"
    assert result["route_count"] == 2
    assert result["route_stop_count"] == 2
    assert len(connection.cursor_instance.inserted) == 2
    assert len(connection.cursor_instance.audit_events) == 4
    assert len({event[6] for event in connection.cursor_instance.audit_events}) == 1
    assert result["correlation_id"] == connection.cursor_instance.audit_events[0][6]
    assert connection.committed
    assert not connection.rolled_back
    assert connection.closed


def test_create_routes_refuses_duplicate_service_date(monkeypatch):
    connection = FakeConnection(master_rows(), existing_route=True)
    monkeypatch.setattr(route_service, "get_connection", lambda: connection)

    with pytest.raises(RouteGenerationError, match="already exist"):
        create_routes_for_date(SERVICE_DATE)

    assert connection.rolled_back
    assert not connection.committed
    assert connection.cursor_instance.inserted == []


class NotificationCursor:
    def __init__(self):
        self.results = []
        self.inserts = []

    def execute(self, query, params=None):
        normalized = " ".join(query.split())
        if normalized.startswith("SELECT student_id, is_valid"):
            self.results = [{
                "student_id": "STU-000001",
                "is_valid": True,
                "consent_status": "GRANTED",
            }]
        elif normalized.startswith("SELECT student_id FROM attendance_event"):
            self.results = [{"student_id": "STU-000001"}]
        elif normalized.startswith("SELECT notification_id FROM notification"):
            self.results = [{"notification_id": "NTF-EXISTING"}]
        else:
            self.inserts.append((normalized, params))
            self.results = []

    def fetchone(self):
        return self.results[0] if self.results else None

    def close(self):
        pass


class NotificationConnection:
    def __init__(self):
        self.cursor_instance = NotificationCursor()
        self.committed = False
        self.rolled_back = False

    def cursor(self, dictionary=False):
        return self.cursor_instance

    def start_transaction(self):
        pass

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True

    def close(self):
        pass


def test_notification_decision_is_not_duplicated_for_an_event(monkeypatch):
    connection = NotificationConnection()
    monkeypatch.setattr(
        notification_service,
        "get_connection",
        lambda: connection,
    )

    with pytest.raises(ValueError, match="already exists"):
        notification_service.record_notification(
            guardian_id="GUA-000001",
            student_id="STU-000001",
            event_id="EVT-EXISTING",
            requester_role="support_staff",
        )

    assert connection.rolled_back
    assert not connection.committed
    assert connection.cursor_instance.inserts == []


def test_create_routes_rejects_buses_without_effective_capacity(monkeypatch):
    rows = master_rows()
    rows["buses"] = []
    connection = FakeConnection(rows)
    monkeypatch.setattr(route_service, "get_connection", lambda: connection)

    with pytest.raises(RouteGenerationError, match="effective capacity"):
        create_routes_for_date(SERVICE_DATE)

    assert connection.rolled_back
    assert connection.cursor_instance.inserted == []


def test_routes_generate_endpoint_is_registered():
    from app.main import app

    assert "/routes/generate" in app.openapi()["paths"]


def test_routes_generate_endpoint_returns_conflict_for_existing_plan(
    monkeypatch,
):
    from fastapi import HTTPException

    from app import main

    def reject_duplicate(service_date):
        raise RouteGenerationError("Routes already exist.")

    monkeypatch.setattr(main, "create_routes_for_date", reject_duplicate)

    with pytest.raises(HTTPException) as exc_info:
        main.generate_routes_endpoint(
            main.RouteGenerationRequest(service_date=SERVICE_DATE)
        )

    assert exc_info.value.status_code == 409
