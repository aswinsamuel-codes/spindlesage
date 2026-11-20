# SpindleSage: Project Charter
## Intelligent Manufacturing Operations Agent

**Project type:** Open-source industrial AI platform
**Development approach:** Research-driven, modular, simulation-first
**Initial application:** Predictive maintenance for CNC manufacturing cells
**Repository:** https://github.com/aswinsamuel-codes/spindlesage
**License:** Apache 2.0
**Status:** Research and architecture planning

---

## 1. Vision

SpindleSage is an open-source intelligent manufacturing operations platform that combines industrial data acquisition, machine learning, anomaly detection and context-aware AI agents.

Its purpose is to help manufacturing teams understand machine condition, identify abnormal operating patterns, investigate potential failures and make evidence-based maintenance decisions.

### Core philosophy

Observe → Understand → Predict → Recommend → Act → Verify.

## 2. Primary research problem

Manufacturing facilities generate large volumes of operational data. Integrating heterogeneous machine information and turning it into actionable decisions is still hard.

This project investigates whether context-aware AI agents, combined with predictive machine-learning models, can improve the quality, explainability and traceability of predictive maintenance workflows.

## 3. Research question

Can a context-aware AI agent combine machine telemetry, predictive models, anomaly detection, machine history and maintenance documentation to generate reliable, evidence-grounded operational recommendations?

### Research hypotheses

- **H1:** On the selected benchmark datasets, machine-learning models identify failure patterns more effectively than simple threshold-based approaches.
- **H2:** Adding machine history and maintenance context improves AI recommendation quality compared with current sensor readings alone.
- **H3:** Structured model outputs and evidence retrieval reduce unsupported AI recommendations.
- **H4:** Human approval and audit mechanisms prevent unauthorized operational actions in the proposed workflow.

Each hypothesis must be tested by experiment.

## 4. Initial use case

**Predictive maintenance for a CNC manufacturing cell.**

The system receives machine telemetry, validates it, detects abnormal behavior, estimates failure risk where the available data supports it, and generates maintenance recommendations.

The initial environment is simulated and benchmarked against publicly available datasets.

No real industrial deployment or operational savings will be claimed without supporting evidence.

## 5. Core modules

1. Machine Intelligence
2. Predictive Maintenance
3. Anomaly Detection
4. AI Operations Agent
5. Maintenance Knowledge Retrieval
6. Industrial Data Integration
7. Human Approval Workflow
8. Operations Dashboard
9. Model and Agent Evaluation

## 6. Initial technology stack

- Python 3.12+
- FastAPI
- Scikit-learn
- XGBoost
- LangGraph
- PostgreSQL
- TimescaleDB
- MQTT / Mosquitto
- OPC UA integration
- React
- TypeScript
- MLflow
- Docker Compose
- uv
- Ruff
- Pytest
- GitHub Actions

Every dependency and its licence must be checked before it is added.

## 7. Dataset strategy

**Primary dataset:** UCI AI4I 2020 Predictive Maintenance Dataset.

**Secondary research dataset:** NASA PCoE Turbofan Engine Degradation Simulation Dataset.

Additional datasets will be evaluated for industrial anomaly detection and sensor analysis.

Dataset rules:

- Preserve original attribution.
- Verify licensing.
- Record source and version.
- Document preprocessing.
- Prevent train/test leakage.
- Never present synthetic data as real factory data.

## 8. Research experiments

### Experiment A: Predictive maintenance

Compare Logistic Regression, Random Forest and XGBoost.

Metrics: precision, recall, F1-score, PR-AUC, confusion matrix, inference latency.

### Experiment B: Anomaly detection

Compare Isolation Forest with threshold-based detection.

Metrics: detection precision, detection recall, false alarms per operating hour, detection delay.

### Experiment C: Agent intelligence

Compare:

- an agent using current sensor readings only, with
- an agent using sensor readings, machine history, predictive outputs and maintenance documentation.

Metrics: recommendation correctness, evidence attribution, unsupported claims, tool execution success, human approval compliance, latency and inference cost.

## 9. Safety requirements

- Read-only machine connectivity by default.
- No autonomous PLC or CNC control.
- No safety-critical decision is made by an LLM alone.
- Human approval for operational workflows.
- Role-based access control.
- Traceable audit records.
- Explicit handling of uncertain predictions.
- Secure credentials and communication.
- Documented failure and fallback behavior.

## 10. Repository architecture

See the layout in the [README](../README.md#repository-layout).

## 11. Ten-week development roadmap

| Week | Focus |
|------|-------|
| 1 | Research and requirements |
| 2 | Data engineering and telemetry ingestion |
| 3 | Predictive maintenance models |
| 4 | Anomaly detection |
| 5 | AI agent and knowledge retrieval |
| 6 | Backend integration |
| 7 | Operations dashboard |
| 8 | MQTT and OPC UA integration |
| 9 | Evaluation, testing and security |
| 10 | Research report, case study and open-source release |

The timeline is provisional and depends on research and validation results.

## 12. Deliverables

1. Public GitHub repository.
2. Software requirements specification.
3. System architecture documentation.
4. Literature review.
5. Dataset documentation.
6. Reproducible ML experiments.
7. Predictive maintenance engine.
8. Anomaly detection engine.
9. Context-aware AI agent.
10. REST API.
11. Operations dashboard.
12. Simulated CNC manufacturing environment.
13. Docker deployment.
14. Automated test suite.
15. Research report.
16. Industrial case study.
17. Demonstration video.
18. Installation and contribution guides.

## 13. Future development

**Phase 2:** multi-machine support, real industrial telemetry, OPC UA deployment, CMMS integration, maintenance team feedback.

**Phase 3:** production optimization, quality inspection, multi-agent workflows, multi-factory deployment, enterprise analytics.

## 14. Definition of success

The first release is successful when:

- The system can ingest machine telemetry.
- Data validation is automated.
- Predictive and anomaly models are reproducible.
- The agent can retrieve relevant evidence.
- Recommendations are traceable.
- Human approval is enforced.
- The dashboard presents operational information.
- The application runs from documented installation steps.
- External contributors can reproduce the experiments.
- Limitations and dataset provenance are documented transparently.

## 15. Research references

1. NIST: *Reference Architecture to Integrate Heterogeneous Manufacturing Systems for the Digital Thread* (2017). https://www.nist.gov/publications/reference-architecture-integrate-heterogeneous-manufacturing-systems-digital-thread
2. UCI: *AI4I 2020 Predictive Maintenance Dataset.* https://archive.ics.uci.edu/dataset/601/ai4i
3. NASA PCoE: *Turbofan Engine Degradation Simulation Dataset.* https://zenodo.org/records/15346912
4. OPC Foundation: *Industrial Interoperability.* https://opcfoundation.org/about/what-is-opc/
5. NIST: *Super Intelligence for Manufacturing.* https://www.nist.gov/programs-projects/super-intelligence-si-manufacturing

---

**Project status:** Architecture and research direction are established. Implementation, experimental validation, an industrial pilot and commercial readiness are future milestones.
