# Industrial data integration: MQTT and OPC UA

SpindleSage connects to machines **read-only**. Gateways collect telemetry and send it to the API with an `ingest`-role key, which can do nothing except add telemetry. No component writes to a machine, calls a machine method, or publishes a command.

```
 OPC UA server (machine / simulator) --read--> OPC UA collector --+
                                                                  +--> POST /telemetry (ingest key) --> API
 MQTT broker <--publish-- gateway / simulator    MQTT bridge -----+
             --subscribe (telemetry only)------>
```

## How read-only is enforced

| Layer | Mechanism |
|---|---|
| OPC UA collector | Only browses and reads values. A test scans `integrations/opcua/collector.py` and fails if a write, method call or node-management call appears. |
| OPC UA simulator | Variables are never made writable, so a client write is refused by the server (`BadUserAccessDenied`). A test tries this. |
| MQTT bridge | Subscribe-only. A test fails if `integrations/mqtt/bridge.py` ever calls `publish`. |
| MQTT publisher | The only publisher, used to replay simulated data. `guard_topic()` refuses any topic that is not `.../telemetry`. |
| API | The `ingest` role can only call `POST /telemetry`. The API has no machine-control endpoint. |

## MQTT

- **Topic:** `spindlesage/v1/<site>/<machine_id>/telemetry`
- **Payload:** one JSON object matching `CncTelemetryReading` (UTC timestamp with offset, five sensor values, product type). The maximum size is 16 KiB.
- **Validation:** the `machine_id` in the payload must match the topic, and invalid messages are counted and dropped. The API then runs the usual checks (out-of-order, future timestamps, unknown machine).
- **Credentials:** `SPINDLESAGE_MQTT_USERNAME` and `SPINDLESAGE_MQTT_PASSWORD` environment variables. Use `--tls-ca` for TLS.

```bash
# Simulated cell -> broker (synthetic data; 30x speed)
uv run python -m integrations.mqtt --broker 127.0.0.1:1883 publish --scenario torque_spike

# Broker -> API
export SPINDLESAGE_INGEST_KEY=...   # key with the ingest role
uv run python -m integrations.mqtt --broker 127.0.0.1:1883 bridge --api http://127.0.0.1:8000
```

A broker such as Eclipse Mosquitto is needed for manual runs. The tests start an in-process broker (amqtt) instead.

## OPC UA

Install the optional extra first: `uv sync --extra opcua` (asyncua, LGPL-3.0; see `docs/dependencies.md`).

Address space of the simulator, which a real deployment maps through `integrations/opcua/nodes.py`:

```
Objects/SpindleSage/<machine_id>/{AirTemperature, ProcessTemperature, SpindleSpeed,
                                  Torque, ToolWear, ProductType, SampleTime}
```

```bash
# Simulated cell as an OPC UA server on 127.0.0.1:4840 (synthetic data)
uv run python -m integrations.opcua server --scenario spindle_overheat --speed 60

# OPC UA -> API
export SPINDLESAGE_INGEST_KEY=...
uv run python -m integrations.opcua collect --endpoint opc.tcp://127.0.0.1:4840/spindlesage/
```

The collector polls (default once per second) and forwards one reading per machine each time `SampleTime` changes. On real equipment, use a secured endpoint, for example `--security "Basic256Sha256,SignAndEncrypt,client-cert.der,client-key.pem"`. The simulator offers no security and binds to localhost only.

## Live replay timing

The simulator scenario is computed up front and replayed. `--speed 30` turns the 30-second sample interval into one second of wall time. Readings are stamped with the time they are emitted, so the gap between stamps is the compressed one.

## Not yet done

- Subscriptions (OPC UA monitored items) instead of polling.
- Per-machine node maps loaded from configuration.
- Certificate management for secured OPC UA endpoints and TLS client certificates for MQTT.
- The commanded spindle speed, which would make speed drift detectable (see `research/experiment-log.md`).
