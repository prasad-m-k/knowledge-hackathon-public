"""Knowledge system for the credit-union snapshot hackathon. Approach: see NOTES.md and DECISIONS.md.

Contract (harness/contract.py): build() returns an object with ingest(), answer(), conflicts().
All heavy work happens in ingest(); answer() reads in-memory structures only.
"""
from __future__ import annotations

import logging
import re
import sys
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(next(d / "harness" for d in HERE.parents if (d / "harness" / "contract.py").exists())))

from contract import Answer, Conflict, Snapshot, Source  # noqa: E402
from ksys.answer import answer_count, answer_facts, answer_link, answer_passages, refusal  # noqa: E402
from ksys.history import History  # noqa: E402
from ksys.ingest import Ingestor  # noqa: E402
from ksys import llm  # noqa: E402
from ksys.passages import PassageIndex  # noqa: E402
from ksys.question import parse  # noqa: E402
from ksys.resolve import build_conflicts, resolve_snapshot  # noqa: E402

logger = logging.getLogger("ksys.solution")

_PROPER = re.compile(r"(?<![.?!]\s)(?<!^)\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)")
# Capitalized words in a question that are not names to look up. A name the site never
# mentions leads to an honest refusal, so these words must never trigger that check.
_QUESTION_WORDS = ("I", "What", "How", "Who", "When", "Where", "Can", "Do", "Does", "Is", "Are")
_SITE_TERMS = ("Visa", "APY", "APR", "CD", "IRA")
_STATES = ("Iowa", "Illinois", "Wisconsin")
_MONTHS = ("January", "February", "March", "April", "May", "June",
           "July", "August", "September", "October", "November", "December")
_WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
_COMMON_CAPS = frozenset(_QUESTION_WORDS + _SITE_TERMS + _STATES + _MONTHS + _WEEKDAYS)


def _names_in(question: str, org_words=frozenset()) -> List[str]:
    """Names in the question, with common capitalized words and the organisation's own name
    dropped word by word, so "Dupaco Visa" asks about nothing extra and "Dupaco Shared Branch"
    keeps "Shared Branch"."""
    names = []
    for m in _PROPER.finditer(question):
        words = [w for w in m.group(1).split() if w not in _COMMON_CAPS and w.lower() not in org_words]
        if words:
            names.append(" ".join(words))
    return names


class KnowledgeSystem:
    def __init__(self, store=None) -> None:
        self._lock = threading.RLock()
        self.ingestor = Ingestor(store=store)
        self.history = History()
        self.order: List[tuple] = []                 # (snapshot_id, taken_on), oldest first
        self.views: Dict[str, dict] = {}
        self.indexes: Dict[str, PassageIndex] = {}
        self.page_types: Dict[str, Dict[str, str]] = {}
        self._conflicts: Optional[List[Conflict]] = None
        self._cache: Dict[tuple, Answer] = {}
        self._site: Dict[str, object] = {}         # url -> newest PageDoc seen so far

    # ---- contract ------------------------------------------------------------------------------
    def ingest(self, snapshot: Snapshot) -> None:
        if snapshot is None:
            raise ValueError("snapshot cannot be None")
        with self._lock:
            doc = self.ingestor.ingest(snapshot)
            # The site as of this snapshot is every page seen so far in its newest version: a page
            # missing from one crawl has not necessarily been taken down (snapshots/README.md).
            for url, page in self._site.items():
                doc.pages.setdefault(url, page)
            self._site = dict(doc.pages)
            self.history.add_snapshot(doc)
            self.order = [(s, t) for s, t in self.order if s != doc.snapshot_id]
            self.order.append((doc.snapshot_id, doc.taken_on))
            self.order.sort(key=lambda x: x[1])
            # Name-variant merging can change as history grows, so every view is rebuilt (cheap).
            self.views = {sid: resolve_snapshot(self.history, sid) for sid, _ in self.order}
            self.indexes[doc.snapshot_id] = PassageIndex(doc)
            self.page_types[doc.snapshot_id] = {u: p.meta.page_type for u, p in doc.pages.items()}
            self._conflicts = None
            self._cache.clear()

    def answer(self, question: str, as_of: Optional[str] = None) -> Answer:
        q_str = str(question or "").strip()
        if not q_str:
            d = refusal("empty question")
            return Answer(text=d.text, sources=[], confident=d.confident, conflict_note=d.note)
        norm_as_of = str(as_of).strip() if as_of else None
        key = (" ".join(q_str.lower().split()), norm_as_of)
        with self._lock:
            cached = self._cache.get(key)
        if cached is None:
            ans = self._answer(q_str, norm_as_of)
            with self._lock:
                self._cache[key] = ans
                cached = ans
        return Answer(cached.text, list(cached.sources), cached.confident, cached.conflict_note)

    def conflicts(self) -> List[Conflict]:
        with self._lock:
            if self._conflicts is None:
                latest = self.order[-1][0] if self.order else None
                raw = build_conflicts(self.history, self.views.get(latest, {})) if latest else []
                self._conflicts = [Conflict(c["topic"], c["values"], [Source(**s) for s in c["sources"]],
                                            c["resolution"], c["reason"]) for c in raw]
            return list(self._conflicts)

    # ---- operational / diagnostics -------------------------------------------------------------
    def health(self) -> Dict[str, Any]:
        """Operational health check and telemetry summary."""
        with self._lock:
            latest_sid = self.order[-1][0] if self.order else None
            return {
                "status": "ready" if self.order else "empty",
                "snapshots_ingested": len(self.order),
                "latest_snapshot": latest_sid,
                "active_urls": len(self._site),
                "total_observations": len(self.history.log),
                "resolved_keys_latest": len(self.views.get(latest_sid, {})) if latest_sid else 0,
                "cached_answers": len(self._cache),
                "store_backend": getattr(self.ingestor.store, "backend", "unknown"),
                "site": {"name": self.ingestor.profile.name, "domain": self.ingestor.profile.domain},
                "llm_extraction": dict(llm.STATS, enabled=llm.enabled()),
            }

    def close(self) -> None:
        with self._lock:
            self.ingestor.store.close()

    # ---- internals ------------------------------------------------------------------------------
    def _snapshot_for(self, as_of: Optional[str]) -> Optional[str]:
        if not self.order:
            return None
        if not as_of:
            return self.order[-1][0]
        eligible = [sid for sid, taken in self.order if taken <= as_of]
        return eligible[-1] if eligible else self.order[0][0]

    def _answer(self, question: str, as_of: Optional[str]) -> Answer:
        q = parse(question, as_of)
        sid = self._snapshot_for(q.as_of)
        if sid is None:
            d = refusal("no snapshots ingested")
        else:
            view = self.views[sid]
            d = answer_count(q, view, self.ingestor.profile)
            if d is None and q.wants_link and q.family and q.is_rate_q:
                d = answer_link(q, view, self.page_types[sid])
            if d is None and q.family and q.is_rate_q:
                d = answer_facts(q, view)
                if d is None:
                    d = refusal("no published rate matches this product and term")
            if d is None:
                site = self.ingestor.profile
                d = answer_passages(q, self.indexes[sid], _names_in(question, site.words), site)
            if d is None:
                d = refusal("no page answers this question")
        sources = [Source(url=u, snapshot_id=s or sid, quote=qt) for u, s, qt in d.sources]
        return Answer(text=d.text, sources=sources, confident=d.confident, conflict_note=d.note)


def build() -> KnowledgeSystem:
    return KnowledgeSystem()


def _cli() -> None:
    import argparse
    import json

    ap = argparse.ArgumentParser(description="KnowledgeSystem CLI for healthcheck, ad-hoc queries and conflict inspection.")
    ap.add_argument("--snapshots", type=Path, default=HERE.parent / "snapshots", help="Folder containing snapshot directories")
    ap.add_argument("--question", type=str, help="Question to ask after ingesting snapshots")
    ap.add_argument("--as-of", type=str, default=None, help="Optional ISO date (YYYY-MM-DD) for temporal queries")
    ap.add_argument("--conflicts", action="store_true", help="Print detected conflicts as JSON")
    ap.add_argument("--health", action="store_true", help="Print system health and telemetry summary")
    args = ap.parse_args()

    ks = build()
    if args.snapshots.is_dir():
        snaps = []
        for d in sorted(p for p in args.snapshots.iterdir() if p.is_dir() and (p / "manifest.json").exists()):
            m = json.loads((d / "manifest.json").read_text(encoding="utf-8"))
            from contract import Page
            pages = [Page(p["url"], p.get("title", ""), (d / p["file"]).read_text(encoding="utf-8"),
                          p.get("fetched_at", m["taken_on"])) for p in m["pages"]]
            snaps.append(Snapshot(m["snapshot_id"], m["taken_on"], pages))
        for s in sorted(snaps, key=lambda x: x.taken_on):
            ks.ingest(s)

    if args.health or (not args.question and not args.conflicts):
        print(json.dumps(ks.health(), indent=2))
    if args.question:
        ans = ks.answer(args.question, as_of=args.as_of)
        print(json.dumps({"text": ans.text, "confident": ans.confident, "conflict_note": ans.conflict_note,
                          "sources": [{"url": s.url, "snapshot_id": s.snapshot_id, "quote": s.quote} for s in ans.sources]}, indent=2))
    if args.conflicts:
        cs = ks.conflicts()
        print(json.dumps([{"topic": c.topic, "values": c.values, "resolution": c.resolution, "reason": c.reason} for c in cs], indent=2))
    ks.close()


if __name__ == "__main__":
    _cli()
