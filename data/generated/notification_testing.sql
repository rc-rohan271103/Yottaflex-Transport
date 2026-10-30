SELECT
    status,
    effective_from,
    effective_to,
    COUNT(*) AS row_count
FROM assignment
GROUP BY status, effective_from, effective_to
ORDER BY status, effective_from, effective_to;

SELECT
    g.guardian_id,
    g.student_id,
    g.is_valid,
    g.consent_status,
    e.event_id
FROM guardian_contact g
JOIN attendance_event e
    ON e.student_id = g.student_id
WHERE e.event_id = 'EVT-fde7559ad27e49408eb1'
LIMIT 10;
USE yottaflex_transport;

SELECT
    notification_id,
    guardian_id,
    student_id,
    event_id,
    status,
    reason,
    created_at
FROM notification
WHERE notification_id = 'NTF-45238190465345d98acb';

SELECT
    guardian_id,
    student_id,
    is_valid,
    consent_status
FROM guardian_contact
WHERE is_valid = FALSE
LIMIT 5;
USE yottaflex_transport;
SELECT
    guardian_id,
    student_id,
    event_id,
    event_type
FROM guardian_contact
JOIN attendance_event USING (student_id)
WHERE guardian_id = 'GUA-000092'
LIMIT 5;

USE yottaflex_transport;

SELECT
    a.student_id,
    a.route_id,
    a.status,
    r.service_date
FROM assignment a
JOIN route r ON r.route_id = a.route_id
WHERE a.student_id = 'STU-000092'
ORDER BY r.service_date DESC
LIMIT 10;