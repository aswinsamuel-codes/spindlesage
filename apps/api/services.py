"""Builds the long-lived objects the API uses.

The anomaly monitor is calibrated on SIMULATED healthy data at startup, since
there is no real machine history yet. /health reports this.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from apps.api.settings import Settings
from core.event_engine.approvals import ApprovalService
from core.event_engine.store import OperationsStore
from core.machine_registry.registry import MachineRegistry
from core.telemetry.buffer import TelemetryBuffer
from intelligence.agent.demo import build_demo_context
from intelligence.agent.engines import ClaudeEngine, RuleBasedEngine
from intelligence.anomaly.monitor import AnomalyMonitor
from intelligence.predictive.risk import FailureRiskModel
from intelligence.retrieval.bm25 import BM25Index


@dataclass
class Services:
    registry: MachineRegistry
    retriever: BM25Index
    monitor: AnomalyMonitor
    risk_model: FailureRiskModel | None
    engine: object
    buffer: TelemetryBuffer
    store: OperationsStore
    approvals: ApprovalService
    demo_scenario: str | None
    monitor_calibration: str = "simulated healthy data (SpindleSage CNC simulator)"


def build_services(settings: Settings) -> Services:
    context = build_demo_context(
        settings.demo_scenario or "healthy", seed=settings.seed, ai4i_path=settings.ai4i_path
    )
    buffer = TelemetryBuffer()
    if settings.demo_scenario:
        buffer.load_frame(context.readings)
    store = OperationsStore(settings.db_path)
    engine = ClaudeEngine() if settings.engine == "claude" else RuleBasedEngine()
    return Services(
        registry=context.registry,
        retriever=context.retriever,
        monitor=context.anomaly_monitor,
        risk_model=context.risk_model,
        engine=engine,
        buffer=buffer,
        store=store,
        approvals=ApprovalService(store, ttl=timedelta(hours=settings.approval_ttl_hours)),
        demo_scenario=settings.demo_scenario,
    )
