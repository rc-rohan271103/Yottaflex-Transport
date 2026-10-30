
import argparse
from pathlib import Path

import pandas as pd

DATA_DIR = Path("data/generated")


def load_csv(data_dir, name):
    path = data_dir / f"{name}.csv"

    if not path.exists():
        raise FileNotFoundError(f"Missing file: {path}")

    return pd.read_csv(path, dtype=str)


def check_primary_key(df, column, table):
    if column not in df.columns:
        raise ValueError(f"{table}: missing column {column}")

    if df[column].isna().any():
        raise ValueError(f"{table}: null primary keys")

    if df[column].duplicated().any():
        raise ValueError(f"{table}: duplicate primary keys")

    return True


def check_foreign_key(child, child_col, parent, parent_col):
    if child[child_col].isna().any():
        raise ValueError(f"{child_col}: null foreign keys")

    invalid = set(child[child_col]) - set(parent[parent_col])

    if invalid:
        raise ValueError(
            f"{child_col}: invalid references "
            f"{list(invalid)[:10]}"
        )

    return True


def validate(data_dir=DATA_DIR):
    required_columns = {
        "address_zone": {"zone_id", "zone_name", "approved_status"},
        "address": {
            "address_id",
            "zone_id",
            "synthetic_label",
            "approval_status",
            "disclosure_authorized",
        },
        "student": {
            "student_id",
            "zone_id",
            "address_id",
            "accessibility_required",
            "pickup_window_start",
            "pickup_window_end",
            "status",
        },
        "guardian_contact": {
            "guardian_id",
            "student_id",
            "synthetic_phone",
            "synthetic_email",
            "is_valid",
            "consent_status",
        },
        "stop": {
            "stop_id",
            "zone_id",
            "x",
            "y",
            "approval_status",
            "active_status",
        },
        "bus": {"bus_id", "capacity", "is_accessible", "status"},
        "driver": {"driver_id", "driver_name", "status"},
        "bus_capacity_history": {
            "capacity_history_id",
            "bus_id",
            "capacity",
            "effective_from",
            "effective_to",
        },
    }
    tables = {
        name: load_csv(data_dir, name)
        for name in [
            "address_zone",
            "address",
            "student",
            "guardian_contact",
            "stop",
            "bus",
            "driver",
            "bus_capacity_history",
        ]
    }
    for name, frame in tables.items():
        missing_columns = required_columns[name] - set(frame.columns)
        if missing_columns:
            raise ValueError(
                f"{name}: missing required columns "
                f"{sorted(missing_columns)}"
            )
        required_values = frame.drop(
            columns=["effective_to"] if name == "bus_capacity_history" else []
        )
        if required_values.isna().any().any() or required_values.astype(
            str
        ).apply(lambda column: column.str.strip().eq("")).any().any():
            raise ValueError(f"{name}: required fields contain null or empty values")

    primary_keys = {
        "address_zone": "zone_id",
        "address": "address_id",
        "student": "student_id",
        "guardian_contact": "guardian_id",
        "stop": "stop_id",
        "bus": "bus_id",
        "driver": "driver_id",
        "bus_capacity_history": "capacity_history_id",
    }

    for name, key in primary_keys.items():
        check_primary_key(tables[name], key, name)
        if tables[name][key].astype(str).str.strip().eq("").any():
            raise ValueError(f"{name}.{key}: empty primary keys")

    relationships = [
        ("address", "zone_id", "address_zone", "zone_id"),
        ("student", "zone_id", "address_zone", "zone_id"),
        ("student", "address_id", "address", "address_id"),
        ("guardian_contact", "student_id", "student", "student_id"),
        ("stop", "zone_id", "address_zone", "zone_id"),
        ("bus_capacity_history", "bus_id", "bus", "bus_id"),
    ]

    for child_name, child_col, parent_name, parent_col in relationships:
        check_foreign_key(
            tables[child_name],
            child_col,
            tables[parent_name],
            parent_col,
        )

    # Student's declared zone must match the zone of their address.
    joined = tables["student"][
        ["student_id", "zone_id", "address_id"]
    ].merge(
        tables["address"][["address_id", "zone_id"]],
        on="address_id",
        suffixes=("_student", "_address"),
        validate="many_to_one",
    )

    mismatch = (
        joined["zone_id_student"] != joined["zone_id_address"]
    )

    if mismatch.any():
        raise ValueError(
            f"{int(mismatch.sum())} students have a zone/address mismatch"
        )

    # Allowed values.
    enums = {
        ("address_zone", "approved_status"): {"APPROVED", "REVIEW"},
        ("address", "approval_status"): {"APPROVED", "UNAPPROVED"},
        ("student", "status"): {"ACTIVE", "INACTIVE"},
        ("guardian_contact", "consent_status"): {"GRANTED", "DENIED"},
        ("stop", "approval_status"): {"APPROVED", "PENDING"},
        ("bus", "status"): {"ACTIVE", "MAINTENANCE"},
        ("driver", "status"): {"ACTIVE", "UNAVAILABLE"},
    }

    for (table, column), allowed in enums.items():
        invalid = set(tables[table][column].dropna()) - allowed

        if invalid:
            raise ValueError(
                f"{table}.{column}: invalid values {invalid}"
            )

    boolean_fields = [
        ("address", "disclosure_authorized"),
        ("student", "accessibility_required"),
        ("guardian_contact", "is_valid"),
        ("stop", "active_status"),
        ("bus", "is_accessible"),
    ]
    for table, column in boolean_fields:
        normalized = tables[table][column].astype(str).str.strip().str.lower()
        invalid = set(normalized) - {"0", "1", "false", "true", "no", "yes"}
        if invalid:
            raise ValueError(f"{table}.{column}: invalid boolean values {invalid}")

    student_times = tables["student"].copy()
    student_times["pickup_window_start"] = pd.to_datetime(
        student_times["pickup_window_start"],
        format="%H:%M:%S",
        errors="raise",
    )
    student_times["pickup_window_end"] = pd.to_datetime(
        student_times["pickup_window_end"],
        format="%H:%M:%S",
        errors="raise",
    )
    if not (
        student_times["pickup_window_start"]
        < student_times["pickup_window_end"]
    ).all():
        raise ValueError("student: pickup window start must precede its end")

    coordinates = tables["stop"][["x", "y"]].apply(
        pd.to_numeric, errors="raise"
    )
    if not coordinates.apply(lambda column: column.map(pd.notna)).all().all():
        raise ValueError("stop: coordinates must be finite numeric values")
    if not coordinates.map(lambda value: abs(value) != float("inf")).all().all():
        raise ValueError("stop: coordinates must be finite numeric values")
    if not coordinates.apply(lambda column: column.between(0, 100)).all().all():
        raise ValueError("stop: synthetic x/y coordinates must be in [0, 100]")

    for table in ["bus", "bus_capacity_history"]:
        capacities = pd.to_numeric(
            tables[table]["capacity"], errors="raise"
        )

        if (capacities <= 0).any():
            raise ValueError(f"{table}: capacity must be positive")

    capacity = tables["bus_capacity_history"].copy()
    capacity["effective_from"] = pd.to_datetime(
        capacity["effective_from"], errors="raise"
    )
    capacity["effective_to"] = pd.to_datetime(
        capacity["effective_to"].replace("", pd.NA),
        errors="raise",
    )
    invalid_ranges = (
        capacity["effective_to"].notna()
        & (capacity["effective_to"] < capacity["effective_from"])
    )
    if invalid_ranges.any():
        raise ValueError("bus_capacity_history: invalid effective date range")

    overlaps = []
    for bus_id, records in capacity.sort_values(
        ["bus_id", "effective_from"]
    ).groupby("bus_id", sort=False):
        previous_end = None
        has_previous = False
        for row in records.itertuples(index=False):
            if has_previous and (
                pd.isna(previous_end) or row.effective_from <= previous_end
            ):
                overlaps.append(bus_id)
                break
            previous_end = row.effective_to
            has_previous = True
    if overlaps:
        raise ValueError(
            "bus_capacity_history: overlapping effective periods for buses "
            + ", ".join(sorted(set(overlaps))[:10])
        )

    for table, df in tables.items():
        print(f"PASS: {table}: {len(df)} rows")

    print("\nAll master-data validation checks passed.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=DATA_DIR)
    validate(parser.parse_args().input)
