"""BM25 retrieval over the maintenance knowledge base.

Documents are Markdown with a small front-matter block; every `## ` section
becomes one chunk with a stable, citable id `<doc_id>#<section-slug>`.
Okapi BM25 (Robertson and Zaragoza, 2009) is implemented directly so the
retriever has no dependencies and behaves the same on every machine.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

DEFAULT_CORPUS_DIR = Path("knowledge/maintenance")

_STOPWORDS = frozenset(
    [
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "by",
        "for",
        "from",
        "has",
        "have",
        "if",
        "in",
        "into",
        "is",
        "it",
        "its",
        "of",
        "on",
        "or",
        "that",
        "the",
        "their",
        "then",
        "there",
        "these",
        "this",
        "to",
        "was",
        "were",
        "will",
        "with",
        "without",
        "not",
        "no",
        "should",
        "can",
        "may",
        "when",
        "than",
        "which",
        "while",
        "about",
        "over",
        "after",
        "before",
        "more",
        "most",
    ]
)
_TOKEN = re.compile(r"[a-z0-9]+")


def _stem(token: str) -> str:
    # Deliberately light: enough to match overheating/overheat, temperatures/temperature.
    for suffix in ("ing", "ed", "s"):
        if len(token) > len(suffix) + 3 and token.endswith(suffix):
            return token[: -len(suffix)]
    return token


def tokenize(text: str) -> list[str]:
    return [_stem(t) for t in _TOKEN.findall(text.lower()) if t not in _STOPWORDS]


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


@dataclass(frozen=True)
class Chunk:
    chunk_id: str
    doc_id: str
    doc_title: str
    section: str
    text: str
    source_path: str


def parse_document(path: Path) -> list[Chunk]:
    raw = path.read_text(encoding="utf-8")
    meta: dict[str, str] = {}
    body = raw
    if raw.startswith("---"):
        _, front, body = raw.split("---", 2)
        for line in front.strip().splitlines():
            key, _, value = line.partition(":")
            meta[key.strip()] = value.strip()

    doc_id = meta.get("id") or path.stem
    title = meta.get("title") or doc_id
    chunks: list[Chunk] = []
    for block in re.split(r"(?m)^## ", body)[1:]:
        heading, _, text = block.partition("\n")
        heading = heading.strip()
        chunks.append(
            Chunk(
                chunk_id=f"{doc_id}#{_slug(heading)}",
                doc_id=doc_id,
                doc_title=title,
                section=heading,
                text=" ".join(text.split()),
                source_path=path.as_posix(),
            )
        )
    return chunks


def load_corpus(directory: Path | str = DEFAULT_CORPUS_DIR) -> list[Chunk]:
    directory = Path(directory)
    files = sorted(directory.glob("*.md"))
    if not files:
        raise FileNotFoundError(f"No Markdown documents found in {directory}")
    chunks = [chunk for path in files for chunk in parse_document(path)]
    ids = [c.chunk_id for c in chunks]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate chunk ids in knowledge base")
    return chunks


@dataclass(frozen=True)
class SearchHit:
    chunk: Chunk
    score: float


class BM25Index:
    def __init__(self, chunks: list[Chunk], k1: float = 1.5, b: float = 0.75):
        if not chunks:
            raise ValueError("BM25Index needs at least one chunk")
        self.chunks = chunks
        self.k1 = k1
        self.b = b
        # Title and section heading are part of the searchable text.
        self._docs = [tokenize(f"{c.doc_title} {c.section} {c.text}") for c in chunks]
        self._tf = [Counter(doc) for doc in self._docs]
        self._lengths = [len(doc) for doc in self._docs]
        self._avg_length = sum(self._lengths) / len(self._lengths)
        df = Counter(term for doc in self._docs for term in set(doc))
        n = len(self._docs)
        self._idf = {term: math.log(1 + (n - f + 0.5) / (f + 0.5)) for term, f in df.items()}

    @classmethod
    def from_directory(cls, directory: Path | str = DEFAULT_CORPUS_DIR) -> BM25Index:
        return cls(load_corpus(directory))

    def search(self, query: str, k: int = 3) -> list[SearchHit]:
        terms = tokenize(query)
        scores = []
        for i, tf in enumerate(self._tf):
            norm = self.k1 * (1 - self.b + self.b * self._lengths[i] / self._avg_length)
            score = 0.0
            for term in terms:
                freq = tf.get(term, 0)
                if freq:
                    score += self._idf[term] * freq * (self.k1 + 1) / (freq + norm)
            if score > 0:
                scores.append((score, i))
        scores.sort(key=lambda pair: (-pair[0], self.chunks[pair[1]].chunk_id))
        return [SearchHit(self.chunks[i], score) for score, i in scores[:k]]
