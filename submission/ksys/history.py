"""Step 5 of ingest (DECISIONS.md D-012.5, D-012.6, D-018): fact keys, observation log, versions.

Fact key = (family, name, qualifier signature, metric):
  family     product family from the generic vocabulary in taxonomy.py ("org_count" for counts
             of branches, members, employees, keyed by the counted noun)
  name       distinguishing words left after removing generic, family and flag words
             ("bright", "you name it", "launchpad"); empty for the family's plain product
  signature  term, model-year rank, amount tier and identity flags
             model-year rank = position of the row's model-year bucket in its table, newest = 0,
             so a renamed bucket ("2023-26" on a stale page, "2024-27" today) lines up
  metric     apy, apr, rate, ...

Name variants merge when one name's words are a non-empty subset of another's in the same
(family, signature, metric) group ("bright" and "bright online only" become one key).

The observation log is append-only: one row per fact per snapshot. Versions collapse consecutive
snapshots in which a page showed the same value for a key; a key that disappears from a page is
closed at the last snapshot it was seen (this is how ended promotions show up).
"""
from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Tuple
from urllib.parse import urlparse

from .taxonomy import FAMILIES, GENERIC_WORDS, IDENTITY_FLAGS

KEY_VERSION = 1
_TOKEN = re.compile(r"[a-z][a-z'’]*")
_FAMILY_RES = [(fam, re.compile(r"\b(" + "|".join(re.escape(w) for w in words) + r")\b")) for fam, words in FAMILIES]
_FAMILY_WORDS = {t for _, words in FAMILIES for w in words for t in _TOKEN.findall(w)}
_FLAG_WORDS = {t for f in IDENTITY_FLAGS for t in _TOKEN.findall(f)}


def family_of(*texts: str) -> Optional[str]:
    for t in texts:
        low = (t or "").lower()
        for fam, rx in _FAMILY_RES:
            if rx.search(low):
                return fam
    return None


def name_tokens(text: str) -> Tuple[str, ...]:
    toks = {t.replace("’", "'").strip("'") for t in _TOKEN.findall((text or "").lower())}
    return tuple(sorted(t for t in toks if t and t not in GENERIC_WORDS and t not in _FAMILY_WORDS
                        and t not in _FLAG_WORDS and len(t) > 1))


def _amount_sig(a) -> Optional[str]:
    if not a:
        return None
    lo, hi = a
    return f"{lo:g}-{'' if hi is None else f'{hi:g}'}"


def signature(quals: Dict, my_rank: Optional[int]) -> Tuple:
    flags = tuple(sorted(f for f in quals.get("flags", []) if f in IDENTITY_FLAGS))
    return (quals.get("term_months"), my_rank, _amount_sig(quals.get("amount")), flags)


def model_year_ranks(facts: List[Dict]) -> Dict[int, Dict[Tuple, int]]:
    """Per table block: model-year range -> rank (newest bucket first)."""
    ranges: Dict[int, set] = defaultdict(set)
    for f in facts:
        my = f["quals"].get("model_year")
        if f["source"] == "table" and my:
            ranges[f["block"]].add(tuple(my))
    return {b: {r: i for i, r in enumerate(sorted(rs, key=lambda r: (-r[1], -r[0])))} for b, rs in ranges.items()}


_BUSINESS_URL = re.compile(r"/business(?:[-/]|$)", re.I)


def is_business_url(url: str) -> bool:
    """Business pages say so in the URL even when an older table caption does not."""
    return bool(_BUSINESS_URL.search(urlparse(url).path))


def raw_key(f: Dict, page_title: str, ranks: Dict[int, Dict[Tuple, int]], url: str = "") -> Optional[Tuple]:
    if f["metric"] == "count":   # organisation counts: "22 branches", "151,000 members"
        return ("org_count", (f["product"],), (None, None, None, ()), "count")
    fam = family_of(f["product"], f["label"], f.get("context", ""), page_title)
    if fam is None:
        return None
    my = f["quals"].get("model_year")
    rank = ranks.get(f["block"], {}).get(tuple(my)) if (my and f["source"] == "table") else None
    name_src = f["product"] if f["source"] == "table" else ""
    name = name_tokens(f"{name_src} {f['label']}")
    quals = f["quals"]
    if url and is_business_url(url) and "business" not in quals.get("flags", []):
        quals = dict(quals, flags=sorted(set(quals.get("flags", [])) | {"business"}))
    return (fam, name, signature(quals, rank), f["metric"])


def key_str(key: Tuple) -> str:
    fam, name, (term, rank, amount, flags), metric = key
    parts = [fam, " ".join(name) or "-"]
    if term:
        parts.append(f"{term}mo")
    if rank is not None:
        parts.append(f"my{rank}")
    if amount:
        parts.append(f"${amount}")
    if flags:
        parts.append("+".join(flags))
    parts.append(metric)
    return "|".join(parts)


@dataclass
class Observation:
    key: Tuple
    snapshot_id: str
    taken_on: str
    url: str
    page_type: str
    authority: int
    effective: Optional[str]
    published: Optional[str]
    value: str
    num: object
    unit: str
    source: str            # table | prose
    quote: str
    label: str
    product: str
    quals: Dict
    block: int = 0
    row: Optional[int] = None
    title: str = ""


@dataclass
class Version:
    value: str
    first_seen: str        # snapshot_id
    last_seen: str
    first_taken_on: str
    last_taken_on: str
    effective: Optional[str]
    snapshots: List[str] = field(default_factory=list)


class History:
    def __init__(self) -> None:
        self.log: List[Observation] = []
        self.snapshot_order: List[Tuple[str, str]] = []       # (snapshot_id, taken_on)
        self._canon: Dict[Tuple, Tuple] = {}
        self.unkeyed = 0

    # -- building -----------------------------------------------------------------------------
    def add_snapshot(self, doc) -> int:
        self.snapshot_order.append((doc.snapshot_id, doc.taken_on))
        added = 0
        for url in sorted(doc.pages):
            p = doc.pages[url]
            ranks = model_year_ranks(p.facts)
            for f in p.facts:
                k = raw_key(f, p.title, ranks, url)
                if k is None:
                    self.unkeyed += 1
                    continue
                eff = p.meta.effective.get(f["block"]) if f["source"] == "table" else None
                if eff is None and f["source"] == "table":
                    eff = p.meta.effective.get(str(f["block"]))
                self.log.append(Observation(
                    k, doc.snapshot_id, doc.taken_on, url, p.meta.page_type, p.meta.authority, eff,
                    p.meta.published or p.meta.url_date, f["value"], f["num"], f["unit"], f["source"],
                    f["quote"], f["label"], f["product"], f["quals"], f["block"], f.get("row"), p.title))
                added += 1
        self._rebuild_canon()
        return added

    def _rebuild_canon(self) -> None:
        """Merge name variants: within (family, signature, metric), a key whose name words are a
        non-empty subset of another key's name maps to the smallest such name (deterministic)."""
        groups: Dict[Tuple, set] = defaultdict(set)
        for o in self.log:
            fam, name, sig, metric = o.key
            groups[(fam, sig, metric)].add(name)
        canon: Dict[Tuple, Tuple] = {}
        for (fam, sig, metric), names in groups.items():
            ordered = sorted(names, key=lambda n: (len(n), n))
            for n in ordered:
                target = n
                for m in ordered:
                    if m and len(m) < len(n) and set(m) <= set(n):
                        target = m
                        break
                canon[(fam, n, sig, metric)] = (fam, target, sig, metric)
        self._canon = canon

    def canon(self, key: Tuple) -> Tuple:
        return self._canon.get(key, key)

    # -- queries --------------------------------------------------------------------------------
    def observations(self, snapshot_id: Optional[str] = None) -> Iterable[Observation]:
        for o in self.log:
            if snapshot_id is None or o.snapshot_id == snapshot_id:
                yield o

    def by_key(self, snapshot_id: Optional[str] = None) -> Dict[Tuple, List[Observation]]:
        out: Dict[Tuple, List[Observation]] = defaultdict(list)
        for o in self.observations(snapshot_id):
            out[self.canon(o.key)].append(o)
        return out

    def versions(self) -> Dict[Tuple, Dict[str, List[Version]]]:
        """key -> url -> versions, in snapshot order. A gap (page or value absent) closes a version."""
        order = {sid: i for i, (sid, _) in enumerate(self.snapshot_order)}
        taken = dict(self.snapshot_order)
        seen: Dict[Tuple, Dict[str, Dict[int, Observation]]] = defaultdict(lambda: defaultdict(dict))
        for o in self.log:
            slot = seen[self.canon(o.key)][o.url]
            i = order[o.snapshot_id]
            prev = slot.get(i)
            # Several rows of one page can map to one key (duplicated tables); keep the first.
            if prev is None:
                slot[i] = o
        out: Dict[Tuple, Dict[str, List[Version]]] = {}
        for key, by_url in seen.items():
            out[key] = {}
            for url, by_snap in by_url.items():
                vs: List[Version] = []
                for i in sorted(by_snap):
                    o = by_snap[i]
                    sid = o.snapshot_id
                    if vs and vs[-1].value == o.value and order[vs[-1].last_seen] == i - 1:
                        vs[-1].last_seen, vs[-1].last_taken_on = sid, taken[sid]
                        vs[-1].snapshots.append(sid)
                    else:
                        vs.append(Version(o.value, sid, sid, taken[sid], taken[sid], o.effective, [sid]))
                out[key][url] = vs
        return out
