"""Feature construction for failure-risk models.

Leakage guard: identifiers and the failure-mode flags (twf, hdf, pwf, osf, rnf)
are never features. The failure modes are how the AI4I target is defined, so
using them would report near-perfect but meaningless scores.
"""

from __future__ import annotations

import math
from typing import Literal

import pandas as pd

from core.ingestion.ai4i import FAILURE_MODE_COLUMNS, IDENTIFIER_COLUMNS, PRODUCT_TYPES, TARGET
from core.telemetry.schema import SENSOR_FIELDS

FeatureSet = Literal["raw", "engineered"]
FEATURE_SETS: tuple[str, ...] = ("raw", "engineered")

LEAKAGE_COLUMNS: frozenset[str] = frozenset({*IDENTIFIER_COLUMNS, *FAILURE_MODE_COLUMNS, TARGET})

ENGINEERED_FEATURES: tuple[str, ...] = ("temp_delta_k", "mech_power_w", "wear_torque_nm_min")


def build_features(df: pd.DataFrame, feature_set: FeatureSet = "raw") -> pd.DataFrame:
    """Return the model input matrix for the chosen feature set.

    raw:        the five sensor readings plus one-hot product type.
    engineered: raw plus physically motivated combinations (temperature delta,
                mechanical power, wear x torque). Note that these mirror how the
                AI4I synthetic failures were generated, so gains from them say
                more about the dataset than about real machines. Report both.
    """
    if feature_set not in FEATURE_SETS:
        raise ValueError(f"Unknown feature_set {feature_set!r}; choose from {FEATURE_SETS}")

    X = df[list(SENSOR_FIELDS)].astype("float64").copy()
    for product_type in PRODUCT_TYPES:
        X[f"type_{product_type}"] = (df["product_type"] == product_type).astype("float64")

    if feature_set == "engineered":
        X["temp_delta_k"] = X["process_temperature_k"] - X["air_temperature_k"]
        angular_velocity = X["rotational_speed_rpm"] * 2.0 * math.pi / 60.0
        X["mech_power_w"] = X["torque_nm"] * angular_velocity
        X["wear_torque_nm_min"] = X["tool_wear_min"] * X["torque_nm"]

    leaked = LEAKAGE_COLUMNS & set(X.columns)
    if leaked:  # pragma: no cover - defensive, guarded by tests
        raise RuntimeError(f"Leakage columns in features: {sorted(leaked)}")
    return X
