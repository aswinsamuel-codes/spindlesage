"""OPC UA tools (needs the optional extra: uv sync --extra opcua).

Run a simulated cell as an OPC UA server (SYNTHETIC DATA, localhost only):
    uv run python -m integrations.opcua server --scenario spindle_overheat

Collect from an OPC UA server into the API (needs SPINDLESAGE_INGEST_KEY):
    uv run python -m integrations.opcua collect --endpoint opc.tcp://127.0.0.1:4840/spindlesage/
"""

from __future__ import annotations

import argparse
import asyncio
import logging

from integrations.opcua.collector import OpcUaCollector
from integrations.opcua.nodes import DEFAULT_ENDPOINT
from integrations.opcua.sim_server import SimulatedCellServer
from integrations.simulator.scenarios import SCENARIOS
from integrations.sink import ApiTelemetrySink, TelemetryForwarder, ingest_key_from_env


async def _collect(args) -> None:
    forwarder = TelemetryForwarder(
        ApiTelemetrySink.from_url(args.api, ingest_key_from_env()), batch_size=args.batch
    )
    collector = OpcUaCollector(args.endpoint, forwarder.add, args.interval, args.security)
    task = asyncio.create_task(collector.run())
    try:
        while not task.done():
            await asyncio.sleep(args.flush_seconds)
            await asyncio.to_thread(forwarder.flush)
            s, f = collector.stats, forwarder.stats
            print(
                f"  polls {s.polls}, readings {s.readings}, invalid {s.invalid}, "
                f"API accepted {f.accepted}, rejected {f.rejected}"
            )
        await task
    finally:
        forwarder.flush()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="SpindleSage OPC UA tools")
    sub = parser.add_subparsers(dest="command", required=True)

    srv = sub.add_parser("server", help="simulated CNC cell as an OPC UA server")
    srv.add_argument("--endpoint", default=DEFAULT_ENDPOINT)
    srv.add_argument("--scenario", default="healthy", choices=SCENARIOS)
    srv.add_argument("--seed", type=int, default=0)
    srv.add_argument("--speed", type=float, default=30.0)
    srv.add_argument("--loop", action="store_true")

    col = sub.add_parser("collect", help="poll an OPC UA server and forward to the API")
    col.add_argument("--endpoint", default=DEFAULT_ENDPOINT)
    col.add_argument("--api", default="http://127.0.0.1:8000")
    col.add_argument("--interval", type=float, default=1.0, help="poll interval, seconds")
    col.add_argument("--security", help="asyncua security string, e.g. Basic256Sha256,...")
    col.add_argument("--batch", type=int, default=25)
    col.add_argument("--flush-seconds", type=float, default=5.0)

    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logging.getLogger("asyncua").setLevel(logging.WARNING)
    try:
        if args.command == "server":
            print(
                f"Simulated cell ({args.scenario}, synthetic) on {args.endpoint}. Ctrl+C to stop."
            )
            asyncio.run(
                SimulatedCellServer(
                    args.endpoint, args.scenario, args.seed, args.speed, loop=args.loop
                ).run()
            )
        else:
            asyncio.run(_collect(args))
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
