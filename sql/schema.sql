
USE yottaflex_transport_fullscale;

-- 1. Address zones
CREATE TABLE IF NOT EXISTS address_zone (
    zone_id VARCHAR(20) PRIMARY KEY,
    zone_name VARCHAR(100) NOT NULL UNIQUE,
    approved_status ENUM('APPROVED', 'REVIEW') NOT NULL
);

-- Supporting entity: synthetic addresses
CREATE TABLE IF NOT EXISTS address (
    address_id VARCHAR(20) PRIMARY KEY,
    zone_id VARCHAR(20) NOT NULL,
    synthetic_label VARCHAR(150) NOT NULL,
    approval_status ENUM('APPROVED', 'UNAPPROVED') NOT NULL,
    disclosure_authorized BOOLEAN NOT NULL DEFAULT FALSE,
    FOREIGN KEY (zone_id) REFERENCES address_zone(zone_id),
    UNIQUE KEY uq_address_zone (address_id, zone_id)
);

-- 2. Students
CREATE TABLE IF NOT EXISTS student (
    student_id VARCHAR(20) PRIMARY KEY,
    zone_id VARCHAR(20) NOT NULL,
    address_id VARCHAR(20) NOT NULL,
    accessibility_required BOOLEAN NOT NULL DEFAULT FALSE,
    pickup_window_start TIME NOT NULL,
    pickup_window_end TIME NOT NULL,
    status ENUM('ACTIVE', 'INACTIVE') NOT NULL DEFAULT 'ACTIVE',
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (zone_id) REFERENCES address_zone(zone_id),
    FOREIGN KEY (address_id) REFERENCES address(address_id),
    FOREIGN KEY (address_id, zone_id)
        REFERENCES address(address_id, zone_id),
    CHECK (pickup_window_start < pickup_window_end)
);

-- Local API identities. Passwords are PBKDF2 hashes, never plaintext.
CREATE TABLE IF NOT EXISTS app_user (
    username VARCHAR(80) PRIMARY KEY,
    password_hash VARCHAR(255) NOT NULL,
    role ENUM(
        'learner',
        'instructor',
        'academic_administrator',
        'support_staff',
        'platform_administrator'
    ) NOT NULL,
    student_id VARCHAR(20) NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (student_id) REFERENCES student(student_id),
    UNIQUE KEY uq_app_user_student (student_id),
    CHECK (
        (role = 'learner' AND student_id IS NOT NULL)
        OR (role <> 'learner' AND student_id IS NULL)
    )
);

-- 3. Guardian contacts
CREATE TABLE IF NOT EXISTS guardian_contact (
    guardian_id VARCHAR(20) PRIMARY KEY,
    student_id VARCHAR(20) NOT NULL,
    synthetic_phone VARCHAR(30) NOT NULL,
    synthetic_email VARCHAR(150) NOT NULL,
    is_valid BOOLEAN NOT NULL DEFAULT TRUE,
    consent_status ENUM('GRANTED', 'DENIED') NOT NULL,
    FOREIGN KEY (student_id) REFERENCES student(student_id)
);

-- 4. Stops
CREATE TABLE IF NOT EXISTS stop (
    stop_id VARCHAR(20) PRIMARY KEY,
    zone_id VARCHAR(20) NOT NULL,
    x DECIMAL(10,3) NOT NULL,
    y DECIMAL(10,3) NOT NULL,
    approval_status ENUM('APPROVED', 'PENDING') NOT NULL,
    active_status BOOLEAN NOT NULL DEFAULT TRUE,
    FOREIGN KEY (zone_id) REFERENCES address_zone(zone_id)
);

-- 5. Buses
CREATE TABLE IF NOT EXISTS bus (
    bus_id VARCHAR(20) PRIMARY KEY,
    capacity INT NOT NULL,
    is_accessible BOOLEAN NOT NULL DEFAULT FALSE,
    status ENUM('ACTIVE', 'MAINTENANCE') NOT NULL DEFAULT 'ACTIVE',
    CHECK (capacity > 0)
);

-- 6. Drivers
CREATE TABLE IF NOT EXISTS driver (
    driver_id VARCHAR(20) PRIMARY KEY,
    driver_name VARCHAR(100) NOT NULL,
    status ENUM('ACTIVE', 'UNAVAILABLE') NOT NULL DEFAULT 'ACTIVE'
);

-- 7. Routes
CREATE TABLE IF NOT EXISTS route (
    route_id VARCHAR(30) PRIMARY KEY,
    bus_id VARCHAR(20) NOT NULL,
    driver_id VARCHAR(20) NOT NULL,
    service_date DATE NOT NULL,
    status ENUM(
        'PLANNED', 'ACTIVE', 'DISRUPTED',
        'COMPLETED', 'CANCELLED'
    ) NOT NULL DEFAULT 'PLANNED',
    FOREIGN KEY (bus_id) REFERENCES bus(bus_id),
    FOREIGN KEY (driver_id) REFERENCES driver(driver_id),
    UNIQUE KEY uq_bus_service (bus_id, service_date),
    UNIQUE KEY uq_driver_service (driver_id, service_date)
);

-- Instructor access is explicitly granted per route.
CREATE TABLE IF NOT EXISTS instructor_route_scope (
    scope_id VARCHAR(30) PRIMARY KEY,
    username VARCHAR(80) NOT NULL,
    route_id VARCHAR(30) NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (username) REFERENCES app_user(username),
    FOREIGN KEY (route_id) REFERENCES route(route_id),
    UNIQUE KEY uq_instructor_route_scope (username, route_id),
    INDEX idx_instructor_scope_active (username, is_active)
);

-- 8. Route stops
CREATE TABLE IF NOT EXISTS route_stop (
    route_stop_id VARCHAR(30) PRIMARY KEY,
    route_id VARCHAR(30) NOT NULL,
    stop_id VARCHAR(20) NOT NULL,
    sequence_no INT NOT NULL,
    arrival_time TIME NOT NULL,
    travel_minutes INT NOT NULL DEFAULT 0,
    FOREIGN KEY (route_id) REFERENCES route(route_id),
    FOREIGN KEY (stop_id) REFERENCES stop(stop_id),
    UNIQUE KEY uq_route_sequence (route_id, sequence_no),
    UNIQUE KEY uq_route_stop_pair (route_id, stop_id),
    CHECK (sequence_no > 0),
    CHECK (travel_minutes >= 0)
);

-- 9. Assignments
CREATE TABLE IF NOT EXISTS assignment (
    assignment_id VARCHAR(60) PRIMARY KEY,
    student_id VARCHAR(20) NOT NULL,
    route_id VARCHAR(30) NOT NULL,
    stop_id VARCHAR(20) NOT NULL,
    effective_from DATE NOT NULL,
    effective_to DATE NULL,
    status ENUM(
        'ASSIGNED', 'REJECTED', 'ENDED', 'NEEDS_REVIEW'
    ) NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (student_id) REFERENCES student(student_id),
    FOREIGN KEY (route_id) REFERENCES route(route_id),
    FOREIGN KEY (stop_id) REFERENCES stop(stop_id),
    CHECK (
        effective_to IS NULL
        OR effective_to >= effective_from
    ),
    INDEX idx_assignment_student (student_id),
    INDEX idx_assignment_route (route_id)
);

-- 10. Attendance events
CREATE TABLE IF NOT EXISTS attendance_event (
    event_id VARCHAR(30) PRIMARY KEY,
    student_id VARCHAR(20) NOT NULL,
    route_id VARCHAR(30) NOT NULL,
    event_type ENUM(
        'PRESENT', 'ABSENT', 'BOARDED',
        'MISSED_PICKUP', 'DISRUPTION_REASSIGNED'
    ) NOT NULL,
    event_time DATETIME NOT NULL,
    reason VARCHAR(255) NOT NULL,
    FOREIGN KEY (student_id) REFERENCES student(student_id),
    FOREIGN KEY (route_id) REFERENCES route(route_id),
    INDEX idx_attendance_time (event_time)
);

-- 11. Notifications
CREATE TABLE IF NOT EXISTS notification (
    notification_id VARCHAR(30) PRIMARY KEY,
    guardian_id VARCHAR(20) NOT NULL,
    student_id VARCHAR(20) NOT NULL,
    event_id VARCHAR(30) NOT NULL,
    status ENUM(
        'SIMULATED_SENT',
        'BLOCKED_INVALID_CONTACT',
        'BLOCKED_CONSENT',
        'BLOCKED_AUTHORIZATION'
    ) NOT NULL,
    reason VARCHAR(255) NOT NULL,
    created_at DATETIME NOT NULL,
    FOREIGN KEY (guardian_id) REFERENCES guardian_contact(guardian_id),
    FOREIGN KEY (student_id) REFERENCES student(student_id),
    FOREIGN KEY (event_id) REFERENCES attendance_event(event_id),
    UNIQUE KEY uq_notification_event (event_id)
);

-- Supporting table 1: effective-dated bus capacity
CREATE TABLE IF NOT EXISTS bus_capacity_history (
    capacity_history_id VARCHAR(30) PRIMARY KEY,
    bus_id VARCHAR(20) NOT NULL,
    capacity INT NOT NULL,
    effective_from DATE NOT NULL,
    effective_to DATE NULL,
    FOREIGN KEY (bus_id) REFERENCES bus(bus_id),
    CHECK (capacity > 0),
    CHECK (
        effective_to IS NULL
        OR effective_to >= effective_from
    )
);

-- Supporting table 2: route disruptions
CREATE TABLE IF NOT EXISTS route_disruption (
    disruption_id VARCHAR(30) PRIMARY KEY,
    route_id VARCHAR(30) NOT NULL,
    service_date DATE NOT NULL,
    disruption_type VARCHAR(50) NOT NULL,
    severity ENUM('LOW', 'MEDIUM', 'HIGH') NOT NULL,
    status ENUM('RECORDED', 'RESOLVED', 'ESCALATED') NOT NULL,
    FOREIGN KEY (route_id) REFERENCES route(route_id)
);

-- Supporting table 3: assignment decisions
CREATE TABLE IF NOT EXISTS assignment_decision (
    decision_id VARCHAR(30) PRIMARY KEY,
    student_id VARCHAR(20) NOT NULL,
    decision ENUM(
        'ACCEPTED', 'REJECTED', 'UNASSIGNED', 'NEEDS_REVIEW'
    ) NOT NULL,
    reason_code VARCHAR(60) NOT NULL,
    explanation TEXT NOT NULL,
    candidate_count INT NOT NULL DEFAULT 0,
    created_at DATETIME NOT NULL,
    FOREIGN KEY (student_id) REFERENCES student(student_id)
);

-- Supporting table 4: audit history
CREATE TABLE IF NOT EXISTS audit_event (
    audit_id VARCHAR(30) PRIMARY KEY,
    entity_type VARCHAR(50) NOT NULL,
    entity_id VARCHAR(60) NOT NULL,
    action VARCHAR(50) NOT NULL,
    before_json JSON NULL,
    after_json JSON NULL,
    created_at DATETIME NOT NULL,
    correlation_id VARCHAR(60) NOT NULL,
    INDEX idx_audit_entity (entity_type, entity_id, created_at),
    INDEX idx_audit_correlation (correlation_id)
);
