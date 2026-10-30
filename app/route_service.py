"""Create a dated route plan from active buses, drivers, and approved stops."""

from datetime import date, datetime, time, timedelta
from typing import Any
from uuid import uuid4

from app.db import get_connection, record_audit_event


class RouteGenerationError(ValueError):
    """Raised when a safe route plan cannot be created for the service date."""


def _as_time(value: Any) -> time:
    if isinstance(value, time):
        return value
    if isinstance(value, timedelta):
        converted = datetime.combine(date.min, time.min) + value
        if converted.date() != date.min:
            raise RouteGenerationError(
                f"Invalid pickup time in master data: {value!r}."
            )
        return converted.time()
    try:
        return time.fromisoformat(str(value))
    except ValueError as exc:
        raise RouteGenerationError(
            f"Invalid pickup time in master data: {value!r}."
        ) from exc


def _as_bool(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes"}
    return bool(value)


def _add_minutes(value: time, minutes: int) -> time | None:
    result = datetime.combine(date.min, value) + timedelta(minutes=minutes)
    if result.date() != date.min:
        return None
    return result.time()


def build_route_plan(
    service_date: date,
    buses: list[dict[str, Any]],
    drivers: list[dict[str, Any]],
    stops: list[dict[str, Any]],
    students: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Build route and route-stop rows without writing to the database."""

    if not buses:
        raise RouteGenerationError("No active buses are available.")
    if not drivers:
        raise RouteGenerationError("No active drivers are available.")
    if not stops:
        raise RouteGenerationError("No approved active stops are available.")

    routes_count = min(len(buses), len(drivers))
    ordered_buses = sorted(
        buses,
        key=lambda bus: (
            not _as_bool(bus["is_accessible"]),
            str(bus["bus_id"]),
        ),
    )[:routes_count]
    ordered_drivers = sorted(drivers, key=lambda row: str(row["driver_id"]))[
        :routes_count
    ]

    route_rows = []
    route_state = []
    for index, (bus, driver) in enumerate(
        zip(ordered_buses, ordered_drivers),
        start=1,
    ):
        route_id = f"R-{service_date:%Y%m%d}-{index:03d}"
        route_rows.append(
            {
                "route_id": route_id,
                "bus_id": bus["bus_id"],
                "driver_id": driver["driver_id"],
                "service_date": service_date,
                "status": "PLANNED",
            }
        )
        route_state.append(
            {
                "route_id": route_id,
                "route_index": index,
                "bus_accessible": _as_bool(bus["is_accessible"]),
                "stop_count": 0,
                "last_arrival": time(7, 0),
            }
        )

    windows_by_zone: dict[str, dict[str, Any]] = {}
    for student in students:
        zone_id = str(student["zone_id"])
        start = _as_time(student["pickup_window_start"])
        end = _as_time(student["pickup_window_end"])
        window = windows_by_zone.get(zone_id)
        if window is None:
            windows_by_zone[zone_id] = {
                "start": start,
                "end": end,
                "needs_accessible_bus": _as_bool(
                    student["accessibility_required"]
                ),
            }
        else:
            window["start"] = max(window["start"], start)
            window["end"] = min(window["end"], end)
            window["needs_accessible_bus"] = (
                window["needs_accessible_bus"]
                or _as_bool(student["accessibility_required"])
            )
        if windows_by_zone[zone_id]["start"] > windows_by_zone[zone_id]["end"]:
            raise RouteGenerationError(
                f"Students in zone {zone_id} have no common pickup window; "
                "routes were not created."
            )

    stops_by_zone: dict[str, list[dict[str, Any]]] = {}
    for stop in stops:
        stops_by_zone.setdefault(str(stop["zone_id"]), []).append(stop)

    missing_zones = sorted(set(windows_by_zone) - set(stops_by_zone))
    if missing_zones:
        raise RouteGenerationError(
            "No approved active stop exists for active student zone(s): "
            + ", ".join(missing_zones)
        )

    default_window = {"start": time(7, 0), "end": time(8, 30)}
    for zone_stops in stops_by_zone.values():
        zone_stops.sort(key=lambda stop: str(stop["stop_id"]))

    prioritized_zones = sorted(
        stops_by_zone,
        key=lambda zone: (
            not windows_by_zone.get(zone, {}).get(
                "needs_accessible_bus", False
            ),
            zone,
        ),
    )

    route_stop_rows = []
    stop_sequences = {state["route_id"]: 0 for state in route_state}

    for zone_id in prioritized_zones:
        window = windows_by_zone.get(zone_id, default_window)
        eligible_routes = [
            state
            for state in route_state
            if (
                not window.get("needs_accessible_bus", False)
                or state["bus_accessible"]
            )
        ]
        if not eligible_routes:
            raise RouteGenerationError(
                f"Zone {zone_id} requires an accessible bus, but none is "
                "available; routes were not created."
            )

        for stop in stops_by_zone[zone_id]:
            candidates = []
            for state in eligible_routes:
                arrival = max(state["last_arrival"], window["start"])
                if state["stop_count"]:
                    next_arrival = _add_minutes(state["last_arrival"], 10)
                    if next_arrival is None:
                        continue
                    arrival = max(
                        arrival,
                        next_arrival,
                    )
                if arrival <= window["end"]:
                    candidates.append((state["stop_count"], state, arrival))

            if not candidates:
                raise RouteGenerationError(
                    f"No route can serve stop {stop['stop_id']} in zone "
                    f"{zone_id} within the pickup window; routes were not "
                    "created."
                )

            _, selected, arrival = min(
                candidates,
                key=lambda candidate: (
                    candidate[0],
                    candidate[1]["route_index"],
                ),
            )
            sequence = stop_sequences[selected["route_id"]] + 1
            stop_sequences[selected["route_id"]] = sequence
            route_stop_rows.append(
                {
                    "route_stop_id": (
                        f"RS-{service_date:%Y%m%d}-"
                        f"{selected['route_index']:03d}-{sequence:03d}"
                    ),
                    "route_id": selected["route_id"],
                    "stop_id": stop["stop_id"],
                    "sequence_no": sequence,
                    "arrival_time": arrival.strftime("%H:%M:%S"),
                    "travel_minutes": 0 if sequence == 1 else 10,
                }
            )
            selected["stop_count"] += 1
            selected["last_arrival"] = arrival

    return route_rows, route_stop_rows


def create_routes_for_date(service_date: date) -> dict[str, Any]:
    """Create routes and route stops atomically for one service date."""

    connection = get_connection()
    cursor = connection.cursor(dictionary=True)
    correlation_id = str(uuid4())

    try:
        connection.start_transaction()

        cursor.execute(
            """
            SELECT b.bus_id, b.is_accessible
            FROM bus AS b
            WHERE b.status = 'ACTIVE'
              AND (
                  SELECT COUNT(*)
                  FROM bus_capacity_history AS ch
                  WHERE ch.bus_id = b.bus_id
                    AND ch.effective_from <= %s
                    AND (
                        ch.effective_to IS NULL
                        OR ch.effective_to >= %s
                    )
              ) = 1
            ORDER BY b.bus_id
            FOR UPDATE
            """,
            (service_date, service_date),
        )
        buses = cursor.fetchall()
        if not buses:
            raise RouteGenerationError(
                "No active buses with exactly one effective capacity record "
                "are available."
            )

        # Locking the shared bus rows serializes route generation requests
        # before checking for an existing service-date plan.
        cursor.execute(
            """
            SELECT route_id
            FROM route
            WHERE service_date = %s
            LIMIT 1
            FOR UPDATE
            """,
            (service_date,),
        )
        existing_route = cursor.fetchone()
        if existing_route:
            raise RouteGenerationError(
                f"Routes already exist for {service_date.isoformat()}."
            )

        cursor.execute(
            """
            SELECT driver_id
            FROM driver
            WHERE status = 'ACTIVE'
            ORDER BY driver_id
            FOR UPDATE
            """
        )
        drivers = cursor.fetchall()

        cursor.execute(
            """
            SELECT st.stop_id, st.zone_id
            FROM stop AS st
            JOIN address_zone AS az ON az.zone_id = st.zone_id
            WHERE st.active_status = TRUE
              AND st.approval_status = 'APPROVED'
              AND az.approved_status = 'APPROVED'
            ORDER BY st.zone_id, st.stop_id
            FOR UPDATE
            """
        )
        stops = cursor.fetchall()

        cursor.execute(
            """
            SELECT
                zone_id,
                accessibility_required,
                pickup_window_start,
                pickup_window_end
            FROM student
            WHERE status = 'ACTIVE'
            ORDER BY zone_id, student_id
            """
        )
        students = cursor.fetchall()

        routes, route_stops = build_route_plan(
            service_date,
            buses,
            drivers,
            stops,
            students,
        )

        cursor.executemany(
            """
            INSERT INTO route (
                route_id, bus_id, driver_id, service_date, status
            )
            VALUES (%s, %s, %s, %s, %s)
            """,
            [
                (
                    row["route_id"],
                    row["bus_id"],
                    row["driver_id"],
                    row["service_date"],
                    row["status"],
                )
                for row in routes
            ],
        )
        cursor.executemany(
            """
            INSERT INTO route_stop (
                route_stop_id, route_id, stop_id, sequence_no,
                arrival_time, travel_minutes
            )
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            [
                (
                    row["route_stop_id"],
                    row["route_id"],
                    row["stop_id"],
                    row["sequence_no"],
                    row["arrival_time"],
                    row["travel_minutes"],
                )
                for row in route_stops
            ],
        )
        for row in routes:
            record_audit_event(
                cursor,
                "route",
                row["route_id"],
                "CREATED",
                after=row,
                correlation_id=correlation_id,
            )
        for row in route_stops:
            record_audit_event(
                cursor,
                "route_stop",
                row["route_stop_id"],
                "CREATED",
                after=row,
                correlation_id=correlation_id,
            )
        connection.commit()

        return {
            "status": "CREATED",
            "correlation_id": correlation_id,
            "service_date": service_date.isoformat(),
            "route_count": len(routes),
            "route_stop_count": len(route_stops),
            "route_ids": [row["route_id"] for row in routes],
        }
    except Exception:
        connection.rollback()
        raise
    finally:
        cursor.close()
        connection.close()
