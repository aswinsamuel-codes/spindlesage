# Architecture

SpindleSage v0.1.0 is a research build. Everything runs on one machine, with simulated or synthetic data, and with no path that can control a machine.

## System overview

```
                        READ-ONLY                                      HUMAN DECISIONS
 ┌─────────────────┐  read/subscribe  ┌──────────────────┐  ingest key   ┌──────────────────────────────┐
 │ OPC UA servers   │ ───────────────▶ │ OPC UA collector │ ────────────▶ │                              │
 │ (machines / sim) │                  └──────────────────┘               │          REST API            │
 └─────────────────┘                                                      │  (FastAPI, apps/api)         │
 ┌─────────────────┐   subscribe      ┌──────────────────┐  ingest key   │                              │
 │ MQTT broker      │ ───────────────▶ │ MQTT bridge      │ ────────────▶ │  telemetry buffer            │
 └─────────────────┘                  └──────────────────┘               │  anomaly monitor             │
                                                                          │  operations agent ──▶ Claude │
 ┌─────────────────┐   user API key (same origin)                         │  approval workflow           │
 │ Dashboard (React)│ ◀──────────────────────────────────────────────────▶│  hash-chained audit (SQLite) │
 └─────────────────┘                                                      └──────────────────────────────┘
```

Data flows in one direction, towards SpindleSage. Decisions flow only to people: the agent proposes, a maintenance lead approves, and a technician acts on the machine by hand.

## Components

| Layer | Package | Responsibility |
|---|---|---|
| Telemetry model | `core/telemetry` | `CncTelemetryReading` schema with hard physical limits, and a bounded in-memory buffer per machine |
| Ingestion | `core/ingestion` | AI4I loader. Validation: operating-envelope warnings, errors for missing, future or out-of-order data |
| Machine registry | `core/machine_registry` | Machine records and maintenance history (synthetic fixture) |
| Event engine | `core/event_engine` | Roles and permissions, approval state machine, SQLite store, hash-chained audit trail |
| Simulator | `integrations/simulator` | CNC cell with jobs, tool changes, ambient drift and labelled fault injection. Named scenarios and live replay |
| Gateways | `integrations/mqtt`, `integrations/opcua`, `integrations/sink.py` | Read-only collection, validation, and batched forwarding to the API |
| Predictive | `intelligence/predictive` | Experiment A models; the XGBoost failure-risk model served to the agent |
| Anomaly | `intelligence/anomaly` | Causal per-machine features, threshold and Isolation Forest detectors, calibrated alarm policy, online monitor |
| Retrieval | `intelligence/retrieval` | BM25 over the maintenance manuals, with citable section ids |
| Agent | `intelligence/agent` | Evidence tools, rule and Claude engines, evidence guard, fallback, approval status |
| Evaluation | `intelligence/evaluation` | Metrics and runners for Experiments A, B and C, run provenance |
| API | `apps/api` | Authentication, endpoints, security middleware, serving the dashboard |
| Dashboard | `apps/dashboard` | React + TypeScript UI for technicians and maintenance leads |

## The agent workflow

```
gather_evidence()  ──▶  engine.recommend()  ──▶  check_recommendation()  ──▶  record + approvals
 TEL, VAL, ANO,         rules or Claude          guard: every claim cites      one approval request
 PRED, MACH, HIST,      (structured output)      real evidence; high risk      per operational action,
 DOC (BM25)                                      needs support                 all "pending"
                              │                         │ fails
                              └──── EngineError ───────▶ rule-based fallback (reason recorded)
```

The steps are fixed in code, not chosen by the model, so every run can be audited. The Claude engine makes one structured-output call (`claude-opus-5-5`, with server-side refusal fallbacks) and has no tools.

## Safety design

1. **No control path.** No API endpoint, gateway or agent action can write to a machine. Tests scan gateway source for write calls and check that the OPC UA simulator refuses client writes.
2. **Recommendations, not actions.** Every operational action becomes a pending approval request.
3. **Separation of duties.** Only maintenance leads decide, never on their own request. Admins cannot approve.
4. **Evidence or nothing.** Claims without valid citations are rejected, and the deterministic fallback takes over.
5. **Traceability.** Every change is audited in the same database transaction, in a tamper-evident hash chain.
6. **Honest data labels.** Every dataset, result and UI page says when data is synthetic.

## Charter stack vs v0.1.0

| Charter item | v0.1.0 | Reason |
|---|---|---|
| FastAPI, scikit-learn, XGBoost, React, TypeScript, uv, Ruff, Pytest, GitHub Actions | Used | |
| MQTT / Mosquitto, OPC UA | Used (paho-mqtt, asyncua). Mosquitto is optional for manual runs | Tests use an in-process broker |
| LangGraph | Not used | The workflow is fixed; plain Python is easier to audit (`docs/dependencies.md`) |
| PostgreSQL / TimescaleDB | Not yet: SQLite plus an in-memory telemetry buffer | Runs on the development laptop without Docker |
| MLflow | Not yet | Experiments write versioned `results.json` with provenance instead |
| Docker Compose | Not yet | Planned for deployment on the lab cluster |
