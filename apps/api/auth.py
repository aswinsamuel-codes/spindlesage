"""API-key authentication.

Clients send `X-API-Key: <key>`. Only SHA-256 hashes of keys are stored, and
lookups use constant-time comparison. Keys live in a JSON file outside git
(default .spindlesage/api_keys.json); create them with `python -m apps.api.keys`.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
from dataclasses import dataclass
from pathlib import Path

from core.event_engine.roles import Principal, Role

KEY_PREFIX = "ss_"


def generate_key() -> str:
    return KEY_PREFIX + secrets.token_urlsafe(32)


def hash_key(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ApiKeyEntry:
    key_sha256: str
    user_id: str
    role: Role


class ApiKeyRegistry:
    def __init__(self, entries: list[ApiKeyEntry] | None = None):
        self._entries = list(entries or [])
        users = [e.user_id for e in self._entries]
        if len(users) != len(set(users)):
            raise ValueError("Each user may have only one API key entry")

    @classmethod
    def from_file(cls, path: Path | str) -> ApiKeyRegistry:
        path = Path(path)
        if not path.exists():
            return cls([])
        raw = json.loads(path.read_text(encoding="utf-8"))
        return cls(
            [
                ApiKeyEntry(e["key_sha256"], e["user_id"], Role(e["role"]))
                for e in raw.get("keys", [])
            ]
        )

    @classmethod
    def from_plain_keys(cls, keys: dict[str, tuple[str, Role]]) -> ApiKeyRegistry:
        """For tests: {raw_key: (user_id, role)}."""
        return cls([ApiKeyEntry(hash_key(k), user, role) for k, (user, role) in keys.items()])

    def __len__(self) -> int:
        return len(self._entries)

    def users(self) -> list[tuple[str, Role]]:
        return [(e.user_id, e.role) for e in self._entries]

    def authenticate(self, key: str | None) -> Principal | None:
        if not key:
            return None
        digest = hash_key(key)
        match = None
        for entry in self._entries:
            # Check every entry so timing does not reveal which one matched.
            if hmac.compare_digest(entry.key_sha256, digest):
                match = entry
        return Principal(match.user_id, match.role) if match else None

    def save(self, path: Path | str) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "keys": [
                {"key_sha256": e.key_sha256, "user_id": e.user_id, "role": e.role.value}
                for e in self._entries
            ]
        }
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def with_key(self, user_id: str, role: Role) -> tuple[ApiKeyRegistry, str]:
        """Return a registry with a new key for user_id (replacing any old one) and the key."""
        key = generate_key()
        entries = [e for e in self._entries if e.user_id != user_id]
        entries.append(ApiKeyEntry(hash_key(key), user_id, role))
        return ApiKeyRegistry(entries), key
