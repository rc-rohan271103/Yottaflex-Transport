
import argparse
import json
from datetime import datetime, time, timedelta
from pathlib import Path

import pandas as pd

from app.anomaly_detector import (
    check_capacity,
    check_accessibility,
    check_travel_time,
    check_guardian_contact,
    check_address_disclosure,
)

MASTER_DIR = Path("data/full_scale")
OPS_DIR = MASTER_DIR / "operations"
OUTPUT_DIR = MASTER_DIR / "anomalies"

MINIMUM_TRAVEL_MINUTES = 10


def load_csv(folder, name):
    path = folder / f"{name}.csv"
    if not path.exists():
        raise FileNotFoundError(f"Required file not found: {path}")
    return pd.read_csv(path, dtype=str).fillna("")


def as_bool(value):
    return str(value).strip().lower() in {"1", "true", "yes"}


def require_row(df, column, value, label):
    matches = df[df[column] == value]
    if matches.empty:
        raise ValueError(f"No matching {label} found for {column}={value}")
    return matches.iloc[0]


def validate_baseline(
    students,
    buses,
    guardians,
    addresses,
    routes,
    route_stops,
    assignments,
    attendance,
    capacity_history,
    stops,
):
    keyed_tables = [
        ("student", students, "student_id"),
        ("bus", buses, "bus_id"),
        ("guardian_contact", guardians, "guardian_id"),
        ("address", addresses, "address_id"),
        ("route", routes, "route_id"),
        ("route_stop", route_stops, "route_stop_id"),
        ("assignment", assignments, "assignment_id"),
        ("attendance_event", attendance, "event_id"),
        ("stop", stops, "stop_id"),
        ("bus_capacity_history", capacity_history, "capacity_history_id"),
    ]
    for name, frame, key in keyed_tables:
        if key not in frame or frame[key].eq("").any() or frame[key].duplicated().any():
            raise ValueError(f"Baseline {name}.{key} must be present and unique.")

    relationships = [
        (routes, "bus_id", buses, "bus_id", "route.bus_id"),
        (route_stops, "route_id", routes, "route_id", "route_stop.route_id"),
        (route_stops, "stop_id", stops, "stop_id", "route_stop.stop_id"),
        (assignments, "student_id", students, "student_id", "assignment.student_id"),
        (assignments, "route_id", routes, "route_id", "assignment.route_id"),
        (assignments, "stop_id", stops, "stop_id", "assignment.stop_id"),
        (attendance, "student_id", students, "student_id", "attendance_event.student_id"),
        (attendance, "route_id", routes, "route_id", "attendance_event.route_id"),
        (guardians, "student_id", students, "student_id", "guardian_contact.student_id"),
        (capacity_history, "bus_id", buses, "bus_id", "bus_capacity_history.bus_id"),
    ]
    for child, child_key, parent, parent_key, label in relationships:
        if not child[child_key].isin(parent[parent_key]).all():
            raise ValueError(f"Baseline contains an invalid {label} reference.")

    served_stops = set(zip(route_stops["route_id"], route_stops["stop_id"]))
    if not set(zip(assignments["route_id"], assignments["stop_id"])).issubset(
        served_stops
    ):
        raise ValueError("Baseline assignment references a stop not served by its route.")

    addresses_by_id = addresses.set_index("address_id")
    for student in students.itertuples(index=False):
        address = addresses_by_id.loc[student.address_id]
        if student.zone_id != address["zone_id"]:
            raise ValueError(
                f"Baseline student {student.student_id} zone does not match address."
            )

    routes_with_capacity = routes.merge(
        capacity_history,
        on="bus_id",
        how="left",
        validate="many_to_many",
    )
    routes_with_capacity["service_date_value"] = pd.to_datetime(
        routes_with_capacity["service_date"], errors="raise"
    )
    routes_with_capacity["effective_from_value"] = pd.to_datetime(
        routes_with_capacity["effective_from"], errors="raise"
    )
    routes_with_capacity["effective_to_value"] = pd.to_datetime(
        routes_with_capacity["effective_to"].replace("", pd.NA),
        errors="raise",
    )
    active_capacity = routes_with_capacity[
        routes_with_capacity["effective_from_value"].le(
            routes_with_capacity["service_date_value"]
        )
        & (
            routes_with_capacity["effective_to_value"].isna()
            | routes_with_capacity["effective_to_value"].ge(
                routes_with_capacity["service_date_value"]
            )
        )
    ]
    if not active_capacity.groupby("route_id").size().reindex(
        routes["route_id"], fill_value=0
    ).eq(1).all():
        raise ValueError(
            "Baseline routes must each have exactly one effective capacity record."
        )


def main(
    master_dir=MASTER_DIR,
    operations_dir=OPS_DIR,
    output_dir=OUTPUT_DIR,
):
    output_paths = (
        output_dir / "ground_truth.csv",
        output_dir / "ground_truth.json",
    )
    existing_outputs = [path for path in output_paths if path.exists()]
    if existing_outputs:
        raise FileExistsError(
            "Refusing to overwrite existing ground-truth anomaly examples. "
            "Move or back up the existing files before regenerating: "
            + ", ".join(str(path) for path in existing_outputs)
        )

    output_dir.mkdir(parents=True, exist_ok=True)

    students = load_csv(master_dir, "student")
    buses = load_csv(master_dir, "bus")
    guardians = load_csv(master_dir, "guardian_contact")
    addresses = load_csv(master_dir, "address")
    stops = load_csv(master_dir, "stop")

    routes = load_csv(operations_dir, "route")
    route_stops = load_csv(operations_dir, "route_stop")
    assignments = load_csv(operations_dir, "assignment")
    attendance = load_csv(operations_dir, "attendance_event")
    capacity_history = load_csv(operations_dir, "bus_capacity_history")
    validate_baseline(
        students,
        buses,
        guardians,
        addresses,
        routes,
        route_stops,
        assignments,
        attendance,
        capacity_history,
        stops,
    )

    examples = []

    # GT-001: Proposed assignment exceeding the effective bus capacity.
    route = routes.iloc[0]
    route_bus = require_row(buses, "bus_id", route["bus_id"], "bus")
    route_date = pd.Timestamp(route["service_date"])

    capacity_rows = capacity_history[
        (capacity_history["bus_id"] == route["bus_id"])
        & (
            pd.to_datetime(capacity_history["effective_from"])
            <= route_date
        )
        & (
            capacity_history["effective_to"].eq("")
            | (
                pd.to_datetime(
                    capacity_history["effective_to"].replace("", pd.NA)
                ).isna()
                | (
                    pd.to_datetime(
                        capacity_history["effective_to"].replace("", pd.NA)
                    )
                    >= route_date
                )
            )
        )
    ]

    if len(capacity_rows) != 1:
        raise ValueError(
            "Selected route must have exactly one effective capacity record."
        )
    capacity = int(capacity_rows.iloc[0]["capacity"])

    current_load = int((assignments["route_id"] == route["route_id"]).sum())
    proposed_load = max(current_load, capacity) + 1

    capacity_decision = check_capacity(proposed_load, capacity)

    examples.append({
        "case_id": "GT-001",
        "anomaly_type": "CAPACITY_EXCEEDED",
        "entity_type": "proposed_assignment",
        "route_id": route["route_id"],
        "bus_id": route["bus_id"],
        "service_date": route["service_date"],
        "assigned_passengers": proposed_load,
        "bus_capacity": capacity,
        "expected_outcome": "REJECT",
        "actual_outcome": capacity_decision,
        "detected": capacity_decision == "REJECT",
        "baseline_load": current_load,
        "proposed_additional_passengers": proposed_load - current_load,
    })

    # GT-002: Accessibility-required student proposed for an inaccessible bus.
    inaccessible_buses = buses[
        ~buses["is_accessible"].map(as_bool)
    ]
    students_needing_accessibility = students[
        students["accessibility_required"].map(as_bool)
    ]

    if inaccessible_buses.empty or students_needing_accessibility.empty:
        raise ValueError(
            "Cannot build accessibility example: need both a student "
            "requiring accessibility and an inaccessible bus."
        )

    inaccessible_route_candidates = (
        route_stops.merge(
            routes[["route_id", "bus_id", "service_date"]],
            on="route_id",
            how="inner",
            validate="many_to_one",
        )
        .merge(
            inaccessible_buses[["bus_id", "is_accessible"]],
            on="bus_id",
            how="inner",
            validate="many_to_one",
        )
        .merge(
            stops[["stop_id", "zone_id"]],
            on="stop_id",
            how="inner",
            validate="many_to_one",
        )
    )
    possible_mismatches = []
    for student_row in students_needing_accessibility.itertuples(index=False):
        matching = inaccessible_route_candidates[
            inaccessible_route_candidates["zone_id"].eq(student_row.zone_id)
        ]
        for route_stop_row in matching.itertuples(index=False):
            arrival = pd.Timestamp(
                f"{route_stop_row.service_date} {route_stop_row.arrival_time}"
            ).time()
            if (
                time.fromisoformat(student_row.pickup_window_start)
                <= arrival
                <= time.fromisoformat(student_row.pickup_window_end)
            ):
                possible_mismatches.append(
                    (student_row, route_stop_row)
                )
                break
        if possible_mismatches:
            break
    if not possible_mismatches:
        raise ValueError(
            "Cannot build accessibility example from a valid baseline "
            "route-stop pair with a compatible zone and pickup window."
        )
    student, incompatible_route_stop = possible_mismatches[0]
    bus = require_row(
        buses, "bus_id", incompatible_route_stop.bus_id, "inaccessible bus"
    )

    accessibility_decision = check_accessibility(
        as_bool(student.accessibility_required),
        as_bool(bus["is_accessible"]),
    )

    examples.append({
        "case_id": "GT-002",
        "anomaly_type": "ACCESSIBILITY_MISMATCH",
        "issue_type": "INCOMPATIBLE_ROUTE",
        "entity_type": "proposed_assignment",
        "student_id": student.student_id,
        "stop_id": incompatible_route_stop.stop_id,
        "route_stop_id": incompatible_route_stop.route_stop_id,
        "route_id": incompatible_route_stop.route_id,
        "bus_id": bus["bus_id"],
        "student_needs_accessibility": True,
        "bus_is_accessible": False,
        "expected_outcome": "REJECT",
        "actual_outcome": accessibility_decision,
        "detected": accessibility_decision == "REJECT",
    })

    # GT-003: Route leg with an implausibly short travel time.
    route_stop = route_stops[
        pd.to_numeric(route_stops["sequence_no"], errors="raise") > 1
    ]
    if route_stop.empty:
        raise ValueError("No route leg found for travel-time anomaly.")

    travel_leg = route_stop.iloc[0]
    route_schedule = route_stops[
        route_stops["route_id"].eq(travel_leg["route_id"])
    ].copy()
    route_schedule["sequence_no_numeric"] = pd.to_numeric(
        route_schedule["sequence_no"], errors="raise"
    )
    previous_stop = route_schedule[
        route_schedule["sequence_no_numeric"]
        == int(travel_leg["sequence_no"]) - 1
    ]
    if len(previous_stop) != 1:
        raise ValueError(
            "Travel-time anomaly requires exactly one preceding stop."
        )
    proposed_arrival = (
        datetime.strptime(
            previous_stop.iloc[0]["arrival_time"], "%H:%M:%S"
        )
        + timedelta(minutes=2)
    ).strftime("%H:%M:%S")
    travel_decision = check_travel_time(
        2, MINIMUM_TRAVEL_MINUTES
    )

    examples.append({
        "case_id": "GT-003",
        "anomaly_type": "IMPOSSIBLE_TRAVEL_TIME",
        "issue_type": "IMPOSSIBLE_TRAVEL_TIME",
        "entity_type": "proposed_route_stop",
        "route_stop_id": travel_leg["route_stop_id"],
        "route_id": travel_leg["route_id"],
        "sequence_no": int(travel_leg["sequence_no"]),
        "previous_arrival_time": previous_stop.iloc[0]["arrival_time"],
        "baseline_travel_minutes": int(travel_leg["travel_minutes"]),
        "baseline_arrival_time": travel_leg["arrival_time"],
        "travel_minutes": 2,
        "proposed_arrival_time": proposed_arrival,
        "minimum_plausible_minutes": MINIMUM_TRAVEL_MINUTES,
        "expected_outcome": "FLAG",
        "actual_outcome": travel_decision,
        "detected": travel_decision == "FLAG",
    })

    # GT-004: Proposed notification using a contact flagged invalid for the case.
    guardian_events = (
        attendance[["event_id", "student_id", "route_id"]]
        .drop_duplicates("student_id")
        .merge(
            guardians[["guardian_id", "student_id", "is_valid"]],
            on="student_id",
            how="inner",
            validate="one_to_many",
        )
    )
    if guardian_events.empty:
        raise ValueError(
            "No same-student guardian contact joins to a baseline attendance event."
        )
    guardian_event = guardian_events.iloc[0]
    guardian_contact_baseline_valid = as_bool(guardian_event["is_valid"])
    proposed_contact_valid = False
    contact_decision = check_guardian_contact(int(proposed_contact_valid))

    examples.append({
        "case_id": "GT-004",
        "anomaly_type": "INVALID_GUARDIAN_CONTACT",
        "issue_type": "INVALID_NOTIFICATION_CONTACT",
        "entity_type": "proposed_notification",
        "guardian_id": guardian_event["guardian_id"],
        "student_id": guardian_event["student_id"],
        "event_id": guardian_event["event_id"],
        "route_id": guardian_event["route_id"],
        "proposed_status": "SIMULATED_SENT",
        "baseline_contact_is_valid": int(guardian_contact_baseline_valid),
        "guardian_contact_is_valid": int(proposed_contact_valid),
        "expected_outcome": "BLOCK",
        "actual_outcome": contact_decision,
        "detected": contact_decision == "BLOCK",
    })

    # GT-005: Attempted disclosure of a restricted address.
    if addresses.empty:
        raise ValueError("No address found for unapproved-disclosure example.")
    address = addresses.iloc[0]
    proposed_approval_status = "UNAPPROVED"
    eligible_for_disclosure = (
        proposed_approval_status == "APPROVED"
        and as_bool(address["disclosure_authorized"])
    )
    disclosure_decision = check_address_disclosure(
        int(eligible_for_disclosure),
        1,
    )

    examples.append({
        "case_id": "GT-005",
        "anomaly_type": "UNAUTHORIZED_ADDRESS_DISCLOSURE",
        "issue_type": "UNAPPROVED_ADDRESS_EXPOSED",
        "entity_type": "proposed_address_disclosure",
        "address_id": address["address_id"],
        "baseline_approval_status": address["approval_status"],
        "proposed_approval_status": proposed_approval_status,
        "disclosure_authorized": int(as_bool(address["disclosure_authorized"])),
        "proposed_address_exposed": True,
        "requester_is_authorized": 1,
        "expected_outcome": "BLOCK",
        "actual_outcome": disclosure_decision,
        "detected": disclosure_decision == "BLOCK",
    })

    for example in examples:
        example.setdefault("issue_type", example["anomaly_type"])
        example["ground_truth_label"] = example["anomaly_type"]
        example["scenario_mode"] = "PROPOSED_ONLY"
        example["baseline_modified"] = False

    result = pd.DataFrame(examples)

    csv_path = output_dir / "ground_truth.csv"
    json_path = output_dir / "ground_truth.json"

    result.to_csv(csv_path, index=False)
    json_path.write_text(
        json.dumps(
            {
                "seed": 20261022,
                "case_count": len(examples),
                "cases": examples,
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    print("Full-scale anomaly examples generated.")
    print(f"CSV: {csv_path}")
    print(f"JSON: {json_path}")
    print("\nVerification results:")

    for example in examples:
        status = "PASS" if example["detected"] else "FAIL"
        print(
            f"{status}: {example['case_id']} "
            f"{example['anomaly_type']} "
            f"expected={example['expected_outcome']} "
            f"actual={example['actual_outcome']}"
        )

    passed = sum(bool(example["detected"]) for example in examples)
    print(f"\nResults: {passed}/{len(examples)} anomaly rules detected.")

    if passed != len(examples):
        raise SystemExit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--master", type=Path, default=MASTER_DIR)
    parser.add_argument("--operations", type=Path, default=OPS_DIR)
    parser.add_argument("--output", type=Path, default=OUTPUT_DIR)
    args = parser.parse_args()
    main(
        master_dir=args.master,
        operations_dir=args.operations,
        output_dir=args.output,
    )
