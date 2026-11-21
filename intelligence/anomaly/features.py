"""Features for streaming anomaly detection on CNC telemetry.

raw:        the five sensor readings as they arrive.
contextual: raw plus per-machine rolling variability (catches frozen sensors)
            and physics combinations (temperature rise over ambient, cutting
            power) that separate faults from normal changes such as a new job.

Rolling variability is measured as log10 of the rolling standard deviation.
On a linear scale it is very skewed (a job change can raise it 50-fold), which
squeezes "no variation at all" right next to normal noise; on a log scale a
frozen signal stands far below its healthy band.

Rolling statistics only look backwards, so a score at time t never uses data
from after t. They are computed per machine, never across machines. Each
machine's first sample has no history yet, so its variability is left as NaN;
the detectors fill it with the median they learned from healthy training
data, which keeps the features strictly causal.
"""

from __future__ import annotations

import math
from typing import Literal

import numpy as np
import pandas as pd

from core.telemetry.schema import SENSOR_FIELDS

AnomalyFeatureSet = Literal["raw", "contextual"]
ANOMALY_FEATURE_SETS: tuple[str, ...] = ("raw", "contextual")

# Tool wear rises steadily by design, so its rolling spread carries no signal.
ROLLING_SENSORS: tuple[str, ...] = (
    "air_temperature_k",
    "process_temperature_k",
    "rotational_speed_rpm",
    "torque_nm",
)
ROLLING_SUFFIX = "_log_rolling_std"
# Readings are stored to 0.001, so a spread below 1e-4 means "no variation".
_STD_FLOOR = 1e-4


def build_anomaly_features(
    readings: pd.DataFrame, feature_set: AnomalyFeatureSet = "raw", window: int = 10
) -> pd.DataFrame:
    """Feature matrix aligned to readings.index.

    readings needs timestamp, machine_id and the SENSOR_FIELDS columns.
    """
    if feature_set not in ANOMALY_FEATURE_SETS:
        raise ValueError(f"Unknown feature_set {feature_set!r}; choose {ANOMALY_FEATURE_SETS}")
    if window < 2:
        raise ValueError("window must be at least 2 samples")

    X = readings[list(SENSOR_FIELDS)].astype("float64").copy()
    if feature_set == "raw":
        return X

    ordered = readings.sort_values(["machine_id", "timestamp"], kind="stable")
    grouped = ordered.groupby("machine_id", sort=False)
    for sensor in ROLLING_SENSORS:
        spread = grouped[sensor].transform(lambda s: s.rolling(window, min_periods=2).std())
        X[f"{sensor}{ROLLING_SUFFIX}"] = np.log10(spread.clip(lower=_STD_FLOOR)).reindex(
            readings.index
        )

    X["temp_rise_k"] = X["process_temperature_k"] - X["air_temperature_k"]
    X["mech_power_w"] = X["torque_nm"] * X["rotational_speed_rpm"] * 2.0 * math.pi / 60.0
    return X
