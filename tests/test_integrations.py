"""MQTT and OPC UA integration tests.

The end-to-end tests run real protocol traffic in-process: an amqtt broker
for MQTT and the asyncua simulation server for OPC UA, both on localhost
ports, feeding the real FastAPI app through an ingest-role key.
"""

import asyncio
import json
import logging
import re
import socket
import threading
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import paho.mqtt.client as mqtt
import pytest
from fastapi.testclient import TestClient

from apps.api.app import create_app
from apps.api.auth import ApiKeyRegistry
from apps.api.settings import Settings
from core.event_engine.roles import Role
from core.telemetry.schema import CncTelemetryReading
from integrations.mqtt.bridge import MqttBridge
from integrations.mqtt.codec import (
    MAX_PAYLOAD_BYTES,
    DecodeError,
    decode_reading,
    encode_reading,
    guard_topic,
    parse_telemetry_topic,
    telemetry_topic,
)
from integrations.mqtt.publisher import TelemetryPublisher
from integrations.simulator.live import live_stream, scenario_frames
from integrations.sink import ApiTelemetrySink, SinkError, TelemetryForwarder

REPO = Path(__file__).resolve().parents[1]
KEYS = {"k-ingest": ("gateway", Role.INGEST), "k-viewer": ("vera", Role.VIEWER)}


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def reading(machine="cnc-sim-01", **overrides) -> CncTelemetryReading:
    base = {
        "machine_id": machine,
        "timestamp": datetime.now(UTC),
        "product_type": "L",
        "air_temperature_k": 298.0,
        "process_temperature_k": 308.0,
        "rotational_speed_rpm": 1500.0,
        "torque_nm": 40.0,
        "tool_wear_min": 12.0,
    }
    return CncTelemetryReading(**{**base, **overrides})


@pytest.fixture(scope="module")
def api():
    """The real API with an empty telemetry buffer and an ingest key."""
    app = create_app(
        Settings(db_path=":memory:", ai4i_path=None),
        keys=ApiKeyRegistry.from_plain_keys(KEYS),
        dashboard_dir=Path("missing"),
    )
    return TestClient(app), app.state.services


def api_post(client: TestClient, key: str):
    def post(path: str, body: dict):
        response = client.post(path, json=body, headers={"X-API-Key": key})
        return response.status_code, response.json()

    return post


# -- live replay ----------------------------------------------------------------


class FakeClock:
    def __init__(self):
        self.now = datetime(2026, 11, 22, 12, 0, tzinfo=UTC)

    def __call__(self):
        return self.now


def test_live_stream_restamps_and_paces():
    clock, pauses = FakeClock(), []
    batches = list(
        live_stream("torque_spike", hours=0.5, speed=30, clock=clock, sleep=pauses.append)
    )
    frames = scenario_frames("torque_spike", hours=0.5)
    assert len(batches) == len(frames) == 60
    assert all(len(b) == 3 for b in batches)
    assert set(pauses) == {1.0}
    stamps = [b[0].timestamp for b in batches]
    assert all(later > earlier for earlier, later in zip(stamps, stamps[1:], strict=False))
    first = frames[0].set_index("machine_id")
    assert batches[0][0].torque_nm == pytest.approx(first.loc["cnc-sim-01", "torque_nm"])


def test_live_stream_rejects_bad_speed():
    with pytest.raises(ValueError):
        next(live_stream(speed=0))


# -- MQTT codec, publisher, bridge ---------------------------------------------------------


class TestCodec:
    def test_topics(self):
        topic = telemetry_topic("lab", "cnc-sim-01")
        assert topic == "spindlesage/v1/lab/cnc-sim-01/telemetry"
        assert parse_telemetry_topic(topic) == ("lab", "cnc-sim-01")
        assert parse_telemetry_topic("spindlesage/v1/lab/cnc-sim-01/command") is None
        with pytest.raises(ValueError):
            telemetry_topic("lab", "bad/machine")

    def test_round_trip(self):
        r = reading()
        topic = telemetry_topic("lab", r.machine_id)
        assert decode_reading(topic, encode_reading(r)) == r

    @pytest.mark.parametrize(
        "payload, message",
        [
            (b"not json", "valid JSON"),
            (b"[1, 2]", "JSON object"),
            (json.dumps({"machine_id": "cnc-sim-02"}).encode(), "does not match"),
            (json.dumps({"machine_id": "cnc-sim-01", "torque_nm": -1}).encode(), "schema"),
            (b"x" * (MAX_PAYLOAD_BYTES + 1), "exceeds"),
        ],
    )
    def test_bad_payloads(self, payload, message):
        with pytest.raises(DecodeError, match=message):
            decode_reading("spindlesage/v1/lab/cnc-sim-01/telemetry", payload)

    @pytest.mark.parametrize(
        "topic",
        [
            "spindlesage/v1/lab/cnc-sim-01/command",
            "spindlesage/v1/lab/cnc-sim-01/telemetry/extra",
            "factory/cnc-sim-01/setpoint",
        ],
    )
    def test_guard_blocks_non_telemetry_topics(self, topic):
        with pytest.raises(PermissionError):
            guard_topic(topic)


class FakeMqttClient:
    def __init__(self):
        self.published = []

    def publish(self, topic, payload, qos=0):
        self.published.append((topic, payload, qos))


def test_publisher_only_uses_telemetry_topics():
    client = FakeMqttClient()
    TelemetryPublisher(client, site="lab").publish(reading())
    ((topic, payload, qos),) = client.published
    assert topic == "spindlesage/v1/lab/cnc-sim-01/telemetry"
    assert qos == 1
    assert json.loads(payload)["machine_id"] == "cnc-sim-01"


class ListSink:
    def __init__(self, fail: SinkError | None = None):
        self.batches, self.fail = [], fail

    def send(self, batch):
        if self.fail:
            raise self.fail
        self.batches.append(batch)
        return {"accepted": len(batch), "rejected": []}


def test_bridge_forwards_valid_and_counts_invalid():
    sink = ListSink()
    bridge = MqttBridge(TelemetryForwarder(sink, batch_size=1))
    topic = telemetry_topic("lab", "cnc-sim-01")
    assert bridge.handle_message(topic, encode_reading(reading()))
    assert not bridge.handle_message(topic, b"garbage")
    assert bridge.stats.messages == 2
    assert bridge.stats.forwarded == 1
    assert bridge.stats.decode_errors == 1
    assert len(sink.batches) == 1


class TestForwarder:
    def test_batches(self):
        sink = ListSink()
        forwarder = TelemetryForwarder(sink, batch_size=3)
        for _ in range(7):
            forwarder.add(reading())
        assert [len(b) for b in sink.batches] == [3, 3]
        forwarder.flush()
        assert [len(b) for b in sink.batches] == [3, 3, 1]
        assert forwarder.stats.accepted == 7

    def test_retryable_failure_keeps_readings(self):
        sink = ListSink(fail=SinkError("down", retryable=True))
        forwarder = TelemetryForwarder(sink, batch_size=2)
        forwarder.add(reading())
        forwarder.add(reading())
        assert forwarder.stats.failed_batches == 1
        sink.fail = None
        forwarder.flush()
        assert [len(b) for b in sink.batches] == [2]

    def test_fatal_failure_raises(self):
        forwarder = TelemetryForwarder(ListSink(fail=SinkError("403", retryable=False)))
        forwarder.add(reading())
        with pytest.raises(SinkError):
            forwarder.flush()

    def test_buffer_is_bounded(self):
        sink = ListSink(fail=SinkError("down", retryable=True))
        forwarder = TelemetryForwarder(sink, batch_size=1000, max_buffer=5)
        for _ in range(8):
            forwarder.add(reading())
        assert len(forwarder._pending) == 5


class TestApiSink:
    def test_ingest_key_reaches_buffer(self, api):
        client, services = api
        sink = ApiTelemetrySink(api_post(client, "k-ingest"))
        result = sink.send([reading("cnc-sim-03")])
        assert result["accepted"] == 1
        assert services.buffer.count("cnc-sim-03") >= 1

    def test_wrong_role_is_fatal(self, api):
        client, _ = api
        with pytest.raises(SinkError) as excinfo:
            ApiTelemetrySink(api_post(client, "k-viewer")).send([reading()])
        assert not excinfo.value.retryable

    def test_rejections_are_counted(self, api):
        client, _ = api
        forwarder = TelemetryForwarder(ApiTelemetrySink(api_post(client, "k-ingest")))
        forwarder.add(reading("cnc-sim-99"))
        forwarder.flush()
        assert forwarder.stats.rejected == 1


# -- real MQTT broker ------------------------------------------------------------


@pytest.fixture(scope="module")
def broker_port():
    from amqtt.broker import Broker

    logging.getLogger("amqtt").setLevel(logging.ERROR)
    port = free_port()
    loop = asyncio.new_event_loop()
    started = threading.Event()
    box = {}

    def run():
        asyncio.set_event_loop(loop)

        async def start():
            box["broker"] = Broker(
                {
                    "listeners": {"default": {"type": "tcp", "bind": f"127.0.0.1:{port}"}},
                    "plugins": {
                        "amqtt.plugins.authentication.AnonymousAuthPlugin": {
                            "allow_anonymous": True
                        }
                    },
                },
                loop=loop,
            )
            await box["broker"].start()
            started.set()

        loop.run_until_complete(start())
        loop.run_forever()

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    assert started.wait(10), "in-process MQTT broker did not start"
    yield port
    asyncio.run_coroutine_threadsafe(box["broker"].shutdown(), loop).result(10)
    loop.call_soon_threadsafe(loop.stop)


def wait_until(condition, timeout=10.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(0.05)
    return False


def test_mqtt_end_to_end_into_api(api, broker_port):
    client, services = api
    before = services.buffer.count("cnc-sim-02")
    forwarder = TelemetryForwarder(ApiTelemetrySink(api_post(client, "k-ingest")), batch_size=10)
    bridge = MqttBridge(forwarder)

    subscriber = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    subscribed = threading.Event()
    bridge.attach(subscriber)
    original_on_connect = subscriber.on_connect

    def on_connect(*args):
        original_on_connect(*args)
        subscribed.set()

    subscriber.on_connect = on_connect
    subscriber.connect("127.0.0.1", broker_port)
    subscriber.loop_start()
    publisher_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    publisher_client.connect("127.0.0.1", broker_port)
    publisher_client.loop_start()
    try:
        assert subscribed.wait(10)
        time.sleep(0.3)  # let the SUBACK land before publishing
        publisher = TelemetryPublisher(publisher_client, site="lab")
        stream = live_stream("healthy", hours=0.25, speed=1e6, sleep=lambda _: None)
        for batch in stream:
            for r in batch:
                publisher.publish(r).wait_for_publish(5)
        assert wait_until(lambda: bridge.stats.messages >= publisher.published)
        forwarder.flush()
    finally:
        subscriber.loop_stop()
        publisher_client.loop_stop()

    assert publisher.published == 90
    assert bridge.stats.decode_errors == 0
    assert forwarder.stats.accepted == 90
    assert services.buffer.count("cnc-sim-02") == before + 30


# -- real OPC UA server ------------------------------------------------------------


def test_opcua_end_to_end_and_read_only(api):
    from asyncua import Client, ua

    from integrations.opcua.collector import OpcUaCollector
    from integrations.opcua.nodes import NAMESPACE_URI
    from integrations.opcua.sim_server import SimulatedCellServer

    logging.getLogger("asyncua").setLevel(logging.ERROR)
    client, services = api
    before = services.buffer.count("cnc-sim-01")
    endpoint = f"opc.tcp://127.0.0.1:{free_port()}/spindlesage/"
    forwarder = TelemetryForwarder(ApiTelemetrySink(api_post(client, "k-ingest")), batch_size=5)
    write_error: dict[str, str] = {}

    async def scenario():
        server = SimulatedCellServer(endpoint, "spindle_overheat", speed=600, hours=0.5)
        stop = asyncio.Event()
        server_task = asyncio.create_task(server.run(stop))
        # Generous: asyncua loads its full address space, which is slow under coverage.
        await asyncio.wait_for(server.ready.wait(), 120)
        collector = OpcUaCollector(endpoint, forwarder.add, interval_s=0.06)
        await collector.run(max_polls=12)

        async with Client(endpoint) as probe:
            idx = await probe.get_namespace_index(NAMESPACE_URI)
            torque = await probe.nodes.objects.get_child(
                [f"{idx}:SpindleSage", f"{idx}:cnc-sim-01", f"{idx}:Torque"]
            )
            try:
                await torque.write_value(ua.Variant(99.0, ua.VariantType.Double))
            except ua.UaStatusCodeError as exc:
                write_error["code"] = type(exc).__name__
        stop.set()
        await server_task
        return collector

    collector = asyncio.run(scenario())
    forwarder.flush()

    assert collector.stats.readings >= 9  # several samples x 3 machines
    assert collector.stats.invalid == 0
    assert forwarder.stats.accepted == collector.stats.readings
    assert services.buffer.count("cnc-sim-01") > before
    latest = services.buffer.latest("cnc-sim-01", 1)[0]
    assert latest.timestamp > datetime.now(UTC) - timedelta(minutes=1)
    assert write_error.get("code") == "BadUserAccessDenied"


# -- read-only guarantees in source ---------------------------------------------------


@pytest.mark.parametrize(
    "path, forbidden",
    [
        (
            "integrations/opcua/collector.py",
            r"\.(write_value|set_value|write_attribute|write_params|call_method|add_nodes?"
            r"|delete_nodes?|set_writable)\(",
        ),
        ("integrations/mqtt/bridge.py", r"\.publish\("),
        ("integrations/sink.py", r"/(machines/[^\"']*/)?(command|control|setpoint)"),
    ],
)
def test_gateways_have_no_write_path(path, forbidden):
    code = "\n".join(
        line for line in (REPO / path).read_text("utf-8").splitlines()
        if not line.lstrip().startswith("#")
    )  # fmt: skip
    code = re.sub(r'"""[\s\S]*?"""', "", code)  # ignore docstrings
    assert not re.search(forbidden, code), f"{path} contains a forbidden write operation"
