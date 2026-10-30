# Yottaflex.ai Technologies --- School Transportation Assignment System

## Project overview

Yottaflex is a school transportation assignment project built with
Python, FastAPI, and MySQL. It models student registration, bus routes
and stops, assignment capacity, accessibility requirements, attendance
events, notification readiness, address-disclosure checks, and anomaly
detection.

The project uses synthetic data for development and testing. The
repository includes application code, data-generation and validation
scripts, SQL schema files, generated CSV/JSON artifacts, and supporting
documentation.

## Main capabilities

-   Generate synthetic master and operational school-transport data.
-   Store transport entities and relationships in MySQL.
-   Register a student and guardian contact in a combined workflow.
-   Assign an eligible student to a suitable route and stop using
    capacity, accessibility, zone, pickup-window, and service-date
    checks.
-   Check notification readiness using guardian validity, consent, and
    authorization checks. The demo simulates notifications; it does not
    send real messages.
-   Generate one simulated notification decision for each generated
    assignment/attendance event in the full-scale operational dataset.
-   Check address disclosure authorization without returning restricted
    address details.
-   Apply anomaly rules for capacity violations, accessibility
    mismatches, implausible travel times, invalid guardian contacts, and
    unauthorized address disclosure.
-   Validate generated data and record SHA-256 checksums for selected
    artifacts.

## Repository layout

``` text
Yottaflex/
├── app/                    # FastAPI application, database access, services, anomaly rules
├── generator/              # Synthetic-data generators and validation scripts
├── sql/                    # Database schema and SQL scripts
├── data/
│   ├── generated/          # Small operational/demo datasets
│   ├── full_scale/         # Full-scale synthetic master and operational datasets
│   └── ground_truth/       # Ground-truth anomaly labels, where generated
├── docs/                   # Project notes and validation documentation, if present
├── submission/             # Contribution and prompt-history documents, if present
├── .env                    # Local database settings; do not commit
├── .gitignore
└── README.md
```

Some folders or files may be created by running the project scripts.
Keep the actual repository contents aligned with this overview.

## Requirements

-   Python 3.12
-   MySQL Server and a MySQL database user
-   MySQL Workbench is optional but useful for running SQL checks
-   VS Code is optional

Install the Python packages listed in `requirements.txt` if that file is
present in the repository.

## Setup

### 1. Open the project

Open the project root (`F:\Yottaflex` on the development machine) in VS
Code, then open a terminal at that directory.

### 2. Create and activate a virtual environment

PowerShell:

``` powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

### 3. Install dependencies

If `requirements.txt` is present:

``` powershell
python -m pip install -r requirements.txt
```

If dependencies are not captured in that file, install the packages
documented by the project before running the application.

### 4. Configure the database connection

Create a local `.env` file using the variable names expected by
`app/db.py`. Use your own MySQL credentials and database settings. Do
not place real passwords in source code, documentation, screenshots, or
Git history.

The project database used during development was named
`yottaflex_transport`.

### 5. Create the database schema

Use MySQL Workbench or the MySQL command-line client to execute the
schema file under `sql/` (for example, `sql/schema.sql`, if that is the
schema file in your checkout). Confirm the database selected by your
connection is the intended development database before running SQL.

### Local JWT RBAC

The local API uses short-lived HS256 bearer tokens and PBKDF2-HMAC-SHA256
password hashes. Set a private JWT signing secret in the local, ignored
`.env` file; there is deliberately no built-in secret or fallback:

``` text
AUTH_JWT_SECRET=<paste-a-generated-secret-of-at-least-32-bytes>
AUTH_JWT_TTL_SECONDS=900
```

Generate a secret locally, then copy its output into `.env`:

``` powershell
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

After applying `sql/schema.sql` to an empty development database, create
the first platform administrator. The command prompts for the username
and for the password twice without echoing either password. It fails if
any account already exists; it does not provide a reset or second
bootstrap path.

``` powershell
python -m app.auth_cli bootstrap-admin
```

Use the local login endpoint to obtain a bearer token. For example:

``` powershell
$login = Invoke-RestMethod -Method Post `
  -Uri http://127.0.0.1:8000/auth/login `
  -ContentType "application/json" `
  -Body '{"username":"<local-user>","password":"<local-password>"}'
$headers = @{ Authorization = "Bearer $($login.access_token)" }
```

Pass `$headers` to protected API calls. Token lifetime defaults to 900
seconds; `AUTH_JWT_TTL_SECONDS` accepts 60–3600 seconds. A missing or
shorter-than-32-byte `AUTH_JWT_SECRET` prevents token issuance and
validation. Provision later accounts and instructor scopes through the
platform-admin-only `/auth/users` and `/auth/users/{username}/route-scopes`
endpoints. Password fields and password hashes are never copied to audit
snapshots.

| Role | Allowed API actions |
|---|---|
| `learner` | Read only their own `/students/{student_id}/transport` and `/students/{student_id}/attendance` records |
| `instructor` | Append attendance only for routes with an active instructor route scope |
| `academic_administrator` | Generate routes, register students, assign new students, and view the aggregate anomaly summary |
| `support_staff` | Simulate notifications and check address-access decisions; requester authorization comes from the authenticated role |
| `platform_administrator` | All API actions, user provisioning, and instructor route-scope management |

`/`, `/health`, and `/auth/login` do not require a bearer token. Other
API operations require an authenticated role. Notification and address
requests do not accept a caller-supplied authorization boolean; extra
fields are rejected. The schema contains persistent `app_user` and
`instructor_route_scope` tables. Existing databases created before these
tables were added need a reviewed migration; rerunning `CREATE TABLE IF
NOT EXISTS` does not alter existing tables.

This is a local demonstration workflow, not a claim of production-grade
identity assurance. It has no MFA, refresh tokens, token revocation, or
external identity provider; changing the signing secret invalidates
outstanding tokens. Use synthetic data and a properly protected secret,
database account, and transport channel.

### 6. Generate data

Run generators from the project root so Python can resolve project
imports correctly. For example:

``` powershell
python -m generator.generate_data
```

The master generator uses a default seed of `20261022` and supports
configurable scale parameters. Check the script's argument parser or
help output before overriding defaults.

Full-scale operational generation and anomaly-example generation are
handled by separate scripts. Review each script's output paths and
options before running it, because generators may write or overwrite
files.

Operational assignments are selected from eligible route-stop records
using accessibility, pickup-window, and effective-capacity rules. Among
feasible candidates, the generator prefers the lowest current
capacity-utilization ratio, then shorter travel time, earlier arrival,
and stable IDs. Assignment dates come from route service dates;
assignment intervals are limited to that service date. Attendance
timestamps use the selected stop's scheduled arrival. Daily attendance
outcomes are derived from the numeric student ID and service-day index:
the rule maps stable 0-99 buckets to missed pickup, absent, boarded, or
present. This is a documented synthetic scenario rule, not an observed
prediction. Guardian validity and consent determine notification blocks;
synthetic requester authorization is derived from the student ID and
service date. High-severity unresolved disruptions mark a route
unavailable; active low/medium disruptions add a documented delay to the
stop schedule. The generator reports assignment/unassigned rates,
effective seat utilization, remaining capacity, and missed-pickup rate
from the generated records rather than generating those metrics
separately.

The candidate rank is derived from each candidate's current route load,
effective bus capacity, travel duration, scheduled arrival, and stable
route/stop IDs; candidates are ordered by utilization ratio first, then
travel time, arrival time, route ID, and stop ID. Remaining capacity is
effective seat capacity minus accepted assignments. The missed-pickup
rate is missed-pickup attendance events divided by all attendance events.
These are calculated outcomes, not independently generated scores.

Generate the five labeled edge-case proposals only after a baseline has
been generated. The anomaly script validates its relevant baseline keys
and joins, writes separate `ground_truth.csv` and `ground_truth.json`
artifacts, and refuses to overwrite existing files. It does not mutate
operational records or send real notifications. Each record includes
`issue_type`, a `ground_truth_label`, expected and detected outcomes, and
a `baseline_modified` flag. These labels are never read by the operational
generator.

``` powershell
python -m generator.generate_full_scale_operations --students 100 --days 10 --output data/full_scale/derived_check
python -m generator.validate_full_scale_operations --operations data/full_scale/derived_check --master data/full_scale --days 10 --students 100
python -m generator.inject_full_scale_anomalies --master data/full_scale --operations data/full_scale/derived_check --output data/full_scale/ground_truth_check
python -m generator.validate_ground_truth --definitions data/ground_truth --proposals data/full_scale/ground_truth_check --master data/full_scale --operations data/full_scale/derived_check
```

The five proposals cover capacity exceeded, an accessibility-incompatible
route, an impossible stop travel time, a simulated notification attempt
to an invalid guardian contact, and exposure of a proposed unapproved
address. The source baseline remains unchanged; the predicted safe
decision (reject, flag, or block) is compared with the known ground truth.
For the notification case, the baseline contact validity is retained in
`baseline_contact_is_valid`; the invalid flag is applied only to the
separate proposal, which is why the case is reproducible even when the
selected baseline guardian contact is valid.

Generators refuse to replace existing master, ground-truth, or operational
CSV outputs. For example, generate a small isolated dataset and validate
it without changing the existing full-scale data:

``` powershell
python -m generator.validate_data --input data/full_scale
python -m generator.generate_full_scale_operations --students 100 --days 10 --output data/full_scale/derived_check
python -m generator.validate_full_scale_operations --operations data/full_scale/derived_check --master data/full_scale --days 10 --students 100
```

Use a new output directory for each run. Runtime attendance, assignments,
notifications, and decisions are persisted as separate records/events;
attendance events append to history, and duplicate route plans for a
service date are rejected rather than replaced.

## Run the API

From the project root with the virtual environment active and database
configuration set:

``` powershell
python -m uvicorn app.main:app --reload
```

Open these local URLs in a browser:

-   `http://127.0.0.1:8000/` --- root endpoint
-   `http://127.0.0.1:8000/health` --- health endpoint
-   `http://127.0.0.1:8000/docs` --- interactive API documentation

### Daily runtime workflow

The runtime endpoints support this order for a service date:

1. Register the student and guardian with `POST /students/register`.
2. Create the day's route and stop schedule with `POST /routes/generate`.
   Request body:

   ``` json
   {
     "service_date": "2026-10-30"
   }
   ```

   This creates a planned route for each available active bus/driver pair
   and schedules approved active stops. Each zone's stops are scheduled
   against active students' common pickup window; zones without active
   students use the default 07:00-08:30 window. A route plan that cannot
   fit its stops or accessibility needs is rejected without partial
   writes. The endpoint returns HTTP 409 if routes already exist for
   that service date; it does not replace an existing plan.
3. Assign the student with `POST /assignments/assign-new-student`,
   passing the same `service_date`. Assignment checks the route's stop,
   pickup window, accessibility, active bus/driver, effective capacity,
   and available seats.
4. Append attendance with `POST /attendance/events`.
5. Simulate guardian notification with `POST /notifications/simulate`.

Route generation requires active buses, drivers, approved address zones
and stops, and active bus-capacity history for the requested date so the
assignment endpoint can validate seats. Route stops use the project's
existing synthetic schedule assumption of 10 minutes per leg; this is
not road-network routing or a production travel-time estimate.

The API does not automatically regenerate routes when a student is
registered. Generate a service-date plan after registering the students
who need it and before requesting their assignments. Consult
`app/main.py` for request fields and endpoint behavior.

### Test route generation

Route generation writes to the configured MySQL database. Test against a
development database, and choose a service date that has no routes yet;
this endpoint does not delete or replace existing routes.

1. Start the API from the project root:

   ``` powershell
   .\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
   ```

2. Open `http://127.0.0.1:8000/docs`, expand **POST `/routes/generate`**,
   select **Try it out**, and submit a date, for example:

   ``` json
   {
     "service_date": "2026-10-30"
   }
   ```

   Use this example only if the date is unused in your database.
3. A successful request returns HTTP `201` with `status: "CREATED"`,
   route and route-stop counts, and the generated route IDs. An existing
   route plan for that date returns HTTP `409`; a plan that cannot meet
   the service's prerequisites is also rejected without partial writes.
4. Optionally verify the inserts in MySQL Workbench:

   ``` sql
   SELECT route_id, bus_id, driver_id, service_date, status
   FROM route
   WHERE service_date = '2026-10-30';

   SELECT rs.route_stop_id, rs.route_id, rs.stop_id,
          rs.sequence_no, rs.arrival_time, rs.travel_minutes
   FROM route_stop AS rs
   JOIN route AS r ON r.route_id = rs.route_id
   WHERE r.service_date = '2026-10-30'
   ORDER BY rs.route_id, rs.sequence_no;
   ```

Before testing, confirm the date has no existing routes and that active
buses have exactly one effective capacity-history record for that date.
Active drivers and approved, active stops in approved zones are also
required. Automated tests cover route planning and transaction behavior
with a mocked database; they do not replace this live database check.

**Safety note:** notification behavior is simulated for this project; do
not use synthetic contacts to send real messages. Address-access checks
are a local demonstration and should not be treated as a production
authorization system without stronger identity and access controls.

## Validation and tests

Run commands from the project root. To validate the updated operational
derivation rules without replacing the checked-in legacy CSVs, generate
into a new directory first, then validate that output:

``` powershell
python -m generator.validate_data --input data/full_scale
python -m generator.generate_full_scale_operations --students 500 --days 10 --output data/full_scale/derived_check
python -m generator.validate_full_scale_operations --operations data/full_scale/derived_check --master data/full_scale --days 10 --students 500
python -m generator.inject_full_scale_anomalies --master data/full_scale --operations data/full_scale/derived_check --output data/full_scale/anomaly_check
python -m generator.validate_ground_truth --definitions data/ground_truth --proposals data/full_scale/anomaly_check --master data/full_scale --operations data/full_scale/derived_check
python -m generator.validate_full_scale_anomalies
python -m generator.test_anomaly_rules
```

For a fresh, reproducible ground-truth definition set, generate definitions
to a new directory (the default path is protected from overwrite), then use
that directory for both proposal generation and validation:

``` powershell
python -m generator.generate_ground_truth --output data/full_scale/ground_truth_definitions
python -m generator.inject_full_scale_anomalies --master data/full_scale --operations data/full_scale/derived_check --output data/full_scale/ground_truth_cases
python -m generator.validate_ground_truth --definitions data/full_scale/ground_truth_definitions --proposals data/full_scale/ground_truth_cases --master data/full_scale --operations data/full_scale/derived_check
```

The default `validate_full_scale_operations` path reads the existing
`data/full_scale/operations` files. Those checked-in files predate the
latest derivation rules and currently fail the new disruption-status
check; they were intentionally left unchanged. Choose a new output
directory for each generation because generators refuse to overwrite
existing operational history. The validators check primary-key uniqueness,
every declared CSV foreign-key join, student/address zone consistency,
route/stop/assignment/attendance/notification ownership, effective-date
ranges, capacity reconciliation, event arithmetic, lifecycle enums,
disruption-state reachability and route-state consistency, and duplicate
constraints. Master validation also checks required fields, finite bounded
coordinates, pickup-window ordering, capacity values, and effective-date
ordering. These generated CSVs contain current lifecycle snapshots; they
cannot prove historical status chronology. Runtime state changes are
appended to `audit_event` with before/after state in the database, and
should be queried there when validating an actual runtime history. Run only
scripts that exist in the current checkout, and review output paths before
running file-generating scripts.

Runtime API writes, master/operations CSV imports, and generated
`sync_*.sql` updates append minimized `audit_event` records in the same
transaction as each change. Related writes share a correlation ID. Contact
values and synthetic address labels are excluded from audit snapshots.
Successful state-changing API responses include that `correlation_id` for
follow-up queries against `audit_event`.
Restrict the application's database account from updating or deleting
`audit_event` rows. The added schema keys (student/address-zone consistency,
unique route-stop pairs, and one notification per event) take effect when
creating tables; existing databases need a reviewed schema migration before
those database-level constraints apply.

### Results observed during development

-   The latest full-scale two-run check passed for 5,000 students, 100
    buses, 300 stops, and 200 school days at seed `20261022`. It passed
    the master, operational, and ground-truth validators on both runs.
-   All 34 regenerated artifacts matched row counts and SHA-256 checksums.
    The package at `data/full_scale/submission_exports_v4/` contains the
    regenerated CSV and JSON files plus separate ground-truth
    definitions/proposals. All 34 packaged data files match regenerated
    run 1.
-   The regenerated package contains 20,000 routes, 60,000 route-stop
    records, and 752,480 each of assignments, attendance events, and
    notification decisions. Its notification rule reconciliation passed
    in both runs.
-   The SQL seed loader's table names and CSV headers were validated
    against `sql/schema.sql`. The package was imported into
    `yottaflex_transport_fullscale`, and its core and operational row
    counts were verified in MySQL. The loader uses CRLF-aware CSV line
    endings so final-column lifecycle values and nullable dates are
    preserved.
-   An earlier isolated 500-student, 10-school-day run passed
    master-data and operational validation, including declared CSV
    foreign keys, student/address zone consistency, operational joins,
    capacity-history date checks, and lifecycle values.
-   An earlier five-case anomaly proposal output passed its CSV/JSON,
    ground-truth, source-derivation, and baseline-isolation checks.
-   The baseline anomaly scan reported zero capacity-history coverage
    gaps and zero overlapping effective capacity-history records.
-   The same baseline scan found 500 invalid guardian contacts and
    verified blocking for all 500; it found 2,500 restricted addresses
    and verified blocking for all 2,500.
-   Baseline detections for capacity-exceeded, accessibility-mismatch,
    and impossible-travel-time were zero. Deliberate examples for those
    anomaly types were validated separately.
-   The impossible-travel-time threshold of 10 minutes is provisional at
    the time of validation.
-   The imported MySQL database was checked against the package: it has
    752,480 assignments, all 200 service dates, 125 effective-dated
    capacity records, and no broken assignment, attendance, notification,
    or student/address-zone joins. Route statuses, assignment statuses,
    disruption statuses, and capacity history match their source CSVs.
-   The generated operation metrics show 1,000,000 assignment attempts,
    752,480 accepted assignments, a 24.75% unassigned/rejected rate, and
    100% effective seat utilization. This is a deterministic synthetic
    scenario, not a claim that real-world demand or bus utilization has
    been calibrated.
-   The older checked-in operational CSVs under `data/full_scale/` were
    not overwritten; their row counts differ from the latest generated
    package. Use the self-contained `submission_exports_v4` package for
    the newly verified, internally consistent full-scale dataset.

These results describe the checks actually run. They are not a claim of
production readiness or real-world transport safety.

## Anomaly types and expected outcomes

  Anomaly type                        Expected outcome
  ----------------------------------- ------------------
  `CAPACITY_EXCEEDED`                 `REJECT`
  `ACCESSIBILITY_MISMATCH`            `REJECT`
  `IMPOSSIBLE_TRAVEL_TIME`            `FLAG`
  `INVALID_GUARDIAN_CONTACT`          `BLOCK`
  `UNAUTHORIZED_ADDRESS_DISCLOSURE`   `BLOCK`

The deliberate anomaly examples are maintained separately from baseline
generated data to avoid mixing ground-truth labels into ordinary input
features.

## Reproducibility

Run the end-to-end release check from the project root:

``` powershell
python -m generator.check_reproducibility
```

By default, the tool regenerates master data, operational data,
ground-truth definitions, and source-bound anomaly proposals twice using
seed `20261022` and the full 5,000-student, 100-bus, 300-stop,
200-school-day scale. Both runs use isolated temporary directories and
are validated before row counts and SHA-256 checksums are compared for
every output. The temporary datasets are removed afterward. The command
refuses to overwrite a non-empty export directory.

By default, the export directory is
`data/full_scale/submission_exports_v4`. The command refuses to overwrite
a non-empty directory; use a different new `--output` path for subsequent
runs. It packages newly regenerated CSVs in `csv/master/` and
`csv/operations/`, with ground-truth definitions and proposals kept
separately under `ground_truth/`. Along with `full_scale_seed.sql`,
`source_manifest.json`,
`reproducibility_report.json`, `validation_summary.json`, and
`validation_summary.md`, it exports JSON array companions for all 15
master and operational CSV tables under `json/master/` and
`json/operations/`. Each JSON companion's row count is checked against its
packaged CSV source. The manifest records synthetic provenance,
source/generator checksums, and checksums for all packaged data.

The SQL loader reads the packaged CSVs and uses MySQL
`LOAD DATA LOCAL INFILE`; first apply `sql/schema.sql`, then run from the
project root:

``` cmd
mysql --local-infile=1 -u YOUR_USER -p yottaflex_transport < data/full_scale/submission_exports_v4/full_scale_seed.sql
```

Import into a newly created/empty database: the loader deliberately does
not delete or replace records. Ground-truth labels are excluded from SQL
and operational input features. The master `bus_capacity_history.csv` is
not loaded alongside operational capacity history because both represent
the same table; the effective-dated operational history is the seed
source. Runtime-only `assignment_decision` and `audit_event` tables have
no generated CSV seed. Live MySQL execution is not included in the local
reproducibility check.

## Data and privacy

-   The datasets are synthetic and intended for development and
    demonstration.
-   Do not add real student, guardian, address, or contact information
    to the repository.
-   Do not commit `.env`, database passwords, `.venv`, caches, or local
    logs containing secrets.
-   Keep ground-truth labels separate from model or rule input features
    when evaluating anomaly detection.
-   Document any external datasets if introduced later. The current
    project can be described as synthetic-data-based unless external
    sources are actually used.

## Contribution and AI-use transparency

The `submission/` directory can contain:

-   `my_contribution.md` --- work personally performed, tests run, and
    AI-assisted activities.
-   `prompts_history.md` --- prompt history or a clearly labelled
    reconstructed summary.

If prompt history is reconstructed rather than exported verbatim, label
it clearly as a summary and do not present paraphrased prompts as exact
quotations.

## Current limitations and follow-up items

-   Confirm the exact current contents of `requirements.txt` and the
    environment-specific `.env` variable names before publishing setup
    instructions.
-   Treat the 10-minute travel-time threshold as provisional until a
    justified threshold is documented.
-   The full-scale MySQL import was verified in the local development
    environment; repeat the import check in the submission environment if
    that environment differs.
-   Review the repository and `.gitignore` before publishing to ensure
    secrets and unnecessary generated artifacts are excluded.

## License and status

Add the license and project status required by the submission or hosting
platform. Do not claim an open-source license unless one has been
selected and included.
