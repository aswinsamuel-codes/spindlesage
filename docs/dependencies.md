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
| anthropic | Apache-2.0 | Claude API client for the operations agent (imported only when the Claude engine is used) | 2026-11-21 |

The anthropic SDK pulls in httpx2 (BSD-3-Clause), jiter (MIT), sniffio (MIT or Apache-2.0), anyio (MIT) and others under permissive licences.

Transitive runtime dependencies pulled in by these (scipy, threadpoolctl, python-dateutil, tzdata, typing-extensions and others) are under permissive licences (BSD, MIT, Apache-2.0, PSF). Re-check them when versions change.

## Development

| Package | Licence | Purpose |
|---|---|---|
| pytest | MIT | Tests |
| ruff | MIT | Linting and formatting |

## Planned (not yet added)

FastAPI (MIT), MLflow (Apache-2.0), paho-mqtt (EPL-2.0 / EDL-1.0, needs review), asyncua (LGPL-3.0, needs review), React (MIT). Licences in this list are as commonly published and must be confirmed against the exact version when each is added.

## Decisions

- **LangGraph not adopted (2026-11-21).** The agent's steps are fixed (gather evidence, reason, guard, fall back), so a plain Python workflow is simpler to audit and needs no extra dependency. Revisit if the agent needs branching, multi-turn tool use or persistent graph state.
