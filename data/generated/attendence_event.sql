USE yottaflex_transport;
USE yottaflex_transport;

DESCRIBE bus;

USE yottaflex_transport;

SHOW CREATE TABLE attendance_event;
SHOW CREATE TABLE notification;

SHOW COLUMNS FROM yottaflex_transport.attendance_event;
SHOW COLUMNS FROM yottaflex_transport.notification;


USE yottaflex_transport;

SELECT
    event_id,
    student_id,
    route_id,
    event_type,
    event_time,
    reason
FROM attendance_event
WHERE event_id = 'EVT-fde7559ad27e49408eb1';

USE yottaflex_transport;

SELECT
    s.student_id,
    s.zone_id,
    s.address_id,
    s.status AS student_status,
    g.guardian_id,
    g.synthetic_email,
    g.is_valid,
    g.consent_status
FROM student AS s
JOIN guardian_contact AS g
    ON g.student_id = s.student_id
WHERE s.student_id = 'STU-NEW-002';