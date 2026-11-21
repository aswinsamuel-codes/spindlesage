# Installation and running

Tested on Windows 11 (8 GB RAM laptop) and in GitHub Actions on Ubuntu. No Docker needed.

## Prerequisites

| Tool | Version | Needed for |
|---|---|---|
| [uv](https://docs.astral.sh/uv/) | 0.11+ | Python, dependencies and every command below. Downloads Python 3.12 automatically |
| Node.js | 24 | Building the dashboard (optional if you only use the API) |
| Git | any recent | Cloning |

## 1. Install

```bash
git clone https://github.com/aswinsamuel-codes/spindlesage.git
cd spindlesage
uv sync --all-extras        # --all-extras adds OPC UA support (asyncua, LGPL-3.0)
```

Check everything works:

```bash
uv run pytest               # about 1.5 minutes
```

## 2. Get the benchmark dataset (optional, recommended)

```bash
uv run python datasets/download_scripts/download_ai4i.py
```

This downloads AI4I 2020 (CC BY 4.0, synthetic) from UCI and verifies its SHA-256 checksum. Without it, everything still runs; the agent just has no failure-risk model.

## 3. Reproduce the experiments

```bash
uv run python -m experiments.exp_a_predictive --feature-set raw   # ~1 min
uv run python -m experiments.exp_b_anomaly                        # ~15 s
uv run python -m experiments.exp_c_agent                          # ~10 s, rule engine
```

Results go to `experiments/results/` (git-ignored) as `results.json` and `summary.md`, with the git commit and host recorded. Published numbers are in `research/experiment-log.md`.

## 4. Run the platform

```bash
# API keys: each is printed once; only hashes are stored in .spindlesage/
uv run python -m apps.api.keys add --user alice --role technician
uv run python -m apps.api.keys add --user carol --role maintenance_lead

# Dashboard (build once)
cd apps/dashboard && npm ci && npm run build && cd ../..

# API + dashboard with a simulated fault preloaded
uv run python -m apps.api --demo-scenario spindle_overheat
```

Open http://127.0.0.1:8000/dashboard/ and sign in with a key. API docs are at http://127.0.0.1:8000/docs.

Scenarios: `healthy`, `spindle_overheat`, `torque_spike`, `speed_drift`, `sensor_flatline`.

## 5. Live telemetry through OPC UA or MQTT (optional)

Start the API without `--demo-scenario`, then in two more terminals:

```bash
uv run python -m apps.api.keys add --user gateway --role ingest
export SPINDLESAGE_INGEST_KEY=...          # PowerShell: $env:SPINDLESAGE_INGEST_KEY = "..."

uv run python -m integrations.opcua server --scenario torque_spike --speed 60
uv run python -m integrations.opcua collect
```

MQTT works the same way with `integrations.mqtt publish` and `integrations.mqtt bridge`, but needs a broker such as Mosquitto on `127.0.0.1:1883`. See `docs/integrations.md`.

## 6. Use Claude for recommendations (optional, paid)

Set `ANTHROPIC_API_KEY` (or sign in with `ant auth login`), then either:

```bash
uv run python -m intelligence.agent --scenario torque_spike --engine claude
uv run python -m apps.api --demo-scenario torque_spike --engine claude
```

If the key is missing or the call fails, the agent falls back to the rule-based engine and records why.

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `SPINDLESAGE_DATA_DIR` | `.spindlesage` | Database and API key file |
| `SPINDLESAGE_ENGINE` | `rules` | `rules` or `claude` |
| `SPINDLESAGE_DEMO_SCENARIO` | none | Preload simulated telemetry |
| `SPINDLESAGE_APPROVAL_TTL_HOURS` | `8` | Approval request expiry |
| `SPINDLESAGE_EXPOSE_DOCS` | `1` | `0` hides `/docs` and `/openapi.json` |
| `SPINDLESAGE_INGEST_KEY` | none | Ingest key for the gateways |

## Troubleshooting

- **`Missing or invalid API key`:** create a key with `apps.api.keys`, and restart the API after adding keys (they are read at startup).
- **Recommendation returns 409:** the machine has fewer than 10 readings. Use `--demo-scenario` or start a gateway.
- **The dashboard shows "Not Found":** build it first (`npm run build` in `apps/dashboard`).
- **Port 8000 in use:** `uv run python -m apps.api --port 8001`.
- **Low-memory machines:** run experiments with `--n-jobs 1` (the default) and avoid running the experiments and the API at the same time.
