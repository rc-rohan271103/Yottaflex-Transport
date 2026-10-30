"""Pytest-discoverable unit tests for anomaly rules."""
import pytest

from app.anomaly_detector import (
    check_capacity,
    check_accessibility,
    check_travel_time,
    check_guardian_contact,
    check_address_disclosure,
)


@pytest.mark.parametrize(
    ("assigned", "capacity", "expected"),
    [(31, 30, "REJECT"), (30, 30, "ACCEPT"), (29, 30, "ACCEPT")],
)
def test_capacity_rule(assigned, capacity, expected):
    assert check_capacity(assigned, capacity) == expected


@pytest.mark.parametrize(
    ("needs_access", "bus_accessible", "expected"),
    [(True, False, "REJECT"), (True, True, "ACCEPT"), (False, False, "ACCEPT")],
)
def test_accessibility_rule(needs_access, bus_accessible, expected):
    assert check_accessibility(needs_access, bus_accessible) == expected


@pytest.mark.parametrize(
    ("travel", "minimum", "expected"),
    [(9, 10, "FLAG"), (10, 10, "ACCEPT"), (11, 10, "ACCEPT")],
)
def test_travel_time_rule(travel, minimum, expected):
    assert check_travel_time(travel, minimum) == expected


@pytest.mark.parametrize(
    ("valid", "expected"),
    [(False, "BLOCK"), (True, "ALLOW")],
)
def test_guardian_contact_rule(valid, expected):
    assert check_guardian_contact(valid) == expected


@pytest.mark.parametrize(
    ("disclosure_authorized", "requester_authorized", "expected"),
    [
        (False, True, "BLOCK"),
        (True, False, "BLOCK"),
        (False, False, "BLOCK"),
        (True, True, "ALLOW"),
    ],
)
def test_address_disclosure_rule(disclosure_authorized, requester_authorized, expected):
    assert check_address_disclosure(
        disclosure_authorized, requester_authorized
    ) == expected
