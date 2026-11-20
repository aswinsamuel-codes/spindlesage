"""Smoke tests: the planned module layout is importable."""

import importlib

import pytest

MODULES = [
    "apps.api",
    "core.ingestion",
    "core.telemetry",
    "core.machine_registry",
    "core.event_engine",
    "intelligence.predictive",
    "intelligence.anomaly",
    "intelligence.agent",
    "intelligence.retrieval",
    "intelligence.evaluation",
    "integrations.mqtt",
    "integrations.opcua",
    "integrations.simulator",
]


@pytest.mark.parametrize("name", MODULES)
def test_module_importable(name: str) -> None:
    importlib.import_module(name)
