
"""Core validation rules for Yottaflex transport anomalies.

These functions return decisions; they do not modify the database,
send notifications, or disclose addresses.
"""


def check_capacity(assigned_passengers, bus_capacity):
    """Return ACCEPT or REJECT for a proposed assignment."""
    if assigned_passengers > bus_capacity:
        return "REJECT"
    return "ACCEPT"


def check_accessibility(student_needs_accessibility, bus_is_accessible):
    """Reject assignments that cannot meet accessibility needs."""
    if student_needs_accessibility and not bus_is_accessible:
        return "REJECT"
    return "ACCEPT"


def check_travel_time(travel_minutes, minimum_plausible_minutes):
    """Flag a route leg shorter than the configured minimum."""
    if travel_minutes < minimum_plausible_minutes:
        return "FLAG"
    return "ACCEPT"


def check_guardian_contact(guardian_contact_is_valid):
    """Block notifications to contacts marked invalid."""
    if not guardian_contact_is_valid:
        return "BLOCK"
    return "ALLOW"


def check_address_disclosure(disclosure_authorized, requester_is_authorized):
    """Allow disclosure only when both authorizations are present."""
    if not disclosure_authorized or not requester_is_authorized:
        return "BLOCK"
    return "ALLOW"
