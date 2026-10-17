"""Governed knowledge packs and BM25 retrieval.

A knowledge pack is a YAML file of source entries. Every entry carries a
stable ``ref``, version, jurisdiction and domain, and gets a SHA-256 of its
text at load time, so a finding can cite exactly which text it relied on.
Retrieval is Okapi BM25 over :func:`infraagentkit.text.tokens`; a hit below
``min_score`` is not evidence.
"""
from __future__ import annotations

import hashlib
import math
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .text import tokens

PACK_DIR = Path(__file__).resolve().parent / "packs"


@dataclass(frozen=True)
class Source:
    ref: str
    title: str
    text: str
    domain: str
    jurisdiction: str = "GENERIC"
    version: str = "1.0"
    authority: str = ""
    source_url: str = ""
    digest: str = ""

    def citation(self) -> dict:
        return {"ref": self.ref, "title": self.title, "version": self.version, "jurisdiction": self.jurisdiction,
                "domain": self.domain, "digest": self.digest}


@dataclass
class KnowledgeIndex:
    sources: list[Source]
    k1: float = 1.4
    b: float = 0.75
    min_score: float = 3.0
    min_terms: int = 2  # distinct query terms that must match; one shared word is not evidence
    _docs: list[Counter] = field(default_factory=list, init=False)
    _df: Counter = field(default_factory=Counter, init=False)
    _avg: float = field(default=1.0, init=False)

    def __post_init__(self) -> None:
        self._docs = [Counter(tokens(f"{s.title} {s.text}")) for s in self.sources]
        for doc in self._docs:
            self._df.update(doc.keys())
        self._avg = sum(sum(d.values()) for d in self._docs) / max(1, len(self._docs))

    def search(self, query: str, top_k: int = 3, jurisdiction: str | None = None) -> list[dict]:
        terms = set(tokens(query))
        n = len(self.sources)
        scored = []
        for source, doc in zip(self.sources, self._docs):
            if jurisdiction and source.jurisdiction not in {jurisdiction, "GENERIC"}:
                continue
            length = sum(doc.values())
            score, hits = 0.0, 0
            for term in terms:
                tf = doc.get(term, 0)
                if not tf:
                    continue
                hits += 1
                idf = math.log(1 + (n - self._df[term] + 0.5) / (self._df[term] + 0.5))
                score += idf * tf * (self.k1 + 1) / (tf + self.k1 * (1 - self.b + self.b * length / self._avg))
            if score >= self.min_score and hits >= min(self.min_terms, len(terms)):
                scored.append((score, source))
        scored.sort(key=lambda item: item[0], reverse=True)
        return [{**s.citation(), "text": s.text, "score": round(score, 3)} for score, s in scored[:top_k]]


def load_pack(path: str | Path) -> list[Source]:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    out = []
    for item in data.get("sources", []):
        text = " ".join(str(item["text"]).split())
        out.append(Source(
            ref=item["ref"], title=item["title"], text=text, domain=item.get("domain", "general"),
            jurisdiction=item.get("jurisdiction", "GENERIC"), version=str(item.get("version", "1.0")),
            authority=item.get("authority", ""), source_url=item.get("source_url", ""),
            digest=hashlib.sha256(text.encode("utf-8")).hexdigest(),
        ))
    return out


def load_packs(directory: str | Path = PACK_DIR) -> list[Source]:
    sources: list[Source] = []
    for path in sorted(Path(directory).glob("*.yaml")):
        sources.extend(load_pack(path))
    refs = [s.ref for s in sources]
    duplicates = {r for r in refs if refs.count(r) > 1}
    if duplicates:
        raise ValueError(f"duplicate knowledge refs: {sorted(duplicates)}")
    return sources
