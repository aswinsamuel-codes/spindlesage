"""Machine metadata and maintenance history.

The default fixture (datasets/fixtures/machine_registry.json) is synthetic and
describes the simulated cell. A real deployment would read the same shapes
from a CMMS or database.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict

DEFAULT_REGISTRY_PATH = Path("datasets/fixtures/machine_registry.json")

MaintenanceKind = Literal["preventive", "corrective", "inspection"]


class Machine(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    machine_id: str
    name: str
    model: str
    product_type: Literal["L", "M", "H"]
    commissioned: date
    spindle_max_rpm: int
    location: str


class MaintenanceRecord(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    record_id: str
    machine_id: str
    date: date
    kind: MaintenanceKind
    component: str
    description: str
    outcome: str


class MachineRegistry:
    def __init__(
        self,
        machines: list[Machine],
        history: list[MaintenanceRecord],
        data_nature: str = "unknown",
    ):
        self._machines = {m.machine_id: m for m in machines}
        if len(self._machines) != len(machines):
            raise ValueError("Duplicate machine_id in registry")
        unknown = {r.machine_id for r in history} - set(self._machines)
        if unknown:
            raise ValueError(f"Maintenance records reference unknown machines: {sorted(unknown)}")
        self._history = sorted(history, key=lambda r: r.date, reverse=True)
        self.data_nature = data_nature

    @classmethod
    def from_json(cls, path: Path | str = DEFAULT_REGISTRY_PATH) -> MachineRegistry:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls(
            machines=[Machine(**m) for m in raw["machines"]],
            history=[MaintenanceRecord(**r) for r in raw.get("maintenance_history", [])],
            data_nature=raw.get("data_nature", "unknown"),
        )

    def machine_ids(self) -> list[str]:
        return sorted(self._machines)

    def get(self, machine_id: str) -> Machine:
        try:
            return self._machines[machine_id]
        except KeyError:
            raise KeyError(f"Unknown machine {machine_id!r}") from None

    def history(self, machine_id: str, limit: int | None = None) -> list[MaintenanceRecord]:
        """Most recent first."""
        self.get(machine_id)
        records = [r for r in self._history if r.machine_id == machine_id]
        return records if limit is None else records[:limit]
