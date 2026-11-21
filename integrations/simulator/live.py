"""Live replay of the simulated cell (SYNTHETIC DATA).

Feeds the MQTT publisher and the OPC UA simulation server. A scenario is
simulated up front, then played back sample by sample. `speed` compresses
time: at speed 30, the 30 s sample interval becomes 1 s of wall time.

Readings are re-stamped with the wall-clock time at which they are emitted,
so they look like live data to downstream validation (no future or stale
timestamps). The sample spacing in the stamps is therefore the compressed one.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta

import pandas as pd

from core.telemetry.schema import SENSOR_FIELDS, CncTelemetryReading
from integrations.simulator.cnc import SimulationConfig, simulate_cell
from integrations.simulator.scenarios import scenario_fault

_SIM_START = datetime(2026, 1, 5, tzinfo=UTC)


def scenario_frames(
    scenario: str = "healthy",
    seed: int = 0,
    hours: float = 6.0,
    n_machines: int = 3,
    sample_interval: timedelta = timedelta(seconds=30),
) -> list[pd.DataFrame]:
    """The scenario's readings grouped by sample time, oldest first."""
    duration = timedelta(hours=hours)
    result = simulate_cell(
        SimulationConfig(
            n_machines=n_machines,
            start=_SIM_START,
            duration=duration,
            sample_interval=sample_interval,
            seed=seed,
            scheduled_faults=scenario_fault(scenario, _SIM_START, duration),
        )
    )
    readings = result.readings.sort_values(["timestamp", "machine_id"], kind="stable")
    return [group for _, group in readings.groupby("timestamp", sort=True)]


def live_stream(
    scenario: str = "healthy",
    seed: int = 0,
    speed: float = 30.0,
    hours: float = 6.0,
    n_machines: int = 3,
    sample_interval: timedelta = timedelta(seconds=30),
    loop: bool = False,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    sleep: Callable[[float], None] = time.sleep,
) -> Iterator[list[CncTelemetryReading]]:
    """Yield one batch of readings (one per machine) per compressed sample interval."""
    if speed <= 0:
        raise ValueError("speed must be positive")
    frames = scenario_frames(scenario, seed, hours, n_machines, sample_interval)
    pause = sample_interval.total_seconds() / speed
    last_stamp: datetime | None = None
    while True:
        for frame in frames:
            stamp = clock()
            if last_stamp is not None and stamp <= last_stamp:
                stamp = last_stamp + timedelta(milliseconds=1)
            last_stamp = stamp
            yield [
                CncTelemetryReading(
                    machine_id=row["machine_id"],
                    timestamp=stamp,
                    product_type=row["product_type"],
                    **{s: float(row[s]) for s in SENSOR_FIELDS},
                )
                for row in frame.to_dict("records")
            ]
            sleep(pause)
        if not loop:
            return
