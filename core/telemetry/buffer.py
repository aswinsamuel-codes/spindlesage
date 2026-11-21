"""In-memory recent-telemetry buffer, one bounded window per machine.

Holds what the agent and anomaly monitor need (the last day by default). It
is not long-term storage; TimescaleDB is planned for that.
"""

from __future__ import annotations

import threading
from collections import deque
from dataclasses import dataclass

import pandas as pd

from core.ingestion.validation import ValidationResult, validate_reading
from core.telemetry.schema import SENSOR_FIELDS, CncTelemetryReading


@dataclass(frozen=True)
class IngestOutcome:
    reading: CncTelemetryReading
    accepted: bool
    validation: ValidationResult


class TelemetryBuffer:
    def __init__(self, max_per_machine: int = 2880):
        self.max_per_machine = max_per_machine
        self._data: dict[str, deque[CncTelemetryReading]] = {}
        self._lock = threading.Lock()

    def add(self, reading: CncTelemetryReading) -> IngestOutcome:
        """Validate and store. Readings with validation errors are rejected."""
        with self._lock:
            window = self._data.setdefault(reading.machine_id, deque(maxlen=self.max_per_machine))
            previous = window[-1].timestamp if window else None
            result = validate_reading(reading, previous_timestamp=previous)
            if result.ok:
                window.append(reading)
            return IngestOutcome(reading, result.ok, result)

    def load_frame(self, readings: pd.DataFrame) -> int:
        """Bulk-load readings (e.g. a simulated scenario). Returns rows accepted."""
        accepted = 0
        for record in readings.sort_values("timestamp").to_dict("records"):
            reading = CncTelemetryReading(
                machine_id=record["machine_id"],
                timestamp=pd.Timestamp(record["timestamp"]).to_pydatetime(),
                product_type=record["product_type"],
                **{s: float(record[s]) for s in SENSOR_FIELDS},
            )
            with self._lock:
                window = self._data.setdefault(
                    reading.machine_id, deque(maxlen=self.max_per_machine)
                )
                if window and reading.timestamp <= window[-1].timestamp:
                    continue
                window.append(reading)
                accepted += 1
        return accepted

    def machine_ids(self) -> list[str]:
        with self._lock:
            return sorted(self._data)

    def count(self, machine_id: str) -> int:
        with self._lock:
            return len(self._data.get(machine_id, ()))

    def latest(self, machine_id: str, limit: int = 60) -> list[CncTelemetryReading]:
        with self._lock:
            window = self._data.get(machine_id)
            return list(window)[-limit:] if window else []

    def frame(self, machine_id: str, limit: int | None = None) -> pd.DataFrame:
        with self._lock:
            readings = list(self._data.get(machine_id, ()))
        if limit is not None:
            readings = readings[-limit:]
        columns = ["timestamp", "machine_id", "product_type", *SENSOR_FIELDS]
        if not readings:
            return pd.DataFrame(columns=columns)
        df = pd.DataFrame([r.model_dump() for r in readings])[columns]
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
        return df
