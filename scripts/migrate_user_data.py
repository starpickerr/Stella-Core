"""Copy the legacy local user's state into the canonical user directory."""

from __future__ import annotations

import argparse

from common.user_data_migration import migrate_local_default


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--confirm-offline", action="store_true",
                        help="Confirm all Stella desktop and backend processes are stopped")
    args = parser.parse_args()
    if not args.confirm_offline:
        parser.error("stop Stella, then pass --confirm-offline")
    print(migrate_local_default())


if __name__ == "__main__":
    main()
