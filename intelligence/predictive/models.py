"""Models compared in Experiment A, plus the threshold baseline used to test H1."""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.base import BaseEstimator, ClassifierMixin
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from xgboost import XGBClassifier

from core.telemetry.schema import SENSOR_FIELDS

MODEL_NAMES: tuple[str, ...] = (
    "threshold_baseline",
    "logistic_regression",
    "random_forest",
    "xgboost",
)


class SensorThresholdBaseline(ClassifierMixin, BaseEstimator):
    """Classic alarm-limit baseline.

    On fit, learns a [quantile, 1 - quantile] band per sensor from healthy
    training samples only. A sample is flagged as a failure when any sensor
    leaves its band. This mirrors fixed alarm limits common in plant SCADA
    systems and is the "simple threshold-based approach" in hypothesis H1.

    The score is the largest signed distance to a band edge, in band widths:
    negative inside every band, positive once any sensor is outside. That gives
    a continuous ranking for PR-AUC while predict() stays a plain limit check.
    """

    def __init__(self, features: tuple[str, ...] = SENSOR_FIELDS, quantile: float = 0.01):
        self.features = features
        self.quantile = quantile

    def fit(self, X: pd.DataFrame, y) -> SensorThresholdBaseline:
        if not 0.0 <= self.quantile < 0.5:
            raise ValueError("quantile must be in [0, 0.5)")
        y = np.asarray(y)
        healthy = X.loc[y == 0, list(self.features)]
        if healthy.empty:
            raise ValueError("Threshold baseline needs at least one healthy (y=0) sample")
        self.low_ = healthy.quantile(self.quantile).to_numpy(dtype=float)
        self.high_ = healthy.quantile(1.0 - self.quantile).to_numpy(dtype=float)
        width = self.high_ - self.low_
        self.width_ = np.where(width > 0, width, 1.0)
        self.classes_ = np.array([0, 1])
        return self

    def decision_function(self, X: pd.DataFrame) -> np.ndarray:
        values = X[list(self.features)].to_numpy(dtype=float)
        above = (values - self.high_) / self.width_
        below = (self.low_ - values) / self.width_
        return np.maximum(above, below).max(axis=1)

    def predict_proba(self, X: pd.DataFrame) -> np.ndarray:
        # Logistic squashing keeps the ranking and maps the band edge to 0.5.
        p1 = 1.0 / (1.0 + np.exp(-10.0 * self.decision_function(X)))
        return np.column_stack([1.0 - p1, p1])

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        return (self.decision_function(X) > 0).astype(int)


def make_model(name: str, *, y_train, seed: int, n_jobs: int = 1):
    """Build an unfitted model. y_train is used only for class-imbalance weighting."""
    y_train = np.asarray(y_train)
    positives = int(y_train.sum())
    negatives = int(len(y_train) - positives)

    if name == "threshold_baseline":
        return SensorThresholdBaseline()
    if name == "logistic_regression":
        return make_pipeline(
            StandardScaler(),
            LogisticRegression(class_weight="balanced", max_iter=2000, random_state=seed),
        )
    if name == "random_forest":
        return RandomForestClassifier(
            n_estimators=300,
            min_samples_leaf=2,
            class_weight="balanced_subsample",
            n_jobs=n_jobs,
            random_state=seed,
        )
    if name == "xgboost":
        return XGBClassifier(
            n_estimators=300,
            max_depth=4,
            learning_rate=0.1,
            subsample=0.9,
            colsample_bytree=0.9,
            scale_pos_weight=negatives / max(positives, 1),
            eval_metric="aucpr",
            tree_method="hist",
            n_jobs=n_jobs,
            random_state=seed,
        )
    raise ValueError(f"Unknown model {name!r}; choose from {MODEL_NAMES}")
