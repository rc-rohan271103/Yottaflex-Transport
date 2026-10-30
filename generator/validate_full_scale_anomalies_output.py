
import argparse
import json
from datetime import datetime, time, timedelta
from pathlib import Path

import pandas as pd

OUTPUT_DIR = Path("data/full_scale/anomalies")
MASTER_DIR = Path("data/full_scale")
OPERATIONS_DIR = MASTER_DIR / "operations"
DEFINITIONS_DIR = Path("data/ground_truth")

EXPECTED = {
    "GT-001": ("CAPACITY_EXCEEDED", "CAPACITY_EXCEEDED", "REJECT"),
    "GT-002": ("ACCESSIBILITY_MISMATCH", "INCOMPATIBLE_ROUTE", "REJECT"),
    "GT-003": ("IMPOSSIBLE_TRAVEL_TIME", "IMPOSSIBLE_TRAVEL_TIME", "FLAG"),
    "GT-004": ("INVALID_GUARDIAN_CONTACT", "INVALID_NOTIFICATION_CONTACT", "BLOCK"),
    "GT-005": (
        "UNAUTHORIZED_ADDRESS_DISCLOSURE",
        "UNAPPROVED_ADDRESS_EXPOSED",
        "BLOCK",
    ),
}


def normalized(value):
    if value is None:
        return ""
    if isinstance(value, bool):
        return str(value).lower()
    text = str(value)
    if text.lower() in {"true", "false"}:
        return text.lower()
    try:
        number = float(text)
    except ValueError:
        return text
    return str(int(number)) if number.is_integer() else format(number, "g")


def as_int(value):
    return int(float(value))


def as_bool(value):
    return str(value).strip().lower() in {"1", "true", "yes"}


def check(condition, message, checks):
    checks.append((message, bool(condition)))


def load_csv(folder, filename):
    path = folder / filename
    if not path.exists():
        raise FileNotFoundError(f"Required source file not found: {path}")
    return pd.read_csv(path, dtype=str).fillna("")


def load_json_cases(path):
    document = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(document, list):
        return document
    if not isinstance(document, dict) or not isinstance(
        document.get("cases"), list
    ):
        raise ValueError(f"{path} must contain a cases array.")
    if document.get("case_count") != len(document["cases"]):
        raise ValueError(f"{path} case_count does not match its cases array.")
    return document["cases"]


def validate_source_cases(cases, master_dir, operations_dir, checks):
    master_files = [
        "address_zone.csv",
        "address.csv",
        "student.csv",
        "guardian_contact.csv",
        "stop.csv",
        "bus.csv",
        "driver.csv",
        "bus_capacity_history.csv",
    ]
    operation_files = [
        "route.csv",
        "route_stop.csv",
        "assignment.csv",
        "attendance_event.csv",
        "notification.csv",
        "bus_capacity_history.csv",
        "route_disruption.csv",
    ]
    feature_columns = {
        "issue_type",
        "ground_truth_label",
        "expected_outcome",
        "actual_outcome",
        "detected",
    }
    for folder, filenames, label in (
        (master_dir, master_files, "master"),
        (operations_dir, operation_files, "operational"),
    ):
        for filename in filenames:
            frame = load_csv(folder, filename)
            leaked = feature_columns.intersection(frame.columns)
            check(
                not leaked,
                f"{label} input {filename} excludes ground-truth labels",
                checks,
            )

    students = load_csv(master_dir, "student.csv").set_index("student_id")
    buses = load_csv(master_dir, "bus.csv").set_index("bus_id")
    addresses = load_csv(master_dir, "address.csv").set_index("address_id")
    guardians = load_csv(master_dir, "guardian_contact.csv").set_index("guardian_id")
    stops = load_csv(master_dir, "stop.csv").set_index("stop_id")
    routes = load_csv(operations_dir, "route.csv").set_index("route_id")
    route_stops = load_csv(operations_dir, "route_stop.csv").set_index(
        "route_stop_id"
    )
    assignments = load_csv(operations_dir, "assignment.csv")
    attendance = load_csv(operations_dir, "attendance_event.csv").set_index(
        "event_id"
    )
    capacity_history = load_csv(
        operations_dir, "bus_capacity_history.csv"
    )

    by_id = {record["case_id"]: record for record in cases}
    complete_case_ids = set(by_id) == set(EXPECTED)
    check(complete_case_ids, "Source ground truth contains all five cases", checks)
    if not complete_case_ids:
        return

    for case_id in EXPECTED:
        record = by_id[case_id]
        try:
            if case_id == "GT-001":
                route = routes.loc[record["route_id"]]
                matching_capacity = capacity_history[
                    capacity_history["bus_id"].eq(route["bus_id"])
                    & capacity_history["effective_from"].le(route["service_date"])
                    & (
                        capacity_history["effective_to"].eq("")
                        | capacity_history["effective_to"].ge(route["service_date"])
                    )
                ]
                load = int(assignments["route_id"].eq(record["route_id"]).sum())
                capacity = int(matching_capacity.iloc[0]["capacity"])
                check(
                    len(matching_capacity) == 1
                    and route["bus_id"] == record["bus_id"]
                    and route["service_date"] == record["service_date"]
                    and load == as_int(record["baseline_load"])
                    and capacity == as_int(record["bus_capacity"])
                    and as_int(record["assigned_passengers"])
                    == max(load, capacity) + 1,
                    "GT-001 derives its route load and effective capacity from baseline",
                    checks,
                )
                safe_outcome = (
                    "REJECT"
                    if as_int(record["assigned_passengers"]) > capacity
                    else "ACCEPT"
                )
            elif case_id == "GT-002":
                student = students.loc[record["student_id"]]
                route = routes.loc[record["route_id"]]
                stop = stops.loc[record["stop_id"]]
                route_stop = route_stops.loc[record["route_stop_id"]]
                bus = buses.loc[route["bus_id"]]
                arrival_time = time.fromisoformat(route_stop["arrival_time"])
                check(
                    record["route_stop_id"] in route_stops.index
                    and route_stop["route_id"] == record["route_id"]
                    and route_stop["stop_id"] == record["stop_id"]
                    and route["bus_id"] == record["bus_id"]
                    and stop["zone_id"] == student["zone_id"]
                    and time.fromisoformat(student["pickup_window_start"])
                    <= arrival_time
                    <= time.fromisoformat(student["pickup_window_end"])
                    and as_bool(student["accessibility_required"])
                    and not as_bool(bus["is_accessible"])
                    and as_bool(record["student_needs_accessibility"])
                    and not as_bool(record["bus_is_accessible"]),
                    "GT-002 references a valid same-zone stop and an accessibility-incompatible route",
                    checks,
                )
                safe_outcome = (
                    "REJECT"
                    if as_bool(student["accessibility_required"])
                    and not as_bool(bus["is_accessible"])
                    else "ACCEPT"
                )
            elif case_id == "GT-003":
                route_stop = route_stops.loc[record["route_stop_id"]]
                schedule = route_stops[
                    route_stops["route_id"].eq(record["route_id"])
                ].copy()
                schedule["sequence_number"] = pd.to_numeric(
                    schedule["sequence_no"], errors="raise"
                )
                previous = schedule[
                    schedule["sequence_number"]
                    == as_int(record["sequence_no"]) - 1
                ]
                proposed_arrival = (
                    datetime.strptime(
                        previous.iloc[0]["arrival_time"], "%H:%M:%S"
                    )
                    + timedelta(minutes=as_int(record["travel_minutes"]))
                ).strftime("%H:%M:%S")
                check(
                    route_stop["route_id"] == record["route_id"]
                    and route_stop["arrival_time"]
                    == record["baseline_arrival_time"]
                    and as_int(route_stop["travel_minutes"])
                    == as_int(record["baseline_travel_minutes"])
                    and len(previous) == 1
                    and previous.iloc[0]["arrival_time"]
                    == record["previous_arrival_time"]
                    and record["proposed_arrival_time"] == proposed_arrival,
                    "GT-003 proposal derives from its baseline stop and prior arrival",
                    checks,
                )
                safe_outcome = (
                    "FLAG"
                    if as_int(record["travel_minutes"])
                    < as_int(record["minimum_plausible_minutes"])
                    else "ACCEPT"
                )
            elif case_id == "GT-004":
                guardian = guardians.loc[record["guardian_id"]]
                event = attendance.loc[record["event_id"]]
                check(
                    guardian["student_id"] == record["student_id"]
                    and event["student_id"] == record["student_id"]
                    and event["route_id"] == record["route_id"]
                    and as_int(guardian["is_valid"])
                    == as_int(record["baseline_contact_is_valid"])
                    and not as_bool(record["guardian_contact_is_valid"]),
                    "GT-004 joins a real same-student guardian and attendance event",
                    checks,
                )
                safe_outcome = (
                    "BLOCK"
                    if not as_bool(record["guardian_contact_is_valid"])
                    else "ALLOW"
                )
            else:
                address = addresses.loc[record["address_id"]]
                check(
                    address["approval_status"]
                    == record["baseline_approval_status"]
                    and record["proposed_approval_status"] == "UNAPPROVED"
                    and as_bool(record["proposed_address_exposed"]),
                    "GT-005 references a source address and proposes unapproved exposure",
                    checks,
                )
                safe_outcome = (
                    "BLOCK"
                    if record["proposed_approval_status"] != "APPROVED"
                    or not as_bool(address["disclosure_authorized"])
                    else "ALLOW"
                )
            check(
                safe_outcome == EXPECTED[case_id][2]
                and record["actual_outcome"] == safe_outcome,
                f"{case_id} safe decision is recomputed from its proposal",
                checks,
            )
        except (KeyError, IndexError, ValueError, TypeError) as error:
            check(False, f"{case_id} source references are valid ({error})", checks)


def main(
    output_dir=OUTPUT_DIR,
    master_dir=MASTER_DIR,
    operations_dir=OPERATIONS_DIR,
    definitions_dir=DEFINITIONS_DIR,
):
    csv_path = output_dir / "ground_truth.csv"
    json_path = output_dir / "ground_truth.json"

    for path in (csv_path, json_path):
        if not path.exists():
            raise FileNotFoundError(f"Required output file not found: {path}")

    df = pd.read_csv(csv_path, dtype=str).fillna("")
    records = load_json_cases(json_path)

    checks = []
    definition_path = definitions_dir / "ground_truth.csv"
    if definition_path.exists():
        definitions = pd.read_csv(definition_path, dtype=str).fillna("")
        definition_by_id = definitions.set_index("case_id")
        check(
            set(definition_by_id.index) == set(EXPECTED),
            "Ground-truth definitions contain all expected cases",
            checks,
        )
        for case_id, (anomaly_type, _, expected_outcome) in EXPECTED.items():
            check(
                case_id in definition_by_id.index
                and definition_by_id.loc[case_id, "anomaly_type"] == anomaly_type
                and definition_by_id.loc[case_id, "expected_outcome"]
                == expected_outcome,
                f"{case_id} proposal agrees with its documented definition",
                checks,
            )
    else:
        raise FileNotFoundError(f"Ground-truth definitions not found: {definition_path}")

    # CSV structure and unique case IDs.
    checks.append(
        ("CSV contains exactly five cases", len(df) == 5)
    )
    checks.append(
        (
            "CSV case IDs are unique",
            df["case_id"].is_unique,
        )
    )
    checks.append(
        (
            "CSV contains all five expected case IDs",
            set(df["case_id"]) == set(EXPECTED),
        )
    )

    # Validate every case's type, expected outcome, actual outcome,
    # and detector result in the CSV.
    csv_cases = df.set_index("case_id", drop=False)

    for case_id, (anomaly_type, issue_type, expected_outcome) in EXPECTED.items():
        if case_id not in csv_cases.index:
            checks.append((f"{case_id} exists in CSV", False))
            continue

        row = csv_cases.loc[case_id]
        checks.append(
            (
                f"{case_id} anomaly type is correct",
                row["anomaly_type"] == anomaly_type,
            )
        )
        checks.append(
            (
                f"{case_id} issue type and ground-truth label are explicit",
                row["issue_type"] == issue_type
                and row["ground_truth_label"] == anomaly_type,
            )
        )
        checks.append(
            (
                f"{case_id} expected outcome is correct",
                row["expected_outcome"] == expected_outcome,
            )
        )
        checks.append(
            (
                f"{case_id} actual outcome matches expected",
                row["actual_outcome"] == expected_outcome,
            )
        )
        checks.append(
            (
                f"{case_id} was detected",
                str(row["detected"]).strip().lower() == "true",
            )
        )
        checks.append(
            (
                f"{case_id} is a separate proposal, not a baseline mutation",
                row["scenario_mode"] == "PROPOSED_ONLY"
                and str(row["baseline_modified"]).strip().lower() == "false",
            )
        )

        if case_id == "GT-001":
            checks.append(
                (
                    "GT-001 proposed load is derived and exceeds capacity",
                    as_int(row["assigned_passengers"])
                    > as_int(row["bus_capacity"])
                    and as_int(row["assigned_passengers"])
                    == as_int(row["baseline_load"])
                    + as_int(row["proposed_additional_passengers"]),
                )
            )
        elif case_id == "GT-002":
            checks.append(
                (
                    "GT-002 has an accessibility incompatibility",
                    row["student_needs_accessibility"] == "True"
                    and row["bus_is_accessible"] == "False",
                )
            )
        elif case_id == "GT-003":
            proposed_arrival = (
                datetime.strptime(row["previous_arrival_time"], "%H:%M:%S")
                + timedelta(minutes=as_int(row["travel_minutes"]))
            ).strftime("%H:%M:%S")
            checks.append(
                (
                    "GT-003 timing is derived and below the plausibility limit",
                    as_int(row["travel_minutes"])
                    < as_int(row["minimum_plausible_minutes"])
                    and row["proposed_arrival_time"] == proposed_arrival,
                )
            )
        elif case_id == "GT-004":
            checks.append(
                (
                    "GT-004 proposes sending to an invalid contact",
                    as_int(row["guardian_contact_is_valid"]) == 0
                    and row["proposed_status"] == "SIMULATED_SENT",
                )
            )
        elif case_id == "GT-005":
            checks.append(
                (
                    "GT-005 proposes exposure of an unapproved address",
                    row["proposed_approval_status"] == "UNAPPROVED"
                    and row["proposed_address_exposed"] == "True",
                )
            )

    # JSON structure and consistency with the CSV.
    checks.append(
        ("JSON contains exactly five cases", len(records) == 5)
    )

    json_ids = [record.get("case_id") for record in records]
    checks.append(
        (
            "JSON case IDs are unique",
            len(json_ids) == len(set(json_ids)),
        )
    )
    checks.append(
        (
            "JSON case IDs match the expected set",
            set(json_ids) == set(EXPECTED),
        )
    )

    json_by_id = {
        record.get("case_id"): record for record in records
    }

    for case_id, (anomaly_type, issue_type, expected_outcome) in EXPECTED.items():
        record = json_by_id.get(case_id)

        if record is None:
            checks.append((f"{case_id} exists in JSON", False))
            continue

        checks.append(
            (
                f"{case_id} JSON type and outcomes are correct",
                record.get("anomaly_type") == anomaly_type
                and record.get("issue_type") == issue_type
                and record.get("ground_truth_label") == anomaly_type
                and record.get("expected_outcome") == expected_outcome
                and record.get("actual_outcome") == expected_outcome
                and record.get("detected") is True,
            )
        )

    csv_records = df.to_dict("records")
    json_records_by_id = {record.get("case_id"): record for record in records}
    for csv_record in csv_records:
        json_record = json_records_by_id.get(csv_record["case_id"], {})
        checks.append(
            (
                f"{csv_record['case_id']} CSV and JSON fields match",
                all(
                    normalized(csv_record[column])
                    == normalized(json_record.get(column))
                    for column in df.columns
                ),
            )
        )

    validate_source_cases(records, master_dir, operations_dir, checks)

    print("Full-scale anomaly output validation")
    print("=" * 48)

    for description, passed in checks:
        print(f"{'PASS' if passed else 'FAIL'}: {description}")

    passed_count = sum(passed for _, passed in checks)
    total_count = len(checks)

    print("-" * 48)
    print(f"Results: {passed_count}/{total_count} checks passed")

    if passed_count != total_count:
        raise SystemExit(1)

    print("PASS: CSV and JSON anomaly outputs are consistent.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=OUTPUT_DIR)
    parser.add_argument("--master", type=Path, default=MASTER_DIR)
    parser.add_argument("--operations", type=Path, default=OPERATIONS_DIR)
    parser.add_argument("--definitions", type=Path, default=DEFINITIONS_DIR)
    args = parser.parse_args()
    main(
        output_dir=args.output,
        master_dir=args.master,
        operations_dir=args.operations,
        definitions_dir=args.definitions,
    )
