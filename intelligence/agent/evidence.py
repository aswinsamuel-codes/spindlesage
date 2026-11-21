"""Evidence items the agent reasons over.

Every fact the agent may use is wrapped in an Evidence item with a stable id
(TEL-1, ANO-1, DOC-2, ...). Recommendations must cite these ids, and the guard
rejects citations that do not exist. This is the mechanism behind H3:
structured outputs plus evidence attribution should reduce unsupported claims.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Literal

EvidenceKind = Literal[
    "telemetry", "validation", "anomaly", "prediction", "machine", "history", "document"
]


@dataclass(frozen=True)
class Evidence:
    evidence_id: str
    kind: EvidenceKind
    title: str
    content: dict
    source: str

    def render(self) -> str:
        body = json.dumps(self.content, indent=2, sort_keys=True, default=str)
        return f"[{self.evidence_id}] ({self.kind}) {self.title}\nsource: {self.source}\n{body}"

    def to_dict(self) -> dict:
        return {
            "evidence_id": self.evidence_id,
            "kind": self.kind,
            "title": self.title,
            "content": self.content,
            "source": self.source,
        }


@dataclass(frozen=True)
class EvidenceBundle:
    machine_id: str
    mode: str
    as_of: str
    items: tuple[Evidence, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        ids = [e.evidence_id for e in self.items]
        if len(ids) != len(set(ids)):
            raise ValueError(f"Duplicate evidence ids: {ids}")

    def ids(self) -> set[str]:
        return {e.evidence_id for e in self.items}

    def get(self, evidence_id: str) -> Evidence | None:
        return next((e for e in self.items if e.evidence_id == evidence_id), None)

    def of_kind(self, kind: EvidenceKind) -> list[Evidence]:
        return [e for e in self.items if e.kind == kind]

    def render(self) -> str:
        header = f"Machine: {self.machine_id}\nAs of: {self.as_of}\nContext mode: {self.mode}\n"
        return header + "\n\n".join(e.render() for e in self.items)

    def to_dict(self) -> dict:
        return {
            "machine_id": self.machine_id,
            "mode": self.mode,
            "as_of": self.as_of,
            "items": [e.to_dict() for e in self.items],
        }
