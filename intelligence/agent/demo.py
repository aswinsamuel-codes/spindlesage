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
from integrations.simulator.cnc import SimulationConfig, simulate_cell
from integrations.simulator.scenarios import DEMO_MACHINE, SCENARIOS, scenario_fault
from intelligence.agent.tools import AgentContext
from intelligence.anomaly.monitor import AnomalyMonitor
from intelligence.predictive.risk import FailureRiskModel
from intelligence.retrieval.bm25 import DEFAULT_CORPUS_DIR, BM25Index

__all__ = ["DEMO_MACHINE", "SCENARIOS", "build_demo_context", "scenario_fault"]

_BASE = datetime(2026, 1, 5, tzinfo=UTC)


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
