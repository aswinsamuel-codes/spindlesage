# SpindleSage

**An evidence-grounded AI operations agent for manufacturing.**

SpindleSage is an open-source platform for intelligent manufacturing operations. It combines industrial data acquisition, machine learning, anomaly detection and context-aware AI agents. It helps manufacturing teams understand machine condition, spot abnormal operating patterns, investigate likely failures and make maintenance decisions based on evidence.

> **Status:** Research and architecture planning. Nothing here is production-ready. No industrial deployment or operational savings are claimed.

**Core philosophy:** Observe → Understand → Predict → Recommend → Act → Verify.

---

## Research question

> Can a context-aware AI agent combine machine telemetry, predictive models, anomaly detection, machine history and maintenance documentation to generate reliable, evidence-grounded operational recommendations?

| ID | Hypothesis |
|----|------------|
| H1 | On the selected benchmark datasets, machine-learning models identify failure patterns more effectively than simple threshold-based approaches. |
| H2 | Adding machine history and maintenance context improves recommendation quality compared with current sensor readings alone. |
| H3 | Structured model outputs and evidence retrieval reduce unsupported AI recommendations. |
| H4 | Human approval and audit mechanisms prevent unauthorized operational actions in the proposed workflow. |

Each hypothesis must be tested by experiment. See [docs/project-charter.md](docs/project-charter.md) for the full research plan.

## Initial use case

**Predictive maintenance for a CNC manufacturing cell.** The system receives machine telemetry, validates it, detects abnormal behavior, estimates failure risk where the data supports it, and generates maintenance recommendations. The initial environment is simulated and benchmarked against public datasets.

## Core modules

1. Machine Intelligence
2. Predictive Maintenance
3. Anomaly Detection
4. AI Operations Agent
5. Maintenance Knowledge Retrieval
6. Industrial Data Integration
7. Human Approval Workflow
8. Operations Dashboard
9. Model and Agent Evaluation

## Safety principles

- Read-only machine connectivity by default.
- No autonomous PLC or CNC control.
- No safety-critical decision is made by an LLM alone.
- Operational workflows require human approval.
- Role-based access control and traceable audit records.
- Uncertain predictions are handled explicitly.
- Failure and fallback behavior is documented.

## Repository layout

```
spindlesage/
├── apps/
│   ├── api/                 # FastAPI backend
│   └── dashboard/           # React + TypeScript operations dashboard
├── core/
│   ├── ingestion/           # Telemetry intake and validation
│   ├── telemetry/           # Time-series models and storage
│   ├── machine_registry/    # Machine metadata and history
│   └── event_engine/        # Events, alerts, approval workflow
├── intelligence/
│   ├── predictive/          # Failure-risk models (LR, RF, XGBoost)
│   ├── anomaly/             # Isolation Forest and threshold baselines
│   ├── agent/               # LangGraph operations agent
│   ├── retrieval/           # Maintenance knowledge retrieval
│   └── evaluation/          # Model and agent evaluation
├── integrations/
│   ├── mqtt/
│   ├── opcua/
│   └── simulator/           # Simulated CNC cell
├── datasets/
│   ├── metadata/            # Source, version, licence, preprocessing notes
│   └── download_scripts/    # Datasets are downloaded, never committed
├── experiments/             # Reproducible experiments A, B and C
├── research/                # Literature review and reports
├── docs/
├── tests/
├── scripts/
├── docker/
└── .github/workflows/
```

## Getting started (development)

Requires [uv](https://docs.astral.sh/uv/) and Python 3.12+.

```bash
git clone https://github.com/aswinsamuel-codes/spindlesage.git
cd spindlesage
uv sync
uv run ruff check .
uv run pytest
```

## Datasets

| Dataset | Role | Nature | Licence | Source |
|---------|------|--------|---------|--------|
| UCI AI4I 2020 Predictive Maintenance | Primary | **Synthetic** | CC BY 4.0 | https://doi.org/10.24432/C5HS5C |
| NASA PCoE Turbofan Engine Degradation Simulation | Secondary | Simulated | To be verified | https://zenodo.org/records/15346912 |

Datasets are never committed to this repository. Each one keeps its original attribution and licence, and its source, version, checksum and preprocessing are recorded in `datasets/metadata/`. Synthetic data is never presented as real factory data.

```bash
uv run python datasets/download_scripts/download_ai4i.py   # downloads and verifies the checksum
```

## Experiments

### Experiment A: predictive maintenance models

Compares a sensor alarm-limit baseline, Logistic Regression, Random Forest and XGBoost on AI4I 2020. Each seed uses a stratified 80/20 split, 5-fold cross-validation on the training split only, then one evaluation on the held-out test split. Failure-mode columns (TWF, HDF, PWF, OSF, RNF) are excluded from the features because they encode the target.

```bash
# Quick check (one seed)
uv run python -m experiments.exp_a_predictive --seeds 0

# Full run, e.g. on a cluster node: five seeds, all cores, both feature sets
uv run python -m experiments.exp_a_predictive --feature-set raw --n-jobs -1
uv run python -m experiments.exp_a_predictive --feature-set engineered --n-jobs -1
```

Results go to `experiments/results/exp_a/<timestamp>_<feature-set>/`: `results.json` (config, dataset checksum, environment, git commit, every run) and `summary.md`. The `engineered` features mirror how AI4I's synthetic failures were generated, so report both feature sets side by side.

### Experiment B: anomaly detection

Compares threshold alarms with Isolation Forest on the simulated CNC cell, using raw and contextual features. Detectors train on healthy data, are calibrated to the same healthy flag rate on a separate healthy period, then are scored on a test period with labelled faults. Metrics: detection recall and precision, false alarms per operating hour, and detection delay, overall and per fault type.

```bash
uv run python -m experiments.exp_b_anomaly --seeds 0     # quick check, about 10 s
uv run python -m experiments.exp_b_anomaly --n-jobs -1   # five seeds
```

Recorded results and how to read them: [research/experiment-log.md](research/experiment-log.md).

## CNC cell simulator

Generates **synthetic** CNC telemetry (jobs, tool changes, ambient drift) with labelled faults: spindle overheat, torque spike, speed drift and sensor flatline.

```bash
uv run python -m integrations.simulator --days 1 --machines 3 --faults 4 --out data/sim/cell.csv
```

This writes the readings CSV and a `.events.json` file with each fault's machine, type, start and end.

## Operations agent

The agent turns telemetry into an evidence-cited maintenance recommendation. It runs as a fixed workflow, so every step can be audited:

1. **Gather evidence** with read-only tools: latest readings and a window summary, validation, anomaly status (the threshold detector, chosen from Experiment B), failure risk (XGBoost from Experiment A), the machine record, maintenance history, and maintenance manual sections found by BM25 retrieval. Each item gets an id such as `ANO-1` or `DOC-2`.
2. **Reason** with Claude (one structured-output call) or with transparent rules. Every finding and action must cite evidence ids.
3. **Guard:** citations that don't exist, uncited claims, or high risk without supporting evidence make the output unusable. The agent then falls back to the rule-based engine and records why.
4. **Approve:** the agent never acts. Any action other than continued monitoring is returned as `pending_approval`.

```bash
# No API key needed (rule-based engine)
uv run python -m intelligence.agent --scenario spindle_overheat

# Claude engine: needs ANTHROPIC_API_KEY (or `ant auth login`); falls back to rules if unavailable
uv run python -m intelligence.agent --scenario torque_spike --engine claude

# Sensor-only context, the baseline for Experiment C
uv run python -m intelligence.agent --scenario torque_spike --mode sensor_only
```

Scenarios: `healthy`, `spindle_overheat`, `torque_spike`, `speed_drift` and `sensor_flatline`.

## REST API and approval workflow

A FastAPI service exposes telemetry, anomaly status, agent recommendations, human approvals and the audit trail. **It has no endpoint that sends anything to a machine.**

```bash
# 1. Create API keys (shown once; only hashes are stored in .spindlesage/, which git ignores)
uv run python -m apps.api.keys add --user alice --role technician
uv run python -m apps.api.keys add --user carol --role maintenance_lead

# 2. Start the server on 127.0.0.1:8000 with simulated telemetry preloaded
uv run python -m apps.api --demo-scenario spindle_overheat
```

Interactive docs are at http://127.0.0.1:8000/docs. Send the key as an `X-API-Key` header.

| Role | Can |
|---|---|
| `viewer` | Read machines, telemetry, recommendations and approvals |
| `ingest` | Send telemetry only (for gateways) |
| `technician` | Read, request recommendations, mark approved actions as done |
| `maintenance_lead` | Everything a technician can, plus approve or reject actions and read the audit trail |
| `admin` | Read, ingest, read the audit trail. Admins cannot approve maintenance actions |

Approval rules (hypothesis H4):
- Every proposed action other than continued monitoring opens an approval request.
- Only a maintenance lead can decide, and never on a recommendation they requested themselves (four-eyes rule).
- Rejections, and approvals of stop requests, need a written note.
- Requests expire after 8 hours (`SPINDLESAGE_APPROVAL_TTL_HOURS`).
- Only approved actions can be marked completed.
- Every change is written to a hash-chained audit trail in the same transaction. `GET /audit/verify` detects any edited or deleted record.

Data is stored in SQLite (`.spindlesage/spindlesage.db`) for now. The anomaly monitor is calibrated on simulated healthy data at startup, and `/health` says so. All of them are simulated. The maintenance manuals in `knowledge/` are illustrative documents written for the simulated cell (see [knowledge/README.md](knowledge/README.md)).

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

[Apache License 2.0](LICENSE).
