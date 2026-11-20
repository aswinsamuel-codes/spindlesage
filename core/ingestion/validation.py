"""Telemetry validation rules.

Two severities:

* ERROR: the reading cannot be trusted (missing value, timestamp in the future
  or out of order). It must not feed models or the agent.
* WARNING: the reading is physically possible but outside the expected
  operating envelope. It is kept and flagged, because unusual values are often
  exactly what anomaly detection needs to see.
"""

from __future__ import annotations

from dataclasses import dataclass, field, fields
from datetime import UTC, datetime, timedelta
from enum import StrEnum

import pandas as pd

from core.telemetry.schema import SENSOR_FIELDS, CncTelemetryReading


class Severity(StrEnum):
    WARNING = "warning"
    ERROR = "error"


@dataclass(frozen=True)
class Range:
    low: float
    high: float

    def __post_init__(self) -> None:
        if self.low > self.high:
            raise ValueError(f"Range low {self.low} is above high {self.high}")

    def contains(self, value: float) -> bool:
        return self.low <= value <= self.high


@dataclass(frozen=True)
class OperatingEnvelope:
    """Expected operating ranges for each sensor.

    The defaults are the AI4I 2020 observed ranges widened by a small margin.
    They are placeholders for simulation and benchmarking: real machines need
    limits from their own specifications and history.
    """

    air_temperature_k: Range = field(default_factory=lambda: Range(290.0, 310.0))
    process_temperature_k: Range = field(default_factory=lambda: Range(300.0, 320.0))
    rotational_speed_rpm: Range = field(default_factory=lambda: Range(1000.0, 3000.0))
    torque_nm: Range = field(default_factory=lambda: Range(0.0, 85.0))
    tool_wear_min: Range = field(default_factory=lambda: Range(0.0, 270.0))
    # Process temperature is expected to sit at or above ambient air temperature.
    min_process_minus_air_k: float = 0.0

    def ranges(self) -> dict[str, Range]:
        return {f.name: getattr(self, f.name) for f in fields(self) if f.name in SENSOR_FIELDS}


@dataclass(frozen=True)
class ValidationIssue:
    rule: str
    severity: Severity
    message: str
    field: str | None = None


@dataclass(frozen=True)
class ValidationResult:
    issues: tuple[ValidationIssue, ...] = ()

    @property
    def ok(self) -> bool:
        """True when there are no errors. Warnings do not make a reading invalid."""
        return not any(issue.severity is Severity.ERROR for issue in self.issues)

    @property
    def errors(self) -> tuple[ValidationIssue, ...]:
        return tuple(i for i in self.issues if i.severity is Severity.ERROR)

    @property
    def warnings(self) -> tuple[ValidationIssue, ...]:
        return tuple(i for i in self.issues if i.severity is Severity.WARNING)


def validate_reading(
    reading: CncTelemetryReading,
    envelope: OperatingEnvelope | None = None,
    *,
    previous_timestamp: datetime | None = None,
    now: datetime | None = None,
    max_clock_skew: timedelta = timedelta(minutes=5),
) -> ValidationResult:
    """Check one reading that already passed schema validation."""
    envelope = envelope or OperatingEnvelope()
    now = now or datetime.now(UTC)
    issues: list[ValidationIssue] = []

    for name, allowed in envelope.ranges().items():
        value = getattr(reading, name)
        if not allowed.contains(value):
            issues.append(
                ValidationIssue(
                    rule="outside_envelope",
                    severity=Severity.WARNING,
                    message=(
                        f"{name}={value} outside expected range [{allowed.low}, {allowed.high}]"
                    ),
                    field=name,
                )
            )

    delta = reading.process_temperature_k - reading.air_temperature_k
    if delta < envelope.min_process_minus_air_k:
        issues.append(
            ValidationIssue(
                rule="process_below_air_temperature",
                severity=Severity.WARNING,
                message=f"process temperature is {abs(delta):.2f} K below air temperature",
                field="process_temperature_k",
            )
        )

    if reading.timestamp > now + max_clock_skew:
        issues.append(
            ValidationIssue(
                rule="timestamp_in_future",
                severity=Severity.ERROR,
                message=(
                    f"timestamp {reading.timestamp.isoformat()} is ahead of now {now.isoformat()}"
                ),
                field="timestamp",
            )
        )

    if previous_timestamp is not None and reading.timestamp <= previous_timestamp:
        issues.append(
            ValidationIssue(
                rule="timestamp_not_increasing",
                severity=Severity.ERROR,
                message=(
                    f"timestamp {reading.timestamp.isoformat()} is not after the previous "
                    f"reading {previous_timestamp.isoformat()}"
                ),
                field="timestamp",
            )
        )

    return ValidationResult(tuple(issues))


@dataclass(frozen=True)
class FrameValidationReport:
    """Batch validation summary for a DataFrame of sensor readings."""

    n_rows: int
    counts: dict[str, int]
    severities: dict[str, Severity]
    error_rows: pd.Series

    @property
    def ok(self) -> bool:
        return not bool(self.error_rows.any())

    def to_dict(self) -> dict:
        return {
            "n_rows": self.n_rows,
            "n_error_rows": int(self.error_rows.sum()),
            "rules": {
                rule: {"severity": str(self.severities[rule]), "count": count}
                for rule, count in self.counts.items()
            },
        }


def validate_frame(
    df: pd.DataFrame, envelope: OperatingEnvelope | None = None
) -> FrameValidationReport:
    """Validate a batch of readings that use the SENSOR_FIELDS column names."""
    envelope = envelope or OperatingEnvelope()
    missing_columns = [c for c in SENSOR_FIELDS if c not in df.columns]
    if missing_columns:
        raise ValueError(f"Missing sensor columns: {missing_columns}")

    sensors = df[list(SENSOR_FIELDS)].apply(pd.to_numeric, errors="coerce")
    counts: dict[str, int] = {}
    severities: dict[str, Severity] = {}

    missing = sensors.isna().any(axis=1)
    counts["missing_or_non_numeric"] = int(missing.sum())
    severities["missing_or_non_numeric"] = Severity.ERROR

    for name, allowed in envelope.ranges().items():
        col = sensors[name]
        outside = col.notna() & ((col < allowed.low) | (col > allowed.high))
        rule = f"outside_envelope:{name}"
        counts[rule] = int(outside.sum())
        severities[rule] = Severity.WARNING

    delta = sensors["process_temperature_k"] - sensors["air_temperature_k"]
    below = delta < envelope.min_process_minus_air_k
    counts["process_below_air_temperature"] = int(below.sum())
    severities["process_below_air_temperature"] = Severity.WARNING

    return FrameValidationReport(
        n_rows=len(df), counts=counts, severities=severities, error_rows=missing
    )
