"""Publishes simulated telemetry to MQTT, standing in for a machine gateway.

This is the only SpindleSage component that publishes to MQTT, and it can
publish only telemetry topics: guard_topic() rejects anything else.
"""

from __future__ import annotations

import paho.mqtt.client as mqtt

from core.telemetry.schema import CncTelemetryReading
from integrations.mqtt.codec import encode_reading, guard_topic, telemetry_topic


class TelemetryPublisher:
    def __init__(self, client: mqtt.Client, site: str = "lab", qos: int = 1):
        self.client = client
        self.site = site
        self.qos = qos
        self.published = 0

    def publish(self, reading: CncTelemetryReading) -> mqtt.MQTTMessageInfo:
        topic = telemetry_topic(self.site, reading.machine_id)
        guard_topic(topic)
        info = self.client.publish(topic, encode_reading(reading), qos=self.qos)
        self.published += 1
        return info
