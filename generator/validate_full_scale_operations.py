
import argparse
from datetime import date
from pathlib import Path
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
MASTER = PROJECT_ROOT / "data" / "full_scale"
parser = argparse.ArgumentParser()
parser.add_argument("--operations", type=Path, default=MASTER / "operations")
parser.add_argument("--master", type=Path, default=MASTER)
parser.add_argument("--days", type=int, default=200)
parser.add_argument("--students", type=int, default=5000)
args = parser.parse_args()
OPS = args.operations
MASTER_DIR = args.master

def load(folder, name):
    path = folder / f"{name}.csv"
    if not path.exists():
        raise FileNotFoundError(path)
    return pd.read_csv(path, dtype=str).fillna("")


def check(condition, message):
    if not condition:
        raise AssertionError(f"FAIL: {message}")
    print(f"PASS: {message}")

route = load(OPS, "route")
route_stop = load(OPS, "route_stop")
assignment = load(OPS, "assignment")
attendance = load(OPS, "attendance_event")
notification = load(OPS, "notification")
capacity = load(OPS, "bus_capacity_history")
disruption = load(OPS, "route_disruption")

students = load(MASTER_DIR, "student")
buses = load(MASTER_DIR, "bus")
stops = load(MASTER_DIR, "stop")
drivers = load(MASTER_DIR, "driver")
guardians = load(MASTER_DIR, "guardian_contact")
zones = load(MASTER_DIR, "address_zone")
addresses = load(MASTER_DIR, "address")

# Every master and operational primary key must be present and unique.
primary_keys = [
    ("address_zone", zones, "zone_id"),
    ("address", addresses, "address_id"),
    ("student", students, "student_id"),
    ("guardian_contact", guardians, "guardian_id"),
    ("stop", stops, "stop_id"),
    ("bus", buses, "bus_id"),
    ("driver", drivers, "driver_id"),
    ("route", route, "route_id"),
    ("route_stop", route_stop, "route_stop_id"),
    ("assignment", assignment, "assignment_id"),
    ("attendance_event", attendance, "event_id"),
    ("notification", notification, "notification_id"),
    ("bus_capacity_history", capacity, "capacity_history_id"),
    ("route_disruption", disruption, "disruption_id"),
]
tables = {
    "address_zone": zones,
    "address": addresses,
    "student": students,
    "guardian_contact": guardians,
    "stop": stops,
    "bus": buses,
    "driver": drivers,
    "bus_capacity_history": capacity,
    "route": route,
    "route_stop": route_stop,
    "assignment": assignment,
    "attendance_event": attendance,
    "notification": notification,
    "route_disruption": disruption,
}
required_columns = {
    "address_zone": {"zone_id", "zone_name", "approved_status"},
    "address": {
        "address_id", "zone_id", "synthetic_label", "approval_status",
        "disclosure_authorized",
    },
    "student": {
        "student_id", "zone_id", "address_id", "accessibility_required",
        "pickup_window_start", "pickup_window_end", "status",
    },
    "guardian_contact": {
        "guardian_id", "student_id", "synthetic_phone", "synthetic_email",
        "is_valid", "consent_status",
    },
    "stop": {"stop_id", "zone_id", "x", "y", "approval_status", "active_status"},
    "bus": {"bus_id", "capacity", "is_accessible", "status"},
    "driver": {"driver_id", "driver_name", "status"},
    "bus_capacity_history": {
        "capacity_history_id", "bus_id", "capacity", "effective_from",
        "effective_to",
    },
    "route": {"route_id", "bus_id", "driver_id", "service_date", "status"},
    "route_stop": {
        "route_stop_id", "route_id", "stop_id", "sequence_no",
        "arrival_time", "travel_minutes",
    },
    "assignment": {
        "assignment_id", "student_id", "route_id", "stop_id",
        "effective_from", "effective_to", "status",
    },
    "attendance_event": {
        "event_id", "student_id", "route_id", "event_type", "event_time",
        "reason",
    },
    "notification": {
        "notification_id", "guardian_id", "student_id", "event_id",
        "status", "reason", "created_at",
    },
    "route_disruption": {
        "disruption_id", "route_id", "service_date", "disruption_type",
        "severity", "status",
    },
}
for table_name, frame in tables.items():
    missing_columns = required_columns[table_name] - set(frame.columns)
    check(
        not missing_columns,
        f"{table_name} includes all required fields",
    )
    if missing_columns:
        raise ValueError(
            f"{table_name} is missing required columns: "
            f"{sorted(missing_columns)}"
        )
    optional_blank_columns = (
        {"effective_to"} if table_name in {
            "assignment", "bus_capacity_history"
        } else set()
    )
    required_values = frame.drop(
        columns=list(optional_blank_columns), errors="ignore"
    )
    check(
        not required_values.isna().any().any()
        and not required_values.apply(
            lambda column: column.astype(str).str.strip().eq("")
        ).any().any(),
        f"{table_name} required values are populated",
    )

allowed_states = [
    ("address_zone", zones, "approved_status", {"APPROVED", "REVIEW"}),
    (
        "address",
        addresses,
        "approval_status",
        {"APPROVED", "UNAPPROVED"},
    ),
    ("student", students, "status", {"ACTIVE", "INACTIVE"}),
    ("guardian_contact", guardians, "consent_status", {"GRANTED", "DENIED"}),
    ("stop", stops, "approval_status", {"APPROVED", "PENDING"}),
    ("bus", buses, "status", {"ACTIVE", "MAINTENANCE"}),
    ("driver", drivers, "status", {"ACTIVE", "UNAVAILABLE"}),
    (
        "route",
        route,
        "status",
        {"PLANNED", "ACTIVE", "DISRUPTED", "COMPLETED", "CANCELLED"},
    ),
    (
        "assignment",
        assignment,
        "status",
        {"ASSIGNED", "REJECTED", "ENDED", "NEEDS_REVIEW"},
    ),
    (
        "attendance_event",
        attendance,
        "event_type",
        {
            "PRESENT",
            "ABSENT",
            "BOARDED",
            "MISSED_PICKUP",
            "DISRUPTION_REASSIGNED",
        },
    ),
    (
        "notification",
        notification,
        "status",
        {
            "SIMULATED_SENT",
            "BLOCKED_INVALID_CONTACT",
            "BLOCKED_CONSENT",
            "BLOCKED_AUTHORIZATION",
        },
    ),
    (
        "route_disruption",
        disruption,
        "severity",
        {"LOW", "MEDIUM", "HIGH"},
    ),
    (
        "route_disruption",
        disruption,
        "status",
        {"RECORDED", "RESOLVED", "ESCALATED"},
    ),
]
for table_name, frame, column, allowed in allowed_states:
    check(
        frame[column].isin(allowed).all(),
        f"{table_name}.{column} uses documented lifecycle values",
    )

boolean_fields = [
    ("address", addresses, "disclosure_authorized"),
    ("student", students, "accessibility_required"),
    ("guardian_contact", guardians, "is_valid"),
    ("stop", stops, "active_status"),
    ("bus", buses, "is_accessible"),
]
for table_name, frame, column in boolean_fields:
    normalized = frame[column].astype(str).str.strip().str.lower()
    check(
        normalized.isin({"0", "1", "false", "true", "no", "yes"}).all(),
        f"{table_name}.{column} contains boolean values",
    )

for name, frame, key in primary_keys:
    check(
        frame[key].ne("").all() and frame[key].is_unique,
        f"{name}.{key} is present and unique",
    )

foreign_keys = [
    ("address", "zone_id", "address_zone", "zone_id"),
    ("student", "zone_id", "address_zone", "zone_id"),
    ("student", "address_id", "address", "address_id"),
    ("guardian_contact", "student_id", "student", "student_id"),
    ("stop", "zone_id", "address_zone", "zone_id"),
    ("bus_capacity_history", "bus_id", "bus", "bus_id"),
    ("route", "bus_id", "bus", "bus_id"),
    ("route", "driver_id", "driver", "driver_id"),
    ("route_stop", "route_id", "route", "route_id"),
    ("route_stop", "stop_id", "stop", "stop_id"),
    ("assignment", "student_id", "student", "student_id"),
    ("assignment", "route_id", "route", "route_id"),
    ("assignment", "stop_id", "stop", "stop_id"),
    ("attendance_event", "student_id", "student", "student_id"),
    ("attendance_event", "route_id", "route", "route_id"),
    ("notification", "guardian_id", "guardian_contact", "guardian_id"),
    ("notification", "student_id", "student", "student_id"),
    ("notification", "event_id", "attendance_event", "event_id"),
    ("route_disruption", "route_id", "route", "route_id"),
]
for child_name, child_col, parent_name, parent_col in foreign_keys:
    child = tables[child_name][child_col]
    parent_ids = set(tables[parent_name][parent_col])
    check(
        child.ne("").all() and child.isin(parent_ids).all(),
        f"{child_name}.{child_col} references {parent_name}.{parent_col}",
    )

student_address = students[
    ["student_id", "zone_id", "address_id"]
].merge(
    addresses[["address_id", "zone_id"]],
    on="address_id",
    how="left",
    validate="many_to_one",
    suffixes=("_student", "_address"),
)
check(
    student_address["zone_id_student"].eq(
        student_address["zone_id_address"]
    ).all(),
    "Each student's zone matches their referenced address zone",
)

disruption_routes = disruption.merge(
    route[["route_id", "service_date", "status"]],
    on="route_id",
    how="left",
    validate="many_to_one",
    suffixes=("", "_route"),
)
check(
    (
        disruption_routes["service_date"]
        == disruption_routes["service_date_route"]
    ).all(),
    "Disruption dates match their route service dates",
)
check(notification["event_id"].isin(attendance["event_id"]).all(),
      "Every notification references an attendance event")
check(notification["guardian_id"].isin(guardians["guardian_id"]).all(),
      "Every notification references a guardian")
check(notification["event_id"].is_unique,
      "Each attendance event has at most one notification decision")
check(disruption["route_id"].is_unique,
      "A route has at most one disruption record per service date")

approved_zone_ids = set(
    zones.loc[zones["approved_status"] == "APPROVED", "zone_id"]
)
approved_active_stop_ids = set(
    stops.loc[
        stops["approval_status"].eq("APPROVED")
        & stops["active_status"].str.lower().isin(["1", "true", "yes"])
        & stops["zone_id"].isin(approved_zone_ids),
        "stop_id",
    ]
)
check(
    route_stop["stop_id"].isin(approved_active_stop_ids).all(),
    "Routes use only approved active stops in approved zones",
)
check(
    not route.duplicated(["bus_id", "service_date"]).any(),
    "A bus has at most one route per service date",
)
check(
    not route.duplicated(["driver_id", "service_date"]).any(),
    "A driver has at most one route per service date",
)
check(
    not route_stop.duplicated(["route_id", "stop_id"]).any(),
    "A route-stop bridge pair is unique",
)
check(
    not route_stop.duplicated(["route_id", "sequence_no"]).any(),
    "Route stop sequence numbers are unique within each route",
)
route_stop["sequence_number"] = pd.to_numeric(
    route_stop["sequence_no"], errors="raise"
)
route_stop["travel_duration"] = pd.to_numeric(
    route_stop["travel_minutes"], errors="raise"
)
valid_sequence = True
for _, route_schedule in route_stop.groupby("route_id", sort=False):
    sequence_numbers = sorted(
        route_schedule["sequence_number"].astype(int).tolist()
    )
    if sequence_numbers != list(range(1, len(sequence_numbers) + 1)):
        valid_sequence = False
        break
check(
    valid_sequence and route_stop["sequence_number"].gt(0).all(),
    "Route stop sequences are positive and contiguous",
)
check(
    route_stop["travel_duration"].ge(0).all()
    and route_stop["travel_duration"].mod(1).eq(0).all(),
    "Route travel durations are non-negative whole minutes",
)
high_active_disruptions = set(
    disruption.loc[
        disruption["severity"].eq("HIGH")
        & disruption["status"].ne("RESOLVED"),
        "route_id",
    ]
)
disrupted_routes = set(
    route.loc[route["status"] == "DISRUPTED", "route_id"]
)
disruption_transition_graph = {
    "RECORDED": {"RECORDED", "ESCALATED", "RESOLVED"},
    "ESCALATED": {"ESCALATED", "RESOLVED"},
    "RESOLVED": {"RESOLVED"},
}
reachable_disruption_states = {"RECORDED"}
frontier = ["RECORDED"]
while frontier:
    prior_state = frontier.pop()
    for next_state in disruption_transition_graph[prior_state]:
        if next_state not in reachable_disruption_states:
            reachable_disruption_states.add(next_state)
            frontier.append(next_state)
check(
    disruption["status"].isin(reachable_disruption_states).all(),
    "Disruption lifecycle states are reachable through allowed transitions",
)
check(
    disrupted_routes == high_active_disruptions,
    "High unresolved disruptions derive the disrupted route status",
)
expected_disrupted = disruption.loc[
    disruption["severity"].eq("HIGH")
    & disruption["status"].isin({"RECORDED", "ESCALATED"}),
    "route_id",
]
check(
    set(expected_disrupted) == disrupted_routes,
    "Unresolved high-severity state derives route unavailability",
)
check(
    not assignment["route_id"].isin(disrupted_routes).any(),
    "Students are not assigned to unavailable disrupted routes",
)

# Every assignment's stop must actually be served by its route.
served_pairs = set(zip(route_stop["route_id"], route_stop["stop_id"]))
assignment_pairs = set(zip(assignment["route_id"], assignment["stop_id"]))
check(assignment_pairs.issubset(served_pairs),
      "Every assigned stop is served by the assigned route")

# Planned arrivals derive from the previous stop and disruption-adjusted travel.
route_stop = route_stop.sort_values(
    ["route_id", "sequence_no"],
    key=lambda column: pd.to_numeric(column, errors="raise")
    if column.name == "sequence_no"
    else column,
)
arrival_values = pd.to_datetime(
    route_stop["arrival_time"],
    format="%H:%M:%S",
)
route_stop["arrival_minute"] = (
    arrival_values.dt.hour * 60 + arrival_values.dt.minute
)
disruption_by_route = {
    row["route_id"]: row
    for row in disruption.to_dict("records")
}
valid_route_timing = True
for _, route_schedule in route_stop.groupby("route_id", sort=False):
    route_id = route_schedule.iloc[0]["route_id"]
    route_disruption = disruption_by_route.get(route_id)
    delay_minutes = 0
    if route_disruption and route_disruption["status"] != "RESOLVED":
        delay_minutes = (
            5 if route_disruption["severity"] == "LOW" else 10
        )
    previous_arrival = None
    for row in route_schedule.itertuples():
        travel_minutes = int(row.travel_minutes)
        expected_travel = (
            0 if previous_arrival is None else 10 + delay_minutes
        )
        expected_arrival = (
            7 * 60 + delay_minutes
            if previous_arrival is None
            else previous_arrival + expected_travel
        )
        if (
            travel_minutes != expected_travel
            or int(row.arrival_minute) != expected_arrival
        ):
            valid_route_timing = False
            break
        previous_arrival = int(row.arrival_minute)
    if not valid_route_timing:
        break
check(valid_route_timing,
      "Stop arrivals derive from travel duration and disruption delay")
# Operational dates and expected scale.
route["service_date"] = pd.to_datetime(
    route["service_date"], format="%Y-%m-%d", errors="raise"
).dt.strftime("%Y-%m-%d")
service_dates = sorted(route["service_date"].unique())
check(
    route["service_date"].drop_duplicates().tolist() == service_dates
    and all(
        date.fromisoformat(service_date).weekday() < 5
        for service_date in service_dates
    ),
    "Service dates are valid weekdays in chronological order",
)
check(route["service_date"].nunique() == args.days,
      f"Exactly {args.days} service dates exist")
check(route["route_id"].nunique() == len(route),
      "Route IDs are unique across service days")
check(len(students) == 5000, "Master data contains 5,000 students")
check(len(buses) == 100, "Master data contains 100 buses")
check(len(stops) == 300, "Master data contains 300 stops")

# Capacity history must have positive capacities and valid date ranges.
capacity["capacity"] = pd.to_numeric(capacity["capacity"], errors="raise")
check((capacity["capacity"] > 0).all()
      and (capacity["capacity"] % 1 == 0).all(),
      "All historical capacities are positive")
capacity["effective_from_date"] = pd.to_datetime(
    capacity["effective_from"], errors="raise"
)
capacity["effective_to_date"] = pd.to_datetime(
    capacity["effective_to"].replace("", pd.NA),
    errors="raise",
)
valid_capacity_ranges = (
    capacity["effective_to_date"].isna()
    | (
        capacity["effective_to_date"]
        >= capacity["effective_from_date"]
    )
)
check(
    valid_capacity_ranges.all(),
    "Capacity-history effective date ranges are valid",
)
capacity_ranges_nonoverlapping = True
for bus_id, records in capacity.sort_values(
    ["bus_id", "effective_from_date"]
).groupby("bus_id", sort=False):
    previous_end = None
    has_previous_record = False
    for row in records.itertuples():
        if has_previous_record and (
            pd.isna(previous_end)
            or row.effective_from_date <= previous_end
        ):
            capacity_ranges_nonoverlapping = False
            break
        previous_end = row.effective_to_date
        has_previous_record = True
    if not capacity_ranges_nonoverlapping:
        break
check(
    capacity_ranges_nonoverlapping,
    "Bus capacity-history intervals do not overlap",
)
initial_capacity = capacity.sort_values(
    ["bus_id", "effective_from_date"]
).drop_duplicates("bus_id", keep="first").merge(
    buses[["bus_id", "capacity"]],
    on="bus_id",
    how="left",
    validate="one_to_one",
    suffixes=("_history", "_master"),
)
check(
    pd.to_numeric(initial_capacity["capacity_history"], errors="raise").eq(
        pd.to_numeric(initial_capacity["capacity_master"], errors="raise")
    ).all(),
    "Initial capacity-history values reconcile to bus master capacities",
)

assignment_dates = assignment.merge(
    route[["route_id", "service_date"]],
    on="route_id",
    how="left",
    validate="many_to_one",
)
assignment_dates["effective_from"] = pd.to_datetime(
    assignment_dates["effective_from"], format="%Y-%m-%d", errors="raise"
).dt.strftime("%Y-%m-%d")
assignment_dates["effective_to"] = assignment_dates["effective_to"].replace(
    "", pd.NA
)
assignment_dates["effective_to_date"] = pd.to_datetime(
    assignment_dates["effective_to"], format="%Y-%m-%d", errors="raise"
)
check(
    (assignment_dates["effective_from"] == assignment_dates["service_date"]).all(),
    "Assignment start dates match route service dates",
)
check(
    (
        assignment_dates["effective_to_date"].isna()
        | (
            assignment_dates["effective_to_date"]
            >= pd.to_datetime(assignment_dates["effective_from"])
        )
    ).all(),
    "Assignment effective end dates are not before their starts",
)
check(
    (
        assignment_dates["effective_to_date"].isna()
        | (
            assignment_dates["effective_to_date"]
            >= pd.to_datetime(assignment_dates["service_date"])
        )
    ).all(),
    "Assignment validity ranges include their service dates",
)
check(
    not assignment_dates.duplicated(["student_id", "service_date"]).any(),
    "A student has at most one assignment per service date",
)
check(
    assignment["status"].eq("ASSIGNED").all(),
    "Operational assignment rows contain accepted assignments only",
)
assignment_rules = assignment.merge(
    route[["route_id", "service_date", "bus_id"]],
    on="route_id",
    how="left",
    validate="many_to_one",
).merge(
    route_stop[["route_id", "stop_id", "arrival_time"]],
    on=["route_id", "stop_id"],
    how="left",
    validate="many_to_one",
).merge(
    students[
        [
            "student_id",
            "zone_id",
            "accessibility_required",
            "pickup_window_start",
            "pickup_window_end",
        ]
    ],
    on="student_id",
    how="left",
    validate="many_to_one",
).merge(
    stops[["stop_id", "zone_id"]].rename(
        columns={"zone_id": "stop_zone_id"}
    ),
    on="stop_id",
    how="left",
    validate="many_to_one",
).merge(
    buses[["bus_id", "is_accessible"]],
    on="bus_id",
    how="left",
    validate="many_to_one",
)
check(
    (assignment_rules["zone_id"] == assignment_rules["stop_zone_id"]).all(),
    "Assignments use a stop in the student's zone",
)
check(
    (
        (assignment_rules["arrival_time"] >= assignment_rules["pickup_window_start"])
        & (assignment_rules["arrival_time"] <= assignment_rules["pickup_window_end"])
    ).all(),
    "Assignments satisfy student pickup windows",
)
needs_accessible = assignment_rules["accessibility_required"].map(
    lambda value: str(value).strip().lower() in {"1", "true", "yes"}
)
has_accessible_bus = assignment_rules["is_accessible"].map(
    lambda value: str(value).strip().lower() in {"1", "true", "yes"}
)
check(
    (~needs_accessible | has_accessible_bus).all(),
    "Assignments meet student accessibility requirements",
)

route_capacity = route.merge(capacity, on="bus_id", how="left")
effective_route_capacity = route_capacity[
    (route_capacity["effective_from"] <= route_capacity["service_date"])
    & (
        (route_capacity["effective_to"] == "")
        | (route_capacity["effective_to"] >= route_capacity["service_date"])
    )
]
effective_counts = effective_route_capacity.groupby("route_id").size()
check(
    effective_counts.reindex(route["route_id"], fill_value=0).eq(1).all(),
    "Every route has exactly one effective capacity source record",
)
capacity_by_route = effective_route_capacity.drop_duplicates(
    "route_id"
).set_index("route_id")["capacity"]
passengers_by_route = assignment.groupby("route_id").size()
route_loads = passengers_by_route.reindex(route["route_id"], fill_value=0)
route_capacities = route["route_id"].map(capacity_by_route)
check(
    (route_loads.to_numpy() <= route_capacities.to_numpy()).all(),
    "Derived route loads do not exceed effective bus capacities",
)

attendance_dates = attendance.merge(
    route[["route_id", "service_date"]],
    on="route_id",
    how="left",
    validate="many_to_one",
)
attendance_dates["event_datetime"] = pd.to_datetime(
    attendance_dates["event_time"],
    format="%Y-%m-%d %H:%M:%S",
    errors="raise",
)
attendance_dates["event_date"] = attendance_dates["event_time"].str[:10]
check(
    (attendance_dates["event_date"] == attendance_dates["service_date"]).all(),
    "Attendance event dates match their route service dates",
)
service_day_indices = {
    service_date: index
    for index, service_date in enumerate(
        sorted(route["service_date"].unique())
    )
}
attendance_sources = attendance_dates.merge(
    students[["student_id"]],
    on="student_id",
    how="left",
    validate="many_to_one",
)

def student_sequence(student_id):
    suffix = str(student_id).rsplit("-", 1)[-1]
    if not suffix.isdigit():
        raise ValueError(
            f"Student ID must end with a numeric sequence: {student_id!r}."
        )
    return int(suffix)


expected_attendance = []
for row in attendance_sources.itertuples():
    day_index = service_day_indices[row.service_date]
    bucket = (student_sequence(row.student_id) + day_index * 37) % 100
    if bucket < 2:
        expected_attendance.append("MISSED_PICKUP")
    elif bucket < 10:
        expected_attendance.append("ABSENT")
    elif bucket < 25:
        expected_attendance.append("BOARDED")
    else:
        expected_attendance.append("PRESENT")
check(
    (attendance_sources["event_type"] == expected_attendance).all(),
    "Attendance outcomes derive from the documented student/day rule",
)
assignment_event_keys = assignment_dates[
    ["student_id", "route_id", "service_date"]
]
attendance_event_keys = attendance_dates[
    ["student_id", "route_id", "service_date"]
]
assignment_attendance_match = assignment_event_keys.merge(
    attendance_event_keys,
    on=["student_id", "route_id", "service_date"],
    how="outer",
    indicator=True,
)
check(
    assignment_attendance_match["_merge"].eq("both").all(),
    "Attendance events match their assigned student, route, and date",
)
check(
    not attendance_dates.duplicated(
        ["student_id", "route_id", "service_date"]
    ).any(),
    "A student has at most one attendance event per route service date",
)
attendance_schedule = attendance_dates.merge(
    assignment_dates[
        ["student_id", "route_id", "service_date", "stop_id"]
    ],
    on=["student_id", "route_id", "service_date"],
    how="left",
    validate="one_to_one",
    indicator=True,
).merge(
    route_stop[["route_id", "stop_id", "arrival_time"]],
    on=["route_id", "stop_id"],
    how="left",
    validate="many_to_one",
)
check(
    attendance_schedule["_merge"].eq("both").all(),
    "Every attendance event joins to its assigned route stop",
)
check(
    (
        attendance_schedule["event_time"].str[11:19]
        == attendance_schedule["arrival_time"]
    ).all(),
    "Attendance timestamps match assigned stop arrivals",
)
check(
    len(attendance) == len(assignment),
    "One attendance event is generated for each assignment",
)
check(
    len(notification) == len(attendance),
    "One notification decision is generated for each attendance event",
)

notification_sources = notification.merge(
    guardians[["guardian_id", "student_id", "is_valid", "consent_status"]],
    on="guardian_id",
    how="left",
    validate="many_to_one",
    suffixes=("", "_guardian"),
)
notification_sources = notification_sources.merge(
    attendance_dates[
        ["event_id", "student_id", "event_time", "service_date"]
    ],
    on="event_id",
    how="left",
    validate="many_to_one",
    suffixes=("", "_event"),
)
check(
    (
        (notification_sources["student_id"] == notification_sources["student_id_guardian"])
        & (notification_sources["student_id"] == notification_sources["student_id_event"])
    ).all(),
    "Notification guardian and attendance event belong to the same student",
)
notification_sources["is_valid"] = notification_sources["is_valid"].map(
    lambda value: str(value).strip().lower() in {"1", "true", "yes"}
)
notification_sources["consent_status"] = (
    notification_sources["consent_status"].str.upper()
)
authorization_values = []
expected_notification_status = []
for row in notification_sources.itertuples():
    authorized = (
        student_sequence(row.student_id)
        + date.fromisoformat(row.service_date).toordinal()
    ) % 100 != 0
    authorization_values.append(authorized)
    if not row.is_valid:
        expected_notification_status.append("BLOCKED_INVALID_CONTACT")
    elif row.consent_status != "GRANTED":
        expected_notification_status.append("BLOCKED_CONSENT")
    elif not authorized:
        expected_notification_status.append("BLOCKED_AUTHORIZATION")
    else:
        expected_notification_status.append("SIMULATED_SENT")
notification_sources["requester_authorized"] = authorization_values
check(
    (notification_sources["status"] == expected_notification_status).all(),
    "Notification status derives from contact, consent, and authorization rules",
)
expected_notification_reason = {
    "BLOCKED_INVALID_CONTACT": "Guardian contact is marked invalid",
    "BLOCKED_CONSENT": "Guardian consent is not granted",
    "BLOCKED_AUTHORIZATION": "Requester is not authorized",
    "SIMULATED_SENT": "Checks passed; no real message was sent",
}
check(
    (
        notification_sources["reason"]
        == notification_sources["status"].map(expected_notification_reason)
    ).all(),
    "Notification decision reasons match their derived statuses",
)
check(
    (
        notification_sources["created_at"]
        == notification_sources["event_time"]
    ).all(),
    "Notification timestamps derive from attendance event timestamps",
)
notification_sources["created_at_datetime"] = pd.to_datetime(
    notification_sources["created_at"],
    format="%Y-%m-%d %H:%M:%S",
    errors="raise",
)
check(
    notification_sources["created_at_datetime"].notna().all(),
    "Notification timestamps use valid ordered datetime values",
)

print("\nRow counts:")
for name, df in [
    ("route", route),
    ("route_stop", route_stop),
    ("assignment", assignment),
    ("attendance_event", attendance),
    ("notification", notification),
    ("bus_capacity_history", capacity),
    ("route_disruption", disruption),
]:
    print(f"{name}: {len(df):,}")

active_student_count = int((students["status"] == "ACTIVE").sum())
assignment_attempts = (
    min(active_student_count, args.students)
    * route["service_date"].nunique()
)
assignment_count = len(assignment)
available_route_mask = route["status"] != "DISRUPTED"
seat_count = int(route_capacities[available_route_mask].sum())
attendance_count = len(attendance)
missed_pickups = int((attendance["event_type"] == "MISSED_PICKUP").sum())
print("\nDerived evaluation metrics:")
print(f"Assignment attempts: {assignment_attempts:,}")
print(f"Assignments accepted: {assignment_count:,}")
print(
    "Unassigned/rejected rate: "
    f"{(assignment_attempts - assignment_count) / assignment_attempts:.2%}"
)
print(f"Effective seat capacity: {seat_count:,}")
print(f"Remaining capacity: {seat_count - assignment_count:,}")
seat_utilization = assignment_count / seat_count if seat_count else 0
print(f"Seat utilization: {seat_utilization:.2%}")
print(
    "Missed-pickup rate: "
    f"{missed_pickups / attendance_count if attendance_count else 0:.2%}"
)

print("\nFull-scale validation checks completed.")
