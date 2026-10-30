
import json
import argparse
from pathlib import Path

import pandas as pd

SEED = 20261022
OUTPUT_DIR = Path("data/ground_truth")

CASES = [
    {
        "case_id": "GT-001",
        "anomaly_type": "CAPACITY_EXCEEDED",
        "issue_type": "CAPACITY_EXCEEDED",
        "ground_truth_label": "CAPACITY_EXCEEDED",
        "entity_type": "assignment",
        "expected_outcome": "REJECT",
        "severity": "HIGH",
        "description": (
            "A proposed assignment would make the passenger count "
            "exceed the bus capacity."
        ),
        "validation_rule": "assigned_passengers <= bus_capacity",
    },
    {
        "case_id": "GT-002",
        "anomaly_type": "ACCESSIBILITY_MISMATCH",
        "issue_type": "INCOMPATIBLE_ROUTE",
        "ground_truth_label": "ACCESSIBILITY_MISMATCH",
        "entity_type": "assignment",
        "expected_outcome": "REJECT",
        "severity": "HIGH",
        "description": (
            "A student requiring accessibility support is proposed "
            "for a bus without the required accessibility capability."
        ),
        "validation_rule": (
            "not student_needs_accessibility or bus_is_accessible"
        ),
    },
    {
        "case_id": "GT-003",
        "anomaly_type": "IMPOSSIBLE_TRAVEL_TIME",
        "issue_type": "IMPOSSIBLE_TRAVEL_TIME",
        "ground_truth_label": "IMPOSSIBLE_TRAVEL_TIME",
        "entity_type": "route_stop",
        "expected_outcome": "FLAG",
        "severity": "HIGH",
        "description": (
            "A proposed route leg has a travel-time value that violates "
            "the configured plausibility rule."
        ),
        "validation_rule": "travel_minutes >= minimum_plausible_minutes",
    },
    {
        "case_id": "GT-004",
        "anomaly_type": "INVALID_GUARDIAN_CONTACT",
        "issue_type": "INVALID_NOTIFICATION_CONTACT",
        "ground_truth_label": "INVALID_GUARDIAN_CONTACT",
        "entity_type": "notification",
        "expected_outcome": "BLOCK",
        "severity": "HIGH",
        "description": (
            "A notification to a guardian whose contact is marked invalid "
            "must not be sent."
        ),
        "validation_rule": "guardian_contact_is_valid = 1",
    },
    {
        "case_id": "GT-005",
        "anomaly_type": "UNAUTHORIZED_ADDRESS_DISCLOSURE",
        "issue_type": "UNAPPROVED_ADDRESS_EXPOSED",
        "ground_truth_label": "UNAUTHORIZED_ADDRESS_DISCLOSURE",
        "entity_type": "address",
        "expected_outcome": "BLOCK",
        "severity": "HIGH",
        "description": (
            "An address not authorized for disclosure must not be exposed "
            "to an unauthorized requester."
        ),
        "validation_rule": (
            "disclosure_authorized = 1 and requester_is_authorized = 1"
        ),
    },
]


def main(output_dir=OUTPUT_DIR):
    csv_path = output_dir / "ground_truth.csv"
    json_path = output_dir / "ground_truth.json"
    existing_outputs = [
        path for path in (csv_path, json_path) if path.exists()
    ]
    if existing_outputs:
        raise FileExistsError(
            "Refusing to overwrite existing ground-truth labels. "
            "Move or back up the existing files before regenerating: "
            + ", ".join(str(path) for path in existing_outputs)
        )

    output_dir.mkdir(parents=True, exist_ok=True)

    df = pd.DataFrame(CASES)

    if df["case_id"].duplicated().any():
        raise ValueError("Ground-truth case IDs must be unique.")

    if df["anomaly_type"].duplicated().any():
        raise ValueError("Expected one ground-truth case per anomaly type.")

    df.to_csv(csv_path, index=False)
    json_path.write_text(
        json.dumps(
            {
                "seed": SEED,
                "case_count": len(CASES),
                "cases": CASES,
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    print(f"Ground-truth cases generated: {len(df)}")
    print(f"CSV: {csv_path}")
    print(f"JSON: {json_path}")
    print("Seed:", SEED)
    print("\nCases by anomaly type:")
    print(df["anomaly_type"].to_string(index=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=OUTPUT_DIR)
    args = parser.parse_args()
    main(output_dir=args.output)
