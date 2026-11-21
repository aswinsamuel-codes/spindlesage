"""The SpindleSage operations agent: gather evidence, reason, check, report.

Workflow (fixed in code, so every step is auditable):

1. gather_evidence(): read-only tools collect the evidence bundle.
2. The primary engine (Claude or rules) proposes a structured recommendation.
3. The guard checks every citation. If the engine fails or the guard finds
   errors, the deterministic rule-based engine is used instead, and the
   reason is recorded.
4. The result carries an approval status. The agent never executes actions:
   anything beyond continue_monitoring stays "pending" until a person
   approves it (the approval workflow itself is built in Week 6).
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from intelligence.agent.engines import EngineError, ReasoningEngine, RuleBasedEngine
from intelligence.agent.evidence import EvidenceBundle
from intelligence.agent.guard import GuardReport, check_recommendation
from intelligence.agent.schema import Recommendation
from intelligence.agent.tools import AgentContext, ContextMode, gather_evidence
from intelligence.evaluation.provenance import utc_now_iso


@dataclass(frozen=True)
class AgentResult:
    recommendation: Recommendation
    evidence: EvidenceBundle
    guard: GuardReport
    engine: str
    primary_engine: str
    fallback_reason: str | None
    primary_guard: GuardReport | None
    llm_usage: dict | None
    latency_s: float
    created_utc: str

    @property
    def approval_status(self) -> str:
        return "pending_approval" if self.recommendation.requires_approval else "not_required"

    def to_dict(self) -> dict:
        return {
            "created_utc": self.created_utc,
            "machine_id": self.recommendation.machine_id,
            "engine": self.engine,
            "primary_engine": self.primary_engine,
            "fallback_reason": self.fallback_reason,
            "approval_status": self.approval_status,
            "recommendation": self.recommendation.model_dump(),
            "guard": self.guard.to_dict(),
            "primary_guard": self.primary_guard.to_dict() if self.primary_guard else None,
            "llm_usage": self.llm_usage,
            "latency_s": round(self.latency_s, 3),
            "evidence": self.evidence.to_dict(),
        }


class OperationsAgent:
    def __init__(
        self,
        context: AgentContext,
        engine: ReasoningEngine | None = None,
        fallback: ReasoningEngine | None = None,
    ):
        self.context = context
        self.engine = engine or RuleBasedEngine()
        self.fallback = fallback or RuleBasedEngine()

    def run(self, machine_id: str, mode: ContextMode = "full") -> AgentResult:
        started = time.perf_counter()
        bundle = gather_evidence(machine_id, self.context, mode)

        engine_used = self.engine.name
        fallback_reason = None
        primary_guard = None
        recommendation = None
        guard = None
        try:
            recommendation = self.engine.recommend(bundle)
            guard = check_recommendation(recommendation, bundle)
            if not guard.passed:
                primary_guard = guard
                fallback_reason = "primary recommendation failed the evidence guard"
        except EngineError as exc:
            fallback_reason = str(exc)

        if fallback_reason is not None:
            recommendation = self.fallback.recommend(bundle)
            guard = check_recommendation(recommendation, bundle)
            engine_used = self.fallback.name

        return AgentResult(
            recommendation=recommendation,
            evidence=bundle,
            guard=guard,
            engine=engine_used,
            primary_engine=self.engine.name,
            fallback_reason=fallback_reason,
            primary_guard=primary_guard,
            llm_usage=getattr(self.engine, "last_usage", None),
            latency_s=time.perf_counter() - started,
            created_utc=utc_now_iso(),
        )
