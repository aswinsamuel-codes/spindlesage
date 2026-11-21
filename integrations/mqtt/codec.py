"""MQTT topic scheme and payload codec for SpindleSage telemetry.

Topic:   spindlesage/v1/<site>/<machine_id>/telemetry
Payload: one JSON object matching core.telemetry.schema.CncTelemetryReading

Only telemetry topics exist in this scheme. There are no command topics, and
the publisher refuses to publish anything else (see guard_topic).
"""

from __future__ import annotations

import json
import re

from pydantic import ValidationError

from core.telemetry.schema import CncTelemetryReading

TOPIC_ROOT = "spindlesage/v1"
TELEMETRY_FILTER = f"{TOPIC_ROOT}/+/+/telemetry"
MAX_PAYLOAD_BYTES = 16 * 1024
_SEGMENT = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")
_TELEMETRY_TOPIC = re.compile(
    rf"^{re.escape(TOPIC_ROOT)}/(?P<site>[A-Za-z0-9_.-]{{1,64}})/"
    r"(?P<machine>[A-Za-z0-9_.-]{1,64})/telemetry$"
)


class DecodeError(ValueError):
    """A message could not be turned into a valid reading."""


def telemetry_topic(site: str, machine_id: str) -> str:
    for name, value in (("site", site), ("machine_id", machine_id)):
        if not _SEGMENT.match(value):
            raise ValueError(f"Invalid {name} for an MQTT topic segment: {value!r}")
    return f"{TOPIC_ROOT}/{site}/{machine_id}/telemetry"


def parse_telemetry_topic(topic: str) -> tuple[str, str] | None:
    match = _TELEMETRY_TOPIC.match(topic)
    return (match["site"], match["machine"]) if match else None


def guard_topic(topic: str) -> None:
    """Refuse any topic that is not a SpindleSage telemetry topic."""
    if parse_telemetry_topic(topic) is None:
        raise PermissionError(
            f"Refusing to publish to {topic!r}: SpindleSage only publishes telemetry topics"
        )


def encode_reading(reading: CncTelemetryReading) -> bytes:
    return reading.model_dump_json().encode("utf-8")


def decode_reading(topic: str, payload: bytes) -> CncTelemetryReading:
    parsed = parse_telemetry_topic(topic)
    if parsed is None:
        raise DecodeError(f"Not a telemetry topic: {topic!r}")
    if len(payload) > MAX_PAYLOAD_BYTES:
        raise DecodeError(f"Payload of {len(payload)} bytes exceeds {MAX_PAYLOAD_BYTES}")
    try:
        data = json.loads(payload)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise DecodeError(f"Payload is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise DecodeError("Payload must be a JSON object")
    _, topic_machine = parsed
    if data.get("machine_id") != topic_machine:
        raise DecodeError(
            f"machine_id {data.get('machine_id')!r} does not match topic machine {topic_machine!r}"
        )
    try:
        return CncTelemetryReading(**data)
    except (ValidationError, TypeError) as exc:
        raise DecodeError(f"Payload failed schema validation: {exc}") from exc
