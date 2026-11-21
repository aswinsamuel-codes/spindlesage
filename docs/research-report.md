# SpindleSage v0.1.0: research report

**Evidence-grounded AI recommendations for predictive maintenance in a simulated CNC cell**

Status: interim report for the v0.1.0 research release (November 2026). All data is simulated or from synthetic benchmarks. No result here demonstrates performance on real machines or real savings.

---

## Summary

SpindleSage combines telemetry validation, failure-risk models, anomaly detection, maintenance-document retrieval and an AI agent that proposes maintenance actions. Every proposal must cite evidence, and a maintenance lead must approve it. Three experiments were run on a development laptop:

- **Failure prediction (H1).** On AI4I 2020, XGBoost reaches a PR-AUC of 0.78 ± 0.03, against 0.30 ± 0.06 for a sensor alarm-limit baseline. The benchmark is synthetic and favours tree models.
- **Anomaly detection.** On a simulated cell with labelled faults, calibrated per-feature thresholds on contextual features detect 81% of faults, at 0.02 false alarms per operating hour and a median delay of 5 minutes. Isolation Forest trailed on every metric. Speed drift stays almost undetectable without the commanded spindle speed.
- **Agent context (H2), first evidence.** With the same deterministic engine, full context (anomaly status, history, manuals, risk model) detects 78% of faults on held-out seeds with no false alarms. Sensor-only context detects none. The LLM version of this test has not been run yet.
- **Unsupported claims (H3).** The evidence guard and structured schema are in place and tested. The comparison that tests H3 needs the Claude engine and is not done yet.
- **Approval (H4).** In all 200 evaluated recommendations, every operational action opened a pending approval and none was approved automatically. Tests show that only maintenance leads can decide, never on their own requests, and that tampering with the audit trail is detected.

## 1. Research question and hypotheses

> Can a context-aware AI agent combine machine telemetry, predictive models, anomaly detection, machine history and maintenance documentation to generate reliable, evidence-grounded operational recommendations?

| ID | Hypothesis | Status in v0.1.0 |
|---|---|---|
| H1 | ML models identify failure patterns better than simple thresholds on the selected benchmark | **Supported on AI4I 2020** (synthetic) |
| H2 | Machine history and maintenance context improve recommendation quality over current readings alone | **Supported for the rule engine; untested for an LLM** |
| H3 | Structured outputs and evidence retrieval reduce unsupported recommendations | **Mechanism built and tested; not yet measured against a baseline** |
| H4 | Human approval and audit mechanisms prevent unauthorized operational actions in the proposed workflow | **Supported for the implemented workflow** |

## 2. Data

| Source | Nature | Used for |
|---|---|---|
| UCI AI4I 2020 (Matzka, 2020; CC BY 4.0; 10,000 rows, 3.4% failures) | Synthetic benchmark | Experiment A, and the agent's failure-risk model |
| SpindleSage CNC simulator | Simulated, labelled faults | Experiments B and C, the demos and the gateways |
| Maintenance manuals in `knowledge/` | Illustrative documents written for the simulator | Retrieval and citations |
| Machine registry and history | Synthetic fixture | Agent context |

The simulator models three machines with jobs (spindle speed and cutting power per job), tool wear and tool changes, and ambient drift. It injects four fault types with exact labels: spindle overheat (a temperature ramp), torque spike (a step), speed drift (a ramp) and sensor flatline (a frozen value). The NASA turbofan dataset named in the charter has not been used yet.

## 3. Methods

**Experiment A (failure prediction).** Stratified 80/20 split per seed, 5-fold cross-validation on the training split only, then one held-out test evaluation. There are 5 seeds. Failure-mode columns, which encode the label, are excluded. The baseline flags a failure when any sensor leaves its healthy [0.01, 0.99] quantile band.

**Experiment B (anomaly detection).** Per seed: 3 days of healthy training data, 1 day of healthy calibration data, then 3 days of test data with 8 faults per machine. Both detectors are calibrated to flag 0.2% of healthy calibration samples and need 3 consecutive exceedances to alarm. Metrics are event-based: detection recall and precision, false alarms per operating hour, and detection delay.

**Experiment C (agent).** 100 cases: 5 scenarios × 5 seeds × 2 stages (20 and 90 minutes into the fault) × 2 machines (faulty and healthy). Each case runs with `full` and `sensor_only` context. A run is correct when the issue is flagged exactly when a fault exists and the action type fits the fault. The experiment also measures attribution, right-manual citation, unsupported claims (from the guard, before any fallback), tool success, approval compliance, latency and cost.

All runs record the git commit, host, package versions and dataset checksum.

## 4. Results

### 4.1 Experiment A (AI4I 2020, raw features, 5 seeds)

| Model | PR-AUC | F1 | Precision | Recall |
|---|---|---|---|---|
| Sensor threshold baseline | 0.300 ± 0.060 | 0.257 ± 0.044 | 0.178 ± 0.028 | 0.468 ± 0.090 |
| Logistic regression | 0.425 ± 0.056 | 0.239 ± 0.017 | 0.140 ± 0.010 | 0.803 ± 0.065 |
| Random forest | 0.739 ± 0.035 | 0.648 ± 0.031 | 0.787 ± 0.060 | 0.553 ± 0.034 |
| XGBoost | **0.779 ± 0.032** | **0.700 ± 0.036** | 0.639 ± 0.038 | 0.776 ± 0.045 |

Engineered features (temperature difference, mechanical power, wear × torque) raise tree models to a PR-AUC of about 0.87–0.89. Those features restate the rules that generated AI4I's failures, so the raw-feature table is the headline.

### 4.2 Experiment B (simulated cell, 5 seeds)

| Detector / features | Detection recall | Detection precision | False alarms / h | Median delay (min) |
|---|---|---|---|---|
| Threshold / raw | 0.567 ± 0.124 | 0.729 ± 0.232 | 0.057 ± 0.070 | 19.5 ± 7.6 |
| Isolation Forest / raw | 0.083 ± 0.078 | 0.388 ± 0.335 | 0.070 ± 0.106 | 20.4 ± 10.0 |
| **Threshold / contextual** | **0.808 ± 0.076** | **0.874 ± 0.075** | **0.021 ± 0.015** | **5.0 ± 0.7** |
| Isolation Forest / contextual | 0.233 ± 0.146 | 0.545 ± 0.221 | 0.025 ± 0.011 | 33.7 ± 16.0 |

By fault type, the threshold detector on contextual features scores: overheat 1.00, torque spike 1.00, sensor flatline 1.00, speed drift 0.12. Measuring rolling variability on a log scale was essential for frozen sensors: flatline recall rose from 0.63 to 1.00 compared with a linear scale.

### 4.3 Experiment C (held-out seeds 5–9, rule-based engine)

| Context | Accuracy | Fault detection | False alarms | Right action | Right manual cited | Unsupported claims / run | Approval compliance |
|---|---|---|---|---|---|---|---|
| Full | **91%** | **78%** | 0% | 78% | 78% | 0.00 | 100% |
| Sensor only | 60% | 0% | 0% | 0% | 0% | 0.00 | 100% |

With full context, overheat, torque spike and sensor flatline were correct in every case at both stages. Speed drift was correct in 0% of early cases and 20% of late ones. A retrieval gap found on seeds 0–4 (torque spikes that alarmed on cutting power retrieved the wrong manual) was fixed and confirmed on these held-out seeds.

## 5. Discussion

**H1.** Tree ensembles clearly beat alarm limits on AI4I, with non-overlapping spreads across seeds. This says little about real machines: AI4I's failures follow simple rules over exactly these sensors.

**Simple, calibrated thresholds beat Isolation Forest.** With equal calibration and alarm rules, per-feature thresholds on physically meaningful features (temperature rise, cutting power, log-scale variability) outperformed Isolation Forest. The simulator is partly responsible: most injected faults push one signal out of range, which thresholds are built to catch. Multivariate faults, where every signal stays in range, are needed before generalising.

**Context is what makes faults visible (H2).** Readings alone, checked against a generic operating envelope, never flagged a fault, even 90 minutes in. The same rules with anomaly status and documents caught three of four fault types within 20 minutes. Because the rule engine was written alongside these scenarios, this shows what the evidence makes *possible*. Whether an LLM uses it well is the open H2 question.

**The approval design holds (H4) for what it covers.** The workflow cannot auto-approve, separates duties, and records every decision in a tamper-evident chain. It does not cover a compromised host, stolen lead credentials, or someone editing the database and recomputing the whole chain; `docs/security.md` lists these gaps.

**Speed drift is a data problem, not a model problem.** Every method fails on it, because the telemetry lacks the commanded spindle speed. Adding that signal, which real controllers expose over OPC UA, is the most valuable next data change.

## 6. Limitations

- All data is synthetic or simulated. The simulator's parameters are illustrative, not calibrated to a real machine.
- The maintenance manuals were written for the simulator, so retrieval quality on real manuals is unknown.
- Experiment C uses the rule-based engine only. The LLM results needed for H2 and H3 are pending.
- One fault magnitude per scenario, and four fault types.
- One development machine. No load, latency or long-running stability testing.
- No industrial pilot, user study or external security test.

## 7. Next steps

1. Run Experiment C with the Claude engine (about 200 calls, after cost approval). Add a free-text baseline without structured output or the guard to test H3.
2. Add the commanded spindle speed to the telemetry schema, simulator and OPC UA mapping.
3. Add multivariate and gradual faults to the simulator, and vary fault magnitudes.
4. Evaluate on the NASA turbofan dataset (remaining-useful-life framing).
5. Docker Compose deployment on the lab cluster, then PostgreSQL/TimescaleDB, then MLflow tracking.
6. Before any pilot: TLS, single sign-on, OPC UA certificates and audit anchoring (`docs/security.md`).

## Reproducing

See `docs/installation.md`. Exact numbers, commits and caveats for every run are in `research/experiment-log.md`.

## References

1. Matzka, S. (2020). *AI4I 2020 Predictive Maintenance Dataset* [Dataset]. UCI Machine Learning Repository. https://doi.org/10.24432/C5HS5C
2. Liu, F. T., Ting, K. M., and Zhou, Z.-H. (2008). Isolation Forest. *Proceedings of the 8th IEEE International Conference on Data Mining*, 413–422.
3. Robertson, S., and Zaragoza, H. (2009). The Probabilistic Relevance Framework: BM25 and Beyond. *Foundations and Trends in Information Retrieval*, 3(4), 333–389.
4. Chen, T., and Guestrin, C. (2016). XGBoost: A Scalable Tree Boosting System. *Proceedings of KDD 2016*, 785–794.
5. NIST (2017). *Reference Architecture to Integrate Heterogeneous Manufacturing Systems for the Digital Thread.*
6. OPC Foundation. *OPC Unified Architecture.* https://opcfoundation.org/about/what-is-opc/
