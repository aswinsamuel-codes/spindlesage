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

| Dataset | Role | Source |
|---------|------|--------|
| UCI AI4I 2020 Predictive Maintenance | Primary | https://archive.ics.uci.edu/dataset/601/ai4i |
| NASA PCoE Turbofan Engine Degradation Simulation | Secondary | https://zenodo.org/records/15346912 |

Datasets are never committed to this repository. Each one keeps its original attribution and licence, and its source, version and preprocessing are recorded in `datasets/metadata/`. Synthetic data is never presented as real factory data.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

[Apache License 2.0](LICENSE).
