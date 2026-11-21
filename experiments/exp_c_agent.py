"""Run Experiment C (agent recommendation quality by context).

Examples:
    # Rule-based engine only: free, no API key, about a minute on a laptop
    uv run python -m experiments.exp_c_agent

    # Add the Claude engine (needs an API key; prints the run count and asks first)
    uv run python -m experiments.exp_c_agent --engines rules claude
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

from integrations.simulator.scenarios import SCENARIOS
from intelligence.agent.tools import CONTEXT_MODES
from intelligence.evaluation.agent_eval import (
    ENGINES,
    STAGES,
    ExperimentCConfig,
    render_summary_markdown,
    run_experiment_c,
    write_results,
)

DEFAULT_OUTPUT = Path("experiments/results/exp_c")


def main(argv: list[str] | None = None) -> int:
    defaults = ExperimentCConfig()
    parser = argparse.ArgumentParser(description="Experiment C: agent intelligence")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--engines", nargs="+", default=list(defaults.engines), choices=ENGINES)
    parser.add_argument("--modes", nargs="+", default=list(defaults.modes), choices=CONTEXT_MODES)
    parser.add_argument("--scenarios", nargs="+", default=list(SCENARIOS), choices=SCENARIOS)
    parser.add_argument("--seeds", nargs="+", type=int, default=list(defaults.seeds))
    parser.add_argument("--stages", nargs="+", default=list(STAGES), choices=list(STAGES))
    parser.add_argument("--no-risk-model", action="store_true")
    parser.add_argument("--claude-effort", default="high", choices=("low", "medium", "high"))
    parser.add_argument("--yes", action="store_true", help="skip the paid-run confirmation")
    args = parser.parse_args(argv)

    config = ExperimentCConfig(
        engines=tuple(args.engines),
        modes=tuple(args.modes),
        scenarios=tuple(args.scenarios),
        seeds=tuple(args.seeds),
        stages=tuple(args.stages),
        ai4i_path=None if args.no_risk_model else defaults.ai4i_path,
        claude_effort=args.claude_effort,
    )
    if "claude" in config.engines and not args.yes:
        calls = config.case_count() * len(config.modes)
        answer = input(
            f"This makes {calls} Claude API calls ({config.claude_model}, effort "
            f"{config.claude_effort}), which are billed to your account. Continue? [y/N] "
        )
        if answer.strip().lower() not in ("y", "yes"):
            print("Cancelled.")
            return 1

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logging.getLogger("intelligence.evaluation.agent_eval").setLevel(logging.WARNING)
    results = run_experiment_c(config)
    run_dir = write_results(results, args.output)
    print(render_summary_markdown(results))
    print(f"Saved to {run_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
