
import argparse
import random
from datetime import date, datetime, time, timedelta
from pathlib import Path

import pandas as pd

SEED = 20261022
DATA_DIR = Path("data/generated")
SERVICE_DATE = date(2026, 10, 29)


def load_csv(name, input_dir=DATA_DIR):
    return pd.read_csv(input_dir / f"{name}.csv", dtype=str)


def main(output_dir=DATA_DIR):
    output_names = ("route", "route_stop", "assignment")
    existing_outputs = [
        output_dir / f"{name}.csv"
        for name in output_names
        if (output_dir / f"{name}.csv").exists()
    ]
    if existing_outputs:
        raise FileExistsError(
            "Refusing to overwrite existing operational history. "
            "Choose a new output directory: "
            + ", ".join(str(path) for path in existing_outputs)
        )
    output_dir.mkdir(parents=True, exist_ok=True)

    rng = random.Random(SEED)

    students = load_csv("student")
    buses = load_csv("bus")
    drivers = load_csv("driver")
    stops = load_csv("stop")

    # Use active records only.
    students = students[students["status"] == "ACTIVE"].copy()
    buses = buses[buses["status"] == "ACTIVE"].copy()
    drivers = drivers[drivers["status"] == "ACTIVE"].copy()
    stops = stops[stops["active_status"].astype(str).isin(["1", "True", "true"])].copy()

    if students.empty or buses.empty or drivers.empty or stops.empty:
        raise ValueError("Students, buses, drivers, and stops must be active.")

    # One route per bus and driver for this service date.
    route_count = min(len(buses), len(drivers), len(stops))
    # Reserve accessible buses for routes serving students who need them.
    buses = buses.copy()
    buses["_accessible"] = (
         buses["is_accessible"]
        .astype(str)
        .str.strip()
        .str.lower()
        .isin(["1", "true"])
    )
    chosen_buses = (
          buses.sort_values("_accessible", ascending=False, kind="stable")
         .head(route_count)
         .drop(columns="_accessible")
         .reset_index(drop=True)
    )

    chosen_drivers = drivers.head(route_count).reset_index(drop=True)

    routes = []
    route_stops = []
    assignments = []

    
    # Build routes so every student zone with an available stop
    # is represented. Assign one stop per zone first, then distribute
    # remaining stops across routes.
    
    # Prioritize zones containing students who require accessibility.
    stop_groups = [[] for _ in range(route_count)]
    remaining_stops = []

    students_needing_access = students[
        students["accessibility_required"]
        .astype(str)
        .str.strip()
        .str.lower()
        .isin(["1", "true"])
    ]

    priority_zones = set(students_needing_access["zone_id"])

    student_zones = set(students["zone_id"])
    stops_by_zone = {
        zone: group
        for zone, group in stops.groupby("zone_id")
    }

    covered_zones = set()

    ordered_zones = (
        sorted(student_zones & priority_zones)
        + sorted(student_zones - priority_zones)
    )

    
    for zone in ordered_zones:
        zone_stops = stops_by_zone.get(zone)

        if zone_stops is not None and not zone_stops.empty:
            chosen_stop = zone_stops.iloc[0]
            zone_needs_access = zone in priority_zones

            if zone_needs_access:
                accessible_route_indices = [
                    idx
                    for idx, bus in enumerate(
                        chosen_buses.to_dict("records")
                    )
                    if str(bus["is_accessible"]).strip().lower()
                    in ("1", "true")
                ]

                if not accessible_route_indices:
                    raise ValueError(
                        f"No accessible bus is available for zone {zone}"
                    )

                route_index = min(
                    accessible_route_indices,
                    key=lambda idx: len(stop_groups[idx])
                )
            else:
                route_index = min(
                    range(route_count),
                    key=lambda idx: len(stop_groups[idx])
                )

            stop_groups[route_index].append(chosen_stop)
            covered_zones.add(zone)

            remaining_stops.extend(
                row for _, row in zone_stops.iloc[1:].iterrows()
            )


    for zone, zone_stops in stops_by_zone.items():
        if zone not in covered_zones:
            remaining_stops.extend(
                row for _, row in zone_stops.iterrows()
            )

    for stop in remaining_stops:
        route_index = min(
            range(route_count),
            key=lambda idx: len(stop_groups[idx])
        )
        stop_groups[route_index].append(stop)


    covered_zones = set()

    # Reserve a stop from each student zone when one exists.
    for zone in sorted(student_zones):
        zone_stops = stops_by_zone.get(zone)

        if zone_stops is not None and not zone_stops.empty:
            chosen_stop = zone_stops.iloc[0]
            route_index = len(covered_zones) % route_count
            stop_groups[route_index].append(chosen_stop)
            covered_zones.add(zone)

            remaining_stops.extend(
                row for _, row in zone_stops.iloc[1:].iterrows()
            )

    # Add stops from zones without students and extra stops.
    for zone, zone_stops in stops_by_zone.items():
        if zone not in covered_zones:
            remaining_stops.extend(
                row for _, row in zone_stops.iterrows()
            )

    # Distribute extra stops to the currently shortest route.
    for stop in remaining_stops:
        route_index = min(
            range(route_count),
            key=lambda idx: len(stop_groups[idx])
        )
        stop_groups[route_index].append(stop)


    for i in range(route_count):
        route_id = f"R-{SERVICE_DATE:%Y%m%d}-{i + 1:03d}"
        bus = chosen_buses.iloc[i]
        driver = chosen_drivers.iloc[i]

        routes.append({
            "route_id": route_id,
            "bus_id": bus["bus_id"],
            "driver_id": driver["driver_id"],
            "service_date": SERVICE_DATE.isoformat(),
            "status": "PLANNED",
        })

        route_start = datetime.combine(SERVICE_DATE, time(7, 0))
        route_stop_ids = []

        for seq, stop in enumerate(stop_groups[i], start=1):
            arrival = route_start + timedelta(minutes=(seq - 1) * 10)
            route_stops.append({
                "route_stop_id": f"RS-{i + 1:03d}-{seq:03d}",
                "route_id": route_id,
                "stop_id": stop["stop_id"],
                "sequence_no": seq,
                "arrival_time": arrival.strftime("%H:%M:%S"),
                "travel_minutes": 0 if seq == 1 else 10,
            })
            route_stop_ids.append(stop["stop_id"])

    
    # Assign students with accessibility needs first.
    # Only choose stops served by routes with suitable buses.
    route_loads = {route["route_id"]: 0 for route in routes}

    students = students.copy()
    students["_needs_access"] = students[
        "accessibility_required"
    ].astype(str).str.strip().str.lower().isin(["true", "1"])

    students = students.sort_values(
        "_needs_access", ascending=False, kind="stable"
    )

    # Index route stops by stop ID for efficient candidate lookup.
    route_stops_by_stop = {}
    for route_stop in route_stops:
        route_stops_by_stop.setdefault(
            route_stop["stop_id"], []
        ).append(route_stop)

    for _, student in students.iterrows():
        needs_access = bool(student["_needs_access"])

        matching_stops = stops[
            stops["zone_id"] == student["zone_id"]
        ]

        # Keep students within their zone; don't silently assign
        # them to a stop in a different zone.
        candidates = []

        for _, stop in matching_stops.iterrows():
            for route_stop in route_stops_by_stop.get(
                stop["stop_id"], []
            ):
                route = next(
                    r for r in routes
                    if r["route_id"] == route_stop["route_id"]
                )

                bus = buses[
                    buses["bus_id"] == route["bus_id"]
                ].iloc[0]

                is_accessible = str(
                    bus["is_accessible"]
                ).strip().lower() in ("true", "1")

                if needs_access and not is_accessible:
                    continue

                if route_loads[route["route_id"]] >= int(
                    bus["capacity"]
                ):
                    continue

                candidates.append((stop, route, bus))

        if not candidates:
            print(
                f"Unassigned: {student['student_id']} "
                f"(no suitable route in zone {student['zone_id']})"
            )
            continue

        stop, route, bus = rng.choice(candidates)

        assignments.append({
            "assignment_id": (
                f"A-{student['student_id']}-{SERVICE_DATE:%Y%m%d}"
            ),
            "student_id": student["student_id"],
            "route_id": route["route_id"],
            "stop_id": stop["stop_id"],
            "effective_from": SERVICE_DATE.isoformat(),
            "effective_to": None,
            "status": "ASSIGNED",
        })

        route_loads[route["route_id"]] += 1


    outputs = {
        "route": routes,
        "route_stop": route_stops,
        "assignment": assignments,
    }

    for name, rows in outputs.items():
        path = output_dir / f"{name}.csv"
        pd.DataFrame(rows).to_csv(path, index=False)
        print(f"Generated {len(rows):,} rows: {path}")

    print("\nOperational data generation complete.")
    print(f"Seed: {SEED}")
    print(f"Service date: {SERVICE_DATE}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DATA_DIR)
    args = parser.parse_args()
    main(output_dir=args.output)
