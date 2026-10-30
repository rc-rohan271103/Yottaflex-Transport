
"""Test notification decisions without connecting to MySQL."""

def decide_notification(is_valid, consent_status, requester_is_authorized):
    if not is_valid:
        return "BLOCKED_INVALID_CONTACT"
    elif consent_status != "GRANTED":
        return "BLOCKED_CONSENT"
    elif not requester_is_authorized:
        return "BLOCKED_AUTHORIZATION"
    return "SIMULATED_SENT"


def main():
    tests = [
        ("Invalid contact", False, "GRANTED", True,
         "BLOCKED_INVALID_CONTACT"),
        ("Denied consent", True, "DENIED", True,
         "BLOCKED_CONSENT"),
        ("Unauthorized requester", True, "GRANTED", False,
         "BLOCKED_AUTHORIZATION"),
        ("All checks pass", True, "GRANTED", True,
         "SIMULATED_SENT"),
        ("Invalid contact takes priority", False, "DENIED", False,
         "BLOCKED_INVALID_CONTACT"),
    ]

    passed = 0

    for name, valid, consent, authorized, expected in tests:
        actual = decide_notification(valid, consent, authorized)

        if actual == expected:
            print(f"PASS: {name}")
            passed += 1
        else:
            print(f"FAIL: {name} (expected {expected}, got {actual})")

    print(f"\nResults: {passed}/{len(tests)} passed")

    if passed != len(tests):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
