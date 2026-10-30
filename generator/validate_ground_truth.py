import argparse
import json
from pathlib import Path

import pandas as pd

from generator.validate_full_scale_anomalies_output import (
    main as validate_proposals,
)

DEFINITIONS_DIR = Path("data/ground_truth")
PROPOSALS_DIR = Path("data/full_scale/anomalies")
MASTER_DIR = Path("data/full_scale")
OPERATIONS_DIR = MASTER_DIR / "operations"

EXPECTED_TYPES = {
    "CAPACITY_EXCEEDED",
    "ACCESSIBILITY_MISMATCH",
    "IMPOSSIBLE_TRAVEL_TIME",
    "INVALID_GUARDIAN_CONTACT",
    "UNAUTHORIZED_ADDRESS_DISCLOSURE",
}


def main(
    definitions_dir=DEFINITIONS_DIR,
    proposals_dir=PROPOSALS_DIR,
    master_dir=MASTER_DIR,
    operations_dir=OPERATIONS_DIR,
):
    csv_path = definitions_dir / "ground_truth.csv"
    json_path = definitions_dir / "ground_truth.json"
    if not csv_path.exists():
        raise FileNotFoundError(f"Ground-truth CSV not found: {csv_path}")
    if not json_path.exists():
        raise FileNotFoundError(f"Ground-truth JSON not found: {json_path}")

    definitions = pd.read_csv(csv_path, dtype=str).fillna("")
    document = json.loads(json_path.read_text(encoding="utf-8"))
    if not isinstance(document, dict) or not isinstance(
        document.get("cases"), list
    ):
        raise ValueError("Ground-truth JSON must contain a cases array.")
    cases = document["cases"]
    if document.get("case_count") != len(cases):
        raise ValueError("Ground-truth JSON case_count does not match cases.")

    case_ids = definitions["case_id"].tolist()
    if len(case_ids) != len(set(case_ids)):
        raise ValueError("Ground-truth case IDs must be unique.")
    if set(definitions["anomaly_type"]) != EXPECTED_TYPES:
        raise ValueError("Ground-truth CSV must contain exactly the five expected anomaly types.")
    if definitions["anomaly_type"].duplicated().any():
        raise ValueError("Each ground-truth anomaly type must occur once.")
    if len(cases) != len(definitions):
        raise ValueError("Ground-truth CSV and JSON row counts differ.")

    json_by_id = {case.get("case_id"): case for case in cases}
    if len(json_by_id) != len(cases) or set(json_by_id) != set(case_ids):
        raise ValueError("Ground-truth CSV and JSON case IDs differ or repeat.")

    for row in definitions.to_dict("records"):
        json_case = json_by_id[row["case_id"]]
        for column, value in row.items():
            if str(json_case.get(column, "")) != value:
                raise ValueError(
                    f"Ground-truth CSV/JSON mismatch for "
                    f"{row['case_id']}.{column}."
                )
        if row.get("ground_truth_label") and (
            row["ground_truth_label"] != row["anomaly_type"]
        ):
            raise ValueError(
                f"Ground-truth label mismatch for {row['case_id']}."
            )

    print(f"PASS: {len(definitions)} ground-truth definitions are unique.")
    print("PASS: Ground-truth CSV and JSON contain matching definitions.")
    print("PASS: All expected anomaly classes have documented outcomes.")

    validate_proposals(
        output_dir=proposals_dir,
        master_dir=master_dir,
        operations_dir=operations_dir,
        definitions_dir=definitions_dir,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--definitions", type=Path, default=DEFINITIONS_DIR)
    parser.add_argument("--proposals", type=Path, default=PROPOSALS_DIR)
    parser.add_argument("--master", type=Path, default=MASTER_DIR)
    parser.add_argument("--operations", type=Path, default=OPERATIONS_DIR)
    args = parser.parse_args()
    main(
        definitions_dir=args.definitions,
        proposals_dir=args.proposals,
        master_dir=args.master,
        operations_dir=args.operations,
    )
