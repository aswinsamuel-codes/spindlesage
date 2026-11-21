"""Run Experiment B (anomaly detection on the simulated CNC cell).

Examples:
    # Quick check on a laptop
    uv run python -m experiments.exp_b_anomaly --seeds 0

    # Full run on a cluster node
    uv run python -m experiments.exp_b_anomaly --n-jobs -1
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

from intelligence.anomaly.detectors import DETECTOR_NAMES
from intelligence.anomaly.experiment import (
    ExperimentBConfig,
    render_summary_markdown,
    run_experiment_b,
    write_results,
)
from intelligence.anomaly.features import ANOMALY_FEATURE_SETS

DEFAULT_OUTPUT = Path("experiments/results/exp_b")


def main(argv: list[str] | None = None) -> int:
    defaults = ExperimentBConfig()
    parser = argparse.ArgumentParser(description="Experiment B: anomaly detection")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--detectors", nargs="+", default=list(DETECTOR_NAMES), choices=DETECTOR_NAMES
    )
    parser.add_argument(
        "--feature-sets",
        nargs="+",
        default=list(ANOMALY_FEATURE_SETS),
        choices=ANOMALY_FEATURE_SETS,
    )
    parser.add_argument("--seeds", nargs="+", type=int, default=list(defaults.seeds))
    parser.add_argument("--machines", type=int, default=defaults.n_machines)
    parser.add_argument("--train-days", type=float, default=defaults.train_days)
    parser.add_argument("--calibration-days", type=float, default=defaults.calibration_days)
    parser.add_argument("--test-days", type=float, default=defaults.test_days)
    parser.add_argument("--faults", type=int, default=defaults.faults_per_machine)
    parser.add_argument("--interval", type=float, default=defaults.sample_interval_s)
    parser.add_argument("--window", type=int, default=defaults.window)
    parser.add_argument(
        "--target-fpr",
        type=float,
        default=defaults.target_false_positive_rate,
        help="fraction of healthy calibration samples allowed above the alarm threshold",
    )
    parser.add_argument("--persistence", type=int, default=defaults.persistence)
    parser.add_argument("--grace-minutes", type=float, default=defaults.grace_minutes)
    parser.add_argument("--n-jobs", type=int, default=defaults.n_jobs, help="-1 uses all cores")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    config = ExperimentBConfig(
        detectors=tuple(args.detectors),
        feature_sets=tuple(args.feature_sets),
        seeds=tuple(args.seeds),
        n_machines=args.machines,
        train_days=args.train_days,
        calibration_days=args.calibration_days,
        test_days=args.test_days,
        faults_per_machine=args.faults,
        sample_interval_s=args.interval,
        window=args.window,
        target_false_positive_rate=args.target_fpr,
        persistence=args.persistence,
        grace_minutes=args.grace_minutes,
        n_jobs=args.n_jobs,
    )
    results = run_experiment_b(config)
    run_dir = write_results(results, args.output)
    print(render_summary_markdown(results))
    print(f"Saved to {run_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
