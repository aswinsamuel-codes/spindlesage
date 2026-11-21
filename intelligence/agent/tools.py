"""Evidence-gathering tools for the operations agent.

Code, not the LLM, decides which tools run, so the evidence-gathering step is
deterministic and auditable. Two context modes exist for Experiment C (H2):

* sensor_only: the latest readings, a short window summary and validation.
* full:        sensor_only plus anomaly status, failure risk, machine record,
               maintenance history and retrieved maintenance documentation.

Every tool reads data only; none of them can change a machine.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

import pandas as pd

from core.ingestion.validation import validate_reading
from core.machine_registry.registry import MachineRegistry
from core.telemetry.schema import SENSOR_FIELDS, CncTelemetryReading
from intelligence.agent.evidence import Evidence, EvidenceBundle
from intelligence.anomaly.features import ROLLING_SUFFIX
from intelligence.anomaly.monitor import AnomalyMonitor
from intelligence.predictive.risk import CAVEAT, FailureRiskModel
from intelligence.retrieval.bm25 import BM25Index

ContextMode = Literal["sensor_only", "full"]
CONTEXT_MODES: tuple[str, ...] = ("sensor_only", "full")

# Retrieval topics per anomaly feature; rolling-variability features map to
# sensor faults only when variability is too LOW (a frozen signal).
_FEATURE_TOPICS: dict[str, str] = {
    "process_temperature_k": "spindle overheating temperature rise coolant lubrication",
    "temp_rise_k": "spindle overheating temperature rise coolant lubrication",
    "air_temperature_k": "ambient air temperature thermal",
    "torque_nm": "torque spike chipped tool breakage",
    # A torque spike at constant speed shows up as a power jump, so search both topics.
    "mech_power_w": "torque spike chipped tool breakage cutting power overstrain",
    "rotational_speed_rpm": "spindle speed deviation drift drive belt encoder",
    "tool_wear_min": "tool wear limit replacement",
}
_SENSOR_FAULT_TOPIC = "frozen sensor flatline data fault"
_TOOL_WEAR_TOPIC = "tool wear limit replacement"
_SAFETY_TOPIC = "lockout inspection human approval triage"


@dataclass
class AgentContext:
    """Everything the agent may read. Unavailable sources are left as None."""

    readings: pd.DataFrame
    anomaly_monitor: AnomalyMonitor | None = None
    risk_model: FailureRiskModel | None = None
    registry: MachineRegistry | None = None
    retriever: BM25Index | None = None
    lookback: int = 60
    history_limit: int = 3
    max_documents: int = 4
    now: datetime | None = None


def _round(value: float, digits: int = 3) -> float:
    return round(float(value), digits)


def _derived(row: pd.Series) -> dict:
    return {
        "temp_rise_k": _round(row["process_temperature_k"] - row["air_temperature_k"]),
        "mech_power_w": _round(
            row["torque_nm"] * row["rotational_speed_rpm"] * 2.0 * math.pi / 60.0, 1
        ),
    }


def _telemetry_evidence(recent: pd.DataFrame) -> list[Evidence]:
    latest = recent.iloc[-1]
    first = recent.iloc[0]
    minutes = (latest["timestamp"] - first["timestamp"]).total_seconds() / 60.0
    window = {
        sensor: {
            "min": _round(recent[sensor].min()),
            "mean": _round(recent[sensor].mean()),
            "max": _round(recent[sensor].max()),
            "change": _round(latest[sensor] - first[sensor]),
        }
        for sensor in SENSOR_FIELDS
    }
    derived_first, derived_last = _derived(first), _derived(latest)
    return [
        Evidence(
            "TEL-1",
            "telemetry",
            "Latest reading",
            {
                "timestamp": latest["timestamp"].isoformat(),
                "product_type": latest["product_type"],
                **{sensor: _round(latest[sensor]) for sensor in SENSOR_FIELDS},
                **derived_last,
            },
            "telemetry stream",
        ),
        Evidence(
            "TEL-2",
            "telemetry",
            f"Summary of the last {len(recent)} readings ({minutes:.0f} minutes)",
            {
                **window,
                "temp_rise_k_change": _round(
                    derived_last["temp_rise_k"] - derived_first["temp_rise_k"]
                ),
                "mech_power_w_change": _round(
                    derived_last["mech_power_w"] - derived_first["mech_power_w"], 1
                ),
            },
            "telemetry stream",
        ),
    ]


def _validation_evidence(recent: pd.DataFrame, now: datetime | None) -> Evidence:
    latest = recent.iloc[-1]
    reading = CncTelemetryReading(
        machine_id=str(latest["machine_id"]),
        timestamp=latest["timestamp"].to_pydatetime(),
        product_type=latest["product_type"],
        **{sensor: float(latest[sensor]) for sensor in SENSOR_FIELDS},
    )
    previous = recent.iloc[-2]["timestamp"].to_pydatetime() if len(recent) > 1 else None
    result = validate_reading(reading, previous_timestamp=previous, now=now or reading.timestamp)
    return Evidence(
        "VAL-1",
        "validation",
        "Validation of the latest reading",
        {
            "ok": result.ok,
            "issues": [
                {"rule": i.rule, "severity": str(i.severity), "message": i.message}
                for i in result.issues
            ],
        },
        "core.ingestion.validation (operating envelope defaults derived from AI4I ranges)",
    )


def retrieval_topics(anomaly: dict | None, latest_wear: float) -> list[str]:
    topics: list[str] = []
    if anomaly and anomaly.get("alarm"):
        for item in anomaly.get("top_features", []):
            feature, direction = item["feature"], item["direction"]
            if feature.endswith(ROLLING_SUFFIX):
                topic = _SENSOR_FAULT_TOPIC if direction == "below" else None
            else:
                topic = _FEATURE_TOPICS.get(feature)
            if topic and topic not in topics:
                topics.append(topic)
    if latest_wear >= 180 and _TOOL_WEAR_TOPIC not in topics:
        topics.append(_TOOL_WEAR_TOPIC)
    topics.append(_SAFETY_TOPIC)
    return topics


def gather_evidence(
    machine_id: str, context: AgentContext, mode: ContextMode = "full"
) -> EvidenceBundle:
    if mode not in CONTEXT_MODES:
        raise ValueError(f"Unknown mode {mode!r}; choose from {CONTEXT_MODES}")
    readings = context.readings
    recent = (
        readings[readings["machine_id"] == machine_id]
        .sort_values("timestamp")
        .tail(context.lookback)
        .reset_index(drop=True)
    )
    if recent.empty:
        raise ValueError(f"No telemetry for machine {machine_id!r}")

    items = [*_telemetry_evidence(recent), _validation_evidence(recent, context.now)]

    if mode == "full":
        anomaly = None
        if context.anomaly_monitor is not None:
            anomaly = context.anomaly_monitor.assess(recent).to_dict()
            items.append(
                Evidence(
                    "ANO-1",
                    "anomaly",
                    "Anomaly monitor status (threshold detector, contextual features)",
                    anomaly,
                    "intelligence.anomaly.monitor (calibrated on simulated healthy data)",
                )
            )
        else:
            items.append(
                Evidence("ANO-1", "anomaly", "Anomaly monitor status", {"available": False}, "none")
            )

        if context.risk_model is not None:
            risk = context.risk_model.predict_risk(recent)
            items.append(
                Evidence(
                    "PRED-1",
                    "prediction",
                    "Failure-risk model output",
                    {
                        "latest_failure_probability": _round(risk[-1]),
                        "max_failure_probability_in_window": _round(risk.max()),
                        "model": context.risk_model.provenance,
                        "caveat": CAVEAT,
                    },
                    "intelligence.predictive.risk",
                )
            )
        else:
            items.append(
                Evidence(
                    "PRED-1",
                    "prediction",
                    "Failure-risk model output",
                    {"available": False, "reason": "no trained failure-risk model loaded"},
                    "none",
                )
            )

        if context.registry is not None:
            machine = context.registry.get(machine_id)
            items.append(
                Evidence(
                    "MACH-1",
                    "machine",
                    f"Machine record for {machine_id}",
                    machine.model_dump(mode="json"),
                    f"machine registry ({context.registry.data_nature})",
                )
            )
            for n, record in enumerate(
                context.registry.history(machine_id, context.history_limit), start=1
            ):
                items.append(
                    Evidence(
                        f"HIST-{n}",
                        "history",
                        f"Maintenance record {record.record_id} ({record.date})",
                        record.model_dump(mode="json"),
                        f"maintenance history ({context.registry.data_nature})",
                    )
                )

        if context.retriever is not None:
            seen: set[str] = set()
            n = 0
            for topic in retrieval_topics(anomaly, float(recent.iloc[-1]["tool_wear_min"])):
                for hit in context.retriever.search(topic, k=2):
                    if hit.chunk.chunk_id in seen or n >= context.max_documents:
                        continue
                    seen.add(hit.chunk.chunk_id)
                    n += 1
                    items.append(
                        Evidence(
                            f"DOC-{n}",
                            "document",
                            f"{hit.chunk.doc_title}: {hit.chunk.section}",
                            {
                                "chunk_id": hit.chunk.chunk_id,
                                "text": hit.chunk.text,
                                "retrieval_query": topic,
                                "bm25_score": _round(hit.score),
                            },
                            f"{hit.chunk.source_path} (illustrative documentation)",
                        )
                    )

    return EvidenceBundle(
        machine_id=machine_id,
        mode=mode,
        as_of=recent.iloc[-1]["timestamp"].isoformat(),
        items=tuple(items),
    )
