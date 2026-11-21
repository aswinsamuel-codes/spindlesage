"""Shared paho-mqtt client setup: broker address, optional TLS and credentials.

Credentials come from SPINDLESAGE_MQTT_USERNAME / SPINDLESAGE_MQTT_PASSWORD,
never from command-line arguments.
"""

from __future__ import annotations

import os
import ssl
import uuid

import paho.mqtt.client as mqtt


def parse_broker(address: str) -> tuple[str, int]:
    host, _, port = address.rpartition(":")
    if not host:
        return address, 1883
    return host, int(port)


def make_client(role: str, tls_ca: str | None = None, client_id: str | None = None) -> mqtt.Client:
    client = mqtt.Client(
        callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
        client_id=client_id or f"spindlesage-{role}-{uuid.uuid4().hex[:8]}",
    )
    username = os.environ.get("SPINDLESAGE_MQTT_USERNAME")
    if username:
        client.username_pw_set(username, os.environ.get("SPINDLESAGE_MQTT_PASSWORD"))
    if tls_ca:
        client.tls_set(ca_certs=tls_ca, tls_version=ssl.PROTOCOL_TLS_CLIENT)
    return client
