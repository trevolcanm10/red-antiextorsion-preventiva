"""Run with python -m app.cli.bootstrap; never run automatically on startup."""
import argparse
import getpass
import sys
import warnings
from collections.abc import Sequence

from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.schemas.accounts import BootstrapRequest
from app.services.accounts import BootstrapConflict, bootstrap_empty_installation


def session_factory() -> Session:
    # Import only after interactive input: --help/tests never load application DB credentials.
    from app.db.session import SessionLocal
    return SessionLocal()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Provision an EMPTY installation privately")
    parser.add_argument("--organization-name", required=True)
    parser.add_argument("--organization-type")
    parser.add_argument("--admin-name", required=True)
    parser.add_argument("--admin-email", required=True)
    args = parser.parse_args(argv)
    if not sys.stdin.isatty():
        print("An interactive private terminal is required.", file=sys.stderr)
        return 2
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", getpass.GetPassWarning)
            password = getpass.getpass("Initial administrator password (hidden): ")
            confirmation = getpass.getpass("Confirm password (hidden): ")
        if password != confirmation:
            print("Passwords do not match; no changes made.", file=sys.stderr)
            return 2
        payload = BootstrapRequest(
            organization_name=args.organization_name, organization_type=args.organization_type,
            admin_name=args.admin_name, admin_email=args.admin_email, password=password,
        )
        with session_factory() as db:
            result = bootstrap_empty_installation(db, payload)
    except (ValidationError, getpass.GetPassWarning):
        print("Invalid private input or unavailable hidden password entry; no changes committed.", file=sys.stderr)
        return 2
    except BootstrapConflict:
        print("Bootstrap refused: installation must be empty at revision 0002.", file=sys.stderr)
        return 1
    except (EOFError, KeyboardInterrupt):
        print("Bootstrap cancelled.", file=sys.stderr)
        return 2
    except Exception:
        # Never print DB exceptions, payloads, passwords, hashes or connection strings.
        print("Bootstrap failed; no changes committed. Check private server configuration.", file=sys.stderr)
        return 1
    print(f"Created organization {result.organization_id}; administrator {result.administrator_id}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
