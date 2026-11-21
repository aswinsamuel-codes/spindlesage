# Dependencies and licences

Every dependency is checked for licence compatibility with Apache 2.0 before it is added. Versions are pinned in `uv.lock`.

## Runtime

| Package | Licence | Purpose | Added |
|---|---|---|---|
| numpy | BSD-3-Clause (bundled parts: 0BSD, MIT, Zlib, CC0-1.0) | Numerical arrays | 2026-11-21 |
| pandas | BSD-3-Clause | Tabular data | 2026-11-21 |
| scikit-learn | BSD-3-Clause | Baseline models, metrics, splitting | 2026-11-21 |
| xgboost | Apache-2.0 | Gradient-boosted trees | 2026-11-21 |
| pydantic | MIT | Telemetry schema validation | 2026-11-21 |
| paho-mqtt | EPL-2.0 OR BSD-3-Clause (used under BSD-3-Clause) | MQTT client for the bridge and publisher | 2026-11-22 |
| fastapi | MIT | REST API (with starlette, BSD-3-Clause) | 2026-11-21 |
| uvicorn | BSD-3-Clause | ASGI server (with h11 MIT, click BSD-3-Clause) | 2026-11-21 |
| anthropic | Apache-2.0 | Claude API client for the operations agent (imported only when the Claude engine is used) | 2026-11-21 |

The anthropic SDK pulls in httpx2 (BSD-3-Clause), jiter (MIT), sniffio (MIT or Apache-2.0), anyio (MIT) and others under permissive licences.

Transitive runtime dependencies pulled in by these (scipy, threadpoolctl, python-dateutil, tzdata, typing-extensions and others) are under permissive licences (BSD, MIT, Apache-2.0, PSF). Re-check them when versions change.

## Optional extras

| Extra | Package | Licence | Purpose |
|---|---|---|---|
| `opcua` | asyncua (pulls in cryptography Apache-2.0/BSD, aiosqlite MIT, sortedcontainers Apache-2.0, pytz MIT) | **LGPL-3.0** | OPC UA simulator and collector |

asyncua is LGPL-3.0. SpindleSage imports it unmodified as a separate library, which LGPL-3.0 permits from an Apache-2.0 project; anyone distributing a modified asyncua must publish those modifications under the LGPL. It is kept as an optional extra so the core install contains no LGPL code. **Needs a final review by the project owner before the first release.**

## Development

| Package | Licence | Purpose |
|---|---|---|
| pytest | MIT | Tests |
| httpx | BSD-3-Clause | FastAPI test client |
| amqtt | MIT | In-process MQTT broker for integration tests |
| pytest-cov | MIT | Coverage measurement |
| asyncua | LGPL-3.0 | OPC UA integration tests |
| ruff | MIT | Linting and formatting |

## Dashboard (npm, apps/dashboard)

| Package | Licence | Purpose |
|---|---|---|
| react, react-dom | MIT | UI |
| vite, @vitejs/plugin-react | MIT | Dev server and build |
| typescript | Apache-2.0 | Type checking |
| vitest, jsdom | MIT | Tests |
| @testing-library/react, user-event, jest-dom | MIT | Component tests |

Versions are locked in `apps/dashboard/package-lock.json`. No charting library: the line charts are plain SVG.

## Planned (not yet added)

MLflow (Apache-2.0). Licences in this list are as commonly published and must be confirmed against the exact version when each is added.

## Decisions

- **LangGraph not adopted (2026-11-21).** The agent's steps are fixed (gather evidence, reason, guard, fall back), so a plain Python workflow is simpler to audit and needs no extra dependency. Revisit if the agent needs branching, multi-turn tool use or persistent graph state.
- **SQLite before PostgreSQL (2026-11-21).** Recommendations, approvals and the audit trail use the standard-library sqlite3 module so the API runs on the development laptop without Docker. The schema uses plain SQL types to ease a later move to PostgreSQL/TimescaleDB.
