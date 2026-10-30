USE yottaflex_transport;

SELECT
    guardian_id,
    student_id,
    is_valid,
    consent_status
FROM guardian_contact
WHERE is_valid = TRUE
  AND consent_status = 'DENIED'
LIMIT 5;

USE yottaflex_transport;
SELECT
    g.guardian_id,
    g.student_id,
    e.event_id,
    g.is_valid,
    g.consent_status
FROM guardian_contact g
JOIN attendance_event e
    ON e.student_id = g.student_id
WHERE g.is_valid = TRUE
  AND g.consent_status = 'DENIED'
LIMIT 5;

SELECT
    student_id,
    route_id,
    status
FROM assignment
WHERE student_id = 'STU-000006'
  AND status = 'ASSIGNED'
LIMIT 5;