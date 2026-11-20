"""Experiment A: compare failure-prediction models on AI4I 2020.

Protocol, repeated for each seed:

1. Stratified train/test split (default 80/20). The test split is touched once,
   after all fitting, so no test information leaks into training.
2. Stratified k-fold cross-validation on the training split only, giving a
   mean and spread per model.
3. Refit each model on the full training split, then score the test split and
   measure inference latency.

Results across seeds are aggregated as mean and standard deviation, which is
what the H1 comparison should be based on, not a single lucky split.
"""

from __future__ import annotations

import json
import logging
import os
import platform
import subprocess
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from importlib import metadata
from pathlib import Path

import numpy as np
from sklearn.model_selection import StratifiedKFold, train_test_split

from core.ingestion.ai4i import DEFAULT_PATH, TARGET, load_ai4i, sha256_file
from core.ingestion.validation import validate_frame
from intelligence.evaluation.classification import (
    METRIC_NAMES,
    classification_metrics,
    mean_std,
    measure_latency,
)
from intelligence.predictive.features import FEATURE_SETS, build_features
from intelligence.predictive.models import MODEL_NAMES, make_model

log = logging.getLogger(__name__)

TRACKED_PACKAGES = ("numpy", "pandas", "scikit-learn", "xgboost", "pydantic")


@dataclass(frozen=True)
class ExperimentAConfig:
    data_path: Path = DEFAULT_PATH
    models: tuple[str, ...] = MODEL_NAMES
    feature_set: str = "raw"
    test_size: float = 0.2
    cv_folds: int = 5
    seeds: tuple[int, ...] = (0, 1, 2, 3, 4)
    n_jobs: int = 1
    decision_threshold: float = 0.5

    def __post_init__(self) -> None:
        unknown = set(self.models) - set(MODEL_NAMES)
        if unknown:
            raise ValueError(f"Unknown models {sorted(unknown)}; choose from {MODEL_NAMES}")
        if self.feature_set not in FEATURE_SETS:
            raise ValueError(f"Unknown feature_set {self.feature_set!r}")
        if self.cv_folds < 2:
            raise ValueError("cv_folds must be at least 2")
        if not 0.0 < self.test_size < 1.0:
            raise ValueError("test_size must be between 0 and 1")
        if not self.seeds:
            raise ValueError("at least one seed is required")


def _score(model, X, y, threshold: float) -> dict:
    y_score = model.predict_proba(X)[:, 1]
    y_pred = (y_score >= threshold).astype(int)
    return classification_metrics(y, y_pred, y_score)


def _git_revision() -> dict:
    def run(*args: str) -> str:
        return subprocess.run(
            ["git", *args], capture_output=True, text=True, check=True, timeout=10
        ).stdout.strip()

    try:
        return {"commit": run("rev-parse", "HEAD"), "dirty": bool(run("status", "--porcelain"))}
    except (OSError, subprocess.SubprocessError):
        return {"commit": None, "dirty": None}


def _environment() -> dict:
    versions = {}
    for package in TRACKED_PACKAGES:
        try:
            versions[package] = metadata.version(package)
        except metadata.PackageNotFoundError:
            versions[package] = None
    return {
        "python": platform.python_version(),
        "platform": platform.platform(),
        "host": platform.node(),
        "cpu_count": os.cpu_count(),
        "packages": versions,
        "git": _git_revision(),
    }


def run_experiment_a(config: ExperimentAConfig) -> dict:
    data_path = Path(config.data_path)
    df = load_ai4i(data_path)

    validation = validate_frame(df)
    if not validation.ok:
        raise ValueError(f"Dataset failed validation: {validation.to_dict()}")

    X = build_features(df, config.feature_set)
    y = df[TARGET].to_numpy()
    log.info("Loaded %d rows, %d positives, %d features", len(y), int(y.sum()), X.shape[1])

    runs = []
    for seed in config.seeds:
        X_train, X_test, y_train, y_test = train_test_split(
            X, y, test_size=config.test_size, stratify=y, random_state=seed
        )
        folds = list(
            StratifiedKFold(config.cv_folds, shuffle=True, random_state=seed).split(
                X_train, y_train
            )
        )

        for name in config.models:
            cv = {metric: [] for metric in METRIC_NAMES}
            for train_idx, val_idx in folds:
                model = make_model(
                    name, y_train=y_train[train_idx], seed=seed, n_jobs=config.n_jobs
                )
                model.fit(X_train.iloc[train_idx], y_train[train_idx])
                fold = _score(
                    model, X_train.iloc[val_idx], y_train[val_idx], config.decision_threshold
                )
                for metric in METRIC_NAMES:
                    cv[metric].append(fold[metric])

            model = make_model(name, y_train=y_train, seed=seed, n_jobs=config.n_jobs)
            start = time.perf_counter()
            model.fit(X_train, y_train)
            fit_seconds = time.perf_counter() - start

            test = _score(model, X_test, y_test, config.decision_threshold)
            runs.append(
                {
                    "seed": seed,
                    "model": name,
                    "cv": {metric: mean_std(values) for metric, values in cv.items()},
                    "test": test,
                    "latency": measure_latency(model, X_test),
                    "fit_seconds": fit_seconds,
                }
            )
            log.info(
                "seed=%d %-20s test PR-AUC=%.3f F1=%.3f recall=%.3f",
                seed,
                name,
                test["pr_auc"],
                test["f1"],
                test["recall"],
            )

    summary = {}
    for name in config.models:
        model_runs = [r for r in runs if r["model"] == name]
        summary[name] = {
            **{m: mean_std([r["test"][m] for r in model_runs]) for m in METRIC_NAMES},
            "batch_ms_per_row": mean_std([r["latency"]["batch_ms_per_row"] for r in model_runs]),
            "single_row_ms_p50": mean_std([r["latency"]["single_row_ms_p50"] for r in model_runs]),
        }

    return {
        "experiment": "A: predictive maintenance model comparison",
        "created_utc": datetime.now(UTC).isoformat(timespec="seconds"),
        "config": {**asdict(config), "data_path": str(data_path)},
        "dataset": {
            "id": "ai4i2020",
            "nature": "synthetic",
            "sha256": sha256_file(data_path),
            "rows": int(len(y)),
            "positives": int(y.sum()),
            "features": list(X.columns),
            "validation": validation.to_dict(),
        },
        "environment": _environment(),
        "summary": summary,
        "runs": runs,
    }


def render_summary_markdown(results: dict) -> str:
    cfg = results["config"]
    lines = [
        "# Experiment A results",
        "",
        f"- Created (UTC): {results['created_utc']}",
        f"- Dataset: AI4I 2020 (**synthetic**), {results['dataset']['rows']} rows, "
        f"{results['dataset']['positives']} failures",
        f"- Feature set: `{cfg['feature_set']}`",
        f"- Seeds: {list(cfg['seeds'])}, test size {cfg['test_size']}, "
        f"{cfg['cv_folds']}-fold CV on the training split",
        f"- Decision threshold: {cfg['decision_threshold']}",
        f"- Host: {results['environment']['host']}, git {results['environment']['git']['commit']}",
        "",
        "Held-out test metrics, mean +/- std across seeds:",
        "",
        "| Model | PR-AUC | F1 | Precision | Recall | Latency (ms/row, batch) |",
        "|---|---|---|---|---|---|",
    ]
    for name, s in results["summary"].items():
        cells = [
            f"{s[m]['mean']:.3f} +/- {s[m]['std']:.3f}"
            for m in ("pr_auc", "f1", "precision", "recall")
        ]
        latency = f"{s['batch_ms_per_row']['mean']:.4f}"
        lines.append(f"| {name} | " + " | ".join(cells) + f" | {latency} |")
    lines += [
        "",
        "Results are on a synthetic benchmark and do not demonstrate performance on real machines.",
        "",
    ]
    return "\n".join(lines)


def write_results(results: dict, output_dir: Path) -> Path:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    run_dir = Path(output_dir) / f"{stamp}_{results['config']['feature_set']}"
    run_dir.mkdir(parents=True, exist_ok=False)
    (run_dir / "results.json").write_text(
        json.dumps(results, indent=2, default=_json_default), "utf-8"
    )
    (run_dir / "summary.md").write_text(render_summary_markdown(results), "utf-8")
    return run_dir


def _json_default(value):
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, np.generic):
        return value.item()
    raise TypeError(f"Not JSON serialisable: {type(value).__name__}")
