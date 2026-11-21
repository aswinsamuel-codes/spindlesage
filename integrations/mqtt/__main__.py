"""MQTT tools.

Publish a simulated cell (SYNTHETIC DATA) to a broker:
    uv run python -m integrations.mqtt publish --broker 127.0.0.1:1883 --scenario torque_spike

Bridge broker telemetry into the API (needs SPINDLESAGE_INGEST_KEY):
    uv run python -m integrations.mqtt bridge --broker 127.0.0.1:1883 --api http://127.0.0.1:8000
"""

from __future__ import annotations

import argparse
import logging
import time

from integrations.mqtt.bridge import MqttBridge
from integrations.mqtt.client import make_client, parse_broker
from integrations.mqtt.publisher import TelemetryPublisher
from integrations.simulator.live import live_stream
from integrations.simulator.scenarios import SCENARIOS
from integrations.sink import ApiTelemetrySink, TelemetryForwarder, ingest_key_from_env


def publish(args) -> int:
    client = make_client("publisher", args.tls_ca)
    host, port = parse_broker(args.broker)
    client.connect(host, port)
    client.loop_start()
    publisher = TelemetryPublisher(client, site=args.site)
    print(f"Publishing scenario {args.scenario!r} (synthetic) to {args.broker} at {args.speed}x")
    try:
        for batch in live_stream(args.scenario, args.seed, args.speed, loop=args.loop):
            for reading in batch:
                publisher.publish(reading)
            if publisher.published % 300 == 0:
                print(f"  {publisher.published} readings published")
    except KeyboardInterrupt:
        pass
    finally:
        client.loop_stop()
        client.disconnect()
    print(f"Published {publisher.published} readings")
    return 0


def bridge(args) -> int:
    forwarder = TelemetryForwarder(
        ApiTelemetrySink.from_url(args.api, ingest_key_from_env()), batch_size=args.batch
    )
    mqtt_bridge = MqttBridge(forwarder)
    client = make_client("bridge", args.tls_ca)
    mqtt_bridge.attach(client)
    host, port = parse_broker(args.broker)
    client.connect(host, port)
    client.loop_start()
    print(f"Bridging {args.broker} -> {args.api}. Ctrl+C to stop.")
    try:
        while True:
            time.sleep(args.flush_seconds)
            forwarder.flush()
            s, f = mqtt_bridge.stats, forwarder.stats
            print(
                f"  messages {s.messages}, decode errors {s.decode_errors}, "
                f"API accepted {f.accepted}, rejected {f.rejected}"
            )
    except KeyboardInterrupt:
        forwarder.flush()
    finally:
        client.loop_stop()
        client.disconnect()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="SpindleSage MQTT tools")
    parser.add_argument("--broker", default="127.0.0.1:1883", help="host:port")
    parser.add_argument("--tls-ca", help="CA certificate file; enables TLS")
    sub = parser.add_subparsers(dest="command", required=True)

    pub = sub.add_parser("publish", help="publish a simulated cell (synthetic data)")
    pub.add_argument("--scenario", default="healthy", choices=SCENARIOS)
    pub.add_argument("--seed", type=int, default=0)
    pub.add_argument("--speed", type=float, default=30.0, help="time compression factor")
    pub.add_argument("--site", default="lab")
    pub.add_argument("--loop", action="store_true", help="repeat the scenario forever")

    br = sub.add_parser("bridge", help="forward broker telemetry to the API")
    br.add_argument("--api", default="http://127.0.0.1:8000")
    br.add_argument("--batch", type=int, default=25)
    br.add_argument("--flush-seconds", type=float, default=5.0)

    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    return publish(args) if args.command == "publish" else bridge(args)


if __name__ == "__main__":
    raise SystemExit(main())
