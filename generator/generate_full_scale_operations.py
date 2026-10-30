
import argparse
import random
from datetime import date, datetime, time, timedelta
from pathlib import Path

import pandas as pd

SEED = 20261022
MASTER_DIR = Path("data/full_scale")
OUTPUT_DIR = MASTER_DIR / "operations"
START_DATE = date(2026, 1, 5)
SCHOOL_DAYS = 200


def load_csv(folder, name):
    path = folder / f"{name}.csv"
    if not path.exists():
        raise FileNotFoundError(f"Required input file not found: {path}")
    return pd.read_csv(path, dtype=str).fillna("")


def is_true(value):
    return str(value).strip().lower() in ("1", "true", "yes")


def school_dates(start_date, count):
    """Return count weekdays, excluding weekends."""
    dates = []
    current = start_date
    while len(dates) < count:
        if current.weekday() < 5:
            dates.append(current)
        current += timedelta(days=1)
    return dates


def capacity_on_date(bus_id, service_date, history):
    service_date_text = service_date.isoformat()
    effective_records = [
        row
        for row in history
        if row["bus_id"] == bus_id
        and row["effective_from"] <= service_date_text
        and (
            not row["effective_to"]
            or row["effective_to"] >= service_date_text
        )
    ]
    if len(effective_records) != 1:
        raise ValueError(
            f"Bus {bus_id} has {len(effective_records)} capacity records "
            f"effective on {service_date_text}; expected exactly one."
        )
    return int(effective_records[0]["capacity"])


def student_sequence(student_id):
    suffix = str(student_id).rsplit("-", 1)[-1]
    if not suffix.isdigit():
        raise ValueError(
            f"Student ID must end with a numeric sequence: {student_id!r}."
        )
    return int(suffix)


def attendance_outcome(student_id, day_index):
    """Derive a reproducible synthetic outcome from student ID and day."""
    bucket = (student_sequence(student_id) + day_index * 37) % 100
    if bucket < 2:
        return "MISSED_PICKUP", "Derived synthetic missed pickup"
    if bucket < 10:
        return "ABSENT", "Derived synthetic student absence"
    if bucket < 25:
        return "BOARDED", "Derived synthetic boarding confirmation"
    return "PRESENT", "Derived synthetic attendance record"


def requester_is_authorized(student_id, service_date):
    """Derive synthetic authorization consistently from ID and service date."""
    return (
        student_sequence(student_id) + service_date.toordinal()
    ) % 100 != 0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--students", type=int, default=5000)
    parser.add_argument("--days", type=int, default=SCHOOL_DAYS)
    parser.add_argument("--seed", type=int, default=SEED)
    parser.add_argument("--input", type=Path, default=MASTER_DIR)
    parser.add_argument("--output", type=Path, default=OUTPUT_DIR)
    parser.add_argument("--start-date", type=date.fromisoformat,
                        default=START_DATE)
    args = parser.parse_args()

    if args.students < 1 or args.days < 1:
        raise ValueError("Students and days must be positive.")
    output_names = (
        "route",
        "route_stop",
        "assignment",
        "notification",
        "attendance_event",
        "bus_capacity_history",
        "route_disruption",
    )
    existing_outputs = [
        args.output / f"{name}.csv"
        for name in output_names
        if (args.output / f"{name}.csv").exists()
    ]
    if existing_outputs:
        raise FileExistsError(
            "Refusing to overwrite existing operational history. "
            "Choose a new --output directory: "
            + ", ".join(str(path) for path in existing_outputs)
        )

    rng = random.Random(args.seed)
    args.output.mkdir(parents=True, exist_ok=True)

    students = load_csv(args.input, "student")
    buses = load_csv(args.input, "bus")
    drivers = load_csv(args.input, "driver")
    stops = load_csv(args.input, "stop")
    zones = load_csv(args.input, "address_zone")
    guardians = load_csv(args.input, "guardian_contact")

    students = students[students["status"] == "ACTIVE"].copy()
    buses = buses[buses["status"] == "ACTIVE"].copy()
    drivers = drivers[drivers["status"] == "ACTIVE"].copy()
    approved_zones = set(
        zones.loc[zones["approved_status"] == "APPROVED", "zone_id"]
    )
    stops = stops[
        stops["active_status"].map(is_true)
        & (stops["approval_status"] == "APPROVED")
        & stops["zone_id"].isin(approved_zones)
    ].copy()

    # Allow a smaller test run without changing the master CSV files.
    students = students.head(args.students).copy()
    guardians["is_valid"] = guardians["is_valid"].map(is_true)
    guardians["consent_status"] = (
        guardians["consent_status"].astype(str).str.strip().str.upper()
    )

    guardian_by_student = {
        row["student_id"]: row
        for _, row in guardians.iterrows()
    }

    missing_guardians = (
        set(students["student_id"]) - set(guardian_by_student)
    )

    if missing_guardians:
        raise ValueError(
            f"Missing guardian contacts for "
            f"{len(missing_guardians)} active students."
        )

    if students.empty or buses.empty or drivers.empty or stops.empty:
        raise ValueError("Active students, buses, drivers and stops are required.")

    if len(drivers) < len(buses):
        raise ValueError("Each active bus needs an active driver.")

    students["accessibility_required"] = (
        students["accessibility_required"].map(is_true)
    )
    buses["is_accessible"] = buses["is_accessible"].map(is_true)
    buses["capacity"] = buses["capacity"].astype(int)

    student_zones = set(students["zone_id"])
    stop_zones = set(stops["zone_id"])
    missing_zones = student_zones - stop_zones
    if missing_zones:
        raise ValueError(
            f"No active stop exists for student zones: {sorted(missing_zones)}"
        )

    dates = school_dates(args.start_date, args.days)
    buses = buses.sort_values("bus_id").reset_index(drop=True)
    drivers = drivers.sort_values("driver_id").reset_index(drop=True)

    # Build one stable route plan per bus per school day.
    # Stops are distributed across routes, spreading each zone across buses.
    zones = sorted(stop_zones)
    stops = stops.sort_values(["zone_id", "stop_id"]).reset_index(drop=True)
    stop_by_id = {
        row["stop_id"]: row
        for _, row in stops.iterrows()
    }
    routes = []
    route_stops = []
    assignments = []
    attendance_events = []
    disruptions = []
    notifications = []

    # Record the initial capacity and dated changes separately from bus.csv.
    capacity_history = []
    capacities = {}
    history_number = 0

    for _, bus in buses.iterrows():
        bus_id = bus["bus_id"]
        capacity = int(bus["capacity"])
        capacities[bus_id] = capacity
        history_number += 1
        capacity_history.append({
            "capacity_history_id": f"CAP-{history_number:06d}",
            "bus_id": bus_id,
            "capacity": capacity,
            "effective_from": dates[0].isoformat(),
            "effective_to": "",
        })

    # Add a planned capacity change for a deterministic subset of buses.
    changeable_buses = [
        bus["bus_id"] for _, bus in buses.iterrows()
        if len(dates) >= 2
    ]
    rng.shuffle(changeable_buses)
    changed_buses = set(changeable_buses[:max(1, len(changeable_buses) // 4)])

    for bus_id in sorted(changed_buses):
        change_index = len(dates) // 2
        change_date = dates[change_index]
        old_capacity = capacities[bus_id]
        new_capacity = rng.choice([30, 35, 40, 45])
        if new_capacity == old_capacity:
            new_capacity = 30 if old_capacity != 30 else 35

        # Close the initial capacity period and append the new period.
        for row in capacity_history:
            if row["bus_id"] == bus_id and row["effective_to"] == "":
                row["effective_to"] = (change_date - timedelta(days=1)).isoformat()

        history_number += 1
        capacity_history.append({
            "capacity_history_id": f"CAP-{history_number:06d}",
            "bus_id": bus_id,
            "capacity": new_capacity,
            "effective_from": change_date.isoformat(),
            "effective_to": "",
        })

    # Route and route-stop IDs include the service date to stay unique.
    for day_index, service_date in enumerate(dates):
        day_text = service_date.strftime("%Y%m%d")
        stop_order = stops.copy()

        # Rotate ordering by day while retaining reproducible shuffling.
        stop_order = stop_order.sample(
            frac=1, random_state=args.seed + day_index
        ).reset_index(drop=True)

        route_ids = []
        route_bus = {}
        route_status_by_id = {}
        route_stop_ids = {}
        route_stop_by_pair = {}
        last_arrival_by_route = {}

        disruptions_by_route = {}
        for bus_index, (_, bus) in enumerate(buses.iterrows()):
            driver = drivers.iloc[bus_index]
            route_id = f"R-{day_text}-{bus_index + 1:03d}"
            route_ids.append(route_id)
            route_bus[route_id] = bus.to_dict()
            route_stop_ids[route_id] = []

            route_status = "PLANNED"
            if rng.random() < 0.01:
                disruption_type = rng.choice([
                    "TRAFFIC_DELAY", "ROAD_CLOSURE", "VEHICLE_DELAY"
                ])
                severity = rng.choice(["LOW", "MEDIUM", "HIGH"])
                disruption_status = rng.choice(
                    ["RECORDED", "RESOLVED", "ESCALATED"]
                )
                disruption = {
                    "disruption_id": f"DIS-{day_text}-{route_id[-3:]}",
                    "route_id": route_id,
                    "service_date": service_date.isoformat(),
                    "disruption_type": disruption_type,
                    "severity": severity,
                    "status": disruption_status,
                }
                disruptions.append(disruption)
                disruptions_by_route[route_id] = disruption

                if disruption_status != "RESOLVED":
                    if severity == "HIGH":
                        route_status = "DISRUPTED"

            route_status_by_id[route_id] = route_status
            routes.append({
                "route_id": route_id,
                "bus_id": bus["bus_id"],
                "driver_id": driver["driver_id"],
                "service_date": service_date.isoformat(),
                "status": route_status,
            })

        # Assign every active stop to one route for this day.
        for stop_index, (_, stop) in enumerate(stop_order.iterrows()):
            route_index = stop_index % len(route_ids)
            route_id = route_ids[route_index]
            sequence_no = len(route_stop_ids[route_id]) + 1
            route_stop_id = (
                f"RS-{day_text}-{route_index + 1:03d}-{sequence_no:03d}"
            )

            disruption = disruptions_by_route.get(route_id)
            delay_minutes = 0
            if disruption and disruption["status"] != "RESOLVED":
                delay_minutes = (
                    5 if disruption["severity"] == "LOW" else 10
                )
            travel_minutes = (
                0 if sequence_no == 1 else 10 + delay_minutes
            )
            previous_arrival = (
                datetime.combine(
                    service_date,
                    time(7, 0),
                ) + timedelta(minutes=delay_minutes)
                if sequence_no == 1
                else last_arrival_by_route[route_id]
            )
            arrival = previous_arrival + timedelta(minutes=travel_minutes)

            route_stop = {
                "route_stop_id": route_stop_id,
                "route_id": route_id,
                "stop_id": stop["stop_id"],
                "sequence_no": sequence_no,
                "arrival_time": arrival.strftime("%H:%M:%S"),
                "travel_minutes": travel_minutes,
            }
            route_stops.append(route_stop)
            route_stop_by_pair[(route_id, stop["stop_id"])] = route_stop
            last_arrival_by_route[route_id] = arrival
            route_stop_ids[route_id].append(stop["stop_id"])

        # Index route stops by zone and exclude capacity-incompatible buses.
        candidates_by_zone = {}
        for route_id in route_ids:
            bus = route_bus[route_id]
            if route_status_by_id[route_id] == "DISRUPTED":
                continue
            effective_capacity = capacity_on_date(
                bus["bus_id"], service_date, capacity_history
            )
            for stop_id in route_stop_ids[route_id]:
                stop = stop_by_id.get(stop_id)
                if stop is None:
                    continue
                zone = stop["zone_id"]
                route_stop = route_stop_by_pair[(route_id, stop_id)]
                candidates_by_zone.setdefault(zone, []).append(
                    (
                        route_id,
                        stop_id,
                        bus,
                        effective_capacity,
                        route_stop,
                    )
                )

        route_loads = {route_id: 0 for route_id in route_ids}
        ordered_students = students.sort_values(
            ["accessibility_required", "student_id"],
            ascending=[False, True],
            kind="stable",
        )

        assignment_number = 0
        for _, student in ordered_students.iterrows():
            zone = student["zone_id"]
            needs_access = bool(student["accessibility_required"])
            candidates = []

            pickup_start = time.fromisoformat(
                str(student["pickup_window_start"])
            )
            pickup_end = time.fromisoformat(
                str(student["pickup_window_end"])
            )
            for (
                route_id,
                stop_id,
                bus,
                capacity,
                route_stop,
            ) in candidates_by_zone.get(zone, []):
                if needs_access and not bool(bus["is_accessible"]):
                    continue

                arrival_time = time.fromisoformat(route_stop["arrival_time"])
                if not pickup_start <= arrival_time <= pickup_end:
                    continue

                if route_loads[route_id] < capacity:
                    candidates.append(
                        {
                            "route_id": route_id,
                            "stop_id": stop_id,
                            "bus": bus,
                            "capacity": capacity,
                            "arrival_time": arrival_time,
                            "travel_minutes": int(
                                route_stop["travel_minutes"]
                            ),
                        }
                    )

            if not candidates:
                continue

            selected = min(
                candidates,
                key=lambda candidate: (
                    route_loads[candidate["route_id"]]
                    / candidate["capacity"],
                    candidate["travel_minutes"],
                    candidate["arrival_time"],
                    candidate["route_id"],
                    candidate["stop_id"],
                ),
            )
            route_id = selected["route_id"]
            stop_id = selected["stop_id"]
            route_loads[route_id] += 1
            assignment_number += 1

            assignment_id = f"A-{student['student_id']}-{day_text}"
            assignments.append({
                "assignment_id": assignment_id,
                "student_id": student["student_id"],
                "route_id": route_id,
                "stop_id": stop_id,
                "effective_from": service_date.isoformat(),
                "effective_to": service_date.isoformat(),
                "status": "ASSIGNED",
            })

            event_type, reason = attendance_outcome(
                student["student_id"],
                day_index,
            )

            event_id = f"EVT-{day_text}-{assignment_number:06d}"
            event_time = datetime.combine(
                service_date,
                selected["arrival_time"],
            )
            attendance_events.append({
                "event_id": event_id,
                "student_id": student["student_id"],
                "route_id": route_id,
                "event_type": event_type,
                "event_time": event_time.strftime("%Y-%m-%d %H:%M:%S"),
                "reason": reason,
            })
            
            # Generate a deterministic, simulated notification decision.
            guardian = guardian_by_student[student["student_id"]]

            requester_authorized = requester_is_authorized(
                student["student_id"],
                service_date,
            )

            if not guardian["is_valid"]:
                notification_status = "BLOCKED_INVALID_CONTACT"
                notification_reason = "Guardian contact is marked invalid"
            elif guardian["consent_status"] != "GRANTED":
                notification_status = "BLOCKED_CONSENT"
                notification_reason = "Guardian consent is not granted"
            elif not requester_authorized:
                notification_status = "BLOCKED_AUTHORIZATION"
                notification_reason = "Requester is not authorized"
            else:
                notification_status = "SIMULATED_SENT"
                notification_reason = (
                    "Checks passed; no real message was sent"
                )

            notifications.append({
                "notification_id": f"NTF-{day_text}-{assignment_number:06d}",
                "guardian_id": guardian["guardian_id"],
                "student_id": student["student_id"],
                "event_id": event_id,
                "status": notification_status,
                "reason": notification_reason,
                "created_at": event_time.strftime("%Y-%m-%d %H:%M:%S"),
            })

    outputs = {
        "route": routes,
        "route_stop": route_stops,
        "assignment": assignments,
        "notification": notifications,
        "attendance_event": attendance_events,
        "bus_capacity_history": capacity_history,
        "route_disruption": disruptions,
    }

    for name, rows in outputs.items():
        path = args.output / f"{name}.csv"
        pd.DataFrame(rows).to_csv(path, index=False)
        print(f"{name}: {len(rows):,} rows -> {path}")

    print("\nFull-scale operational generation complete.")
    print(f"Students requested: {args.students:,}")
    print(f"Active students available: {len(students):,}")
    print(f"Active buses: {len(buses):,}")
    print(f"Active stops: {len(stops):,}")
    print(f"School days: {len(dates):,}")
    print(f"Date range: {dates[0]} to {dates[-1]}")
    assignment_attempts = len(students) * len(dates)
    total_effective_seats = sum(
        capacity_on_date(
            route["bus_id"],
            date.fromisoformat(route["service_date"]),
            capacity_history,
        )
        for route in routes
        if route["status"] != "DISRUPTED"
    )
    assignment_count = len(assignments)
    attendance_count = len(attendance_events)
    missed_pickup_count = sum(
        event["event_type"] == "MISSED_PICKUP"
        for event in attendance_events
    )
    unassigned_attempts = assignment_attempts - assignment_count
    missed_pickup_rate = (
        missed_pickup_count / attendance_count if attendance_count else 0
    )
    seat_utilization = (
        assignment_count / total_effective_seats
        if total_effective_seats
        else 0
    )
    print(f"Assignment attempts: {assignment_attempts:,}")
    print(f"Assignments accepted: {assignment_count:,}")
    print(f"Unassigned/rejected rate: "
          f"{unassigned_attempts / assignment_attempts:.2%}")
    print(f"Effective seat capacity: {total_effective_seats:,}")
    print(f"Remaining capacity: "
          f"{total_effective_seats - assignment_count:,}")
    print(f"Seat utilization: {seat_utilization:.2%}")
    print(f"Attendance events: {attendance_count:,}")
    print(f"Missed-pickup rate: {missed_pickup_rate:.2%}")
    print(f"Seed: {args.seed}")


if __name__ == "__main__":
    main()
