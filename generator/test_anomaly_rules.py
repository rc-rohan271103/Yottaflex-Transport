
"""Deterministic tests for the five Yottaflex transport anomaly rules.

These tests use isolated synthetic scenarios. They do not modify CSV files
or connect to the database.
"""


def check_capacity(assigned_passengers, bus_capacity):
    return assigned_passengers <= bus_capacity


def check_accessibility(student_needs_accessibility, bus_is_accessible):
    return not student_needs_accessibility or bus_is_accessible


def check_travel_time(travel_minutes, minimum_plausible_minutes):
    return travel_minutes >= minimum_plausible_minutes


def check_guardian_contact(guardian_contact_is_valid):
    return guardian_contact_is_valid == 1


def check_address_disclosure(disclosure_authorized, requester_is_authorized):
    return disclosure_authorized == 1 and requester_is_authorized == 1


def run_test(case_id, description, actual_result, expected_result):
    passed = actual_result == expected_result
    status = "PASS" if passed else "FAIL"
    print(f"{status}: {case_id} - {description}")
    if not passed:
        print(f"       Expected: {expected_result}; got: {actual_result}")
    return passed


def main():
    print("Yottaflex anomaly rule tests")
    print("-" * 40)

    results = []

    # GT-001: Assignment must be rejected if passengers exceed capacity.
    allowed = check_capacity(assigned_passengers=31, bus_capacity=30)
    results.append(
        run_test("GT-001", "Over-capacity assignment is rejected",
                 allowed, False)
    )

    # GT-002: A student requiring accessibility needs an accessible bus.
    allowed = check_accessibility(
        student_needs_accessibility=True,
        bus_is_accessible=False,
    )
    results.append(
        run_test("GT-002", "Incompatible accessibility assignment is rejected",
                 allowed, False)
    )

    # GT-003: A travel leg shorter than the configured minimum is flagged.
    plausible = check_travel_time(
        travel_minutes=2,
        minimum_plausible_minutes=8,
    )
    results.append(
        run_test("GT-003", "Implausibly short travel leg is flagged",
                 plausible, False)
    )

    # GT-004: Invalid guardian contacts must not receive notifications.
    allowed = check_guardian_contact(guardian_contact_is_valid=0)
    results.append(
        run_test("GT-004", "Notification to invalid contact is blocked",
                 allowed, False)
    )

    # GT-005: Both address disclosure and requester authorization are required.
    allowed = check_address_disclosure(
        disclosure_authorized=0,
        requester_is_authorized=0,
    )
    results.append(
        run_test("GT-005", "Unauthorized address disclosure is blocked",
                 allowed, False)
    )

    print("-" * 40)
    passed = sum(results)
    total = len(results)
    print(f"Results: {passed}/{total} passed")

    if passed != total:
        raise SystemExit(1)

    print("PASS: All five isolated anomaly rule tests passed.")


if __name__ == "__main__":
    main()
