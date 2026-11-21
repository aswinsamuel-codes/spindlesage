"""Structured recommendation produced by the agent.

The JSON schema below is what the LLM must fill (via structured outputs); the
pydantic models validate it again on our side. machine_id is set by code, not
by the model.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

RiskLevel = Literal["low", "medium", "high", "unknown"]
ActionType = Literal[
    "continue_monitoring",
    "inspect",
    "schedule_maintenance",
    "replace_tool",
    "check_sensor",
    "request_stop",
]
Urgency = Literal["routine", "next_stop", "immediate"]

RISK_LEVELS: tuple[str, ...] = ("low", "medium", "high", "unknown")
ACTION_TYPES: tuple[str, ...] = (
    "continue_monitoring",
    "inspect",
    "schedule_maintenance",
    "replace_tool",
    "check_sensor",
    "request_stop",
)
URGENCIES: tuple[str, ...] = ("routine", "next_stop", "immediate")

# Actions that change what happens on the shop floor. Every one needs a human approval.
OPERATIONAL_ACTIONS = frozenset(set(ACTION_TYPES) - {"continue_monitoring"})


class Finding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    statement: str = Field(min_length=1)
    evidence_ids: list[str]


class ProposedAction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action_type: ActionType
    description: str = Field(min_length=1)
    urgency: Urgency
    evidence_ids: list[str]


class Recommendation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    machine_id: str
    risk_level: RiskLevel
    summary: str = Field(min_length=1)
    findings: list[Finding]
    actions: list[ProposedAction]
    uncertainties: list[str]

    @property
    def requires_approval(self) -> bool:
        return any(a.action_type in OPERATIONAL_ACTIONS for a in self.actions)


def _string_list() -> dict:
    return {"type": "array", "items": {"type": "string"}}


RECOMMENDATION_JSON_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "risk_level": {"type": "string", "enum": list(RISK_LEVELS)},
        "summary": {"type": "string"},
        "findings": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"statement": {"type": "string"}, "evidence_ids": _string_list()},
                "required": ["statement", "evidence_ids"],
                "additionalProperties": False,
            },
        },
        "actions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "action_type": {"type": "string", "enum": list(ACTION_TYPES)},
                    "description": {"type": "string"},
                    "urgency": {"type": "string", "enum": list(URGENCIES)},
                    "evidence_ids": _string_list(),
                },
                "required": ["action_type", "description", "urgency", "evidence_ids"],
                "additionalProperties": False,
            },
        },
        "uncertainties": _string_list(),
    },
    "required": ["risk_level", "summary", "findings", "actions", "uncertainties"],
    "additionalProperties": False,
}
