# Yottaflex Transport Database — Data Dictionary

Source: `sql/schema.sql`. SQL types, nullability, defaults, primary keys, foreign keys, and checks below reflect the supplied schema. CSV generator outputs may represent booleans as `0/1` and nullable dates as blank strings.

## Conventions
- IDs are synthetic string identifiers. SQL primary keys enforce uniqueness, but SQL does not enforce ID prefixes or formats.
- The project owner accepts the generated/runtime ID formats documented in each entity table, even where they differ from the initially suggested examples `ROUTE-2026-000001`, `ASN-<student-id>-2026`, and `NOT-2026-000001`.
- Daily assignment IDs include a date suffix so each immutable student/day assignment has its own unique primary key.
- Dates use ISO `YYYY-MM-DD`; times use `HH:MM:SS`; datetimes use `YYYY-MM-DD HH:MM:SS`.
- `BOOLEAN` values are logical true/false (often serialized as `1/0` in CSV).
- `NULL` means unknown/not applicable; empty CSV fields may represent SQL `NULL` only when the loader maps them that way.
- `PK` = primary key; `FK` = foreign key; `UQ` = unique.

## Relationships and lifecycle
- `address_zone` 1:N `address`, `student`, and `stop`; each child requires exactly one zone. Addresses and stops can exist without students or routes.
- `address` 1:N `student`; each student requires exactly one address and one zone, and the composite FK guarantees that the student's zone matches the address zone. An address may have no students.
- `student` 1:N `guardian_contact`, `assignment`, `attendance_event`, and `assignment_decision`; each child requires exactly one student. A student may have no guardian or assignments yet, and may accumulate many dated decisions, assignments, and attendance events.
- `bus` 1:N `bus_capacity_history` and `route`; each history row or route refers to exactly one bus. `driver` 1:N `route`; each route has exactly one driver. The schema limits a bus and a driver to at most one route per service date.
- `route` N:M `stop` through `route_stop`; the bridge requires one route and one stop per row and enforces unique route/stop pairs and unique stop sequence numbers within a route.
- `route` 1:N `assignment`, `route_stop`, `attendance_event`, and `route_disruption`; each child references exactly one route. An assignment also requires exactly one student and stop.
- `guardian_contact` 1:N `notification`; each notification requires exactly one guardian, student, and attendance event. An attendance event may have zero or one notification decision; `notification.event_id` is unique.
- `app_user` optionally references one `student` for learner accounts. Each `instructor_route_scope` references one instructor account and one route; the username/route pair is unique, and inactive scope rows remain available for audit history.
- Capacity-history effective dates are inclusive, and rows for a bus must not overlap. Exactly one capacity record must apply on each route service date. Assignments have effective start/end dates; generated assignments are bounded to their route service date, and runtime checks prevent overlapping active assignments for the same student/date.
- Lifecycle values are constrained by schema enums. Runtime registration, route creation, assignments/decisions, attendance, notification writes, user provisioning, and instructor-scope changes append audit records in the same transaction. User audit snapshots exclude password hashes and plaintext passwords. CSV imports and the generated synchronization SQL also append audit records. Other audit snapshots exclude synthetic phone numbers, emails, and address labels; `correlation_id` groups related writes. Attendance and notification records are append-only workflow events. The polymorphic `audit_event.entity_id` intentionally has no FK; the CSV validators cannot validate this polymorphic reference because audit rows are stored in MySQL, not exported with the operational CSVs.

## Field-level data dictionary

Each row explicitly records storage type, nullability, domain/units,
uniqueness, and validation. “None” under uniqueness means no additional
unique constraint beyond any listed foreign-key relationship. IDs are
case-sensitive synthetic strings; their observed generator formats are
examples, while SQL validates length and key integrity rather than a prefix
pattern unless stated. Schema constraints are database-enforced; workflow
rules are enforced by the generator/API and validators where indicated.
Text fields without a closed domain accept non-empty UTF-8 text up to their
declared SQL length (or unrestricted `TEXT`).

## `address_zone`
| Field | SQL type | Required | Allowed values / units | Unique | Validation / meaning |
|---|---|---|---|---|---|
| `zone_id` | VARCHAR(20) | Yes | Synthetic ID; generated `ZONE-NNN` | PK | Non-empty; parent key for addresses, students, and stops |
| `zone_name` | VARCHAR(100) | Yes | UTF-8 text | UQ | Non-empty zone display name |
| `approved_status` | ENUM | Yes | `APPROVED`, `REVIEW` | None | Must be one of the enum values; assignment generation uses approved zones |

## `address`
| Field | SQL type | Required | Allowed values / units | Unique | Validation / meaning |
|---|---|---|---|---|---|
| `address_id` | VARCHAR(20) | Yes | Synthetic ID; generated `ADDR-NNNNNN` | PK; unique with `zone_id` | Non-empty |
| `zone_id` | VARCHAR(20) | Yes | Existing `address_zone.zone_id` | FK | Must reference a zone |
| `synthetic_label` | VARCHAR(150) | Yes | Synthetic label, not a deliverable address | None | Non-empty; never use real household address data |
| `approval_status` | ENUM | Yes | `APPROVED`, `UNAPPROVED` | None | Must be one of the enum values |
| `disclosure_authorized` | BOOLEAN | Yes | `TRUE`/`FALSE`; CSV `1`/`0` | None | Defaults `FALSE`; disclose only when both address approval and requester authorization permit it |

## `student`
| Field | SQL type | Required | Allowed values / units | Unique | Validation / meaning |
|---|---|---|---|---|---|
| `student_id` | VARCHAR(20) | Yes | Generated `STU-NNNNNN` | PK | Non-empty; immutable referenced key |
| `zone_id` | VARCHAR(20) | Yes | Existing `address_zone.zone_id` | FK | Must equal the zone of `address_id` |
| `address_id` | VARCHAR(20) | Yes | Existing `address.address_id` | FK; composite FK with `zone_id` | Address must exist and belong to this student's zone |
| `accessibility_required` | BOOLEAN | Yes | `TRUE`/`FALSE`; CSV `1`/`0` | None | Defaults `FALSE`; if true, assignment requires an accessible bus |
| `pickup_window_start` | TIME | Yes | Local 24-hour time, `HH:MM:SS` | None | Must be strictly earlier than `pickup_window_end` |
| `pickup_window_end` | TIME | Yes | Local 24-hour time, `HH:MM:SS` | None | Must be strictly later than `pickup_window_start`; candidate arrival must be within the inclusive window |
| `status` | ENUM | Yes | `ACTIVE`, `INACTIVE` | None | Defaults `ACTIVE`; only active students are assigned/generated |
| `created_at` | TIMESTAMP | Yes | Database timestamp | None | Defaults to `CURRENT_TIMESTAMP`; database-managed creation time |

## `guardian_contact`
| Field | SQL type | Required | Allowed values / units | Unique | Validation / meaning |
|---|---|---|---|---|---|
| `guardian_id` | VARCHAR(20) | Yes | Synthetic ID; generated `GUA-NNNNNN` | PK | Non-empty |
| `student_id` | VARCHAR(20) | Yes | Existing `student.student_id` | FK | Guardian must belong to one existing student; multiple guardians per student are permitted |
| `synthetic_phone` | VARCHAR(30) | Yes | Synthetic, non-deliverable placeholder string | None | Non-empty; never a real phone number |
| `synthetic_email` | VARCHAR(150) | Yes | Synthetic email at reserved `.invalid` domain | None | Must be a syntactically email-shaped synthetic value; not deliverable |
| `is_valid` | BOOLEAN | Yes | `TRUE`/`FALSE`; CSV `1`/`0` | None | Defaults `TRUE`; false contacts block notifications |
| `consent_status` | ENUM | Yes | `GRANTED`, `DENIED` | None | Must be one of the enum values; anything other than granted blocks notifications |

## `stop`
| Field | SQL type | Required | Allowed values / units | Unique | Validation / meaning |
|---|---|---|---|---|---|
| `stop_id` | VARCHAR(20) | Yes | Generated `STOP-NNNNNN` | PK | Non-empty |
| `zone_id` | VARCHAR(20) | Yes | Existing `address_zone.zone_id` | FK | Stop must belong to an existing zone; assignments require the student's zone |
| `x` | DECIMAL(10,3) | Yes | Synthetic coordinate units (generator range 0–100) | None | Numeric, representable to three decimal places; not a real-world geolocation |
| `y` | DECIMAL(10,3) | Yes | Synthetic coordinate units (generator range 0–100) | None | Numeric, representable to three decimal places; not a real-world geolocation |
| `approval_status` | ENUM | Yes | `APPROVED`, `PENDING` | None | Only approved stops are routed/assigned |
| `active_status` | BOOLEAN | Yes | `TRUE`/`FALSE`; CSV `1`/`0` | None | Defaults `TRUE`; only active stops are routed/assigned |

## `bus`
| Field | SQL type | Required | Allowed values / units | Unique | Validation / meaning |
|---|---|---|---|---|---|
| `bus_id` | VARCHAR(20) | Yes | Generated `BUS-NNNNNN` | PK | Non-empty |
| `capacity` | INT | Yes | Whole passengers/seats; generated from 30, 35, 40, 45 | None | Must be greater than zero; operational checks use effective-dated capacity history |
| `is_accessible` | BOOLEAN | Yes | `TRUE`/`FALSE`; CSV `1`/`0` | None | Defaults `FALSE`; required when an assigned student needs accessibility |
| `status` | ENUM | Yes | `ACTIVE`, `MAINTENANCE` | None | Defaults `ACTIVE`; only active buses can receive routes |

## `driver`
| Field | SQL type | Required | Allowed values / units | Unique | Validation / meaning |
|---|---|---|---|---|---|
| `driver_id` | VARCHAR(20) | Yes | Synthetic ID; generated `DRV-NNNNNN` | PK | Non-empty |
| `driver_name` | VARCHAR(100) | Yes | Synthetic display name | None | Non-empty; not treated as a real identity |
| `status` | ENUM | Yes | `ACTIVE`, `UNAVAILABLE` | None | Defaults `ACTIVE`; only active drivers are assigned to generated routes |

## `route`
| Field | SQL type | Required | Allowed values / units | Unique | Validation / meaning |
|---|---|---|---|---|---|
| `route_id` | VARCHAR(30) | Yes | Generated `R-YYYYMMDD-NNN` | PK | Non-empty; one stable ID per service-date route |
| `bus_id` | VARCHAR(20) | Yes | Existing `bus.bus_id` | FK | Must reference a bus; unique with `service_date` |
| `driver_id` | VARCHAR(20) | Yes | Existing `driver.driver_id` | FK | Must reference a driver; unique with `service_date` |
| `service_date` | DATE | Yes | ISO `YYYY-MM-DD` | Participates in two composite UQs | Generator creates weekdays; schema accepts any valid date |
| `status` | ENUM | Yes | `PLANNED`, `ACTIVE`, `DISRUPTED`, `COMPLETED`, `CANCELLED` | None | Defaults `PLANNED`; high-severity unresolved disruption derives `DISRUPTED`; unavailable routes cannot receive assignments |
| `(bus_id, service_date)` | Composite constraint | Yes | One bus per service date | UQ | Prevents a bus from operating multiple routes on the same date |
| `(driver_id, service_date)` | Composite constraint | Yes | One driver per service date | UQ | Prevents a driver from operating multiple routes on the same date |

## `route_stop`
| Field | SQL type | Required | Allowed values / units | Unique | Validation / meaning |
|---|---|---|---|---|---|
| `route_stop_id` | VARCHAR(30) | Yes | Generated `RS-YYYYMMDD-NNN-NNN` | PK | Non-empty |
| `route_id` | VARCHAR(30) | Yes | Existing `route.route_id` | FK; participates in composite UQs | Route must exist |
| `stop_id` | VARCHAR(20) | Yes | Existing `stop.stop_id` | FK; unique with `route_id` | Stop must exist; each stop appears at most once per route |
| `sequence_no` | INT | Yes | Positive integer; 1-based | UQ with `route_id` | Must be greater than zero and unique within the route |
| `arrival_time` | TIME | Yes | Local 24-hour time, `HH:MM:SS` | None | Derived from previous scheduled arrival and travel duration; must fit applicable pickup windows |
| `travel_minutes` | INT | Yes | Whole minutes | None | Must be non-negative; first stop is 0; generator baseline subsequent legs are 10 minutes plus applicable disruption delay |
| `(route_id, stop_id)` | Composite constraint | Yes | Existing bridge endpoints | UQ | Prevents duplicate route-stop association |

## `assignment`
| Field | SQL type | Required | Allowed values / units | Unique | Validation / meaning |
|---|---|---|---|---|---|
| `assignment_id` | VARCHAR(60) | Yes | CSV `A-<student_id>-YYYYMMDD`; runtime `ASG-<student_id>-YYYYMMDD-<8 hex>` | PK | Must be unique; requested annual-style ID alone is insufficient for daily history |
| `student_id` | VARCHAR(20) | Yes | Existing `student.student_id` | FK | Must reference a student |
| `route_id` | VARCHAR(30) | Yes | Existing `route.route_id` | FK | Must reference a route |
| `stop_id` | VARCHAR(20) | Yes | Existing `stop.stop_id` served by the route | FK | Stop must be on route, approved and active; must match student zone and pickup window |
| `effective_from` | DATE | Yes | ISO `YYYY-MM-DD` | None | Must be on/before `effective_to` when bounded; generated value equals route service date |
| `effective_to` | DATE | No (`NULL` allowed) | ISO `YYYY-MM-DD` or open-ended `NULL` | None | Inclusive end date; if present must be on/after `effective_from`; generated assignment is bounded to service date |
| `status` | ENUM | Yes | `ASSIGNED`, `REJECTED`, `ENDED`, `NEEDS_REVIEW` | None | Operational generator emits accepted assignments only; runtime persists rejected/unassigned decisions in `assignment_decision` |
| `created_at` | TIMESTAMP | Yes | Database timestamp | None | Defaults to `CURRENT_TIMESTAMP` |

## `attendance_event`
| Field | SQL type | Required | Allowed values / units | Unique | Validation / meaning |
|---|---|---|---|---|---|
| `event_id` | VARCHAR(30) | Yes | CSV `EVT-YYYYMMDD-NNNNNN`; runtime `EVT-` plus 20 hex characters | PK | Must be unique |
| `student_id` | VARCHAR(20) | Yes | Existing `student.student_id` | FK | Must have an assignment to the referenced route on event/service date |
| `route_id` | VARCHAR(30) | Yes | Existing `route.route_id` | FK | Must reference the route from the student's valid assignment |
| `event_type` | ENUM | Yes | `PRESENT`, `ABSENT`, `BOARDED`, `MISSED_PICKUP`, `DISRUPTION_REASSIGNED` | None | Generated full-scale outcome uses deterministic student/day buckets; runtime accepts the enum as recorded input |
| `event_time` | DATETIME | Yes | Local timestamp `YYYY-MM-DD HH:MM:SS` | None | Date must equal route service date; generated time equals assigned stop arrival |
| `reason` | VARCHAR(255) | Yes | Human-readable text | None | Non-empty explanation; synthetic generation documents the rule/outcome |

## `notification`
| Field | SQL type | Required | Allowed values / units | Unique | Validation / meaning |
|---|---|---|---|---|---|
| `notification_id` | VARCHAR(30) | Yes | CSV `NTF-YYYYMMDD-NNNNNN`; runtime `NTF-` plus 20 hex characters | PK | Must be unique |
| `guardian_id` | VARCHAR(20) | Yes | Existing `guardian_contact.guardian_id` | FK | Guardian must belong to the same student as the event |
| `student_id` | VARCHAR(20) | Yes | Existing `student.student_id` | FK | Must match both the guardian and attendance event |
| `event_id` | VARCHAR(30) | Yes | Existing `attendance_event.event_id` | FK and UQ | One notification decision maximum per event |
| `status` | ENUM | Yes | `SIMULATED_SENT`, `BLOCKED_INVALID_CONTACT`, `BLOCKED_CONSENT`, `BLOCKED_AUTHORIZATION` | None | Derived in that priority order from contact validity, consent, and requester authorization; no real message is sent |
| `reason` | VARCHAR(255) | Yes | Human-readable text | None | Must explain the derived status |
| `created_at` | DATETIME | Yes | Local timestamp `YYYY-MM-DD HH:MM:SS` | None | Generated timestamp equals event time; runtime records decision time |

## Supporting table: `bus_capacity_history`
| Field | SQL type | Required | Allowed values / units | Unique | Validation / meaning |
|---|---|---|---|---|---|
| `capacity_history_id` | VARCHAR(30) | Yes | Generated `CAP-NNNNNN` | PK | Must be unique |
| `bus_id` | VARCHAR(20) | Yes | Existing `bus.bus_id` | FK | Must reference a bus |
| `capacity` | INT | Yes | Whole passengers/seats | None | Must be greater than zero; exactly one effective record is required on a route's service date |
| `effective_from` | DATE | Yes | ISO `YYYY-MM-DD` | None | Inclusive start date |
| `effective_to` | DATE | No (`NULL` allowed) | ISO `YYYY-MM-DD` or open-ended `NULL` | None | Inclusive end date; if present must be on/after start; periods for the same bus must not overlap |

## Supporting table: `route_disruption`
| Field | SQL type | Required | Allowed values / units | Unique | Validation / meaning |
|---|---|---|---|---|---|
| `disruption_id` | VARCHAR(30) | Yes | Generated `DIS-YYYYMMDD-NNN` | PK | Must be unique |
| `route_id` | VARCHAR(30) | Yes | Existing `route.route_id` | FK | Must reference a route; generator permits at most one disruption per route/service date |
| `service_date` | DATE | Yes | ISO `YYYY-MM-DD` | None | Must equal referenced route's service date |
| `disruption_type` | VARCHAR(50) | Yes | Generated examples `TRAFFIC_DELAY`, `ROAD_CLOSURE`, `VEHICLE_DELAY` | None | Non-empty classification string |
| `severity` | ENUM | Yes | `LOW`, `MEDIUM`, `HIGH` | None | High unresolved disruption makes route unavailable; lower active severity affects schedule |
| `status` | ENUM | Yes | `RECORDED`, `RESOLVED`, `ESCALATED` | None | Must be one of the enum values; resolved disruption does not affect schedule |

## Supporting table: `assignment_decision`
| Field | SQL type | Required | Allowed values / units | Unique | Validation / meaning |
|---|---|---|---|---|---|
| `decision_id` | VARCHAR(30) | Yes | Runtime `DEC-` plus 24 hex characters | PK | Must be unique |
| `student_id` | VARCHAR(20) | Yes | Existing `student.student_id` | FK | Must reference a student |
| `decision` | ENUM | Yes | `ACCEPTED`, `REJECTED`, `UNASSIGNED`, `NEEDS_REVIEW` | None | Records the outcome of an assignment attempt; append rather than overwrite |
| `reason_code` | VARCHAR(60) | Yes | Machine-readable text; e.g. `STUDENT_INACTIVE`, `ALREADY_ASSIGNED`, `NO_ELIGIBLE_ROUTE`, `NO_AVAILABLE_CAPACITY`, `ASSIGNMENT_CREATED` | None | Non-empty code for the decision |
| `explanation` | TEXT | Yes | Human-readable text | None | Explains the decision |
| `candidate_count` | INT | Yes | Non-negative candidate count | None | Defaults to 0; must be zero or greater |
| `created_at` | DATETIME | Yes | Database timestamp | None | Decision creation time |

## Authentication table: `app_user`
| Field | SQL type | Required | Allowed values / units | Unique | Validation / meaning |
|---|---|---|---|---|---|
| `username` | VARCHAR(80) | Yes | Local account identifier | PK | Non-empty; used as the JWT subject |
| `password_hash` | VARCHAR(255) | Yes | `pbkdf2_sha256` encoding | None | PBKDF2-HMAC-SHA256 hash with per-user random salt; never store or audit plaintext |
| `role` | ENUM | Yes | `learner`, `instructor`, `academic_administrator`, `support_staff`, `platform_administrator` | None | Role used by API authorization; tokens are signed and expire after a short configured interval |
| `student_id` | VARCHAR(20) | Conditional | Existing student ID for learners; `NULL` otherwise | FK; UQ | At most one learner account per student; learner identity enforces own-student read scope |
| `is_active` | BOOLEAN | Yes | `TRUE`/`FALSE` | None | Inactive accounts cannot log in |
| `created_at` | TIMESTAMP | Yes | Database timestamp | None | Database-managed creation time |
| `updated_at` | TIMESTAMP | Yes | Database timestamp | None | Automatically updated when the account changes |

## Authentication table: `instructor_route_scope`
| Field | SQL type | Required | Allowed values / units | Unique | Validation / meaning |
|---|---|---|---|---|---|
| `scope_id` | VARCHAR(30) | Yes | Runtime `SCP-` plus 24 hex characters | PK | Unique scope record |
| `username` | VARCHAR(80) | Yes | Existing instructor username | FK; UQ with `route_id` | The referenced account must have the instructor role for API-issued scopes |
| `route_id` | VARCHAR(30) | Yes | Existing route ID | FK; UQ with `username` | Route to which attendance append permission is granted |
| `is_active` | BOOLEAN | Yes | `TRUE`/`FALSE` | None | Revocation deactivates the row rather than deleting its history |
| `created_at` | TIMESTAMP | Yes | Database timestamp | None | Database-managed creation time |
| `updated_at` | TIMESTAMP | Yes | Database timestamp | None | Automatically updated when the scope changes |

## Supporting table: `audit_event`
| Field | SQL type | Required | Allowed values / units | Unique | Validation / meaning |
|---|---|---|---|---|---|
| `audit_id` | VARCHAR(30) | Yes | Runtime `AUD-` plus 24 hex characters | PK | Must be unique |
| `entity_type` | VARCHAR(50) | Yes | Table/entity name | None | Non-empty type paired with entity ID |
| `entity_id` | VARCHAR(60) | Yes | ID of the referenced entity; format depends on entity type | None | Polymorphic reference; intentionally has no ordinary FK |
| `action` | VARCHAR(50) | Yes | Current writers use `CREATED`, `UPDATED`, or `IMPORTED` | None | Non-empty action |
| `before_json` | JSON | No (`NULL` allowed) | Valid JSON object or `NULL` | None | Prior minimized state for updates; omitted for create/import |
| `after_json` | JSON | No (`NULL` allowed) | Valid JSON object or `NULL` | None | New minimized state; sensitive contact/address labels are excluded |
| `created_at` | DATETIME | Yes | Database timestamp | None | Audit creation time |
| `correlation_id` | VARCHAR(60) | Yes | UUID string | Indexed, not unique | Groups records from one workflow/import |

Audit entries are inserted in the same transaction as the entity write. The
application and generated sync SQL do not update or delete existing audit
rows. Direct database writes can bypass this convention, so production
database permissions should deny application users `UPDATE` and `DELETE` on
`audit_event`.

## Generator CSVs not represented as database tables
The operations generator also writes CSVs for `route`, `route_stop`, `assignment`, `notification`, `attendance_event`, `bus_capacity_history`, and `route_disruption`; these correspond to the tables above. Ground-truth anomaly examples are evaluation artifacts rather than ordinary operational input fields.

### Ground-truth and anomaly proposal outputs
The ground-truth definition generator writes `ground_truth.csv` and `ground_truth.json` to a definitions directory. The source-bound anomaly injector writes files with the same names to a separate proposals directory; do not merge either into baseline master or operational inputs. It does not update operational records or send real notifications.

| Field | Type | Required | Allowed values / units | Unique | Validation / meaning |
|---|---|---|---|---|---|
| `case_id` | String | Yes | `GT-001` through `GT-005` | Yes | Stable ID for each documented scenario |
| `anomaly_type` | String | Yes | `CAPACITY_EXCEEDED`, `ACCESSIBILITY_MISMATCH`, `IMPOSSIBLE_TRAVEL_TIME`, `INVALID_GUARDIAN_CONTACT`, `UNAUTHORIZED_ADDRESS_DISCLOSURE` | No | Broad detector category |
| `issue_type` | String | Yes | `CAPACITY_EXCEEDED`, `INCOMPATIBLE_ROUTE`, `IMPOSSIBLE_TRAVEL_TIME`, `INVALID_NOTIFICATION_CONTACT`, `UNAPPROVED_ADDRESS_EXPOSED` | No | Explicit business issue represented by the proposal |
| `ground_truth_label` | String | Yes | Same allowed values as `anomaly_type` | No | Expected classification, kept out of baseline operational inputs |
| `entity_type` | String | Yes | `proposed_assignment`, `proposed_route_stop`, `proposed_notification`, `proposed_address_disclosure` | No | Entity affected by the hypothetical proposal |
| `expected_outcome` | String | Yes | `REJECT`, `FLAG`, `BLOCK` | No | Rule-derived safe decision |
| `actual_outcome` | String | Yes | `REJECT`, `FLAG`, `BLOCK`, `ALLOW`, `ACCEPT` | No | Result from the anomaly detector |
| `detected` | Boolean | Yes | `true` or `false` | No | True only when the detector outcome matches the expected outcome |
| `scenario_mode` | String | Yes | `PROPOSED_ONLY` | No | Marks the case as a proposal, not a corrupted operational record |
| `baseline_modified` | Boolean | Yes | `false` | No | Must remain false; anomaly output generation is separate from baseline generation |
| `baseline_contact_is_valid` | Boolean | GT-004 only | `true` or `false` | No | Source value from the referenced guardian contact |
| `guardian_contact_is_valid` | Boolean | GT-004 only | `false` in the proposal | No | Hypothetical contact check value passed to the detector; it does not change the source contact |
| `seed`, `case_count`, `cases` | JSON metadata | Yes in JSON wrapper | Seed `20261022`, count equals cases array length | No | CSV rows and JSON cases must match exactly |
| Case-specific source/proposal fields | String, integer, Boolean, or date/time | Per case | Existing IDs and source units; proposed capacity is passengers, travel time is minutes | No | Source references must resolve against the baseline; derived proposal values and expected outcomes are recomputed by `validate_ground_truth.py` |

The generator derives route suitability order from current route utilization,
travel minutes, scheduled arrival, and stable route/stop IDs. It derives
remaining seats from effective bus capacity minus accepted assignments;
attendance and notification outcomes from their source events and documented
rules; and evaluation rates from generated event counts. See the project
README for the exact formulas and reproducible commands.

## Validation coverage for steps 7–8
`validate_ground_truth.py` checks the definition CSV/JSON contract, exact
case coverage, source joins for each proposal, independently recomputed safe
decisions, and that ground-truth-only fields are absent from master and
operational input files. `validate_data.py` checks master-data required
fields, keys, joins, enums, booleans, pickup-window ordering, coordinates,
capacities, and effective-date ranges. `validate_full_scale_operations.py`
checks operational keys and foreign keys, duplicate constraints, date/time
ordering, capacity and count reconciliation, derived attendance and
notification values, lifecycle enums, and disruption-to-route state
consistency. Operational CSVs are lifecycle snapshots, so historical
transition chronology is available from runtime `audit_event` records, not
reconstructible from those CSV snapshots.

## ID formats
Generated and runtime ID formats are documented in the entity tables above and are accepted for this submission. IDs remain deterministic where generated, immutable, primary-key unique, and consistent across foreign-key references. Daily assignment IDs include the student and service date to distinguish repeated assignments.
