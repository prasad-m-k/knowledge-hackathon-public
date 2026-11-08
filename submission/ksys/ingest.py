"""Ingest pipeline (DECISIONS.md D-012, D-013, D-015, D-016).

Per snapshot: strip boilerplate (step 1), segment each page into blocks (step 2) and classify it
(step 3: page type, authority, dates), then extract facts (step 4). Segments and facts are reused for any page whose cleaned content was
seen before, in this run or, when the SQLite cache is enabled, in an earlier run. Later steps
(versions, resolution) build on the SnapshotDoc produced here.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import logging
import time
from typing import Dict, List

from .boilerplate import clean_snapshot
from .classify import PageMeta, classify_page
from .extract import EXTRACT_VERSION, extract_page
from .segment import SEGMENT_VERSION, segment_page
from .store import open_store

logger = logging.getLogger("ksys.ingest")


@dataclass
class PageDoc:
    url: str
    title: str
    fetched_at: str
    content_hash: str
    blocks: List[Dict]
    meta: PageMeta
    facts: List[Dict]


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
        if snapshot is None:
            raise ValueError("snapshot cannot be None")
        sid = str(getattr(snapshot, "snapshot_id", "") or "unknown")
        taken_on = str(getattr(snapshot, "taken_on", "") or "")
        raw_pages = list(getattr(snapshot, "pages", []) or [])
        t0 = time.monotonic()
        cleaned = clean_snapshot(raw_pages)
        pages: Dict[str, PageDoc] = {}
        hits = misses = fact_count = page_errors = 0
        for url in sorted(cleaned):
            c = cleaned[url]
            try:
                key = f"{c.content_hash}:s{SEGMENT_VERSION}"
                blocks = self.store.get("segments", key)
                if blocks is None:
                    blocks = segment_page(c.text)
                    self.store.put("segments", key, blocks)
                    misses += 1
                else:
                    hits += 1
                fkey = f"{c.content_hash}:s{SEGMENT_VERSION}:x{EXTRACT_VERSION}"
                facts = self.store.get("facts", fkey)
                if facts is None:
                    facts = extract_page(blocks, c.title)
                    self.store.put("facts", fkey, facts)
                fact_count += len(facts)
                pages[url] = PageDoc(url, c.title, c.fetched_at, c.content_hash, blocks,
                                     classify_page(url, c.title, blocks), facts)
            except Exception as e:
                page_errors += 1
                logger.error("failed to process page %s in %s: %s", url, sid, e)
        self.store.flush()
        elapsed_ms = int((time.monotonic() - t0) * 1000)
        stats = {
            "pages": len(pages),
            "segment_cache_hits": hits,
            "segmented": misses,
            "facts": fact_count,
            "page_errors": page_errors,
            "elapsed_ms": elapsed_ms,
        }
        logger.info("ingested %s (%d pages, %d facts, %d cache hits) in %d ms",
                    sid, len(pages), fact_count, hits, elapsed_ms)
        doc = SnapshotDoc(sid, taken_on, pages, stats)
        self.snapshots.append(doc)
        return doc
