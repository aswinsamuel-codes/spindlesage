"""Run the API server.

    uv run python -m apps.api --demo-scenario spindle_overheat

Binds to 127.0.0.1 by default so the API is not exposed on the network.
Use --host 0.0.0.0 only behind proper network controls and TLS.
"""

from __future__ import annotations

import argparse
import os

import uvicorn


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="SpindleSage API server")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--demo-scenario", help="preload simulated telemetry for this scenario")
    parser.add_argument("--engine", choices=("rules", "claude"))
    parser.add_argument("--data-dir", help="folder for the database and API key file")
    args = parser.parse_args(argv)

    if args.data_dir:
        os.environ["SPINDLESAGE_DATA_DIR"] = args.data_dir
    if args.demo_scenario:
        os.environ["SPINDLESAGE_DEMO_SCENARIO"] = args.demo_scenario
    if args.engine:
        os.environ["SPINDLESAGE_ENGINE"] = args.engine

    from apps.api.app import create_app

    uvicorn.run(create_app(), host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
