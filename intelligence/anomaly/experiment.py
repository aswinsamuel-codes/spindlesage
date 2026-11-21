"""Experiment B: Isolation Forest vs threshold alarms on a simulated CNC cell.

Protocol, repeated for each seed (all data is SYNTHETIC, from the simulator):

1. Train period: healthy telemetry only. Detectors are fitted here.
2. Calibration period: separate healthy telemetry. Each detector's alarm
   threshold is set so it flags `target_false_positive_rate` of these samples.
3. Test period: telemetry with injected, labelled faults. Scored once.

The three periods follow each other in time and use different random
streams, so the detectors never see test data while fitting or calibrating.
Every detector uses the same features, calibration rule and alarm persistence.
"""

from __future__ import annotations

import logging
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from integrations.simulator.cnc import FAULT_TYPES, SimulationConfig, simulate_cell
from intelligence.anomaly.detectors import (
    DETECTOR_NAMES,
    apply_alarm_policy,
    calibrate_threshold,
    make_detector,
)
from intelligence.anomaly.features import ANOMALY_FEATURE_SETS, build_anomaly_features
from intelligence.evaluation.anomaly import evaluate_alarms
from intelligence.evaluation.classification import mean_std
from intelligence.evaluation.provenance import environment, utc_now_iso, write_run

log = logging.getLogger(__name__)

SIM_START = datetime(2026, 1, 5, tzinfo=UTC)
SUMMARY_METRICS: tuple[str, ...] = (
    "detection_precision",
    "detection_recall",
    "false_alarms_per_hour",
)


@dataclass(frozen=True)
class ExperimentBConfig:
    detectors: tuple[str, ...] = DETECTOR_NAMES
    feature_sets: tuple[str, ...] = ANOMALY_FEATURE_SETS
    seeds: tuple[int, ...] = (0, 1, 2, 3, 4)
    n_machines: int = 3
    train_days: float = 3.0
    calibration_days: float = 1.0
    test_days: float = 3.0
    faults_per_machine: int = 8
    sample_interval_s: float = 30.0
    window: int = 10
    target_false_positive_rate: float = 0.002
    persistence: int = 3
    grace_minutes: float = 10.0
    n_jobs: int = 1

    def __post_init__(self) -> None:
        if not self.detectors or set(self.detectors) - set(DETECTOR_NAMES):
            raise ValueError(f"detectors must be a non-empty subset of {DETECTOR_NAMES}")
        if not self.feature_sets or set(self.feature_sets) - set(ANOMALY_FEATURE_SETS):
            raise ValueError(f"feature_sets must be a non-empty subset of {ANOMALY_FEATURE_SETS}")
        if not self.seeds:
            raise ValueError("at least one seed is required")
        if min(self.train_days, self.calibration_days, self.test_days) <= 0:
            raise ValueError("train, calibration and test periods must be positive")


def _simulate(config: ExperimentBConfig, seed: int, offset_days: float, days: float, faults: int):
    result = simulate_cell(
        SimulationConfig(
            n_machines=config.n_machines,
            start=SIM_START + timedelta(days=offset_days),
            duration=timedelta(days=days),
            sample_interval=timedelta(seconds=config.sample_interval_s),
            faults_per_machine=faults,
            # Distinct random streams per period; fixed per seed for reproducibility.
            seed=seed * 1000 + int(offset_days * 10) + 1,
        )
    )
    readings = result.readings.sort_values(["machine_id", "timestamp"], kind="stable")
    return readings.reset_index(drop=True), result.events


def run_experiment_b(config: ExperimentBConfig) -> dict:
    interval = timedelta(seconds=config.sample_interval_s)
    grace = timedelta(minutes=config.grace_minutes)
    runs = []
    data_summary = []

    for seed in config.seeds:
        train, _ = _simulate(config, seed, 0.0, config.train_days, 0)
        calib, _ = _simulate(config, seed, config.train_days, config.calibration_days, 0)
        test_offset = config.train_days + config.calibration_days
        test, events = _simulate(
            config, seed, test_offset, config.test_days, config.faults_per_machine
        )
        data_summary.append(
            {
                "seed": seed,
                "train_rows": len(train),
                "calibration_rows": len(calib),
                "test_rows": len(test),
                "test_anomalous_rows": int(test["is_anomaly"].sum()),
                "test_events": len(events),
            }
        )

        for feature_set in config.feature_sets:
            X_train = build_anomaly_features(train, feature_set, config.window)
            X_calib = build_anomaly_features(calib, feature_set, config.window)
            X_test = build_anomaly_features(test, feature_set, config.window)

            for name in config.detectors:
                detector = make_detector(name, seed=seed, n_jobs=config.n_jobs)
                started = time.perf_counter()
                detector.fit(X_train)
                fit_seconds = time.perf_counter() - started

                threshold = calibrate_threshold(
                    detector.score(X_calib), config.target_false_positive_rate
                )
                started = time.perf_counter()
                scores = detector.score(X_test)
                score_ms_per_row = (time.perf_counter() - started) * 1000.0 / len(X_test)

                alarm = apply_alarm_policy(
                    scores, test["machine_id"].to_numpy(), threshold, config.persistence
                )
                metrics = evaluate_alarms(test, alarm, events, interval, grace)
                runs.append(
                    {
                        "seed": seed,
                        "detector": name,
                        "feature_set": feature_set,
                        "threshold": threshold,
                        "metrics": metrics,
                        "fit_seconds": fit_seconds,
                        "score_ms_per_row": score_ms_per_row,
                    }
                )
                delay = metrics["detection_delay_s"]
                log.info(
                    "seed=%d %-16s %-10s recall=%.2f precision=%.2f FA/h=%.3f delay=%s",
                    seed,
                    name,
                    feature_set,
                    metrics["detection_recall"],
                    metrics["detection_precision"],
                    metrics["false_alarms_per_hour"],
                    f"{delay['median']:.0f}s" if delay else "n/a",
                )

    return {
        "experiment": "B: anomaly detection, Isolation Forest vs threshold alarms",
        "created_utc": utc_now_iso(),
        "config": asdict(config),
        "dataset": {
            "id": "spindlesage-cnc-simulator",
            "nature": "synthetic",
            "fault_types": list(FAULT_TYPES),
            "per_seed": data_summary,
        },
        "environment": environment(),
        "summary": _summarise(runs, config),
        "runs": runs,
    }


def _summarise(runs: list[dict], config: ExperimentBConfig) -> dict:
    summary = {}
    for feature_set in config.feature_sets:
        for name in config.detectors:
            group = [r for r in runs if r["detector"] == name and r["feature_set"] == feature_set]
            delays = [
                r["metrics"]["detection_delay_s"]["median"]
                for r in group
                if r["metrics"]["detection_delay_s"]
            ]
            per_type = {}
            for fault_type in FAULT_TYPES:
                recalls = [
                    r["metrics"]["per_fault_type"][fault_type]["recall"]
                    for r in group
                    if fault_type in r["metrics"]["per_fault_type"]
                ]
                if recalls:
                    per_type[fault_type] = mean_std(recalls)
            summary[f"{name}/{feature_set}"] = {
                **{m: mean_std([r["metrics"][m] for r in group]) for m in SUMMARY_METRICS},
                "detection_delay_median_s": mean_std(delays) if delays else None,
                "pointwise_f1": mean_std([r["metrics"]["pointwise"]["f1"] for r in group]),
                "recall_by_fault_type": per_type,
                "score_ms_per_row": mean_std([r["score_ms_per_row"] for r in group]),
            }
    return summary


def render_summary_markdown(results: dict) -> str:
    cfg = results["config"]
    lines = [
        "# Experiment B results",
        "",
        f"- Created (UTC): {results['created_utc']}",
        "- Data: SpindleSage CNC simulator (**synthetic**), "
        f"{cfg['n_machines']} machines, {cfg['sample_interval_s']:.0f} s sampling",
        f"- Periods: train {cfg['train_days']} d (healthy), calibration "
        f"{cfg['calibration_days']} d (healthy), test {cfg['test_days']} d with "
        f"{cfg['faults_per_machine']} faults per machine",
        f"- Seeds: {list(cfg['seeds'])}; calibrated healthy flag rate "
        f"{cfg['target_false_positive_rate']}; persistence {cfg['persistence']} samples",
        f"- Host: {results['environment']['host']}, git {results['environment']['git']['commit']}",
        "",
        "Test-period metrics, mean +/- std across seeds:",
        "",
        "| Detector / features | Detection recall | Detection precision | "
        "False alarms per hour | Median delay (min) |",
        "|---|---|---|---|---|",
    ]

    def fmt(stat: dict | None, scale: float = 1.0, digits: int = 3) -> str:
        if not stat:
            return "n/a"
        return f"{stat['mean'] / scale:.{digits}f} +/- {stat['std'] / scale:.{digits}f}"

    for key, s in results["summary"].items():
        lines.append(
            f"| {key} | {fmt(s['detection_recall'])} | {fmt(s['detection_precision'])} | "
            f"{fmt(s['false_alarms_per_hour'])} | "
            f"{fmt(s['detection_delay_median_s'], 60.0, 1)} |"
        )

    lines += ["", "Detection recall by fault type (mean across seeds):", ""]
    header = "| Detector / features | " + " | ".join(FAULT_TYPES) + " |"
    lines += [header, "|---" * (len(FAULT_TYPES) + 1) + "|"]
    for key, s in results["summary"].items():
        cells = [
            f"{s['recall_by_fault_type'][t]['mean']:.2f}"
            if t in s["recall_by_fault_type"]
            else "n/a"
            for t in FAULT_TYPES
        ]
        lines.append(f"| {key} | " + " | ".join(cells) + " |")

    lines += [
        "",
        "All data is simulated. These results compare detectors on a controlled benchmark "
        "and do not demonstrate performance on real machines.",
        "",
    ]
    return "\n".join(lines)


def write_results(results: dict, output_dir: Path) -> Path:
    return write_run(results, output_dir, "anomaly", render_summary_markdown(results))


__all__ = [
    "ExperimentBConfig",
    "render_summary_markdown",
    "run_experiment_b",
    "write_results",
]
