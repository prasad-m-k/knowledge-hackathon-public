"""Knowledge system for the credit-union snapshot hackathon. Approach: see NOTES.md and DECISIONS.md.

Contract (harness/contract.py): build() returns an object with ingest(), answer(), conflicts().
All heavy work happens in ingest(); answer() reads in-memory structures only.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Dict, List, Optional

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(next(d / "harness" for d in HERE.parents if (d / "harness" / "contract.py").exists())))

from contract import Answer, Conflict, Snapshot, Source  # noqa: E402
from ksys.answer import answer_count, answer_facts, answer_link, answer_passages, refusal  # noqa: E402
from ksys.history import History  # noqa: E402
from ksys.ingest import Ingestor  # noqa: E402
from ksys.passages import PassageIndex  # noqa: E402
from ksys.question import parse  # noqa: E402
from ksys.resolve import build_conflicts, resolve_snapshot  # noqa: E402

_PROPER = re.compile(r"(?<![.?!]\s)(?<!^)\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)")
_COMMON_CAPS = {"Dupaco", "I", "What", "How", "Who", "When", "Where", "Can", "Do", "Does", "Is", "Are", "Visa",
                "APY", "APR", "Iowa", "Illinois", "Wisconsin", "October", "May", "June", "July", "August",
                "September", "January", "February", "March", "April", "November", "December", "CD", "IRA"}


class KnowledgeSystem:
    def __init__(self) -> None:
        self.ingestor = Ingestor()
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
        doc = self.ingestor.ingest(snapshot)
        # The site as of this snapshot is every page seen so far in its newest version: a page
        # missing from one crawl has not necessarily been taken down (snapshots/README.md).
        for url, page in self._site.items():
            doc.pages.setdefault(url, page)
        self._site = dict(doc.pages)
        self.history.add_snapshot(doc)
        self.order.append((doc.snapshot_id, doc.taken_on))
        self.order.sort(key=lambda x: x[1])
        # Name-variant merging can change as history grows, so every view is rebuilt (cheap).
        self.views = {sid: resolve_snapshot(self.history, sid) for sid, _ in self.order}
        self.indexes[doc.snapshot_id] = PassageIndex(doc)
        self.page_types[doc.snapshot_id] = {u: p.meta.page_type for u, p in doc.pages.items()}
        self._conflicts = None
        self._cache.clear()

    def answer(self, question: str, as_of: Optional[str] = None) -> Answer:
        key = (" ".join(question.lower().split()), as_of)
        if key not in self._cache:
            self._cache[key] = self._answer(question, as_of)
        a = self._cache[key]
        return Answer(a.text, list(a.sources), a.confident, a.conflict_note)

    def conflicts(self) -> List[Conflict]:
        if self._conflicts is None:
            latest = self.order[-1][0] if self.order else None
            raw = build_conflicts(self.history, self.views.get(latest, {})) if latest else []
            self._conflicts = [Conflict(c["topic"], c["values"], [Source(**s) for s in c["sources"]],
                                        c["resolution"], c["reason"]) for c in raw]
        return list(self._conflicts)

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
            d = answer_count(q, view)
            if d is None and q.wants_link and q.family and q.is_rate_q:
                d = answer_link(q, view, self.page_types[sid])
            if d is None and q.family and q.is_rate_q:
                d = answer_facts(q, view)
                if d is None:
                    d = refusal("no published rate matches this product and term")
            if d is None:
                proper = [m.group(1) for m in _PROPER.finditer(question) if m.group(1) not in _COMMON_CAPS]
                d = answer_passages(q, self.indexes[sid], proper)
            if d is None:
                d = refusal("no page answers this question")
        sources = [Source(url=u, snapshot_id=s or sid, quote=qt) for u, s, qt in d.sources]
        return Answer(text=d.text, sources=sources, confident=d.confident, conflict_note=d.note)


def build() -> KnowledgeSystem:
    return KnowledgeSystem()
