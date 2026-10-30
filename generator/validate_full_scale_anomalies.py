
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

# Provisional threshold; not a real-world travel-time guarantee.
MINIMUM_TRAVEL_MINUTES = 10


def load_csv(folder, name):
    path = folder / f"{name}.csv"
    if not path.exists():
        raise FileNotFoundError(f"Required file not found: {path}")
    return pd.read_csv(path, dtype=str).fillna("")


def as_bool(value):
    return str(value).strip().lower() in {"1", "true", "yes"}


def report(title, count, examples=None):
    print(f"\n{title}: {count}")
    if examples is not None and not examples.empty:
        print(examples.head(5).to_string(index=False))


def main():
    print("Yottaflex full-scale anomaly validation")
    print("=" * 48)

    # Load existing data. This script does not modify any CSV files.
    students = load_csv(MASTER_DIR, "student")
    buses = load_csv(MASTER_DIR, "bus")
    guardians = load_csv(MASTER_DIR, "guardian_contact")
    addresses = load_csv(MASTER_DIR, "address")

    routes = load_csv(OPS_DIR, "route")
    assignments = load_csv(OPS_DIR, "assignment")
    route_stops = load_csv(OPS_DIR, "route_stop")
    capacity_history = load_csv(OPS_DIR, "bus_capacity_history")

    # Normalize data types.
    students["accessibility_required"] = (
        students["accessibility_required"].map(as_bool)
    )
    buses["is_accessible"] = buses["is_accessible"].map(as_bool)

    buses["capacity"] = pd.to_numeric(
        buses["capacity"], errors="raise"
    )
    capacity_history["capacity"] = pd.to_numeric(
        capacity_history["capacity"], errors="raise"
    )

    routes["service_date"] = pd.to_datetime(
        routes["service_date"], errors="raise"
    ).dt.normalize()

    capacity_history["effective_from"] = pd.to_datetime(
        capacity_history["effective_from"], errors="raise"
    ).dt.normalize()

    capacity_history["effective_to"] = pd.to_datetime(
        capacity_history["effective_to"].replace("", pd.NA),
        errors="raise",
    ).dt.normalize()

    # ---------------------------------------------------------
    # 1. CAPACITY_EXCEEDED
    # Count assignments per route and compare with the capacity
    # effective for that bus on the route's service date.
    # ---------------------------------------------------------
    passenger_counts = (
        assignments.groupby("route_id")
        .size()
        .rename("assigned_passengers")
        .reset_index()
    )

    route_loads = routes[
        ["route_id", "bus_id", "service_date"]
    ].merge(
        passenger_counts,
        on="route_id",
        how="left",
        validate="one_to_one",
    )

    route_loads["assigned_passengers"] = (
        route_loads["assigned_passengers"].fillna(0).astype(int)
    )

    capacity_matches = route_loads.merge(
        capacity_history[
            ["bus_id", "capacity", "effective_from", "effective_to"]
        ],
        on="bus_id",
        how="left",
    )

    capacity_matches = capacity_matches[
        (
            capacity_matches["effective_from"]
            <= capacity_matches["service_date"]
        )
        & (
            capacity_matches["effective_to"].isna()
            | (
                capacity_matches["service_date"]
                <= capacity_matches["effective_to"]
            )
        )
    ].copy()

    capacity_match_counts = capacity_matches.groupby("route_id").size()
    missing_capacity = (
        set(route_loads["route_id"])
        - set(capacity_match_counts.index)
    )
    overlapping_capacity = capacity_match_counts[
        capacity_match_counts != 1
    ]

    print("\nCapacity-history coverage:")
    print(f"Routes with no effective capacity: {len(missing_capacity)}")
    print(
        "Routes with overlapping effective capacity records: "
        f"{len(overlapping_capacity)}"
    )

    capacity_matches["capacity"] = capacity_matches["capacity"].astype(int)

    # The detector returns "REJECT" or "ACCEPT", not True or False.
    capacity_matches["decision"] = capacity_matches.apply(
        lambda row: check_capacity(
            int(row["assigned_passengers"]),
            int(row["capacity"]),
        ),
        axis=1,
    )

    capacity_issues = capacity_matches[
        capacity_matches["decision"] == "REJECT"
    ]

    report(
        "CAPACITY_EXCEEDED detections",
        len(capacity_issues),
        capacity_issues[
            [
                "route_id",
                "bus_id",
                "service_date",
                "assigned_passengers",
                "capacity",
            ]
        ],
    )

    # ---------------------------------------------------------
    # 2. ACCESSIBILITY_MISMATCH
    # Compare each student's needs with the assigned route's bus.
    # ---------------------------------------------------------
    accessibility_data = (
        assignments[["assignment_id", "student_id", "route_id"]]
        .merge(
            students[["student_id", "accessibility_required"]],
            on="student_id",
            how="left",
            validate="many_to_one",
        )
        .merge(
            routes[["route_id", "bus_id", "service_date"]],
            on="route_id",
            how="left",
            validate="many_to_one",
        )
        .merge(
            buses[["bus_id", "is_accessible"]],
            on="bus_id",
            how="left",
            validate="many_to_one",
        )
    )

    accessibility_data["decision"] = accessibility_data.apply(
        lambda row: check_accessibility(
            bool(row["accessibility_required"]),
            bool(row["is_accessible"]),
        ),
        axis=1,
    )

    accessibility_issues = accessibility_data[
        accessibility_data["decision"] == "REJECT"
    ]

    report(
        "ACCESSIBILITY_MISMATCH detections",
        len(accessibility_issues),
        accessibility_issues[
            [
                "assignment_id",
                "student_id",
                "route_id",
                "service_date",
                "accessibility_required",
                "is_accessible",
            ]
        ],
    )

    # ---------------------------------------------------------
    # 3. IMPOSSIBLE_TRAVEL_TIME
    # Sequence 1 is the starting stop, not a travel leg.
    # A travel time below 10 minutes is flagged provisionally.
    # ---------------------------------------------------------
    route_stops["sequence_no"] = pd.to_numeric(
        route_stops["sequence_no"], errors="raise"
    )
    route_stops["travel_minutes"] = pd.to_numeric(
        route_stops["travel_minutes"], errors="raise"
    )

    travel_legs = route_stops[
        route_stops["sequence_no"] > 1
    ].copy()

    travel_legs["decision"] = travel_legs["travel_minutes"].apply(
        lambda value: check_travel_time(
            int(value),
            MINIMUM_TRAVEL_MINUTES,
        )
    )

    travel_issues = travel_legs[
        travel_legs["decision"] == "FLAG"
    ]

    report(
        "IMPOSSIBLE_TRAVEL_TIME detections",
        len(travel_issues),
        travel_issues[
            [
                "route_stop_id",
                "route_id",
                "sequence_no",
                "travel_minutes",
            ]
        ],
    )

    print(
        f"Travel-time threshold: {MINIMUM_TRAVEL_MINUTES} minutes "
        "(provisional)"
    )

    # ---------------------------------------------------------
    # 4. INVALID_GUARDIAN_CONTACT
    # Invalid contacts should be blocked by the detector.
    # ---------------------------------------------------------
    guardians["is_valid_normalized"] = (
        guardians["is_valid"].map(as_bool)
    )

    invalid_guardians = guardians[
        ~guardians["is_valid_normalized"]
    ].copy()

    invalid_guardians["decision"] = invalid_guardians[
        "is_valid"
    ].apply(
        lambda value: check_guardian_contact(
            int(as_bool(value))
        )
    )

    contact_block_failures = invalid_guardians[
        invalid_guardians["decision"] != "BLOCK"
    ]

    report(
        "Invalid guardian contacts found",
        len(invalid_guardians),
        invalid_guardians[
            ["guardian_id", "student_id", "is_valid"]
        ],
    )

    print(
        "Invalid-contact blocking verified: "
        f"{len(invalid_guardians) - len(contact_block_failures)}"
        f"/{len(invalid_guardians)}"
    )

    # ---------------------------------------------------------
    # 5. UNAUTHORIZED_ADDRESS_DISCLOSURE
    # Restricted addresses must be blocked, even when the
    # simulated requester is authorized.
    # ---------------------------------------------------------
    addresses["disclosure_authorized_bool"] = (
        addresses["disclosure_authorized"].map(as_bool)
    )

    restricted_addresses = addresses[
        ~addresses["disclosure_authorized_bool"]
    ].copy()

    restricted_addresses["decision"] = restricted_addresses[
        "disclosure_authorized"
    ].apply(
        lambda value: check_address_disclosure(
            int(as_bool(value)),
            1,
        )
    )

    disclosure_block_failures = restricted_addresses[
        restricted_addresses["decision"] != "BLOCK"
    ]

    report(
        "Addresses restricted from disclosure",
        len(restricted_addresses),
        restricted_addresses[
            [
                "address_id",
                "approval_status",
                "disclosure_authorized",
            ]
        ],
    )

    print(
        "Restricted-address blocking verified: "
        f"{len(restricted_addresses) - len(disclosure_block_failures)}"
        f"/{len(restricted_addresses)}"
    )

    # ---------------------------------------------------------
    # Summary
    # ---------------------------------------------------------
    print("\n" + "=" * 48)
    print("SUMMARY")
    print("=" * 48)

    print(f"CAPACITY_EXCEEDED: {len(capacity_issues)}")
    print(f"ACCESSIBILITY_MISMATCH: {len(accessibility_issues)}")
    print(f"IMPOSSIBLE_TRAVEL_TIME: {len(travel_issues)}")
    print(f"INVALID_GUARDIAN_CONTACT: {len(invalid_guardians)}")
    print(
        "UNAUTHORIZED_ADDRESS_DISCLOSURE: "
        f"{len(restricted_addresses)}"
    )

    print("\nRule-check failures:")
    print(f"Capacity-history coverage gaps: {len(missing_capacity)}")
    print(
        "Capacity-history overlaps: "
        f"{len(overlapping_capacity)}"
    )
    print(f"Invalid-contact blocking failures: {len(contact_block_failures)}")
    print(
        "Address-disclosure blocking failures: "
        f"{len(disclosure_block_failures)}"
    )

    if (
        missing_capacity
        or len(overlapping_capacity)
        or len(contact_block_failures)
        or len(disclosure_block_failures)
    ):
        print("\nWARNING: One or more checks need investigation.")
    else:
        print("\nPASS: Capacity coverage and safety-block checks passed.")

    print(
        "\nNote: This script detects existing matching records. "
        "It does not inject anomalies or modify CSV files. "
        "Zero detections do not prove that deliberate anomaly "
        "examples have been injected."
    )


if __name__ == "__main__":
    main()
