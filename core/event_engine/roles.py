"""Roles and permissions (role-based access control).

Separation of duties is deliberate: an admin runs the system but does not
approve maintenance actions, and the telemetry service account can only send
data. Nobody, including the agent, has a permission that controls a machine.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class Role(StrEnum):
    VIEWER = "viewer"
    INGEST = "ingest"
    TECHNICIAN = "technician"
    MAINTENANCE_LEAD = "maintenance_lead"
    ADMIN = "admin"


class Permission(StrEnum):
    READ = "read"
    INGEST_TELEMETRY = "ingest_telemetry"
    REQUEST_RECOMMENDATION = "request_recommendation"
    DECIDE_APPROVAL = "decide_approval"
    COMPLETE_ACTION = "complete_action"
    READ_AUDIT = "read_audit"


ROLE_PERMISSIONS: dict[Role, frozenset[Permission]] = {
    Role.VIEWER: frozenset({Permission.READ}),
    Role.INGEST: frozenset({Permission.INGEST_TELEMETRY}),
    Role.TECHNICIAN: frozenset(
        {Permission.READ, Permission.REQUEST_RECOMMENDATION, Permission.COMPLETE_ACTION}
    ),
    Role.MAINTENANCE_LEAD: frozenset(
        {
            Permission.READ,
            Permission.REQUEST_RECOMMENDATION,
            Permission.DECIDE_APPROVAL,
            Permission.COMPLETE_ACTION,
            Permission.READ_AUDIT,
        }
    ),
    Role.ADMIN: frozenset({Permission.READ, Permission.INGEST_TELEMETRY, Permission.READ_AUDIT}),
}


@dataclass(frozen=True)
class Principal:
    user_id: str
    role: Role

    def can(self, permission: Permission) -> bool:
        return permission in ROLE_PERMISSIONS[self.role]


SYSTEM = Principal("spindlesage-agent", Role.VIEWER)
