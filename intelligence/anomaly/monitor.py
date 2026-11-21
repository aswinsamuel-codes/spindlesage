"""Online anomaly monitor used by the operations agent.

Uses the threshold detector on contextual features: in Experiment B it had
the best recall, precision and detection delay on the simulated cell (see
research/experiment-log.md), and its alarms can be explained feature by
feature.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from intelligence.anomaly.detectors import (
    ThresholdDetector,
    apply_alarm_policy,
    calibrate_threshold,
)
from intelligence.anomaly.features import build_anomaly_features


@dataclass(frozen=True)
class AnomalyAssessment:
    machine_id: str
    alarm: bool
    score: float
    threshold: float
    consecutive_exceedances: int
    # (feature, exceedance in band widths, "above" or "below" the healthy band)
    top_features: tuple[tuple[str, float, str], ...]
    samples: int

    def to_dict(self) -> dict:
        return {
            "machine_id": self.machine_id,
            "alarm": self.alarm,
            "score": round(self.score, 4),
            "threshold": round(self.threshold, 4),
            "consecutive_exceedances": self.consecutive_exceedances,
            "top_features": [
                {
                    "feature": name,
                    "exceedance_band_widths": round(value, 3),
                    "direction": direction,
                }
                for name, value, direction in self.top_features
            ],
            "samples": self.samples,
        }


class AnomalyMonitor:
    def __init__(
        self,
        feature_set: str = "contextual",
        window: int = 10,
        target_false_positive_rate: float = 0.002,
        persistence: int = 3,
    ):
        self.feature_set = feature_set
        self.window = window
        self.target_false_positive_rate = target_false_positive_rate
        self.persistence = persistence

    def fit(self, healthy_train: pd.DataFrame, healthy_calibration: pd.DataFrame) -> AnomalyMonitor:
        self.detector_ = ThresholdDetector().fit(
            build_anomaly_features(healthy_train, self.feature_set, self.window)
        )
        calib = build_anomaly_features(healthy_calibration, self.feature_set, self.window)
        self.threshold_ = calibrate_threshold(
            self.detector_.score(calib), self.target_false_positive_rate
        )
        return self

    def assess(self, recent: pd.DataFrame, top_k: int = 3) -> AnomalyAssessment:
        """Assess the latest sample of one machine, given its recent history."""
        machines = recent["machine_id"].unique()
        if len(machines) != 1:
            raise ValueError("assess() expects readings from exactly one machine")
        ordered = recent.sort_values("timestamp").reset_index(drop=True)
        X = build_anomaly_features(ordered, self.feature_set, self.window)
        scores = self.detector_.score(X)
        alarm = apply_alarm_policy(
            scores, ordered["machine_id"].to_numpy(), self.threshold_, self.persistence
        )

        consecutive = 0
        for value in scores[::-1]:
            if value <= self.threshold_:
                break
            consecutive += 1

        last_row = X.iloc[[-1]]
        last = self.detector_.exceedance(last_row).iloc[0]
        positive = last[last > 0].sort_values(ascending=False).head(top_k)
        high = dict(zip(self.detector_.columns_, self.detector_.high_, strict=True))
        values = last_row.iloc[0]
        top = tuple(
            (str(name), float(value), "above" if values[name] > high[name] else "below")
            for name, value in positive.items()
        )
        return AnomalyAssessment(
            machine_id=str(machines[0]),
            alarm=bool(alarm[-1]),
            score=float(scores[-1]),
            threshold=float(self.threshold_),
            consecutive_exceedances=consecutive,
            top_features=top,
            samples=len(ordered),
        )
