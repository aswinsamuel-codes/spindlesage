"""Manage API keys.

    uv run python -m apps.api.keys add --user alice --role maintenance_lead
    uv run python -m apps.api.keys list

The key is printed once and only its hash is stored. Keep it somewhere safe.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from apps.api.auth import ApiKeyRegistry
from apps.api.settings import Settings
from core.event_engine.roles import Role


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Manage SpindleSage API keys")
    parser.add_argument("--file", type=Path, default=Settings.from_env().api_keys_file)
    sub = parser.add_subparsers(dest="command", required=True)
    add = sub.add_parser("add", help="create or replace a user's key")
    add.add_argument("--user", required=True)
    add.add_argument("--role", required=True, choices=[r.value for r in Role])
    sub.add_parser("list", help="list users and roles (never keys)")
    args = parser.parse_args(argv)

    registry = ApiKeyRegistry.from_file(args.file)
    if args.command == "add":
        registry, key = registry.with_key(args.user, Role(args.role))
        registry.save(args.file)
        print(f"API key for {args.user} ({args.role}). It is shown only once:\n\n  {key}\n")
        print(f"Stored its hash in {args.file}")
    else:
        for user_id, role in registry.users():
            print(f"{user_id:20} {role.value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
