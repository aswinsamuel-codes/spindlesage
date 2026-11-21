"""Reasoning engines that turn an evidence bundle into a recommendation.

RuleBasedEngine: deterministic, no network, no API key. It is the fallback
                 whenever the LLM engine fails or its output fails the guard,
                 and the baseline for Experiment C.
ClaudeEngine:    one Claude API call with structured outputs; the response
                 must match RECOMMENDATION_JSON_SCHEMA and cite evidence ids.
"""

from __future__ import annotations

import json
from typing import Protocol

from pydantic import ValidationError

from intelligence.agent.evidence import EvidenceBundle
from intelligence.agent.schema import (
    RECOMMENDATION_JSON_SCHEMA,
    Finding,
    ProposedAction,
    Recommendation,
)
from intelligence.anomaly.features import ROLLING_SUFFIX

DEFAULT_MODEL = "claude-opus-5-5"
FALLBACK_BETA = "server-side-fallback-2026-07-01"

_RISK_ORDER = {"unknown": -1, "low": 0, "medium": 1, "high": 2}


class EngineError(RuntimeError):
    """The engine could not produce a valid recommendation."""


class ReasoningEngine(Protocol):
    name: str

    def recommend(self, bundle: EvidenceBundle) -> Recommendation: ...


def _raise(current: str, new: str) -> str:
    return new if _RISK_ORDER[new] > _RISK_ORDER[current] else current


def _docs_matching(bundle: EvidenceBundle, *doc_ids: str) -> list[str]:
    return [
        e.evidence_id
        for e in bundle.of_kind("document")
        if e.content.get("chunk_id", "").split("#")[0] in doc_ids
    ]


def _history_matching(bundle: EvidenceBundle, *keywords: str) -> list[str]:
    hits = []
    for e in bundle.of_kind("history"):
        text = f"{e.content.get('component', '')} {e.content.get('description', '')}".lower()
        if any(k in text for k in keywords):
            hits.append(e.evidence_id)
    return hits


class RuleBasedEngine:
    """Transparent rules mapping evidence to findings and proposed actions."""

    name = "rules"

    def recommend(self, bundle: EvidenceBundle) -> Recommendation:
        findings: list[Finding] = []
        actions: list[ProposedAction] = []
        uncertainties: list[str] = []
        risk = "low"
        safety_docs = _docs_matching(bundle, "alarm-response-and-safety")

        validation = bundle.get("VAL-1")
        if validation is not None:
            for issue in validation.content["issues"]:
                findings.append(
                    Finding(
                        statement=f"Validation {issue['severity']}: {issue['message']}",
                        evidence_ids=["VAL-1"],
                    )
                )
            if not validation.content["ok"]:
                risk = "unknown"
                uncertainties.append("The latest reading failed validation and may be invalid.")
                actions.append(
                    ProposedAction(
                        action_type="check_sensor",
                        description="Check the sensor and data path before trusting this reading.",
                        urgency="next_stop",
                        evidence_ids=["VAL-1"],
                    )
                )

        anomaly = bundle.get("ANO-1")
        if anomaly is None:
            uncertainties.append(
                "Sensor-only context: no anomaly model, failure-risk model, maintenance "
                "history or documentation was available."
            )
            envelope = [
                i
                for i in (validation.content["issues"] if validation else [])
                if i["rule"] == "outside_envelope"
            ]
            if envelope:
                risk = _raise(risk, "medium")
                actions.append(
                    ProposedAction(
                        action_type="inspect",
                        description="Readings are outside the expected operating range; "
                        "inspect the machine at the next stop.",
                        urgency="next_stop",
                        evidence_ids=["VAL-1"],
                    )
                )
        elif not anomaly.content.get("available", True):
            uncertainties.append("The anomaly monitor was not available.")
        elif anomaly.content["alarm"]:
            sustained = anomaly.content["consecutive_exceedances"] >= 10
            handled: set[str] = set()
            for item in anomaly.content["top_features"]:
                self._feature_rules(
                    bundle, item, sustained, safety_docs, handled, findings, actions, uncertainties
                )
            if handled - {c for c in handled if c.startswith("frozen:")}:
                risk = _raise(risk, "high" if sustained else "medium")
            elif handled:
                # Only frozen sensors: the machine state cannot be judged from this data.
                risk = "unknown" if risk == "low" else risk
            else:
                risk = _raise(risk, "medium")
                uncertainties.append(
                    "The anomaly alarm is not linked to a known fault pattern; inspect the "
                    "listed features manually."
                )
                actions.append(
                    ProposedAction(
                        action_type="inspect",
                        description="Review the alarmed signals at the next stop.",
                        urgency="next_stop",
                        evidence_ids=["ANO-1"],
                    )
                )
        else:
            findings.append(
                Finding(
                    statement="The anomaly monitor shows no active alarm.",
                    evidence_ids=["ANO-1"],
                )
            )

        prediction = bundle.get("PRED-1")
        if prediction is not None and prediction.content.get("available", True):
            p = prediction.content["latest_failure_probability"]
            uncertainties.append(prediction.content["caveat"])
            if p >= 0.5:
                risk = _raise(risk, "medium")
                findings.append(
                    Finding(
                        statement=f"The failure-risk model gives {p:.0%} for the latest reading.",
                        evidence_ids=["PRED-1"],
                    )
                )
                actions.append(
                    ProposedAction(
                        action_type="schedule_maintenance",
                        description="Schedule a maintenance check; the failure-risk model is "
                        "elevated.",
                        urgency="next_stop",
                        evidence_ids=["PRED-1"],
                    )
                )

        telemetry = bundle.get("TEL-1")
        wear = telemetry.content["tool_wear_min"] if telemetry else 0.0
        if wear >= 200:
            risk = _raise(risk, "medium")
            docs = _docs_matching(bundle, "tool-wear-and-breakage")
            findings.append(
                Finding(
                    statement=f"Tool wear is {wear:.0f} minutes, past the 200-minute guide.",
                    evidence_ids=["TEL-1", *docs],
                )
            )
            actions.append(
                ProposedAction(
                    action_type="replace_tool",
                    description="Change the cutting tool at the next safe opportunity.",
                    urgency="next_stop",
                    evidence_ids=["TEL-1", *docs],
                )
            )

        if not actions:
            cited = ["TEL-1"] + (["ANO-1"] if anomaly is not None else [])
            actions.append(
                ProposedAction(
                    action_type="continue_monitoring",
                    description="No action needed; keep monitoring.",
                    urgency="routine",
                    evidence_ids=cited,
                )
            )

        return Recommendation(
            machine_id=bundle.machine_id,
            risk_level=risk,
            summary=self._summary(bundle.machine_id, risk, actions),
            findings=findings,
            actions=actions,
            uncertainties=uncertainties,
        )

    @staticmethod
    def _category(feature: str, direction: str) -> str | None:
        if feature in ("process_temperature_k", "temp_rise_k"):
            return "thermal"
        if feature in ("torque_nm", "mech_power_w"):
            return "tool"
        if feature == "rotational_speed_rpm":
            return "speed"
        if feature.endswith(ROLLING_SUFFIX) and direction == "below":
            return f"frozen:{feature.removesuffix(ROLLING_SUFFIX)}"
        return None

    @classmethod
    def _feature_rules(
        cls, bundle, item, sustained, safety_docs, handled, findings, actions, uncertainties
    ):
        feature = item["feature"]
        exceedance = item["exceedance_band_widths"]
        direction = item["direction"]
        findings.append(
            Finding(
                statement=f"{feature} is {exceedance:.1f} band widths {direction} its "
                "healthy range.",
                evidence_ids=["ANO-1"],
            )
        )
        category = cls._category(feature, direction)
        if category is None or category in handled:
            return
        handled.add(category)
        urgency = "immediate" if sustained else "next_stop"
        if category == "thermal":
            docs = _docs_matching(bundle, "spindle-thermal")
            history = _history_matching(bundle, "spindle", "coolant", "bearing")
            actions.append(
                ProposedAction(
                    action_type="inspect",
                    description="Inspect coolant flow and spindle lubrication (spindle thermal "
                    "procedure); apply lockout before any inspection.",
                    urgency=urgency,
                    evidence_ids=["ANO-1", *docs, *history, *safety_docs],
                )
            )
            if history:
                findings.append(
                    Finding(
                        statement="Recent maintenance history involves the spindle or coolant "
                        "system.",
                        evidence_ids=history,
                    )
                )
        elif category == "tool":
            docs = _docs_matching(bundle, "tool-wear-and-breakage", "power-and-overstrain")
            actions.append(
                ProposedAction(
                    action_type="inspect",
                    description="Inspect the cutting tool for chipping or breakage before "
                    "further cutting; apply lockout before inspection.",
                    urgency=urgency,
                    evidence_ids=["ANO-1", *docs, *safety_docs],
                )
            )
        elif category == "speed":
            docs = _docs_matching(bundle, "spindle-speed-control")
            uncertainties.append(
                "Commanded spindle speed is not in the telemetry, so a speed drift cannot be "
                "separated from a job change."
            )
            actions.append(
                ProposedAction(
                    action_type="inspect",
                    description="Confirm the commanded speed; if it is unchanged, inspect the "
                    "spindle drive, belt and encoder.",
                    urgency="next_stop",
                    evidence_ids=["ANO-1", *docs],
                )
            )
        else:
            sensor = category.removeprefix("frozen:")
            docs = _docs_matching(bundle, "sensor-faults")
            uncertainties.append(f"The {sensor} signal may be frozen; do not rely on it.")
            actions.append(
                ProposedAction(
                    action_type="check_sensor",
                    description=f"Check the {sensor} sensor, cabling and data pipeline; the "
                    "signal has stopped varying.",
                    urgency="next_stop",
                    evidence_ids=["ANO-1", *docs],
                )
            )

    @staticmethod
    def _summary(machine_id: str, risk: str, actions: list[ProposedAction]) -> str:
        kinds = sorted({a.action_type.replace("_", " ") for a in actions})
        return (
            f"{machine_id}: risk {risk}. Proposed: {', '.join(kinds)}. "
            "All operational actions need approval from the maintenance lead."
        )


SYSTEM_PROMPT = """\
You are the maintenance advisor in SpindleSage, an open-source research platform that monitors \
CNC machining cells. You receive an evidence bundle for one machine and return one maintenance \
recommendation for a maintenance technician.

How to work:
- Use only the evidence in the bundle. Every finding and every action must list the ids of the \
evidence items that support it, and only ids that appear in the bundle.
- If the evidence is weak, missing or conflicting, say so in uncertainties. Prefer risk_level \
"unknown" or a lower-urgency action over a confident conclusion the evidence does not support.
- You recommend; you never control machines. Every action other than continue_monitoring is a \
proposal that a maintenance lead must approve. Use request_stop only when the evidence shows an \
active fault that is getting worse.
- Remind the reader to apply lockout before any physical inspection.
- The data comes from a simulator and from synthetic benchmarks, and the failure-risk model is \
not calibrated for this machine. Do not describe the data as real factory data, and treat model \
probabilities as weak signals.
- Keep the summary to two or three plain sentences.
"""


class ClaudeEngine:
    """One structured-output call to the Claude API per recommendation."""

    name = "claude"

    def __init__(
        self,
        client=None,
        model: str = DEFAULT_MODEL,
        effort: str = "high",
        max_tokens: int = 16000,
    ):
        self._client = client
        self.model = model
        self.effort = effort
        self.max_tokens = max_tokens
        self.last_usage: dict | None = None

    def _get_client(self):
        if self._client is None:
            import anthropic  # imported lazily so the rest of the agent works without it

            self._client = anthropic.Anthropic()
        return self._client

    def recommend(self, bundle: EvidenceBundle) -> Recommendation:
        import anthropic

        prompt = (
            f"Evidence bundle:\n\n{bundle.render()}\n\nReturn the recommendation for this machine."
        )
        try:
            response = self._get_client().beta.messages.create(
                model=self.model,
                max_tokens=self.max_tokens,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": prompt}],
                output_config={
                    "effort": self.effort,
                    "format": {"type": "json_schema", "schema": RECOMMENDATION_JSON_SCHEMA},
                },
                betas=[FALLBACK_BETA],
                fallbacks="default",
            )
        except anthropic.AuthenticationError as exc:
            raise EngineError(f"Claude API authentication failed: {exc.message}") from exc
        except anthropic.APIStatusError as exc:
            raise EngineError(f"Claude API error {exc.status_code}: {exc.message}") from exc
        except anthropic.APIConnectionError as exc:
            raise EngineError(f"Could not reach the Claude API: {exc}") from exc

        usage = getattr(response, "usage", None)
        self.last_usage = {
            "model": getattr(response, "model", self.model),
            "input_tokens": getattr(usage, "input_tokens", None),
            "output_tokens": getattr(usage, "output_tokens", None),
            "request_id": getattr(response, "_request_id", None),
        }

        if response.stop_reason == "refusal":
            raise EngineError("Claude declined the request (stop_reason=refusal)")
        if response.stop_reason == "max_tokens":
            raise EngineError("Claude response was cut off at max_tokens")

        text = next((b.text for b in response.content if b.type == "text"), None)
        if text is None:
            raise EngineError("Claude response contained no text block")
        try:
            data = json.loads(text)
            return Recommendation.model_validate({**data, "machine_id": bundle.machine_id})
        except (json.JSONDecodeError, ValidationError, TypeError) as exc:
            raise EngineError(f"Claude output did not match the schema: {exc}") from exc
