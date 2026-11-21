"""Simulated CNC machining cell with labelled fault injection.

SYNTHETIC DATA. Everything produced here is generated, never measured. It
exists so anomaly detection can be evaluated against known fault windows
(start, end, type), which public datasets such as AI4I do not provide.

Model of one machine, sampled at a fixed interval:

* Ambient air temperature: daily cycle plus a slow AR(1) drift.
* Jobs of 20-90 minutes, each with a spindle speed set point and a cutting
  power level; torque follows from power / angular velocity.
* Process temperature: ambient + ~10 K, rising slightly with cutting power.
* Tool wear: minutes of cutting since the last tool change; the tool is
  replaced at 180-220 minutes.

Injected faults (non-overlapping, labelled per sample):

* spindle_overheat: process temperature ramps up by 4-8 K.
* torque_spike:     torque steps up 35-70 % (e.g. a chipped tool).
* speed_drift:      spindle speed ramps down 100-250 rpm below set point.
* sensor_flatline:  one sensor freezes at its last value.

The default parameters are illustrative, not calibrated to a real machine.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import numpy as np
import pandas as pd

from core.telemetry.schema import SENSOR_FIELDS

FAULT_TYPES: tuple[str, ...] = (
    "spindle_overheat",
    "torque_spike",
    "speed_drift",
    "sensor_flatline",
)
FLATLINE_SENSORS: tuple[str, ...] = (
    "air_temperature_k",
    "process_temperature_k",
    "rotational_speed_rpm",
    "torque_nm",
)
NO_FAULT = "none"
_PRODUCT_CYCLE = ("L", "M", "H")
_FAULT_GAP = timedelta(hours=1)


def machine_id_for(index: int) -> str:
    return f"cnc-sim-{index + 1:02d}"


@dataclass(frozen=True)
class FaultEvent:
    machine_id: str
    fault_type: str
    start: datetime
    end: datetime
    magnitude: float
    sensor: str | None = None

    @property
    def duration(self) -> timedelta:
        return self.end - self.start

    def to_dict(self) -> dict:
        return {
            "machine_id": self.machine_id,
            "fault_type": self.fault_type,
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "magnitude": self.magnitude,
            "sensor": self.sensor,
        }


@dataclass(frozen=True)
class SimulationConfig:
    n_machines: int = 3
    start: datetime = datetime(2026, 1, 5, tzinfo=UTC)
    duration: timedelta = timedelta(days=1)
    sample_interval: timedelta = timedelta(seconds=30)
    faults_per_machine: int = 0
    fault_types: tuple[str, ...] = FAULT_TYPES
    min_fault_duration: timedelta = timedelta(minutes=30)
    max_fault_duration: timedelta = timedelta(hours=2)
    seed: int = 0
    # Faults placed at exact times, in addition to the random ones. Used for
    # reproducible scenarios (demos, Experiment C). Avoid overlapping them with
    # random faults by setting faults_per_machine=0.
    scheduled_faults: tuple[FaultEvent, ...] = ()

    def __post_init__(self) -> None:
        if self.n_machines < 1:
            raise ValueError("n_machines must be at least 1")
        if self.start.tzinfo is None:
            raise ValueError("start must be timezone-aware")
        if self.sample_interval <= timedelta(0):
            raise ValueError("sample_interval must be positive")
        if self.duration < self.sample_interval:
            raise ValueError("duration must cover at least one sample")
        if self.faults_per_machine < 0:
            raise ValueError("faults_per_machine cannot be negative")
        unknown = set(self.fault_types) - set(FAULT_TYPES)
        if unknown or not self.fault_types:
            raise ValueError(f"fault_types must be a non-empty subset of {FAULT_TYPES}")
        if not timedelta(0) < self.min_fault_duration <= self.max_fault_duration:
            raise ValueError("need 0 < min_fault_duration <= max_fault_duration")
        known_machines = {machine_id_for(i) for i in range(self.n_machines)}
        for fault in self.scheduled_faults:
            if fault.machine_id not in known_machines:
                raise ValueError(f"Scheduled fault on unknown machine {fault.machine_id!r}")
            if fault.fault_type not in FAULT_TYPES:
                raise ValueError(f"Unknown scheduled fault type {fault.fault_type!r}")
            if fault.end <= fault.start:
                raise ValueError("Scheduled fault must end after it starts")
            if fault.fault_type == "sensor_flatline" and fault.sensor not in FLATLINE_SENSORS:
                raise ValueError(f"sensor_flatline needs a sensor from {FLATLINE_SENSORS}")

    @property
    def n_samples(self) -> int:
        return int(self.duration / self.sample_interval)


@dataclass(frozen=True)
class SimulationResult:
    readings: pd.DataFrame
    events: tuple[FaultEvent, ...]
    config: SimulationConfig


def simulate_cell(config: SimulationConfig) -> SimulationResult:
    """Simulate every machine in the cell. Rows are sorted by machine, then time."""
    times = pd.date_range(config.start, periods=config.n_samples, freq=config.sample_interval)
    frames, events = [], []
    for index in range(config.n_machines):
        # Independent, reproducible random stream per (seed, machine).
        rng = np.random.default_rng([config.seed, index])
        frame, machine_events = _simulate_machine(index, times, config, rng)
        frames.append(frame)
        events.extend(machine_events)

    readings = pd.concat(frames, ignore_index=True)
    readings.attrs["data_nature"] = "synthetic"
    return SimulationResult(readings=readings, events=tuple(events), config=config)


def _ar1(rng: np.random.Generator, n: int, phi: float, sigma: float) -> np.ndarray:
    noise = rng.normal(0.0, sigma, n)
    out = np.empty(n)
    level = 0.0
    for i in range(n):
        level = phi * level + noise[i]
        out[i] = level
    return out


def _simulate_machine(
    index: int, times: pd.DatetimeIndex, config: SimulationConfig, rng: np.random.Generator
) -> tuple[pd.DataFrame, list[FaultEvent]]:
    n = len(times)
    step_s = config.sample_interval.total_seconds()
    hour_of_day = (times.hour + times.minute / 60.0 + times.second / 3600.0).to_numpy()

    air = (
        298.0
        + 1.5 * np.sin(2.0 * math.pi * (hour_of_day - 9.0) / 24.0)
        + _ar1(rng, n, phi=0.995, sigma=0.03)
        + rng.normal(0.0, 0.05, n)
    )

    speed_set = np.empty(n)
    power_set = np.empty(n)
    i = 0
    while i < n:
        length = max(1, int(rng.uniform(20.0, 90.0) * 60.0 / step_s))
        speed_set[i : i + length] = rng.uniform(1300.0, 2200.0)
        power_set[i : i + length] = rng.normal(6000.0, 500.0)
        i += length

    speed = speed_set + rng.normal(0.0, 4.0, n)
    angular_velocity = speed * 2.0 * math.pi / 60.0
    torque = power_set / angular_velocity + rng.normal(0.0, 0.6, n)
    process = air + 10.0 + 0.8 * (power_set / 6000.0 - 1.0) + rng.normal(0.0, 0.08, n)

    wear = np.empty(n)
    current, limit = 0.0, rng.uniform(180.0, 220.0)
    for k in range(n):
        wear[k] = current
        current += step_s / 60.0
        if current >= limit:
            current, limit = 0.0, rng.uniform(180.0, 220.0)

    signals = {
        "air_temperature_k": air,
        "process_temperature_k": process,
        "rotational_speed_rpm": speed,
        "torque_nm": torque,
        "tool_wear_min": wear,
    }

    machine_id = machine_id_for(index)
    events = _place_faults(machine_id, times, config, rng)
    events += [f for f in config.scheduled_faults if f.machine_id == machine_id]
    events.sort(key=lambda e: e.start)
    is_anomaly = np.zeros(n, dtype=bool)
    fault_type = np.full(n, NO_FAULT, dtype=object)
    for event in events:
        mask = (times >= event.start) & (times < event.end)
        count = int(mask.sum())
        if count == 0:
            continue
        ramp = np.linspace(0.0, 1.0, count)
        if event.fault_type == "spindle_overheat":
            signals["process_temperature_k"][mask] += ramp * event.magnitude
        elif event.fault_type == "torque_spike":
            signals["torque_nm"][mask] *= 1.0 + event.magnitude
        elif event.fault_type == "speed_drift":
            signals["rotational_speed_rpm"][mask] -= ramp * event.magnitude
        elif event.fault_type == "sensor_flatline":
            values = signals[event.sensor]
            values[mask] = values[np.argmax(mask)]
        is_anomaly[mask] = True
        fault_type[mask] = event.fault_type

    signals["torque_nm"] = np.clip(signals["torque_nm"], 0.0, None)
    frame = pd.DataFrame(
        {
            "timestamp": times,
            "machine_id": machine_id,
            "product_type": _PRODUCT_CYCLE[index % len(_PRODUCT_CYCLE)],
            **{name: np.round(signals[name], 3) for name in SENSOR_FIELDS},
            "is_anomaly": is_anomaly,
            "fault_type": fault_type,
        }
    )
    return frame, events


def _place_faults(
    machine_id: str, times: pd.DatetimeIndex, config: SimulationConfig, rng: np.random.Generator
) -> list[FaultEvent]:
    if config.faults_per_machine == 0:
        return []

    window_start = times[0].to_pydatetime() + _FAULT_GAP
    window_end = times[-1].to_pydatetime() + config.sample_interval - _FAULT_GAP
    span = config.max_fault_duration - config.min_fault_duration

    placed: list[FaultEvent] = []
    for _ in range(10_000):
        if len(placed) == config.faults_per_machine:
            break
        duration = config.min_fault_duration + span * float(rng.random())
        latest_start = window_end - duration
        if latest_start <= window_start:
            break
        start = window_start + (latest_start - window_start) * float(rng.random())
        end = start + duration
        if any(start < p.end + _FAULT_GAP and p.start < end + _FAULT_GAP for p in placed):
            continue

        fault_type = str(rng.choice(config.fault_types))
        sensor = None
        if fault_type == "spindle_overheat":
            magnitude = float(rng.uniform(4.0, 8.0))
        elif fault_type == "torque_spike":
            magnitude = float(rng.uniform(0.35, 0.7))
        elif fault_type == "speed_drift":
            magnitude = float(rng.uniform(100.0, 250.0))
        else:
            magnitude = 0.0
            sensor = str(rng.choice(FLATLINE_SENSORS))
        placed.append(FaultEvent(machine_id, fault_type, start, end, magnitude, sensor))

    if len(placed) < config.faults_per_machine:
        raise ValueError(
            f"Could only place {len(placed)} of {config.faults_per_machine} faults on "
            f"{machine_id}; increase duration or reduce faults_per_machine"
        )
    return sorted(placed, key=lambda e: e.start)
