"""Evidence guard: checks a recommendation against the evidence it cites.

Errors make the recommendation unusable (the agent then falls back to the
rule-based engine). Counts from this guard are the "unsupported claims" and
"evidence attribution" metrics in Experiment C (H3).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from intelligence.agent.evidence import EvidenceBundle
from intelligence.agent.schema import Recommendation

_SUPPORTING_KINDS = {"anomaly", "prediction", "validation"}


@dataclass(frozen=True)
class GuardIssue:
    code: str
    severity: Literal["error", "warning"]
    message: str


@dataclass(frozen=True)
class GuardReport:
    issues: tuple[GuardIssue, ...]
    claims: int
    uncited_claims: int
    unknown_citations: int

    @property
    def passed(self) -> bool:
        return not any(i.severity == "error" for i in self.issues)

    def to_dict(self) -> dict:
        return {
            "passed": self.passed,
            "claims": self.claims,
            "uncited_claims": self.uncited_claims,
            "unknown_citations": self.unknown_citations,
            "issues": [
                {"code": i.code, "severity": i.severity, "message": i.message} for i in self.issues
            ],
        }


def check_recommendation(rec: Recommendation, bundle: EvidenceBundle) -> GuardReport:
    issues: list[GuardIssue] = []
    known = bundle.ids()

    if rec.machine_id != bundle.machine_id:
        issues.append(
            GuardIssue(
                "machine_mismatch",
                "error",
                f"Recommendation is for {rec.machine_id}, evidence is for {bundle.machine_id}",
            )
        )

    claims = [(f"finding {i + 1}", f.evidence_ids) for i, f in enumerate(rec.findings)]
    claims += [(f"action {i + 1}", a.evidence_ids) for i, a in enumerate(rec.actions)]
    uncited = 0
    unknown = 0
    for label, ids in claims:
        if not ids:
            uncited += 1
            issues.append(GuardIssue("uncited_claim", "error", f"{label} cites no evidence"))
        for evidence_id in ids:
            if evidence_id not in known:
                unknown += 1
                issues.append(
                    GuardIssue(
                        "unknown_evidence",
                        "error",
                        f"{label} cites {evidence_id!r}, which is not in the evidence bundle",
                    )
                )

    if not rec.actions:
        issues.append(GuardIssue("no_actions", "error", "Recommendation proposes no action"))

    if rec.risk_level == "high":
        cited = {i for _, ids in claims for i in ids if i in known}
        cited_kinds = {bundle.get(i).kind for i in cited}
        if not cited_kinds & _SUPPORTING_KINDS:
            issues.append(
                GuardIssue(
                    "high_risk_without_support",
                    "error",
                    "High risk is not backed by any cited anomaly, prediction or validation "
                    "evidence",
                )
            )

    for i, action in enumerate(rec.actions):
        if action.action_type == "request_stop" and action.urgency != "immediate":
            issues.append(
                GuardIssue(
                    "stop_not_immediate",
                    "warning",
                    f"action {i + 1} requests a stop without immediate urgency",
                )
            )

    return GuardReport(
        issues=tuple(issues),
        claims=len(claims),
        uncited_claims=uncited,
        unknown_citations=unknown,
    )
