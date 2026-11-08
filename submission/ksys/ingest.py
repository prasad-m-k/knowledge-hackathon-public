"""Ingest pipeline (DECISIONS.md D-012, D-013, D-015, D-016).

Per snapshot: strip boilerplate (step 1), segment each page into blocks (step 2) and classify it
(step 3: page type, authority, dates). Segments are reused for any page whose cleaned content was
seen before, in this run or, when the SQLite cache is enabled, in an earlier run. Later steps
(extraction, versions, resolution) build on the SnapshotDoc produced here.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List

from .boilerplate import clean_snapshot
from .classify import PageMeta, classify_page
from .segment import SEGMENT_VERSION, segment_page
from .store import open_store


@dataclass
class PageDoc:
    url: str
    title: str
    fetched_at: str
    content_hash: str
    blocks: List[Dict]
    meta: PageMeta


@dataclass
class SnapshotDoc:
    snapshot_id: str
    taken_on: str
    pages: Dict[str, PageDoc]
    stats: Dict[str, int] = field(default_factory=dict)


class Ingestor:
    def __init__(self, store=None) -> None:
        self.store = store if store is not None else open_store()
        self.snapshots: List[SnapshotDoc] = []

    def ingest(self, snapshot) -> SnapshotDoc:
        cleaned = clean_snapshot(snapshot.pages)
        pages: Dict[str, PageDoc] = {}
        hits = misses = 0
        for url in sorted(cleaned):
            c = cleaned[url]
            key = f"{c.content_hash}:s{SEGMENT_VERSION}"
            blocks = self.store.get("segments", key)
            if blocks is None:
                blocks = segment_page(c.text)
                self.store.put("segments", key, blocks)
                misses += 1
            else:
                hits += 1
            pages[url] = PageDoc(url, c.title, c.fetched_at, c.content_hash, blocks,
                                 classify_page(url, c.title, blocks))
        self.store.flush()
        doc = SnapshotDoc(snapshot.snapshot_id, snapshot.taken_on, pages,
                          {"pages": len(pages), "segment_cache_hits": hits, "segmented": misses})
        self.snapshots.append(doc)
        return doc
