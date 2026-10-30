"""Test route capacity detection without changing database data."""

from app.anomaly_detector import check_capacity


def main():
    tests = [
        ("Over capacity: 31 passengers, capacity 30", 31, 30, "REJECT"),
        ("Exactly at capacity: 30 passengers, capacity 30", 30, 30, "ACCEPT"),
        ("Below capacity: 12 passengers, capacity 30", 12, 30, "ACCEPT"),
    ]

    passed = 0

    for name, passengers, capacity, expected in tests:
        actual = check_capacity(passengers, capacity)

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