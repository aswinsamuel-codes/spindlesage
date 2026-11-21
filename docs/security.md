# Security model

SpindleSage is a research build. It runs on simulated data and is meant for a single trusted host or lab network. This document records what it protects, how, and what is still missing before any real deployment.

## Assets

| Asset | Why it matters |
|---|---|
| Machines and people on the shop floor | The worst outcome is a machine doing something unsafe. |
| Approval decisions and the audit trail | They must show truthfully who decided what, and when. |
| API keys | They grant roles, including approving maintenance actions. |
| Telemetry and maintenance history | Operational data that could reveal production details. |
| LLM API credentials | Billing and data exposure. |

## Trust boundaries

```
 [Machines / OPC UA servers] --read--> [Gateways: OPC UA collector, MQTT bridge] --ingest key--> [API]
 [MQTT broker] ----subscribe--------^                                                             |
 [Browser dashboard] --user key, same origin------------------------------------------------------>|
 [API] --HTTPS, API key--> [Claude API]   (only when the claude engine is enabled)
```

## Threats and controls (STRIDE)

| Threat | Example | Control | Where | Verified by |
|---|---|---|---|---|
| **Tampering with machines** | Agent or attacker sends a command to a CNC | No control path exists: gateways are read-only, the API has no machine endpoint, the agent only proposes | `integrations/`, `apps/api/app.py` | Source scans for write calls, the OPC UA server refuses writes (`tests/test_integrations.py`) |
| **Elevation of privilege** | Technician approves their own work | RBAC, maintenance-lead-only decisions, four-eyes rule, admin cannot approve | `core/event_engine/` | `tests/test_api.py::TestApprovalWorkflow` |
| **Repudiation** | Someone denies approving an action | Every change is written with actor and role to a hash-chained audit trail in the same transaction | `core/event_engine/store.py` | `TestAuditChain` (edits and deletions detected) |
| **Tampering with records** | Editing the database to rewrite history | Hash chain plus `/audit/verify`. It detects tampering but cannot prevent it, so the chain head must also be anchored externally (see gaps) | `store.py` | `TestAuditChain` |
| **Spoofing** | Stolen or guessed API key | 256-bit random keys, stored only as SHA-256 hashes, constant-time compare, failed-auth logging and throttling, keys only in `sessionStorage` in the browser | `apps/api/auth.py`, `security.py` | `TestAuth`, `TestHardening` |
| **Spoofing telemetry** | Fake readings to trigger or hide alarms | Ingest role limited to telemetry, schema validation, out-of-order and future-timestamp rejection, topic and machine_id consistency for MQTT | `core/ingestion/`, `integrations/mqtt/codec.py` | `test_telemetry.py`, `test_integrations.py` |
| **LLM misuse** | Model invents evidence or overstates risk | Structured outputs, an evidence guard (unknown or missing citations and unsupported high risk are rejected), fallback to rules, human approval anyway | `intelligence/agent/` | `test_agent.py`, Experiment C |
| **Prompt injection via data** | Text in a manual or note steers the model | Manuals are local, curated files. Notes are not sent to the model. The model has no tools and cannot act; output is checked by the guard and approved by a person | `intelligence/agent/` | Design; see gaps |
| **Information disclosure** | Data cached by a browser or proxy | `Cache-Control: no-store` on data responses, no CORS, security headers, strict CSP on the dashboard | `apps/api/security.py` | `TestHardening` |
| **Denial of service** | Huge request bodies, unbounded buffers | 1 MiB body limit, 1,000 readings per batch, bounded telemetry and gateway buffers | `security.py`, `buffer.py`, `sink.py` | `TestHardening`, `TestForwarder` |
| **Supply chain** | Vulnerable or incompatible dependency | Lock files, licence review for every dependency, `pip-audit` and `npm audit` in CI | `uv.lock`, `package-lock.json`, CI | CI `security` job |
| **Insecure transport** | Keys sent in clear text | API binds to 127.0.0.1 by default. Gateways warn when sending a key over plain HTTP to a non-local host. TLS options for MQTT and a security string for OPC UA | `apps/api/__main__.py`, `integrations/` | Manual |

## Automated checks

| Check | Tool | Run |
|---|---|---|
| Static analysis | bandit (findings fixed or annotated with a reason) | CI `security` job |
| Known vulnerabilities | pip-audit (all locked Python packages), npm audit | CI `security` job |
| Security behaviour | pytest suites listed above | CI `test` job |

The last manual run (2026-11-22) found no bandit issues after fixes, no known vulnerabilities in 186 locked Python packages, and 0 npm vulnerabilities.

## Known gaps before any real deployment

1. **TLS termination.** Serve the API only behind HTTPS (reverse proxy) and keep it off untrusted networks.
2. **Audit anchoring.** Periodically copy the latest audit hash to write-once storage, or sign it, so a full rewrite of the database is detectable too.
3. **Identity.** Replace shared API keys for people with single sign-on (OIDC) and per-user sessions. Keep keys for gateways only, with rotation and expiry.
4. **OPC UA security.** Use Sign and SignAndEncrypt endpoints with managed certificates. The simulator is unsecured by design and local-only.
5. **MQTT.** Require broker authentication, TLS and per-topic ACLs (gateways may only publish `.../telemetry`, the bridge may only subscribe).
6. **Throttle scope.** The failed-auth throttle is in-memory and per process. Use the reverse proxy or a shared store when running several instances.
7. **LLM data handling.** Review what telemetry and history may be sent to an external model provider, and the provider's retention terms, before enabling the Claude engine on real data.
8. **Penetration test.** No external security testing has been done.
