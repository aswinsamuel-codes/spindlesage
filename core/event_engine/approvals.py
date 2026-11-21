"""Human approval workflow for agent recommendations.

Every operational action an agent proposes becomes one approval request:

    pending --approve--> approved --complete--> completed
       |
       +--reject--> rejected
       +--(ttl passes)--> expired

Rules enforced here (hypothesis H4):

* Only the maintenance_lead role can approve or reject.
* Four-eyes: the person who requested the recommendation cannot decide on it.
* Rejections, and approvals of request_stop, need a written note.
* Expired requests cannot be approved; a fresh recommendation is needed.
* Only approved actions can be marked completed, by a technician or lead.
* Every state change is written to the hash-chained audit trail in the same
  database transaction, so a change without an audit record cannot happen.

Approving an action records a human decision. It does not send anything to
a machine: SpindleSage has no machine-control path at all.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from enum import StrEnum

from core.event_engine.roles import Permission, Principal
from core.event_engine.store import OperationsStore
from intelligence.agent.agent import AgentResult
from intelligence.agent.schema import OPERATIONAL_ACTIONS
from intelligence.evaluation.provenance import json_default


class ApprovalStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"
    COMPLETED = "completed"


class ApprovalError(Exception):
    """Base class; carries an HTTP-friendly status code."""

    status_code = 400


class NotFoundError(ApprovalError):
    status_code = 404


class ForbiddenError(ApprovalError):
    status_code = 403


class InvalidTransitionError(ApprovalError):
    status_code = 409


def _iso(moment: datetime) -> str:
    return moment.astimezone(UTC).isoformat(timespec="seconds")


class ApprovalService:
    def __init__(
        self,
        store: OperationsStore,
        ttl: timedelta = timedelta(hours=8),
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ):
        self.store = store
        self.ttl = ttl
        self.clock = clock

    @staticmethod
    def _require(principal: Principal, permission: Permission) -> None:
        if not principal.can(permission):
            raise ForbiddenError(
                f"Role {principal.role} is not allowed to {permission.value.replace('_', ' ')}"
            )

    def record_recommendation(
        self, result: AgentResult, principal: Principal, mode: str
    ) -> tuple[str, list[dict]]:
        """Persist an agent result and open one approval request per operational action."""
        self._require(principal, Permission.REQUEST_RECOMMENDATION)
        now = self.clock()
        recommendation_id = str(uuid.uuid4())
        rec = result.recommendation
        payload = json.dumps(result.to_dict(), default=json_default)

        with self.store.transaction() as conn:
            self.store.insert_recommendation(
                conn,
                {
                    "id": recommendation_id,
                    "machine_id": rec.machine_id,
                    "created_utc": _iso(now),
                    "requested_by": principal.user_id,
                    "engine": result.engine,
                    "mode": mode,
                    "risk_level": rec.risk_level,
                    "approval_status": result.approval_status,
                    "payload": payload,
                },
            )
            self.store.append_audit(
                conn,
                ts_utc=_iso(now),
                actor=principal.user_id,
                actor_role=principal.role.value,
                action="recommendation.created",
                subject_type="recommendation",
                subject_id=recommendation_id,
                details={
                    "machine_id": rec.machine_id,
                    "engine": result.engine,
                    "fallback_reason": result.fallback_reason,
                    "risk_level": rec.risk_level,
                    "guard_passed": result.guard.passed,
                    "mode": mode,
                },
            )
            approval_ids = []
            for index, action in enumerate(rec.actions):
                if action.action_type not in OPERATIONAL_ACTIONS:
                    continue
                approval_id = str(uuid.uuid4())
                self.store.insert_approval(
                    conn,
                    {
                        "id": approval_id,
                        "recommendation_id": recommendation_id,
                        "machine_id": rec.machine_id,
                        "action_index": index,
                        "action_type": action.action_type,
                        "urgency": action.urgency,
                        "description": action.description,
                        "evidence_ids": json.dumps(action.evidence_ids),
                        "status": ApprovalStatus.PENDING.value,
                        "requested_by": principal.user_id,
                        "created_utc": _iso(now),
                        "expires_utc": _iso(now + self.ttl),
                    },
                )
                self.store.append_audit(
                    conn,
                    ts_utc=_iso(now),
                    actor=principal.user_id,
                    actor_role=principal.role.value,
                    action="approval.requested",
                    subject_type="approval",
                    subject_id=approval_id,
                    details={
                        "recommendation_id": recommendation_id,
                        "action_type": action.action_type,
                        "urgency": action.urgency,
                    },
                )
                approval_ids.append(approval_id)

        return recommendation_id, [self.store.get_approval(a) for a in approval_ids]

    def _load_pending(self, conn, approval_id: str, now: datetime) -> dict:
        approval = self.store.get_approval(approval_id, conn)
        if approval is None:
            raise NotFoundError(f"Approval {approval_id} not found")
        if approval["status"] == ApprovalStatus.PENDING and now >= datetime.fromisoformat(
            approval["expires_utc"]
        ):
            self.store.update_approval(conn, approval_id, status=ApprovalStatus.EXPIRED.value)
            self.store.append_audit(
                conn,
                ts_utc=_iso(now),
                actor="system",
                actor_role="system",
                action="approval.expired",
                subject_type="approval",
                subject_id=approval_id,
                details={"expires_utc": approval["expires_utc"]},
            )
            approval["status"] = ApprovalStatus.EXPIRED.value
        return approval

    def decide(
        self, approval_id: str, principal: Principal, approve: bool, note: str | None = None
    ) -> dict:
        self._require(principal, Permission.DECIDE_APPROVAL)
        now = self.clock()
        note = (note or "").strip() or None
        with self.store.transaction() as conn:
            approval = self._load_pending(conn, approval_id, now)
            if approval["status"] == ApprovalStatus.EXPIRED:
                # Commit the expiry record, then report the failure.
                expired = True
            else:
                expired = False
                if approval["status"] != ApprovalStatus.PENDING:
                    raise InvalidTransitionError(
                        f"Approval is {approval['status']}; only pending requests can be decided"
                    )
                if principal.user_id == approval["requested_by"]:
                    raise ForbiddenError(
                        "Four-eyes rule: the requester of a recommendation cannot decide on it"
                    )
                if not approve and note is None:
                    raise InvalidTransitionError("A rejection needs a note explaining why")
                if approve and approval["action_type"] == "request_stop" and note is None:
                    raise InvalidTransitionError("Approving a stop request needs a justification")

                status = ApprovalStatus.APPROVED if approve else ApprovalStatus.REJECTED
                self.store.update_approval(
                    conn,
                    approval_id,
                    status=status.value,
                    decided_by=principal.user_id,
                    decided_utc=_iso(now),
                    decision_note=note,
                )
                self.store.append_audit(
                    conn,
                    ts_utc=_iso(now),
                    actor=principal.user_id,
                    actor_role=principal.role.value,
                    action=f"approval.{status.value}",
                    subject_type="approval",
                    subject_id=approval_id,
                    details={
                        "recommendation_id": approval["recommendation_id"],
                        "action_type": approval["action_type"],
                        "note": note,
                    },
                )
        if expired:
            raise InvalidTransitionError("Approval request expired; request a fresh recommendation")
        return self.store.get_approval(approval_id)

    def complete(self, approval_id: str, principal: Principal, note: str | None = None) -> dict:
        self._require(principal, Permission.COMPLETE_ACTION)
        now = self.clock()
        with self.store.transaction() as conn:
            approval = self.store.get_approval(approval_id, conn)
            if approval is None:
                raise NotFoundError(f"Approval {approval_id} not found")
            if approval["status"] != ApprovalStatus.APPROVED:
                raise InvalidTransitionError(
                    f"Approval is {approval['status']}; only approved actions can be completed"
                )
            self.store.update_approval(
                conn,
                approval_id,
                status=ApprovalStatus.COMPLETED.value,
                completed_by=principal.user_id,
                completed_utc=_iso(now),
                completion_note=(note or "").strip() or None,
            )
            self.store.append_audit(
                conn,
                ts_utc=_iso(now),
                actor=principal.user_id,
                actor_role=principal.role.value,
                action="approval.completed",
                subject_type="approval",
                subject_id=approval_id,
                details={"action_type": approval["action_type"], "note": note},
            )
        return self.store.get_approval(approval_id)

    def expire_stale(self) -> int:
        """Mark every pending request past its expiry time as expired."""
        now = self.clock()
        expired = 0
        with self.store.transaction() as conn:
            rows = conn.execute(
                "SELECT id FROM approvals WHERE status = ? AND expires_utc <= ?",
                (ApprovalStatus.PENDING.value, _iso(now)),
            ).fetchall()
            for row in rows:
                self._load_pending(conn, row["id"], now)
                expired += 1
        return expired
