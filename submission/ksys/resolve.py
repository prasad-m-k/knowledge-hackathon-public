"""Step 6 of ingest (DECISIONS.md D-012.7, D-016, D-019): pick the winning value per key per
snapshot, and list the contradictions with their winners.

Resolution for one snapshot uses only observations from that snapshot (each snapshot is the
whole site as of that day). Candidates are ranked by:

  1. authority tier: A = rate sheet / product (>= 80), B = other first-party pages, promos,
     documents (>= 50), C = everything else (legal, guides, calculators, news, blogs, listings).
     Expired pages never win.
  2. effective date written next to the table (newer first; undated last)
  (counts such as branches or employees rank by publication date first: newest statement wins)
  3. publication date for dated pages (newer first), so a 2025 release beats a 2022 one
  4. table over prose
  5. authority score within the tier
  6. support: number of pages showing the value
  7. value string (only for determinism)

Conflicts: a key is contradicted when more than one value was ever shown for it (within one
crawl or across crawls). For rates, table values compete when the key has any (prose
values otherwise). Rate, APR and APY keys of one product slot are folded into one conflict
so the list stays precise. Only rate-like metrics and organisation counts are reported.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from .history import History, Observation, key_str

RESOLVE_VERSION = 1
RATE_METRICS = ("apy", "apr", "rate")
CONFLICT_METRICS = RATE_METRICS + ("count",)
# Counts reported as conflicts: branch counts are stated in a stable sentence in every release;
# member and employee numbers are mixed with unrelated figures and only feed answers.
COUNT_CONFLICT_NOUNS = {("branches",)}


def tier(authority: int) -> int:
    return 2 if authority >= 80 else 1 if authority >= 50 else 0


@dataclass
class Winner:
    key: Tuple
    value: str
    num: object
    unit: str
    url: str
    snapshot_id: str
    taken_on: str
    page_type: str
    effective: Optional[str]
    quote: str
    label: str
    product: str
    quals: Dict
    support: List[str] = field(default_factory=list)          # urls agreeing with the winner
    alternatives: Dict[str, List[str]] = field(default_factory=dict)  # other value -> urls


def _rank(o: Observation, support: int) -> Tuple:
    if o.key[3] == "count":
        # Counts (branches, employees) change over time and are stated in dated releases and
        # bios: the newest dated statement wins; undated statements rank below dated ones.
        return (o.published or "", tier(o.authority), o.authority, support)
    return (tier(o.authority), o.effective or "", o.published or "", o.source == "table", o.authority, support)


def resolve_snapshot(hist: History, snapshot_id: str) -> Dict[Tuple, Winner]:
    out: Dict[Tuple, Winner] = {}
    for key, obs in hist.by_key(snapshot_id).items():
        live = [o for o in obs if o.page_type != "expired"]
        if not live:
            continue
        urls_by_value: Dict[str, set] = defaultdict(set)
        for o in live:
            urls_by_value[o.value].add(o.url)
        best = max(live, key=lambda o: (_rank(o, len(urls_by_value[o.value])), o.value, o.url))
        out[key] = Winner(
            key, best.value, best.num, best.unit, best.url, best.snapshot_id, best.taken_on, best.page_type,
            best.effective, best.quote, best.label, best.product, best.quals,
            support=sorted(urls_by_value[best.value]),
            alternatives={v: sorted(u) for v, u in sorted(urls_by_value.items()) if v != best.value},
        )
    return out


# ---- conflicts -------------------------------------------------------------------------------
FAMILY_NAMES = {
    "auto_loan": "auto loan", "rec_loan": "recreational loan", "mortgage": "mortgage", "home_equity": "home equity",
    "home_improvement": "home improvement loan", "personal_loan": "personal loan", "student_loan": "student loan",
    "business_loan": "business loan", "credit_card": "credit card", "certificate": "certificate", "ira": "IRA certificate",
    "money_market": "money market", "checking": "checking", "savings": "savings", "hsa": "health savings account",
    "org_count": "number of",
}
METRIC_NAMES = {"apy": "APY", "apr": "APR", "rate": "rate", "count": "count"}


def slot_of(key: Tuple) -> Tuple:
    return key[:3]


def topic_of(slot: Tuple, metrics: List[str], label: str) -> str:
    fam, name, (term, rank, amount, flags) = slot
    parts = []
    if term:
        parts.append(f"{term // 12}-year" if term >= 120 and term % 12 == 0 else f"{term}-month")
    parts.extend(f for f in flags if f not in ("fixed",))
    parts.extend(name)
    parts.append(FAMILY_NAMES.get(fam, fam))
    if amount:
        lo, _, hi = amount.partition("-")
        parts.append(f"(${float(lo):,.0f}{' to $' + format(float(hi), ',.0f') if hi else '+'})")
    if rank is not None:
        parts.append("newest model years" if rank == 0 else f"model-year tier {rank + 1}")
    if label:
        parts.append(f"[{label[:60]}]")
    parts.append("/".join(METRIC_NAMES.get(m, m) for m in sorted(set(metrics))))
    return " ".join(parts)


def _reason(win: Winner, loser_obs: List[Observation], latest_id: str) -> str:
    why = []
    types = sorted({o.page_type for o in loser_obs})
    if any(o.page_type == "expired" for o in loser_obs):
        why.append("other value is on an expired offer page")
    stale_types = [t for t in types if t in ("calculator", "blog", "news", "listing", "guide", "legal")]
    if stale_types:
        why.append(f"other value comes from lower-authority pages ({', '.join(stale_types)})")
    if any(o.snapshot_id != latest_id for o in loser_obs) and all(o.snapshot_id != latest_id or o.page_type != win.page_type for o in loser_obs):
        older = sorted({o.taken_on for o in loser_obs if o.snapshot_id != latest_id})
        if older:
            why.append(f"other value was shown in earlier crawls ({older[0]} to {older[-1]}) and was replaced")
    if win.effective:
        why.append(f"winner is on the {win.page_type.replace('_', ' ')} with rates effective {win.effective}")
    else:
        why.append(f"winner is on the highest-authority page ({win.page_type.replace('_', ' ')})")
    return "; ".join(why)


def build_conflicts(hist: History, latest: Dict[Tuple, Winner]) -> List[Dict]:
    """One entry per product slot whose rate-like values (or counts) disagree anywhere in history."""
    latest_id = hist.snapshot_order[-1][0] if hist.snapshot_order else ""
    all_obs = hist.by_key()
    slots: Dict[Tuple, Dict[str, List[Observation]]] = defaultdict(dict)
    for key, obs in all_obs.items():
        if key[3] in CONFLICT_METRICS:
            slots[slot_of(key)][key[3]] = obs
    out: List[Dict] = []
    for slot in sorted(slots, key=lambda s: key_str(s + ("",))):
        by_metric = slots[slot]
        values: Dict[str, List[Observation]] = defaultdict(list)
        winners: List[Winner] = []
        for metric in sorted(by_metric):
            # Rates: only table values compete (stale calculators and landing pages keep their
            # tables; stray percentages in blog prose are not contradictions of a rate table).
            obs = [o for o in by_metric[metric] if o.page_type != "listing"]
            if metric != "count" and any(o.source == "table" for o in obs):
                obs = [o for o in obs if o.source == "table"]
            if metric == "count" and slot[1] not in COUNT_CONFLICT_NOUNS:
                continue
            vals = {o.value for o in obs}
            if len(vals) < 2:
                continue
            w = latest.get(slot + (metric,))
            if w is None:
                continue
            winners.append(w)
            for o in obs:
                values[o.value].append(o)
        if not winners:
            continue
        win_values = {w.value for w in winners}
        # A value that only appears in the winner's own sentence describes it ("2.90% intro APR ...
        # after that 12.50%-19.50%"); it does not contradict it.
        win_quotes = {w.quote for w in winners}
        for v in list(values):
            if v not in win_values and all(o.quote in win_quotes for o in values[v]):
                del values[v]
        losers = [o for v, os in values.items() if v not in win_values for o in os]
        if not losers:
            continue
        main = max(winners, key=lambda w: (w.key[3] == "apy", w.key[3] == "apr", w.key[3]))
        sources = []
        for v in sorted(values):
            o = max(values[v], key=lambda o: (o.snapshot_id, o.authority, o.url))
            sources.append({"url": o.url, "snapshot_id": o.snapshot_id, "quote": f"{v}: {o.quote[:160]}"})
        out.append({
            "topic": topic_of(slot, [w.key[3] for w in winners], main.label),
            "values": sorted(values),
            "sources": sources,
            "resolution": " / ".join(f"{w.value} {METRIC_NAMES.get(w.key[3], w.key[3])}" for w in winners),
            "reason": _reason(main, losers, latest_id),
            "slot": key_str(slot + ("",)).rstrip("|"),
        })
    return out
