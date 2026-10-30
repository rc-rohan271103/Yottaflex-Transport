
"""Positive and negative tests for the Yottaflex anomaly rules."""

from app.anomaly_detector import (
    check_capacity,
    check_accessibility,
    check_travel_time,
    check_guardian_contact,
    check_address_disclosure,
)


def main():
    tests = [
        (
            "GT-001 over capacity",
            check_capacity(31, 30),
            "REJECT",
        ),
        (
            "GT-001 within capacity",
            check_capacity(29, 30),
            "ACCEPT",
        ),
        (
            "GT-002 accessibility mismatch",
            check_accessibility(True, False),
            "REJECT",
        ),
        (
            "GT-002 compatible bus",
            check_accessibility(True, True),
            "ACCEPT",
        ),
        (
            "GT-003 implausibly short travel",
            check_travel_time(2, 8),
            "FLAG",
        ),
        (
            "GT-003 plausible travel",
            check_travel_time(10, 8),
            "ACCEPT",
        ),
        (
            "GT-004 invalid contact",
            check_guardian_contact(False),
            "BLOCK",
        ),
        (
            "GT-004 valid contact",
            check_guardian_contact(True),
            "ALLOW",
        ),
        (
            "GT-005 unauthorized disclosure",
            check_address_disclosure(False, True),
            "BLOCK",
        ),
        (
            "GT-005 both permissions missing",
            check_address_disclosure(False, False), "BLOCK"
        ),
        (
            "GT-005 address permission missing",
             check_address_disclosure(False, True), "BLOCK"
        ),
        (
            "GT-005 requester permission missing",
            check_address_disclosure(True, False), "BLOCK"
        ),
        (
            "GT-005 both permissions present",
            check_address_disclosure(True, True), "ALLOW"
        ),
            
        
    ]

    passed = 0

    for name, actual, expected in tests:
        if actual == expected:
            print(f"PASS: {name}")
            passed += 1
        else:
            print(
                f"FAIL: {name} "
                f"(expected {expected}, got {actual})"
            )

    print(f"\nResults: {passed}/{len(tests)} passed")

    if passed != len(tests):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
