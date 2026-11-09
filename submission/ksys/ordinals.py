"""Repeated-claim conflicts (DECISIONS.md D-026): "It was the fourth time Forbes recognized Dupaco"
in an older release against "This was the fifth time Forbes recognized Dupaco" in a newer one.

Releases keep the count of their own day, like the branch counts in press-release boilerplate,
so the claim from the newest dated page wins. Only two sentence shapes are read, both stating how
many times one thing has happened to the organisation:

  (it|this) (is|was|marks) the <ordinal> time <Name> <verb> ...     -> "times <Name> <verb>"
  (it|this) (is|was|marks) the <ordinal> consecutive year <clause>  -> "consecutive years <clause>"

Sentences such as "for the second time in just a month" or "for a third year in a row, Forbes
named ..." are left out on purpose: they count within a window or describe a different list, and
reading them would pair unrelated recognitions.
"""
from __future__ import annotations

import re
from collections import defaultdict
from typing import Dict, Iterable, List, Optional, Tuple

ORDINALS = ["first", "second", "third", "fourth", "fifth", "sixth", "seventh", "eighth", "ninth", "tenth",
            "eleventh", "twelfth", "thirteenth", "fourteenth", "fifteenth", "sixteenth", "seventeenth",
            "eighteenth", "nineteenth", "twentieth"]
_ORD_RANK = {w: i + 1 for i, w in enumerate(ORDINALS)}
_NUM_ORD = r"\d{1,2}(?:st|nd|rd|th)"
_ORD = r"(?P<ord>" + "|".join(ORDINALS) + "|" + _NUM_ORD + r")"
_LEAD = r"\b(?:it|this)\s+(?:is|was|marks|marked)\s+the\s+" + _ORD + r"\s+"

_TIME_RE = re.compile(_LEAD + r"time\s+(?P<who>(?-i:[A-Z][\w&'-]*(?:\s+[A-Z][\w&'-]*){0,3}))\s+(?:has\s+|had\s+)?"
                      r"(?P<verb>recognized|recognised|named|ranked|honored|honoured|awarded|selected)\b", re.I)
_YEAR_RE = re.compile(_LEAD + r"consecutive\s+year\s+(?P<clause>[^.;:!?]{5,80})", re.I)
_STOP = {"a", "an", "the", "has", "have", "had", "been", "was", "were", "is", "are", "be", "by", "to", "of",
         "for", "its", "their", "our", "that", "this", "it", "and", "in", "on"}


def _rank(word: str) -> int:
    w = word.lower()
    return int(re.match(r"\d+", w).group()) if w[0].isdigit() else _ORD_RANK[w]


def _clause_key(clause: str, org_words: Iterable[str]) -> Optional[str]:
    org = {w.lower() for w in org_words}
    words = [w for w in re.findall(r"[a-z]+", clause.lower()) if w not in _STOP and w not in org]
    return " ".join(words[:4]) or None


def claims_in(text: str, org_words: Iterable[str] = ()) -> List[Tuple[str, str, str]]:
    """(subject key, ordinal as written, sentence) for each repeated-claim sentence in text."""
    out = []
    org = {w.lower() for w in org_words}
    for m in _TIME_RE.finditer(text):
        who = m.group("who").strip()
        if who.lower() in org:     # "the fifth time Dupaco named ..." is not a recognition of Dupaco
            continue
        out.append((f"times {who} {m.group('verb').lower()}", m.group("ord"), _sentence(text, m.start())))
    for m in _YEAR_RE.finditer(text):
        key = _clause_key(m.group("clause"), org)
        if key:
            out.append((f"consecutive years {key}", m.group("ord"), _sentence(text, m.start())))
    return out


def _sentence(text: str, pos: int) -> str:
    dot = text.rfind(". ", 0, pos)
    start = dot + 2 if dot != -1 else 0
    end = text.find(".", pos)
    return text[start:end + 1 if end != -1 else len(text)].strip()[:200]


def build_ordinal_conflicts(pages: Dict[str, object], org_words: Iterable[str], latest_id: str) -> List[Dict]:
    """pages: url -> PageDoc (newest version of every page seen). One entry per subject with >= 2 ordinals."""
    found: Dict[str, Dict[str, List[Tuple[str, str, str]]]] = defaultdict(lambda: defaultdict(list))
    for url, page in pages.items():
        meta = getattr(page, "meta", None)
        if meta is None or meta.page_type == "listing":
            continue
        date = meta.published or meta.url_date or ""
        text = " ".join(b.get("text", "") for b in page.blocks if b.get("text"))
        for key, ordw, sent in claims_in(text, org_words):
            found[key][ordw.lower()].append((date, url, sent))
    out = []
    for key in sorted(found):
        by_value = found[key]
        if len(by_value) < 2:
            continue
        # Newest dated statement wins; undated pages never beat a dated one; ties go to the higher count.
        best = max(by_value, key=lambda v: (max(d for d, _, _ in by_value[v]), _rank(v)))
        newest = max(d for d, _, _ in by_value[best])
        sources = []
        for v in sorted(by_value, key=_rank):
            d, url, sent = max(by_value[v])
            sources.append({"url": url, "snapshot_id": latest_id, "quote": f"{v}: {sent}"})
        older = sorted({d for v, xs in by_value.items() if v != best for d, _, _ in xs if d})
        reason = (f"newest dated release ({newest}) says {best}"
                  + (f"; other values are from older releases ({older[0]} to {older[-1]})" if older else ""))
        out.append({
            "topic": f"number of {key}",
            "values": sorted(by_value, key=_rank),
            "sources": sources,
            "resolution": best,
            "reason": reason,
        })
    return out
