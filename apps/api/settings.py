"""API settings from environment variables (all optional).

SPINDLESAGE_DATA_DIR          default .spindlesage (git-ignored)
SPINDLESAGE_DB_PATH           default <data dir>/spindlesage.db
SPINDLESAGE_API_KEYS_FILE     default <data dir>/api_keys.json
SPINDLESAGE_ENGINE            rules (default) or claude
SPINDLESAGE_DEMO_SCENARIO     preload simulated telemetry: healthy, spindle_overheat, ...
SPINDLESAGE_APPROVAL_TTL_HOURS  default 8
SPINDLESAGE_AI4I_PATH         default datasets/raw/ai4i2020/ai4i2020.csv
SPINDLESAGE_EXPOSE_DOCS       1 (default) or 0 to hide /docs and /openapi.json
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from core.ingestion.ai4i import DEFAULT_PATH as AI4I_DEFAULT


@dataclass(frozen=True)
class Settings:
    db_path: Path | str = Path(".spindlesage/spindlesage.db")
    api_keys_file: Path = Path(".spindlesage/api_keys.json")
    engine: str = "rules"
    demo_scenario: str | None = None
    approval_ttl_hours: float = 8.0
    ai4i_path: Path | None = AI4I_DEFAULT
    seed: int = 0
    # Interactive API docs at /docs. Set SPINDLESAGE_EXPOSE_DOCS=0 to hide them.
    expose_docs: bool = True

    def __post_init__(self) -> None:
        if self.engine not in ("rules", "claude"):
            raise ValueError("engine must be 'rules' or 'claude'")
        if self.approval_ttl_hours <= 0:
            raise ValueError("approval_ttl_hours must be positive")

    @classmethod
    def from_env(cls) -> Settings:
        data_dir = Path(os.environ.get("SPINDLESAGE_DATA_DIR", ".spindlesage"))
        ai4i = os.environ.get("SPINDLESAGE_AI4I_PATH")
        return cls(
            db_path=Path(os.environ.get("SPINDLESAGE_DB_PATH", data_dir / "spindlesage.db")),
            api_keys_file=Path(
                os.environ.get("SPINDLESAGE_API_KEYS_FILE", data_dir / "api_keys.json")
            ),
            engine=os.environ.get("SPINDLESAGE_ENGINE", "rules"),
            demo_scenario=os.environ.get("SPINDLESAGE_DEMO_SCENARIO") or None,
            approval_ttl_hours=float(os.environ.get("SPINDLESAGE_APPROVAL_TTL_HOURS", "8")),
            ai4i_path=Path(ai4i) if ai4i else AI4I_DEFAULT,
            expose_docs=os.environ.get("SPINDLESAGE_EXPOSE_DOCS", "1") not in ("0", "false"),
        )
