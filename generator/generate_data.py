
import argparse
import random
from pathlib import Path

import numpy as np
import pandas as pd

SEED = 20261022
OUTPUT_DIR = Path("data/generated")


def generate_data(
    students: int = 5000,
    buses: int = 100,
    stops: int = 300,
    seed: int = SEED,
    output_dir: Path = OUTPUT_DIR,
):
    output_names = (
        "address_zone",
        "address",
        "student",
        "guardian_contact",
        "stop",
        "bus",
        "driver",
        "bus_capacity_history",
    )
    existing_outputs = [
        output_dir / f"{name}.csv"
        for name in output_names
        if (output_dir / f"{name}.csv").exists()
    ]
    if existing_outputs:
        raise FileExistsError(
            "Refusing to overwrite existing master data. Choose a new "
            "output directory: "
            + ", ".join(str(path) for path in existing_outputs)
        )

    random.seed(seed)
    np.random.seed(seed)
    rng = np.random.default_rng(seed)
    output_dir.mkdir(parents=True, exist_ok=True)

    # 1. Address zones
    zones = pd.DataFrame({
        "zone_id": [f"ZONE-{i:03d}" for i in range(1, 21)],
        "zone_name": [f"Transport Zone {i:02d}" for i in range(1, 21)],
        "approved_status": ["APPROVED"] * 20,
    })

    # 2. Synthetic addresses
    addresses = pd.DataFrame({
        "address_id": [f"ADDR-{i:06d}" for i in range(1, students + 1)],
        "zone_id": rng.choice(zones["zone_id"], students),
        "synthetic_label": [
             f"Synthetic Residence {i:06d}"
             for i in range(1, students + 1)
        ],
        "approval_status": ["APPROVED"] * students,
        "disclosure_authorized": (
             [1] * (students // 2)
             + [0] * (students - students // 2)
        ),
        
    })
    addresses = addresses.sample(
        frac=1,
         random_state=seed
    ).reset_index(drop=True)
    

    # 3. Students
    student_ids = [f"STU-{i:06d}" for i in range(1, students + 1)]
    student_zones = addresses["zone_id"].tolist()
    accessibility = rng.choice([0, 1], size=students, p=[0.92, 0.08])

    students_df = pd.DataFrame({
        "student_id": student_ids,
        "zone_id": student_zones,
        "address_id": addresses["address_id"],
        "accessibility_required": accessibility,
        "pickup_window_start": "07:00:00",
        "pickup_window_end": "08:30:00",
        "status": ["ACTIVE"] * students,
    })

    # 4. Guardian contacts — synthetic, non-deliverable domains/numbers
    
    guardians = pd.DataFrame({
        "guardian_id": [f"GUA-{i:06d}" for i in range(1, students + 1)],
        "student_id": student_ids,
        "synthetic_phone": [
             f"000000{i:06d}" for i in range(1, students + 1)
        ],
        "synthetic_email": [
              f"guardian{i:06d}@example.invalid"
             for i in range(1, students + 1)
        ],
        "is_valid": (
             [1] * (students - max(1, students // 10))
             + [0] * max(1, students // 10)
        ),
        "consent_status": rng.choice(
             ["GRANTED", "DENIED"],
             size=students,
             p=[0.9, 0.1]
        ),
    })


    # 5. Stops
    
    # Guarantee at least one stop per zone.
    zone_ids = zones["zone_id"].tolist()

    if stops < len(zone_ids):
        raise ValueError(
            f"Cannot cover {len(zone_ids)} zones with only {stops} stops."
        )

    stop_zone_ids = zone_ids.copy()

    # Distribute extra stops deterministically.
    if stops > len(zone_ids):
        stop_zone_ids.extend(
            rng.choice(zone_ids, stops - len(zone_ids)).tolist()
        )

    rng.shuffle(stop_zone_ids)

    stops_df = pd.DataFrame({
        "stop_id": [f"STOP-{i:06d}" for i in range(1, stops + 1)],
        "zone_id": stop_zone_ids,
        "x": rng.uniform(0, 100, stops).round(3),
        "y": rng.uniform(0, 100, stops).round(3),
        "approval_status": ["APPROVED"] * stops,
        "active_status": [1] * stops,
    })


    # 6. Buses
    bus_ids = [f"BUS-{i:06d}" for i in range(1, buses + 1)]
    bus_df = pd.DataFrame({
        "bus_id": bus_ids,
        "capacity": rng.choice([30, 35, 40, 45], buses),
        "is_accessible": rng.choice([1, 0], buses, p=[0.2, 0.8]),
        "status": ["ACTIVE"] * buses,
    })

    # 7. Drivers
    drivers_df = pd.DataFrame({
        "driver_id": [f"DRV-{i:06d}" for i in range(1, buses + 1)],
        "driver_name": [f"Synthetic Driver {i:03d}" for i in range(1, buses + 1)],
        "status": ["ACTIVE"] * buses,
    })

    # 8. Initial capacity history
    capacity_history = pd.DataFrame({
        "capacity_history_id": [f"CAP-{i:06d}" for i in range(1, buses + 1)],
        "bus_id": bus_ids,
        "capacity": bus_df["capacity"],
        "effective_from": ["2026-01-01"] * buses,
        "effective_to": [None] * buses,
    })

    tables = {
        "address_zone": zones,
        "address": addresses,
        "student": students_df,
        "guardian_contact": guardians,
        "stop": stops_df,
        "bus": bus_df,
        "driver": drivers_df,
        "bus_capacity_history": capacity_history,
    }

    for name, df in tables.items():
        df.to_csv(output_dir / f"{name}.csv", index=False)

    print(f"Generated master data in: {output_dir.resolve()}")
    for name, df in tables.items():
        print(f"{name}: {len(df)} rows")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--students", type=int, default=5000)
    parser.add_argument("--buses", type=int, default=100)
    parser.add_argument("--stops", type=int, default=300)
    parser.add_argument("--seed", type=int, default=SEED)
    parser.add_argument("--output", type=Path, default=OUTPUT_DIR)
    args = parser.parse_args()

    generate_data(
        students=args.students,
        buses=args.buses,
        stops=args.stops,
        seed=args.seed,
        output_dir=args.output,
    )
