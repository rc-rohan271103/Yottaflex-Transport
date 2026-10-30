
"""Validate generated operational CSV data without modifying it."""

import csv
from pathlib import Path

DATA_DIR = Path("data/generated")


def load_csv(filename):
    path = DATA_DIR / filename
    if not path.exists():
        raise FileNotFoundError(f"Required file not found: {path}")

    with path.open("r", newline="", encoding="utf-8-sig") as file:
        return list(csv.DictReader(file))


def as_bool(value):
    return str(value).strip().lower() in {"1", "true", "yes"}


def main():
    buses = load_csv("bus.csv")
    students = load_csv("student.csv")
    stops = load_csv("stop.csv")
    routes = load_csv("route.csv")
    route_stops = load_csv("route_stop.csv")
    assignments = load_csv("assignment.csv")

    bus_by_id = {row["bus_id"]: row for row in buses}
    student_by_id = {row["student_id"]: row for row in students}
    stop_by_id = {row["stop_id"]: row for row in stops}
    route_by_id = {row["route_id"]: row for row in routes}

    checks = []

    def record(name, errors):
        status = "PASS" if not errors else "FAIL"
        checks.append((name, status, errors))
        print(f"{status}: {name} ({len(errors)} issue(s))")
        for error in errors[:10]:
            print(f"  - {error}")
        if len(errors) > 10:
            print(f"  - ... and {len(errors) - 10} more")

    # IDs must be unique.
    duplicate_errors = []
    for filename, rows, key in [
        ("bus.csv", buses, "bus_id"),
        ("student.csv", students, "student_id"),
        ("stop.csv", stops, "stop_id"),
        ("route.csv", routes, "route_id"),
        ("assignment.csv", assignments, "assignment_id"),
    ]:
        values = [row[key] for row in rows]
        if len(values) != len(set(values)):
            duplicate_errors.append(f"{filename} contains duplicate {key} values")
    record("Unique primary IDs", duplicate_errors)

    # Every assignment must reference an existing student, route and stop.
    reference_errors = []
    assigned_students = []
    for row in assignments:
        if row["student_id"] not in student_by_id:
            reference_errors.append(
                f"{row['assignment_id']}: unknown student {row['student_id']}"
            )
        if row["route_id"] not in route_by_id:
            reference_errors.append(
                f"{row['assignment_id']}: unknown route {row['route_id']}"
            )
        if row["stop_id"] not in stop_by_id:
            reference_errors.append(
                f"{row['assignment_id']}: unknown stop {row['stop_id']}"
            )
        assigned_students.append(row["student_id"])
    record("Assignment references", reference_errors)

    duplicate_student_errors = []
    seen_students = set()
    for student_id in assigned_students:
        if student_id in seen_students:
            duplicate_student_errors.append(
                f"Student {student_id} has multiple assignment rows"
            )
        seen_students.add(student_id)
    record("At most one assignment row per student", duplicate_student_errors)

    # Each route must use an existing bus.
    route_bus_errors = []
    for row in routes:
        if row["bus_id"] not in bus_by_id:
            route_bus_errors.append(
                f"{row['route_id']}: unknown bus {row['bus_id']}"
            )
    record("Route bus references", route_bus_errors)

    # Compare assigned passenger count with the bus capacity.
    capacity_errors = []
    route_passengers = {}
    for row in assignments:
        route_passengers[row["route_id"]] = (
            route_passengers.get(row["route_id"], 0) + 1
        )

    for route_id, passenger_count in route_passengers.items():
        route = route_by_id.get(route_id)
        if not route:
            continue
        bus = bus_by_id.get(route["bus_id"])
        if not bus:
            continue
        capacity_value = bus.get("capacity", "")
        if not capacity_value:
            capacity_errors.append(
                f"{route_id}: bus capacity is missing"
            )
            continue
        capacity = int(capacity_value)
        if passenger_count > capacity:
            capacity_errors.append(
                f"{route_id}: {passenger_count} assignments exceed capacity {capacity}"
            )
    record("Route capacity", capacity_errors)

    # Students needing accessibility support must use an accessible bus.
    accessibility_errors = []
    for row in assignments:
        student = student_by_id.get(row["student_id"])
        route = route_by_id.get(row["route_id"])
        if not student or not route:
            continue
        bus = bus_by_id.get(route["bus_id"])
        if not bus:
            continue

        needs_accessibility = as_bool(
            student.get("needs_accessibility", "0")
        )
        bus_accessible = as_bool(bus.get("is_accessible", "0"))

        if needs_accessibility and not bus_accessible:
            accessibility_errors.append(
                f"{row['assignment_id']}: accessibility need not supported by bus"
            )
    record("Accessibility compatibility", accessibility_errors)

    # Every assignment stop should appear in its assigned route.
    route_stop_pairs = {
        (row["route_id"], row["stop_id"]) for row in route_stops
    }
    route_stop_errors = []
    for row in assignments:
        if (row["route_id"], row["stop_id"]) not in route_stop_pairs:
            route_stop_errors.append(
                f"{row['assignment_id']}: stop not listed on assigned route"
            )
    record("Assigned stops belong to their routes", route_stop_errors)

    # Student and assigned stop should belong to the same zone.
    zone_errors = []
    for row in assignments:
        student = student_by_id.get(row["student_id"])
        stop = stop_by_id.get(row["stop_id"])
        if not student or not stop:
            continue
        if student.get("zone_id") != stop.get("zone_id"):
            zone_errors.append(
                f"{row['assignment_id']}: student zone "
                f"{student.get('zone_id')} != stop zone {stop.get('zone_id')}"
            )
    record("Student-stop zone consistency", zone_errors)

    print("\nSummary")
    print("=" * 40)
    for name, status, _ in checks:
        print(f"{status}: {name}")

    failed = sum(status == "FAIL" for _, status, _ in checks)
    print(f"\nChecks passed: {len(checks) - failed}/{len(checks)}")

    if failed:
        raise SystemExit(1)

    print("PASS: All operational data checks passed.")


if __name__ == "__main__":
    main()
