"""Reproducible demo scenarios for the agent (SYNTHETIC DATA).

Each scenario simulates the cell, trains and calibrates the anomaly monitor on
earlier healthy data, and ends the live window while a chosen fault is active
on cnc-sim-01. These scenarios are also the starting point for Experiment C.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from core.ingestion.ai4i import DEFAULT_PATH
from core.machine_registry.registry import DEFAULT_REGISTRY_PATH, MachineRegistry
from integrations.simulator.cnc import FAULT_TYPES, FaultEvent, SimulationConfig, simulate_cell
from intelligence.agent.tools import AgentContext
from intelligence.anomaly.monitor import AnomalyMonitor
from intelligence.predictive.risk import FailureRiskModel
from intelligence.retrieval.bm25 import DEFAULT_CORPUS_DIR, BM25Index

SCENARIOS: tuple[str, ...] = ("healthy", *FAULT_TYPES)
DEMO_MACHINE = "cnc-sim-01"
_BASE = datetime(2026, 1, 5, tzinfo=UTC)
_MAGNITUDE = {
    "spindle_overheat": 7.0,
    "torque_spike": 0.5,
    "speed_drift": 200.0,
    "sensor_flatline": 0.0,
}


def scenario_fault(scenario: str, live_start: datetime, live_duration: timedelta):
    if scenario not in SCENARIOS:
        raise ValueError(f"Unknown scenario {scenario!r}; choose from {SCENARIOS}")
    if scenario == "healthy":
        return ()
    end = live_start + live_duration
    return (
        FaultEvent(
            machine_id=DEMO_MACHINE,
            fault_type=scenario,
            start=end - timedelta(minutes=90),
            end=end,
            magnitude=_MAGNITUDE[scenario],
            sensor="torque_nm" if scenario == "sensor_flatline" else None,
        ),
    )


def build_demo_context(
    scenario: str = "spindle_overheat",
    seed: int = 0,
    ai4i_path: Path | str | None = DEFAULT_PATH,
    registry_path: Path | str = DEFAULT_REGISTRY_PATH,
    corpus_dir: Path | str = DEFAULT_CORPUS_DIR,
    train_days: float = 1.0,
    live_hours: float = 6.0,
) -> AgentContext:
    def sim(offset_days: float, duration: timedelta, sim_seed: int, faults=()):
        return simulate_cell(
            SimulationConfig(
                start=_BASE + timedelta(days=offset_days),
                duration=duration,
                seed=sim_seed,
                scheduled_faults=faults,
            )
        ).readings

    train = sim(0.0, timedelta(days=train_days), seed * 100 + 1)
    calib = sim(train_days, timedelta(days=0.5), seed * 100 + 2)
    live_start = _BASE + timedelta(days=train_days + 0.5)
    live_duration = timedelta(hours=live_hours)
    live = sim(
        train_days + 0.5,
        live_duration,
        seed * 100 + 3,
        scenario_fault(scenario, live_start, live_duration),
    )

    risk_model = None
    if ai4i_path is not None and Path(ai4i_path).exists():
        risk_model = FailureRiskModel.train_on_ai4i(ai4i_path, seed=seed)

    return AgentContext(
        readings=live,
        anomaly_monitor=AnomalyMonitor().fit(train, calib),
        risk_model=risk_model,
        registry=MachineRegistry.from_json(registry_path),
        retriever=BM25Index.from_directory(corpus_dir),
    )
