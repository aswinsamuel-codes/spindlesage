"""Run the operations agent on a simulated scenario (SYNTHETIC DATA).

Examples:
    # No API key needed: deterministic rule-based engine
    uv run python -m intelligence.agent --scenario spindle_overheat

    # Claude engine (needs ANTHROPIC_API_KEY or an `ant auth login` profile)
    uv run python -m intelligence.agent --scenario torque_spike --engine claude

    # Sensor-only context (the Experiment C baseline)
    uv run python -m intelligence.agent --scenario torque_spike --mode sensor_only
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from intelligence.agent.agent import AgentResult, OperationsAgent
from intelligence.agent.demo import DEMO_MACHINE, SCENARIOS, build_demo_context
from intelligence.agent.engines import DEFAULT_MODEL, ClaudeEngine, RuleBasedEngine
from intelligence.agent.tools import CONTEXT_MODES
from intelligence.evaluation.provenance import json_default


def render(result: AgentResult) -> str:
    rec = result.recommendation
    lines = [
        f"Machine {rec.machine_id} at {result.evidence.as_of}  (SYNTHETIC DATA)",
        f"Engine: {result.engine}"
        + (
            f"  [fell back from {result.primary_engine}: {result.fallback_reason}]"
            if result.fallback_reason
            else ""
        ),
        f"Risk: {rec.risk_level.upper()}   Approval: {result.approval_status}",
        "",
        rec.summary,
        "",
        "Findings:",
        *[f"  - {f.statement}  [{', '.join(f.evidence_ids)}]" for f in rec.findings],
        "Proposed actions (none are executed automatically):",
        *[
            f"  - {a.action_type} ({a.urgency}): {a.description}  [{', '.join(a.evidence_ids)}]"
            for a in rec.actions
        ],
    ]
    if rec.uncertainties:
        lines += ["Uncertainties:", *[f"  - {u}" for u in rec.uncertainties]]
    lines += [
        "",
        f"Evidence guard: {'passed' if result.guard.passed else 'FAILED'} "
        f"({result.guard.claims} claims, {result.guard.uncited_claims} uncited, "
        f"{result.guard.unknown_citations} unknown citations)",
        "Evidence:",
        *[f"  {e.evidence_id:7} {e.title}" for e in result.evidence.items],
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="SpindleSage operations agent demo")
    parser.add_argument("--scenario", default="spindle_overheat", choices=SCENARIOS)
    parser.add_argument("--machine", default=DEMO_MACHINE)
    parser.add_argument("--mode", default="full", choices=CONTEXT_MODES)
    parser.add_argument("--engine", default="rules", choices=("rules", "claude"))
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--effort", default="high", choices=("low", "medium", "high", "xhigh"))
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--json", action="store_true", help="print the full result as JSON")
    parser.add_argument("--audit-log", type=Path, help="append the result to this JSONL file")
    args = parser.parse_args(argv)

    context = build_demo_context(args.scenario, seed=args.seed)
    engine = (
        ClaudeEngine(model=args.model, effort=args.effort)
        if args.engine == "claude"
        else RuleBasedEngine()
    )
    result = OperationsAgent(context, engine).run(args.machine, args.mode)

    payload = {"scenario": args.scenario, "seed": args.seed, **result.to_dict()}
    if args.audit_log:
        args.audit_log.parent.mkdir(parents=True, exist_ok=True)
        with args.audit_log.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(payload, default=json_default) + "\n")

    print(json.dumps(payload, indent=2, default=json_default) if args.json else render(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
