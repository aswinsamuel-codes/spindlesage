"""Failure-risk model served to the operations agent.

Trained on AI4I 2020 (synthetic) with raw features, the headline setting of
Experiment A. Its probabilities are NOT calibrated for the simulated cell or
for any real machine: the agent must treat them as one weak signal, and the
evidence it passes on says so.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from core.ingestion.ai4i import DEFAULT_PATH, TARGET, load_ai4i, sha256_file
from intelligence.predictive.features import build_features
from intelligence.predictive.models import make_model

CAVEAT = (
    "Model trained on the synthetic AI4I 2020 benchmark; probabilities are not calibrated "
    "for this machine and should be read as a relative signal only."
)


class FailureRiskModel:
    def __init__(self, model, feature_set: str = "raw", provenance: dict | None = None):
        self.model = model
        self.feature_set = feature_set
        self.provenance = provenance or {}

    @classmethod
    def train_on_ai4i(
        cls, path: Path | str = DEFAULT_PATH, seed: int = 0, n_jobs: int = 1
    ) -> FailureRiskModel:
        path = Path(path)
        df = load_ai4i(path)
        X = build_features(df, "raw")
        y = df[TARGET].to_numpy()
        model = make_model("xgboost", y_train=y, seed=seed, n_jobs=n_jobs).fit(X, y)
        return cls(
            model,
            "raw",
            {"model": "xgboost", "dataset": "ai4i2020", "sha256": sha256_file(path), "seed": seed},
        )

    def predict_risk(self, readings: pd.DataFrame) -> np.ndarray:
        """Failure probability per reading. Needs product_type and the sensor columns."""
        X = build_features(readings, self.feature_set)
        return self.model.predict_proba(X)[:, 1]
