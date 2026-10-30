# Yottaflex Anomaly Detection Results

## Current full-scale database check

**Database:** `yottaflex_transport_fullscale`  
**Dataset:** Synthetic, seed `20261022`; 5,000 students, 100 buses, 300 stops, and 200 service dates  
**Travel-time threshold:** 10 minutes (illustrative)

The protected `GET /anomalies/summary` endpoint returned:

| Ground-truth case | Anomaly type | Findings | Interpretation |
|---|---|---:|---|
| GT-001 | Capacity exceeded | 0 | No route exceeds its effective-dated bus capacity |
| GT-002 | Accessibility mismatch | 0 | No assigned student requiring accessibility was found on an inaccessible bus |
| GT-003 | Impossible travel time | 0 | No route leg below the illustrative 10-minute threshold |
| GT-004 | Invalid guardian contact | 500 | Synthetic contacts marked invalid; notification rules block these |
| GT-005 | Unauthorized address disclosure | 2,500 | Synthetic addresses are not eligible for disclosure |
| **Total** | | **3,000** | Aggregate record counts, not necessarily distinct incidents |

This endpoint returns counts only, not the underlying records. GT-003's
threshold is a demonstration rule; it has not been calibrated to road
distance, conditions, or realistic travel speeds.

The GT-001 query uses capacity-history records effective on each route's
service date. Direct database checks found complete capacity-history
coverage and no effective-capacity violations.

## Deliberate anomaly proposals

Five labeled proposals are kept separate from baseline operational input:

| Case | Scenario | Expected decision | Validation |
|---|---|---|---|
| GT-001 | Proposed assignment exceeds bus capacity | `REJECT` | Detected |
| GT-002 | Student's accessibility need is incompatible with the bus | `REJECT` | Detected |
| GT-003 | Proposed route leg takes 2 minutes, below the 10-minute threshold | `FLAG` | Detected |
| GT-004 | Proposed notification targets a contact treated as invalid | `BLOCK` | Detected |
| GT-005 | Proposed exposure of an unapproved address | `BLOCK` | Detected |

The proposals are hypothetical evaluation cases. They do not mutate
baseline rows, leak labels into input features, send messages, or disclose
addresses. The packaged ground-truth validator passed 83 checks for these
cases and their source joins and derived decisions.

## Application safeguards

- Notification simulation and address-access checks require an authenticated
  support or platform-administrator role.
- The requester cannot supply an authorization boolean to bypass the
  authenticated role check; unexpected request fields are rejected.
- Notification outcomes are simulated and persisted locally; no external
  messaging service is connected.
- Address checks return an access decision rather than exposing address
  details.
- The full project test suite passed **45 tests** during the latest
  submission verification.

## Historical initial scan

An earlier read-only scan of the smaller `yottaflex_transport` development
database reported 10 invalid guardian contacts and 50 restricted addresses.
Those are historical counts from that smaller dataset, not the current
full-scale database counts above. No records were changed by that scan.

## Limitations

These are synthetic-data and local-demo results, not evidence of production
readiness or real-world transport safety. The 10-minute travel-time
threshold and generated demand/utilization patterns are illustrative and
should be calibrated before operational use.
