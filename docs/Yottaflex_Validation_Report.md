# Yottaflex.ai Technologies — Validation Report

**Project:** School Transportation Assignment System  
**Validation scope:** Synthetic full-scale regeneration, operational rules, ground truth, export packaging, and reproducibility  
**Seed:** `20261022`  
**Operational period:** 2026-01-05 to 2026-10-09 (200 school days)  
**Report status:** Full-scale two-run verification and local MySQL import completed

---

## 1. Executive summary

The full-scale pipeline was regenerated twice in isolated temporary directories using the same seed and parameters. Both master-data and operational validators passed; all 34 compared CSV/JSON/ground-truth artifacts had matching row counts and SHA-256 checksums.

A self-contained package was written to `data/full_scale/submission_exports_v4/`. Its CSVs, JSON companions, and separate ground-truth artifacts match regenerated run 1. The SQL loader was applied to the separate local database `yottaflex_transport_fullscale`. Post-import checks found and corrected a CRLF parsing issue affecting final-column values and nullable capacity-history rows; the loader now declares CRLF line endings, and the imported data was reconciled against the packaged CSVs.

These results establish reproducibility and rule consistency for this synthetic package. They do not establish production readiness or real-world transport safety.

## 2. Dataset generation summary

| Artifact | Rows |
|---|---:|
| `route.csv` | 20,000 |
| `route_stop.csv` | 60,000 |
| `assignment.csv` | 752,480 |
| `attendance_event.csv` | 752,480 |
| `notification.csv` | 752,480 |
| `bus_capacity_history.csv` (operational output) | 125 |
| `route_disruption.csv` | 194 |

Master data used by the operational generator included:

| Master dataset | Rows |
|---|---:|
| `address_zone.csv` | 20 |
| `address.csv` | 5,000 |
| `student.csv` | 5,000 |
| `guardian_contact.csv` | 5,000 |
| `stop.csv` | 300 |
| `bus.csv` | 100 |
| `driver.csv` | 100 |
| `bus_capacity_history.csv` (master input) | 100 |

The generated package uses 5,000 students, 100 buses, 300 stops, 200 school days, and seed `20261022`. It is stored separately from the pre-existing full-scale operational CSVs, which were not overwritten.

## 3. Notification status distribution

| Status | Count | Percentage |
|---|---:|---:|
| `SIMULATED_SENT` | 661,578 | 87.92% |
| `BLOCKED_INVALID_CONTACT` | 8,743 | 1.16% |
| `BLOCKED_CONSENT` | 75,461 | 10.03% |
| `BLOCKED_AUTHORIZATION` | 6,698 | 0.89% |
| **Total** | **752,480** | **100.00%** |

Percentages are rounded to two decimal places. `SIMULATED_SENT` means the synthetic checks passed; no real message was sent.

## 4. Notification structural and relationship validation

The operational validator passed 131 explicit checks for each regenerated full-scale run. This includes notification/event/guardian joins, student ownership consistency, uniqueness, required values, and notification-rule reconciliation.

| Check | Reported result | Outcome |
|---|---:|---|
| Notification rows | 752,480 | Pass |
| Attendance-event rows | 752,480 | Pass |
| Validator checks per regenerated run | 131 | Pass |
| Master-data validator checks per regenerated run | 8 | Pass |
| Ground-truth validator checks per regenerated run | 87 | Pass |

The rule validator joins each notification to its event and guardian and checks that referenced student IDs agree. Each generated event has one notification decision.

## 5. Notification rule validation

The rule-level validator compared each notification status with the expected outcome based on guardian validity, consent status, and the generator's simulated authorization pattern.

| Rule condition, in priority order | Expected status |
|---|---|
| Guardian contact is invalid | `BLOCKED_INVALID_CONTACT` |
| Contact is valid but consent is not `GRANTED` | `BLOCKED_CONSENT` |
| Prior checks pass but requester is simulated as unauthorized | `BLOCKED_AUTHORIZATION` |
| All checks pass | `SIMULATED_SENT` |

**Verified result:** notification rule reconciliation passed in both regenerated runs. The latest package contains 752,480 decisions; the outcome counts above were computed from its exported CSV.

The authorization pattern is synthetic and validates consistency with the generator's rules, not real-world identity or access authorization. Notifications are simulated; no messages were sent.

## 6. Operational reproducibility

The command `python -m generator.check_reproducibility` regenerated master data, operational data, ground-truth definitions, and anomaly proposals twice with the same seed and full scale.

**Verified result:** all 34 artifacts (15 CSVs, 15 typed JSON arrays, and 4 ground-truth CSV/JSON files) matched by row count and SHA-256 across both runs. The 34 packaged data files also match regenerated run 1. Fifteen JSON arrays parse successfully and have the same row counts as their packaged CSV sources.

The resulting package is self-contained and does not rely on the older CSV snapshots under `data/full_scale/`. The package includes a SQL seed loader validated for schema/table/header compatibility and foreign-key import order. The loader was executed against local MySQL and imported data was checked against the package source.

## 7. Other validation evidence reported during development

The project notes record these additional results from separate validation runs:

- Full-scale master-data validator: 8 checks passed.
- Full-scale operations validator: 131 checks passed.
- Ground-truth/anomaly-output validator: 83 of 83 checks passed for the five deliberate anomaly proposals in CSV and JSON.
- Capacity-history checks: zero coverage gaps and zero overlapping effective periods in the reported scan.
- Baseline anomaly scan: 500 invalid guardian contacts found, with blocking verified for all 500.
- Baseline address scan: 2,500 restricted addresses found, with blocking verified for all 2,500.
- Baseline detections for `CAPACITY_EXCEEDED`, `ACCESSIBILITY_MISMATCH`, and `IMPOSSIBLE_TRAVEL_TIME`: zero. Deliberate examples for those anomaly types were validated separately.
- The 10-minute impossible-travel-time threshold is illustrative and provisional.
- The imported database contains 5,000 students, 100 buses, 300 stops, 20,000 routes, 60,000 route stops, 125 capacity-history records, and 752,480 each of assignments, attendance events, and notification decisions across 200 service dates.
- Imported enum/status distributions and all capacity-history rows were reconciled against their packaged CSV sources. Assignment, attendance, notification, and student/address-zone joins passed direct database checks; effective route capacity checks found no violating routes.
- The first import exposed a CRLF final-column parsing issue: enum-valued final columns were blank, 100 open-ended capacity-history records were omitted, and attendance reason text ended with a carriage return. The loader was corrected to use CRLF line endings; imported records were restored from the source CSVs and revalidated.
- The protected anomaly summary was checked against the imported database. It reports zero capacity, accessibility, and travel-time findings; 500 invalid guardian contacts; and 2,500 restricted addresses. Its capacity check now uses effective-dated capacity history rather than the bus's original capacity.

The packaged CSV validations were rerun for this submission review. The live MySQL import was separately checked for core row counts, status-value reconciliation, capacity-history completeness, and key foreign-key joins.

## 8. Required anomaly scenarios

| Anomaly scenario | Expected outcome | Evidence status |
|---|---|---|
| `CAPACITY_EXCEEDED` | `REJECT` | Deliberate example validated separately; baseline detections reported as zero |
| `ACCESSIBILITY_MISMATCH` | `REJECT` | Deliberate example validated separately; baseline detections reported as zero |
| `IMPOSSIBLE_TRAVEL_TIME` | `FLAG` | Deliberate example validated separately; threshold provisional and baseline detections reported as zero |
| `INVALID_GUARDIAN_CONTACT` | `BLOCK` | Blocking checks reported successful |
| `UNAUTHORIZED_ADDRESS_DISCLOSURE` | `BLOCK` | Blocking checks reported successful |

The five deliberate anomaly examples are kept separate from baseline operational inputs to avoid leaking ground-truth labels into ordinary input features.

## 9. Reproduction commands

Run commands from the project root in the configured Python environment.

Run the end-to-end two-run verifier and create the self-contained full-scale package:

```powershell
python -m generator.check_reproducibility
```

The default package path is `data/full_scale/submission_exports_v4/`.
The verifier refuses to overwrite a non-empty output directory; choose a
new path with `--output` for another run:

```powershell
python -m generator.check_reproducibility --output data/full_scale/submission_exports_next
```

The package contains CSVs in `csv/master/` and `csv/operations/`, JSON
companions in `json/master/` and `json/operations/`, separate ground-truth
definitions/proposals under `ground_truth/`, the SQL seed loader, a
source/provenance manifest, a two-run checksum report, and machine-readable
and Markdown validation summaries. Apply `sql/schema.sql` before importing
the seed; the locally configured full-scale database has already been
imported and verified.

The verifier keeps its temporary regeneration directories isolated and
does not modify the existing files under `data/full_scale/`.

## 10. Limitations and follow-up actions

1. Document and justify the travel-time threshold before treating it as a production rule.
2. Run the complete validation suite against a clean checkout before final release.
3. Confirm that `.env`, credentials, virtual environments, caches, and unintended temporary data are excluded from version control.
4. Keep all student, guardian, address, and contact data synthetic in the public repository.
5. Treat notification decisions and address-disclosure checks as demonstrations; production use would require stronger identity, authorization, privacy, operational, and safety controls.
6. Repeat the import validation in the submission environment if it differs from the verified local MySQL setup.

## 11. Conclusion

The full-scale verifier passed for the configured synthetic dataset: both regeneration runs validated, all 34 compared artifacts matched, the packaged dataset matches regenerated run 1, all 15 JSON exports parsed and reconciled with their CSV sources, and the SQL seed headers matched the schema. The package was also imported and checked in local MySQL. The provisional travel-time threshold and production-hardening limitations remain.
