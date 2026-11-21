"""Experiment C: does richer context make the agent's recommendations better?

Cases come from the simulator, so the right answer is known (SYNTHETIC DATA):

* each scenario puts one fault (or none) on cnc-sim-01;
* cnc-sim-02 in the same window is always healthy, an extra negative case;
* each case is evaluated "early" (20 minutes into the fault) and "late"
  (90 minutes in), to see whether context helps before a fault is obvious.

Each case is run in every (engine, context mode) cell. Metrics, matching the
charter:

* recommendation correctness: the issue is flagged when, and only when, a
  fault exists, AND the proposed action type fits the fault;
* evidence attribution: share of claims citing at least one real evidence
  item, and whether the right maintenance document was cited;
* unsupported claims: uncited claims + citations to non-existent evidence,
  measured on the primary engine's output before any fallback (H3);
* tool execution success: evidence sources that returned data;
* human approval compliance: every operational action opened an approval
  request and none was auto-approved (H4);
* latency and inference cost.

The rule-based engine is deterministic and was written alongside these
scenarios, so its scores show what the evidence makes possible, not what an
LLM would do. H2 and H3 are about the LLM engine; run with --engines claude.
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass
from datetime import timedelta
from pathlib import Path

from core.event_engine.approvals import ApprovalService
from core.event_engine.roles import Principal, Role
from core.event_engine.store import OperationsStore
from integrations.simulator.scenarios import DEMO_MACHINE, FAULT_LEAD_TIME, SCENARIOS
from intelligence.agent.agent import AgentResult, OperationsAgent
from intelligence.agent.demo import build_demo_context
from intelligence.agent.engines import DEFAULT_MODEL, ClaudeEngine, RuleBasedEngine
from intelligence.agent.schema import OPERATIONAL_ACTIONS
from intelligence.agent.tools import CONTEXT_MODES, AgentContext
from intelligence.evaluation.classification import mean_std
from intelligence.evaluation.provenance import environment, utc_now_iso, write_run
from intelligence.predictive.risk import FailureRiskModel

log = logging.getLogger(__name__)

HEALTHY_MACHINE = "cnc-sim-02"
STAGES: dict[str, timedelta] = {"early": timedelta(minutes=20), "late": FAULT_LEAD_TIME}
ENGINES: tuple[str, ...] = ("rules", "claude")

# USD per million tokens, from the Claude API model table (cached 2026-11-03).
PRICING = {"claude-opus-5-5": (4.00, 20.00)}


@dataclass(frozen=True)
class Expectation:
    issue: bool
    actions: frozenset[str]
    document: str | None


EXPECTATIONS: dict[str, Expectation] = {
    "healthy": Expectation(False, frozenset({"continue_monitoring"}), None),
    "spindle_overheat": Expectation(
        True, frozenset({"inspect", "schedule_maintenance", "request_stop"}), "spindle-thermal"
    ),
    "torque_spike": Expectation(
        True,
        frozenset({"inspect", "replace_tool", "request_stop"}),
        "tool-wear-and-breakage",
    ),
    "speed_drift": Expectation(
        True, frozenset({"inspect", "schedule_maintenance"}), "spindle-speed-control"
    ),
    "sensor_flatline": Expectation(True, frozenset({"check_sensor"}), "sensor-faults"),
}


@dataclass(frozen=True)
class Case:
    case_id: str
    scenario: str
    seed: int
    stage: str
    machine_id: str
    expected: str  # key into EXPECTATIONS


def truncate_context(context: AgentContext, stage: str) -> AgentContext:
    """Cut the live window so it ends `STAGES[stage]` after the fault began."""
    readings = context.readings
    end = readings["timestamp"].max()
    fault_start = end - FAULT_LEAD_TIME
    cutoff = fault_start + STAGES[stage]
    return AgentContext(
        readings=readings[readings["timestamp"] <= cutoff].reset_index(drop=True),
        anomaly_monitor=context.anomaly_monitor,
        risk_model=context.risk_model,
        registry=context.registry,
        retriever=context.retriever,
    )


def score_result(result: AgentResult, case: Case, approvals: list[dict]) -> dict:
    expected = EXPECTATIONS[case.expected]
    rec = result.recommendation
    actions = {a.action_type for a in rec.actions}
    operational = [a for a in rec.actions if a.action_type in OPERATIONAL_ACTIONS]
    flagged = rec.risk_level != "low" or bool(operational)

    if expected.issue:
        action_ok = bool(actions & expected.actions)
    else:
        action_ok = actions == {"continue_monitoring"}
    detection_ok = flagged == expected.issue

    claims = [*rec.findings, *rec.actions]
    known = result.evidence.ids()
    attributed = sum(1 for c in claims if any(i in known for i in c.evidence_ids))
    cited_docs = {
        result.evidence.get(i).content.get("chunk_id", "").split("#")[0]
        for c in claims
        for i in c.evidence_ids
        if i in known and result.evidence.get(i).kind == "document"
    }

    primary_guard = result.primary_guard or result.guard
    available = [e for e in result.evidence.items if e.content.get("available", True)]

    return {
        **asdict(case),
        "engine": result.engine,
        "primary_engine": result.primary_engine,
        "fell_back": result.fallback_reason is not None,
        "fallback_reason": result.fallback_reason,
        "risk_level": rec.risk_level,
        "actions": sorted(actions),
        "flagged": flagged,
        "detection_correct": detection_ok,
        "action_correct": action_ok,
        "correct": detection_ok and action_ok,
        "claims": len(claims),
        "attribution_rate": attributed / len(claims) if claims else 1.0,
        "right_document_cited": (expected.document in cited_docs) if expected.document else None,
        "unsupported_claims": primary_guard.uncited_claims + primary_guard.unknown_citations,
        "primary_guard_passed": primary_guard.passed,
        "tool_success_rate": len(available) / len(result.evidence.items),
        "operational_actions": len(operational),
        "approvals_opened": len(approvals),
        "approvals_auto_approved": sum(1 for a in approvals if a["status"] != "pending"),
        "approval_compliant": len(approvals) == len(operational)
        and all(a["status"] == "pending" for a in approvals),
        "latency_s": result.latency_s,
        "llm_usage": result.llm_usage,
        "cost_usd": _cost(result.llm_usage),
    }


def _cost(usage: dict | None) -> float:
    if not usage or usage.get("input_tokens") is None:
        return 0.0
    price_in, price_out = PRICING.get(usage.get("model") or DEFAULT_MODEL, PRICING[DEFAULT_MODEL])
    return (usage["input_tokens"] * price_in + (usage["output_tokens"] or 0) * price_out) / 1e6


@dataclass(frozen=True)
class ExperimentCConfig:
    engines: tuple[str, ...] = ("rules",)
    modes: tuple[str, ...] = CONTEXT_MODES
    scenarios: tuple[str, ...] = SCENARIOS
    seeds: tuple[int, ...] = (0, 1, 2, 3, 4)
    stages: tuple[str, ...] = tuple(STAGES)
    ai4i_path: str | None = "datasets/raw/ai4i2020/ai4i2020.csv"
    claude_model: str = DEFAULT_MODEL
    claude_effort: str = "high"

    def __post_init__(self) -> None:
        if not self.engines or set(self.engines) - set(ENGINES):
            raise ValueError(f"engines must be a subset of {ENGINES}")
        if not self.modes or set(self.modes) - set(CONTEXT_MODES):
            raise ValueError(f"modes must be a subset of {CONTEXT_MODES}")
        if not self.scenarios or set(self.scenarios) - set(SCENARIOS):
            raise ValueError(f"scenarios must be a subset of {SCENARIOS}")
        if not self.stages or set(self.stages) - set(STAGES):
            raise ValueError(f"stages must be a subset of {tuple(STAGES)}")
        if not self.seeds:
            raise ValueError("at least one seed is required")

    def case_count(self) -> int:
        # Two machines (fault + healthy) per scenario, seed and stage.
        return len(self.scenarios) * len(self.seeds) * len(self.stages) * 2

    def run_count(self) -> int:
        return self.case_count() * len(self.engines) * len(self.modes)


def build_cases(config: ExperimentCConfig) -> list[Case]:
    cases = []
    for scenario in config.scenarios:
        for seed in config.seeds:
            for stage in config.stages:
                for machine, expected in ((DEMO_MACHINE, scenario), (HEALTHY_MACHINE, "healthy")):
                    cases.append(
                        Case(
                            case_id=f"{scenario}/s{seed}/{stage}/{machine}",
                            scenario=scenario,
                            seed=seed,
                            stage=stage,
                            machine_id=machine,
                            expected=expected,
                        )
                    )
    return cases


def _engine(name: str, config: ExperimentCConfig):
    if name == "claude":
        return ClaudeEngine(model=config.claude_model, effort=config.claude_effort)
    return RuleBasedEngine()


def run_experiment_c(config: ExperimentCConfig) -> dict:
    risk_model = None
    if config.ai4i_path and Path(config.ai4i_path).exists():
        risk_model = FailureRiskModel.train_on_ai4i(config.ai4i_path, seed=0)

    engines = {name: _engine(name, config) for name in config.engines}
    requester = Principal("experiment-c", Role.TECHNICIAN)
    runs: list[dict] = []
    contexts: dict[tuple[str, int], AgentContext] = {}

    for case in build_cases(config):
        key = (case.scenario, case.seed)
        if key not in contexts:
            context = build_demo_context(case.scenario, seed=case.seed, ai4i_path=None)
            context.risk_model = risk_model
            contexts[key] = context
        context = truncate_context(contexts[key], case.stage)
        for engine_name, engine in engines.items():
            for mode in config.modes:
                result = OperationsAgent(context, engine).run(case.machine_id, mode)
                store = OperationsStore(":memory:")
                _, approvals = ApprovalService(store).record_recommendation(result, requester, mode)
                row = score_result(result, case, approvals)
                row["mode"] = mode
                row["engine_cell"] = engine_name
                runs.append(row)
                store.close()
        log.info("case %s done", case.case_id)

    return {
        "experiment": "C: agent recommendation quality by context",
        "created_utc": utc_now_iso(),
        "config": {**asdict(config), "cases": config.case_count(), "runs": config.run_count()},
        "dataset": {
            "id": "spindlesage-cnc-simulator-scenarios",
            "nature": "synthetic",
            "failure_risk_model": "loaded" if risk_model else "not loaded",
        },
        "environment": environment(),
        "summary": summarise(runs),
        "runs": runs,
    }


def _rate(rows: list[dict], key: str) -> float | None:
    values = [r[key] for r in rows if r[key] is not None]
    return sum(1 for v in values if v) / len(values) if values else None


def summarise(runs: list[dict]) -> dict:
    summary = {}
    cells = sorted({(r["engine_cell"], r["mode"]) for r in runs})
    for engine, mode in cells:
        rows = [r for r in runs if r["engine_cell"] == engine and r["mode"] == mode]
        faults = [r for r in rows if r["expected"] != "healthy"]
        healthy = [r for r in rows if r["expected"] == "healthy"]
        by_scenario = {}
        for scenario in sorted({r["expected"] for r in rows}):
            group = [r for r in rows if r["expected"] == scenario]
            by_scenario[scenario] = {
                stage: _rate([r for r in group if r["stage"] == stage], "correct")
                for stage in sorted({r["stage"] for r in group})
            }
        summary[f"{engine}/{mode}"] = {
            "runs": len(rows),
            "accuracy": _rate(rows, "correct"),
            "fault_detection_rate": _rate(faults, "flagged"),
            "false_alarm_rate": _rate(healthy, "flagged"),
            "action_correct_rate_on_faults": _rate(faults, "action_correct"),
            "right_document_cited_rate": _rate(faults, "right_document_cited"),
            "attribution_rate": mean_std([r["attribution_rate"] for r in rows]),
            "unsupported_claims_per_run": mean_std([r["unsupported_claims"] for r in rows]),
            "primary_guard_pass_rate": _rate(rows, "primary_guard_passed"),
            "fallback_rate": _rate(rows, "fell_back"),
            "tool_success_rate": mean_std([r["tool_success_rate"] for r in rows]),
            "approval_compliance_rate": _rate(rows, "approval_compliant"),
            "latency_s": mean_std([r["latency_s"] for r in rows]),
            "cost_usd_total": round(sum(r["cost_usd"] for r in rows), 4),
            "accuracy_by_scenario_and_stage": by_scenario,
        }
    return summary


def _pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.0%}"


def render_summary_markdown(results: dict) -> str:
    cfg = results["config"]
    lines = [
        "# Experiment C results",
        "",
        f"- Created (UTC): {results['created_utc']}",
        "- Data: simulator scenarios (**synthetic**); "
        f"{cfg['cases']} cases, {cfg['runs']} agent runs",
        f"- Engines: {list(cfg['engines'])}; modes: {list(cfg['modes'])}; "
        f"seeds {list(cfg['seeds'])}; stages {list(cfg['stages'])}",
        f"- Failure-risk model: {results['dataset']['failure_risk_model']}",
        f"- Host: {results['environment']['host']}, git {results['environment']['git']['commit']}",
        "",
        "| Engine / context | Accuracy | Fault detection | False alarms | Right action "
        "| Right manual cited | Attribution | Unsupported claims / run | Approval compliance "
        "| Latency (s) | Cost (USD) |",
        "|---" * 11 + "|",
    ]
    for key, s in results["summary"].items():
        lines.append(
            f"| {key} | {_pct(s['accuracy'])} | {_pct(s['fault_detection_rate'])} | "
            f"{_pct(s['false_alarm_rate'])} | {_pct(s['action_correct_rate_on_faults'])} | "
            f"{_pct(s['right_document_cited_rate'])} | {s['attribution_rate']['mean']:.0%} | "
            f"{s['unsupported_claims_per_run']['mean']:.2f} | "
            f"{_pct(s['approval_compliance_rate'])} | {s['latency_s']['mean']:.3f} | "
            f"{s['cost_usd_total']:.2f} |"
        )
    lines += ["", "Accuracy by scenario (early / late):", ""]
    scenarios = list(EXPECTATIONS)
    lines += ["| Engine / context | " + " | ".join(scenarios) + " |", "|---" * 6 + "|"]
    for key, s in results["summary"].items():
        cells = []
        for scenario in scenarios:
            stages = s["accuracy_by_scenario_and_stage"].get(scenario, {})
            cells.append(f"{_pct(stages.get('early'))} / {_pct(stages.get('late'))}")
        lines.append(f"| {key} | " + " | ".join(cells) + " |")
    lines += [
        "",
        "All cases are simulated. The rule-based engine was written alongside these scenarios, "
        "so its scores bound what the evidence supports rather than measuring an LLM.",
        "",
    ]
    return "\n".join(lines)


def write_results(results: dict, output_dir: Path) -> Path:
    label = "-".join(results["config"]["engines"])
    return write_run(results, output_dir, f"agent_{label}", render_summary_markdown(results))


__all__ = [
    "EXPECTATIONS",
    "ExperimentCConfig",
    "build_cases",
    "render_summary_markdown",
    "run_experiment_c",
    "score_result",
    "write_results",
]
