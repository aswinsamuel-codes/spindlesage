# Changelog

All notable changes are recorded here. Versions follow [Semantic Versioning](https://semver.org/); before 1.0, minor versions may change APIs.

## [0.1.0] - 2026-11-22

First research release. **Research preview only:** all data is simulated or synthetic, and SpindleSage never controls machines.

### Added

- **Data and validation:** AI4I 2020 download with checksum and provenance metadata, a CNC telemetry schema with physical limits, and validation (operating envelope, missing, future and out-of-order data).
- **CNC cell simulator:** jobs, tool wear, ambient drift and four labelled fault types, plus named scenarios and live replay.
- **Experiment A:** failure prediction (threshold baseline, logistic regression, random forest, XGBoost) with a leakage guard, multi-seed protocol and provenance.
- **Experiment B:** anomaly detection (threshold vs Isolation Forest) with equal calibration, persistence alarms and event-level metrics.
- **Operations agent:** read-only evidence tools, BM25 retrieval over maintenance manuals, a rule engine and a Claude engine (`claude-opus-5-5`, structured outputs, refusal fallbacks), an evidence guard with deterministic fallback, and approval status.
- **REST API:** API-key roles, the human approval workflow (maintenance leads only, four-eyes rule, notes, expiry) and a hash-chained, tamper-evident audit trail.
- **Operations dashboard:** React + TypeScript; machines, telemetry charts, recommendations with citations, approvals and the audit trail.
- **Read-only gateways:** MQTT bridge (subscribe-only) and OPC UA collector (read-only), plus a simulated OPC UA server and an MQTT publisher.
- **Experiment C:** agent evaluation over 100 simulated cases in full and sensor-only context.
- **Security:** headers, strict CSP, body limit, failed-auth throttling, bandit, pip-audit and npm audit in CI, and a threat model.
- **Tests:** 238 Python tests (91% coverage, CI minimum 80%) and 14 dashboard tests.
- **Documentation:** architecture, installation, integrations, security, dependencies and licences, research report and experiment log.

### Known limitations

- No real-machine data, industrial pilot or user study.
- Experiment C has been run with the rule engine only; the Claude evaluation of H2 and H3 is pending.
- Speed drift is nearly undetectable without the commanded spindle speed.
- SQLite and an in-memory buffer instead of PostgreSQL/TimescaleDB; no MLflow, no Docker deployment.
- Not hardened for untrusted networks: needs TLS, SSO, OPC UA certificates and audit anchoring (see `docs/security.md`).
- `asyncua` (OPC UA extra) is LGPL-3.0; its use needs the project owner's sign-off before redistribution.

[0.1.0]: https://github.com/aswinsamuel-codes/spindlesage/releases/tag/v0.1.0
