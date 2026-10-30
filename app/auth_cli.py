"""Command-line tools for initializing local Yottaflex authentication."""

import argparse
from getpass import getpass

from app.auth import bootstrap_platform_admin


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser(
        "bootstrap-admin",
        help="Create the first platform administrator in an empty user table.",
    )
    args = parser.parse_args()

    if args.command == "bootstrap-admin":
        username = input("Platform administrator username: ").strip()
        password = getpass("Password (hidden): ")
        confirmation = getpass("Confirm password (hidden): ")
        if password != confirmation:
            parser.error("Passwords do not match.")
        try:
            bootstrap_platform_admin(username, password)
        except RuntimeError as exc:
            parser.error(str(exc))
        except ValueError as exc:
            parser.error(str(exc))
        print("First platform administrator created.")
        return 0

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
