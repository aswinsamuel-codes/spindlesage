"""Shared fixtures.

SYNTHETIC TEST DATA ONLY: frames generated here mimic the AI4I column layout so
tests run without network access. They are not real or benchmark data.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from core.ingestion.ai4i import COLUMN_MAP
from core.telemetry.schema import CncTelemetryReading


def make_synthetic_ai4i(n: int = 600, seed: int = 0) -> pd.DataFrame:
    """Raw AI4I-style frame (original column names) with a learnable failure rule."""
    rng = np.random.default_rng(seed)
    air = rng.normal(300.0, 2.0, n)
    process = air + 10.0 + rng.normal(0.0, 1.0, n)
    speed = rng.normal(1540.0, 170.0, n)
    torque = rng.normal(40.0, 10.0, n).clip(4.0, 76.0)
    wear = rng.integers(0, 250, n).astype(float)
    failure = ((wear > 215) | (torque > 62)).astype(int)
    twf = ((wear > 215) & (failure == 1)).astype(int)
    osf = ((torque > 62) & (failure == 1) & (twf == 0)).astype(int)
    product_type = rng.choice(["L", "M", "H"], n, p=[0.6, 0.3, 0.1])

    return pd.DataFrame(
        {
            "UDI": np.arange(1, n + 1),
            "Product ID": [f"{t}{10000 + i}" for i, t in enumerate(product_type)],
            "Type": product_type,
            "Air temperature [K]": air.round(1),
            "Process temperature [K]": process.round(1),
            "Rotational speed [rpm]": speed.round(0),
            "Torque [Nm]": torque.round(1),
            "Tool wear [min]": wear,
            "Machine failure": failure,
            "TWF": twf,
            "HDF": 0,
            "PWF": 0,
            "OSF": osf,
            "RNF": 0,
        }
    )[list(COLUMN_MAP)]


@pytest.fixture
def synthetic_ai4i_csv(tmp_path: Path) -> Path:
    path = tmp_path / "ai4i_synthetic.csv"
    # Written with a BOM, like the published file.
    make_synthetic_ai4i().to_csv(path, index=False, encoding="utf-8-sig")
    return path


@pytest.fixture
def reading() -> CncTelemetryReading:
    return CncTelemetryReading(
        machine_id="cnc-sim-01",
        timestamp=datetime(2026, 1, 1, 12, 0, tzinfo=UTC),
        product_type="M",
        air_temperature_k=300.0,
        process_temperature_k=310.0,
        rotational_speed_rpm=1500.0,
        torque_nm=40.0,
        tool_wear_min=100.0,
    )
