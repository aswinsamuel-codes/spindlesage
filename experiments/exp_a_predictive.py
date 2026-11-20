"""Run Experiment A (predictive maintenance model comparison).

Examples:
    # Quick check on a laptop: one seed, raw features
    uv run python -m experiments.exp_a_predictive --seeds 0

    # Full run on a cluster node: five seeds, all cores, both feature sets
    uv run python -m experiments.exp_a_predictive --feature-set raw --n-jobs -1
    uv run python -m experiments.exp_a_predictive --feature-set engineered --n-jobs -1
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

from core.ingestion.ai4i import DEFAULT_PATH
from intelligence.predictive.experiment import (
    ExperimentAConfig,
    render_summary_markdown,
    run_experiment_a,
    write_results,
)
from intelligence.predictive.features import FEATURE_SETS
from intelligence.predictive.models import MODEL_NAMES

DEFAULT_OUTPUT = Path("experiments/results/exp_a")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Experiment A: predictive maintenance models")
    parser.add_argument("--data", type=Path, default=DEFAULT_PATH, help="path to ai4i2020.csv")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="results directory")
    parser.add_argument("--models", nargs="+", default=list(MODEL_NAMES), choices=MODEL_NAMES)
    parser.add_argument("--feature-set", default="raw", choices=FEATURE_SETS)
    parser.add_argument("--seeds", nargs="+", type=int, default=[0, 1, 2, 3, 4])
    parser.add_argument("--cv-folds", type=int, default=5)
    parser.add_argument("--test-size", type=float, default=0.2)
    parser.add_argument("--n-jobs", type=int, default=1, help="-1 uses all cores")
    parser.add_argument("--threshold", type=float, default=0.5, help="decision threshold")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    config = ExperimentAConfig(
        data_path=args.data,
        models=tuple(args.models),
        feature_set=args.feature_set,
        test_size=args.test_size,
        cv_folds=args.cv_folds,
        seeds=tuple(args.seeds),
        n_jobs=args.n_jobs,
        decision_threshold=args.threshold,
    )
    results = run_experiment_a(config)
    run_dir = write_results(results, args.output)
    print(render_summary_markdown(results))
    print(f"Saved to {run_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
