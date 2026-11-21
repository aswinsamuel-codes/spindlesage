"""Anomaly detectors for Experiment B and the shared alarm policy.

Both detectors are trained on healthy data only and output a score where
higher means more anomalous. They are compared on equal terms:

1. calibrate_threshold() picks each detector's alarm threshold so it flags
   the same fraction of a separate healthy calibration set;
2. apply_alarm_policy() raises an alarm only after `persistence` consecutive
   samples exceed that threshold, for every detector alike.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest

DETECTOR_NAMES: tuple[str, ...] = ("threshold", "isolation_forest")


class ThresholdDetector:
    """Static per-feature alarm limits learned from healthy data.

    Score: the largest signed distance outside the [quantile, 1 - quantile]
    healthy band, in band widths. Negative inside every band.
    """

    def __init__(self, quantile: float = 0.001):
        if not 0.0 <= quantile < 0.5:
            raise ValueError("quantile must be in [0, 0.5)")
        self.quantile = quantile

    def fit(self, X: pd.DataFrame) -> ThresholdDetector:
        self.columns_ = list(X.columns)
        self.low_ = X.quantile(self.quantile).to_numpy(dtype=float)
        self.high_ = X.quantile(1.0 - self.quantile).to_numpy(dtype=float)
        width = self.high_ - self.low_
        self.width_ = np.where(width > 0, width, 1.0)
        return self

    def score(self, X: pd.DataFrame) -> np.ndarray:
        values = X[self.columns_].to_numpy(dtype=float)
        above = (values - self.high_) / self.width_
        below = (self.low_ - values) / self.width_
        return np.maximum(above, below).max(axis=1)


class IsolationForestDetector:
    """Isolation Forest (Liu et al., 2008) on the same features."""

    def __init__(self, n_estimators: int = 200, seed: int = 0, n_jobs: int = 1):
        self.n_estimators = n_estimators
        self.seed = seed
        self.n_jobs = n_jobs

    def fit(self, X: pd.DataFrame) -> IsolationForestDetector:
        self.columns_ = list(X.columns)
        self.model_ = IsolationForest(
            n_estimators=self.n_estimators, random_state=self.seed, n_jobs=self.n_jobs
        ).fit(X[self.columns_].to_numpy(dtype=float))
        return self

    def score(self, X: pd.DataFrame) -> np.ndarray:
        # score_samples is higher for normal points; negate so higher = more anomalous.
        return -self.model_.score_samples(X[self.columns_].to_numpy(dtype=float))


def make_detector(name: str, *, seed: int = 0, n_jobs: int = 1):
    if name == "threshold":
        return ThresholdDetector()
    if name == "isolation_forest":
        return IsolationForestDetector(seed=seed, n_jobs=n_jobs)
    raise ValueError(f"Unknown detector {name!r}; choose from {DETECTOR_NAMES}")


def calibrate_threshold(healthy_scores: np.ndarray, target_false_positive_rate: float) -> float:
    """Score threshold that flags about the target fraction of healthy samples."""
    if not 0.0 < target_false_positive_rate < 1.0:
        raise ValueError("target_false_positive_rate must be between 0 and 1")
    return float(np.quantile(np.asarray(healthy_scores), 1.0 - target_false_positive_rate))


def apply_alarm_policy(
    scores: np.ndarray, machine_ids: np.ndarray, threshold: float, persistence: int = 3
) -> np.ndarray:
    """Alarm when `persistence` consecutive samples of the same machine exceed threshold.

    Rows must be ordered by machine, then time.
    """
    if persistence < 1:
        raise ValueError("persistence must be at least 1")
    scores = np.asarray(scores)
    machine_ids = np.asarray(machine_ids)
    exceed = scores > threshold
    alarm = np.zeros(len(scores), dtype=bool)
    run = 0
    for i in range(len(scores)):
        if i > 0 and machine_ids[i] != machine_ids[i - 1]:
            run = 0
        run = run + 1 if exceed[i] else 0
        alarm[i] = run >= persistence
    return alarm
