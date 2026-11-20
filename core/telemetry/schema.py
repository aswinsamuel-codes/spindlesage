"""Telemetry data model for a CNC machining cell.

Hard physical limits live here: a reading that breaks them is rejected outright.
Softer operating-envelope checks (unusual but possible values) live in
core.ingestion.validation and produce warnings instead.
"""

from __future__ import annotations

from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

ProductType = Literal["L", "M", "H"]

SENSOR_FIELDS: tuple[str, ...] = (
    "air_temperature_k",
    "process_temperature_k",
    "rotational_speed_rpm",
    "torque_nm",
    "tool_wear_min",
)


class CncTelemetryReading(BaseModel):
    """One telemetry sample from a CNC machine.

    Timestamps must be timezone-aware so readings from different machines and
    sites can be ordered unambiguously.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    machine_id: str = Field(min_length=1, max_length=64)
    timestamp: AwareDatetime
    product_type: ProductType
    # Absolute temperature cannot be zero or negative; 1000 K is far beyond any machining cell.
    air_temperature_k: float = Field(gt=0, le=1000, allow_inf_nan=False)
    process_temperature_k: float = Field(gt=0, le=1000, allow_inf_nan=False)
    rotational_speed_rpm: float = Field(ge=0, le=60_000, allow_inf_nan=False)
    # Spindle torque magnitude; the AI4I data has no direction component.
    torque_nm: float = Field(ge=0, le=10_000, allow_inf_nan=False)
    tool_wear_min: float = Field(ge=0, le=100_000, allow_inf_nan=False)
