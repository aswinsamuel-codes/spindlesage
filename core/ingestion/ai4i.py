"""Loader for the UCI AI4I 2020 Predictive Maintenance Dataset.

See datasets/metadata/ai4i2020.json for provenance, licence and known quirks.
The dataset is synthetic; it is not real factory data.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pandas as pd

COLUMN_MAP: dict[str, str] = {
    "UDI": "udi",
    "Product ID": "product_id",
    "Type": "product_type",
    "Air temperature [K]": "air_temperature_k",
    "Process temperature [K]": "process_temperature_k",
    "Rotational speed [rpm]": "rotational_speed_rpm",
    "Torque [Nm]": "torque_nm",
    "Tool wear [min]": "tool_wear_min",
    "Machine failure": "machine_failure",
    "TWF": "twf",
    "HDF": "hdf",
    "PWF": "pwf",
    "OSF": "osf",
    "RNF": "rnf",
}

TARGET = "machine_failure"
IDENTIFIER_COLUMNS: tuple[str, ...] = ("udi", "product_id")
FAILURE_MODE_COLUMNS: tuple[str, ...] = ("twf", "hdf", "pwf", "osf", "rnf")
PRODUCT_TYPES: tuple[str, ...] = ("L", "M", "H")

DEFAULT_PATH = Path("datasets/raw/ai4i2020/ai4i2020.csv")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_ai4i(path: Path | str = DEFAULT_PATH) -> pd.DataFrame:
    """Load the AI4I CSV with snake_case column names and checked types."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(
            f"{path} not found. Run: uv run python datasets/download_scripts/download_ai4i.py"
        )

    # The published CSV starts with a UTF-8 byte-order mark.
    raw = pd.read_csv(path, encoding="utf-8-sig")
    missing = [c for c in COLUMN_MAP if c not in raw.columns]
    if missing:
        raise ValueError(f"{path} is missing expected AI4I columns: {missing}")

    df = raw.rename(columns=COLUMN_MAP)[list(COLUMN_MAP.values())].copy()

    unknown_types = set(df["product_type"].unique()) - set(PRODUCT_TYPES)
    if unknown_types:
        raise ValueError(f"Unexpected product_type values: {sorted(unknown_types)}")

    for col in (TARGET, *FAILURE_MODE_COLUMNS):
        values = set(df[col].unique())
        if not values <= {0, 1}:
            raise ValueError(f"Column {col} must be binary 0/1, found {sorted(values)}")
        df[col] = df[col].astype("int8")

    return df
