"""Classification metrics and inference latency for Experiment A."""

from __future__ import annotations

import time

import numpy as np
import pandas as pd
from sklearn.metrics import (
    average_precision_score,
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
)

METRIC_NAMES: tuple[str, ...] = ("precision", "recall", "f1", "pr_auc")


def classification_metrics(y_true, y_pred, y_score) -> dict:
    """Precision, recall, F1, PR-AUC (average precision) and the confusion matrix."""
    y_true = np.asarray(y_true)
    y_pred = np.asarray(y_pred)
    tn, fp, fn, tp = confusion_matrix(y_true, y_pred, labels=[0, 1]).ravel()
    return {
        "precision": float(precision_score(y_true, y_pred, zero_division=0)),
        "recall": float(recall_score(y_true, y_pred, zero_division=0)),
        "f1": float(f1_score(y_true, y_pred, zero_division=0)),
        "pr_auc": float(average_precision_score(y_true, y_score)),
        "confusion_matrix": {"tn": int(tn), "fp": int(fp), "fn": int(fn), "tp": int(tp)},
        "n": int(len(y_true)),
        "positives": int(y_true.sum()),
    }


def measure_latency(model, X: pd.DataFrame, *, single_row_samples: int = 50) -> dict:
    """Wall-clock inference latency of predict_proba.

    batch_ms_per_row: one call over all of X, divided by the row count.
    single_row_ms_p50 / p95: repeated one-row calls, closer to streaming use.
    Absolute numbers depend on the machine; compare models on the same host.
    """
    start = time.perf_counter()
    model.predict_proba(X)
    batch_ms = (time.perf_counter() - start) * 1000.0

    n_single = min(single_row_samples, len(X))
    timings = []
    for i in range(n_single):
        row = X.iloc[[i]]
        t0 = time.perf_counter()
        model.predict_proba(row)
        timings.append((time.perf_counter() - t0) * 1000.0)

    return {
        "batch_ms_per_row": batch_ms / max(len(X), 1),
        "single_row_ms_p50": float(np.percentile(timings, 50)) if timings else None,
        "single_row_ms_p95": float(np.percentile(timings, 95)) if timings else None,
    }


def mean_std(values: list[float]) -> dict:
    arr = np.asarray(values, dtype=float)
    return {"mean": float(arr.mean()), "std": float(arr.std(ddof=1)) if len(arr) > 1 else 0.0}
