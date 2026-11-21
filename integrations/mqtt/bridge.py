"""MQTT -> SpindleSage API bridge. Subscribe-only.

Subscribes to spindlesage/v1/+/+/telemetry, validates each message, and
forwards valid readings to the API through an ingest-role key. It never
publishes, so it cannot send anything towards a machine.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import paho.mqtt.client as mqtt

from integrations.mqtt.codec import TELEMETRY_FILTER, DecodeError, decode_reading
from integrations.sink import TelemetryForwarder

log = logging.getLogger(__name__)


@dataclass
class BridgeStats:
    messages: int = 0
    forwarded: int = 0
    decode_errors: int = 0
    last_errors: list[str] = field(default_factory=list)


class MqttBridge:
    def __init__(self, forwarder: TelemetryForwarder, topic_filter: str = TELEMETRY_FILTER):
        self.forwarder = forwarder
        self.topic_filter = topic_filter
        self.stats = BridgeStats()

    def handle_message(self, topic: str, payload: bytes) -> bool:
        """Decode and forward one message. Returns True if it was forwarded."""
        self.stats.messages += 1
        try:
            reading = decode_reading(topic, payload)
        except DecodeError as exc:
            self.stats.decode_errors += 1
            self.stats.last_errors = [*self.stats.last_errors[-9:], f"{topic}: {exc}"]
            log.warning("Dropped message on %s: %s", topic, exc)
            return False
        self.forwarder.add(reading)
        self.stats.forwarded += 1
        return True

    def attach(self, client: mqtt.Client, qos: int = 1) -> None:
        """Wire the bridge to a paho client: subscribe on connect, handle messages."""

        def on_connect(client, _userdata, _flags, reason_code, _properties):
            if reason_code.is_failure:
                log.error("MQTT connection failed: %s", reason_code)
                return
            client.subscribe(self.topic_filter, qos=qos)
            log.info("Subscribed to %s", self.topic_filter)

        def on_message(_client, _userdata, message):
            self.handle_message(message.topic, message.payload)

        client.on_connect = on_connect
        client.on_message = on_message
