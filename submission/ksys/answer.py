"""Step 7c (DECISIONS.md D-020): answer a question from resolved facts or passages.

Order of attempts:
  1. Counts ("how many branches") -> newest dated count winner.
  2. Rate questions with a product family -> resolved winners of the chosen snapshot, scored
     against the parsed question. Ties are listed (all 30-year mortgage tiers, all credit cards).
     Only current winners from tables on pages with authority >= 50 are ever stated.
  3. Everything else -> best passages (BM25 weighted by authority), trimmed to the sentences that
     match the question; links are included when the question asks for a link.
  4. Nothing reliable -> an honest refusal with confident=False and no numbers.
Answer text never repeats a replaced or stale value; reasons go in conflict_note.
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple

from .history import key_str
from .question import Query, tokens_of
from .taxonomy import GENERIC_WORDS
from .resolve import METRIC_NAMES, Winner

DEPOSIT_FAMILIES = {"certificate", "savings", "money_market", "checking", "ira", "hsa"}
RATE_METRICS = ("apy", "apr", "rate")
SOFT_KEY_FLAGS = {"jumbo", "business", "intro", "introductory", "balance transfer", "roth", "traditional",
                  "refinance", "promotional", "variable", "youth", "teen", "holiday", "student", "health savings"}
MAX_LIST = 40
# Words that narrow a rate question to a product variant; if none of the family's published rate
# facts mention them, the site does not publish that rate and the honest answer is a refusal.
NARROWING = {"adjustable", "arm", "variable", "construction", "jumbo", "fha", "va", "usda", "bridge", "lot",
             "land", "boat", "rv", "motorcycle", "used", "new", "refinance", "refi", "balloon", "interest-only",
             "commercial", "farm", "agricultural", "roth", "traditional", "sep", "coverdell", "youth", "teen",
             "student", "secured", "unsecured", "signature", "share-secured", "pledge"}
GENERIC_Q = GENERIC_WORDS | {"loan", "rate", "mortgage", "certificate", "saving", "checking", "card"}
REFUSAL = "I'm sorry, that isn't listed on our website. Please contact us for details."
_COUNT_Q = re.compile(r"\bhow many\b.*\b(branch(?:es)?|locations?|offices?|employees|members|atms)\b", re.I)
_COUNT_NOUN = {"branch": "branches", "branches": "branches", "location": "branches", "locations": "branches",
               "office": "branches", "offices": "branches", "employees": "employees", "members": "members", "atms": "atms"}
_SENT = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9“\"(])")
# What kind of value a question asks for, and how to recognise it in a passage.
ANSWER_TYPES = [
    # "When will the branch close?" asks for a date, so "close" only counts with "what time".
    (re.compile(r"\bhours?\b|\bwhat time\b|\bwhen\b.*\bopens?\b|\bopens?\b.*\b(when|time)\b", re.I),
     re.compile(r"\b\d{1,2}(?::\d{2})?\s*(?:a\.?m\.?|p\.?m\.?)|\bnoon\b", re.I)),
    (re.compile(r"\baddress\b|\bwhere is\b|\blocated\b", re.I),
     re.compile(r"\b\d{2,6}\s+[A-Z][a-z]+.*\b\d{5}\b|\b\d{2,6}\s+[A-Z][a-z]+\s+(?:St|Ave|Rd|Ln|Dr|Blvd|Way|Hwy|Road|Street|Avenue)\b")),
    (re.compile(r"\b(phone|call|telephone|number to call)\b", re.I),
     re.compile(r"\(?\b\d{3}\)?[-. ]\d{3}[-. ]\d{4}\b")),
    (re.compile(r"\brouting\b", re.I), re.compile(r"\b\d{9}\b")),
]
_URL = re.compile(r"\((https?://[^)\s]+)\)|(?<![(\w])(https?://[^\s)\]]+|\b[a-z0-9-]+\.dupaco\.com[^\s)\]]*)", re.I)


class Draft:
    def __init__(self, text: str, sources: List[Tuple[str, str, str]], confident: bool = True,
                 note: Optional[str] = None) -> None:
        self.text, self.sources, self.confident, self.note = text, sources, confident, note


def refusal(reason: str = "") -> Draft:
    return Draft(REFUSAL, [], confident=False, note=reason or None)


# ---- facts ------------------------------------------------------------------------------------
def _slot_metrics(view: Dict[Tuple, Winner]) -> Dict[Tuple, Dict[str, Winner]]:
    """Rate slots that may be stated: table winners on pages with authority >= 50. A family with
    no table facts at all (a site that states rates in sentences) falls back to prose winners."""
    out: Dict[Tuple, Dict[str, Winner]] = {}
    families_with_tables = {k[0] for k, w in view.items() if k[3] in RATE_METRICS and w.source == "table"}
    for k, w in view.items():
        if k[3] not in RATE_METRICS or w.authority < 50:
            continue
        if w.source == "table" or k[0] not in families_with_tables:
            out.setdefault(k[:3], {})[k[3]] = w
    return out


def _score_slot(q: Query, slot: Tuple, w: Winner) -> Optional[float]:
    fam, name, (term, rank, amount, flags) = slot
    s = 0.0
    if q.term_months is not None:
        if term is None:
            s -= 2
        elif term != q.term_months:
            return None
        else:
            s += 3
    if q.model_year is not None:
        my = w.quals.get("model_year")
        if not my:
            s -= 1
        elif not (my[0] <= q.model_year <= my[1]):
            return None
        else:
            s += 3
    if q.amount is not None:
        a = w.quals.get("amount")
        if a:
            lo, hi = a
            if not (lo <= q.amount <= (hi if hi is not None else float("inf"))):
                return None
            s += 3
    kflags = set(flags)
    for f in q.flags:
        s += 2 if f in kflags else -1
    for f in kflags - set(q.flags):
        if f in SOFT_KEY_FLAGS:
            s -= 1.5
    qn = set(q.names)
    for t in name:
        s += 2 if t in qn else -0.5
    return s


def _is_specific(q: Query) -> bool:
    """A question that names a term, tier, model year, product name or identity flag."""
    return bool(q.term_months or q.model_year or q.amount or q.names or q.superlative
                or set(q.flags) - {"standard"})


def _metric_order(q: Query, family: str, available: Dict[str, Winner]) -> List[str]:
    if q.metric and q.metric in available:
        main = [q.metric]
    elif family in DEPOSIT_FAMILIES:
        main = ["apy", "rate"]
    elif "rate" in available and "apr" in available:
        main = ["rate", "apr"]
    else:
        main = ["apr", "rate", "apy"]
    return [m for m in main if m in available][:2] or sorted(available)[:1]


def _describe(slot_w: Winner) -> str:
    label = slot_w.label or slot_w.product
    product = slot_w.product
    if product and product.lower() not in label.lower():
        label = f"{product}, {label}"
    return label.replace(" | ", ", ")


def _num(w: Winner) -> float:
    n = w.num
    return max(n) if isinstance(n, list) else float(n or 0)


def _with_names(q: Query, names: Tuple[str, ...]) -> Query:
    import copy
    q2 = copy.copy(q)
    q2.names = names
    return q2


def unmatched_terms(q: Query, slots_text: str, vocab: set) -> List[str]:
    """Question words that would narrow the product but appear in no rate fact of the family
    (e.g. "adjustable" for a mortgage when only fixed rates are published)."""
    have = set(tokens_of(slots_text))
    return [t for t in q.tokens if t not in have and t not in GENERIC_Q and not t.isdigit() and t in NARROWING]


def answer_facts(q: Query, view: Dict[Tuple, Winner]) -> Optional[Draft]:
    if not q.family:
        return None
    slots = {s: m for s, m in _slot_metrics(view).items() if s[0] == q.family}
    if not slots:
        return None
    # Once rate-sheet or product pages publish this family, weaker pages (promos, other pages)
    # never supply a stated value.
    if any(max(w.authority for w in m.values()) >= 80 for m in slots.values()):
        slots = {s: m for s, m in slots.items() if max(w.authority for w in m.values()) >= 80}
    # Only question words that name a product variant on the site count as names.
    name_vocab = {t for s_ in slots for t in s_[1]}
    q = _with_names(q, tuple(t for t in q.names if t in name_vocab))
    fam_text = " ".join(f"{w.product} {w.label} {w.title}" for m in slots.values() for w in m.values())
    missing = unmatched_terms(q, fam_text, set())
    if missing:
        return refusal(f"no published rate for: {', '.join(missing)}")
    scored = []
    for slot, metrics in slots.items():
        sc = _score_slot(q, slot, next(iter(metrics.values())))
        if sc is not None:
            scored.append((sc, slot, metrics))
    if not scored:
        return None
    if _is_specific(q):
        best = max(sc for sc, _, _ in scored)
        top = [(slot, metrics) for sc, slot, metrics in scored if sc >= best - 1e-9]
    else:
        top = [(slot, metrics) for _, slot, metrics in scored]   # list the whole family
    if q.amount is not None and len(top) > 1:
        # "$100,000 or less" also falls inside "$300,000 or less": keep the narrowest tier.
        def width(sm):
            a = next(iter(sm[1].values())).quals.get("amount")
            if not a:
                return float("inf")
            return (a[1] if a[1] is not None else float("inf")) - a[0]
        narrow = min(width(sm) for sm in top)
        top = [sm for sm in top if width(sm) == narrow]
    if q.superlative and len(top) > 1:
        pick = max if q.superlative == "max" else min
        top = [pick(top, key=lambda sm: (_num(sm[1][_metric_order(q, sm[0][0], sm[1])[0]]), key_str(sm[0] + ("",))))]
    want_biz = "business" in q.flags
    top.sort(key=lambda sm: (-max(w.authority for w in sm[1].values()),
                             ("business" in sm[0][2][3]) != want_biz,
                             min(w.url for w in sm[1].values()), next(iter(sm[1].values())).block,
                             next(iter(sm[1].values())).row or 0, key_str(sm[0] + ("",))))
    lines, sources, seen, src_seen = [], [], set(), set()
    for slot, metrics in top:
        order = _metric_order(q, slot[0], metrics)
        main = metrics[order[0]]
        desc = _describe(main)
        vals = ", ".join(f"{metrics[m].value} {METRIC_NAMES[m]}" if m != "rate" else
                         f"{metrics[m].value} {'dividend' if slot[0] in DEPOSIT_FAMILIES else 'interest'} rate"
                         for m in order)
        line = f"{desc}: {vals}"
        if line in seen:
            continue
        seen.add(line)
        lines.append(line)
        # Cite the winning page and the product pages that show the same value.
        for u in [main.url] + [u for u in main.support if u != main.url]:
            if u not in src_seen and len(src_seen) < 6:
                src_seen.add(u)
                sources.append((u, main.snapshot_id, main.quote[:200] if u == main.url else None))
        if len(lines) >= MAX_LIST:
            break
    eff = sorted({w.effective for _, ms in top for w in ms.values() if w.effective})
    tail = f" (rates effective as of {eff[-1]})" if eff and len(eff) == 1 else ""
    if len(lines) == 1:
        text = lines[0] + tail + "."
    else:
        text = "Current rates" + tail + ":\n" + "\n".join(f"- {l}" for l in lines)
    alts = {v for _, ms in top for w in ms.values() for v in w.alternatives}
    note = None
    if alts:
        note = "Other values on older or lower-authority pages were not used: " + ", ".join(sorted(alts)[:8])
    return Draft(text, sources, True, note)


def answer_link(q: Query, view: Dict[Tuple, Winner], page_types: Dict[str, str]) -> Optional[Draft]:
    """"Where can I see certificate rates?" -> the product pages that publish the family's rates."""
    if not q.family:
        return None
    business = "business" in q.flags
    pages = {}
    for k, w in view.items():
        if k[0] == q.family and k[3] in RATE_METRICS and w.source == "table" and w.authority >= 80:
            for u in [w.url] + list(w.support):
                if ("business" in u.lower()) == business:
                    pages.setdefault(u, w)
    if not pages:
        return None
    ranked = sorted(pages, key=lambda u: (page_types.get(u) != "product", u.count("/"), len(u), u))
    urls = [u.rstrip("/") + "#rates" if page_types.get(u) == "product" else u for u in ranked[:2]]
    text = "You can see current rates at " + " and ".join(urls) + "."
    return Draft(text, [(u, pages[u].snapshot_id, None) for u in ranked[:2]], True)


def answer_count(q: Query, view: Dict[Tuple, Winner]) -> Optional[Draft]:
    m = _COUNT_Q.search(q.text)
    if not m:
        return None
    count_words = {"how", "many", "dupaco", "have", "doe", "there", "total", "operate", "branch", "location",
                   "office", "employee", "member", "atm", "full", "service", "full-service"}
    prefixes = {w[:5] for w in count_words}
    extra = [t for t in q.tokens if t not in count_words and t[:5] not in prefixes]
    if extra:                       # "how many employees used Volunteer Time Off" is not a size question
        return None
    noun = _COUNT_NOUN.get(m.group(1).lower(), m.group(1).lower())
    w = view.get(("org_count", (noun,), (None, None, None, ()), "count"))
    if not w:
        return None
    return Draft(f"Dupaco has {w.value} {noun}.", [(w.url, w.snapshot_id, w.quote[:200])], True,
                 f"Newest dated statement ({w.url}); older pages list other counts." if w.alternatives else None)


# ---- passages -----------------------------------------------------------------------------------
def _best_sentences(text: str, qtok: set, limit: int = 3) -> str:
    sents = [s.strip() for s in _SENT.split(text.replace("\n", " ")) if s.strip()]
    if len(sents) <= limit:
        return " ".join(sents)
    scored = sorted(range(len(sents)), key=lambda i: (-len(qtok & set(tokens_of(sents[i]))), i))[:limit - 1]
    keep = sorted(set(scored) | {0})
    # A defining sentence often follows a matching one without repeating the name
    # ("The Home$tart program ... This initiative provides up to $15,000 ...").
    for i in list(keep):
        if len(keep) < limit + 1 and i + 1 < len(sents) and i + 1 not in keep and re.search(r"\d", sents[i + 1]):
            keep.append(i + 1)
    return " ".join(sents[i] for i in sorted(set(keep)))


def _links(md: str) -> List[str]:
    out = []
    for m in _URL.finditer(md):
        u = (m.group(1) or m.group(2) or "").rstrip(".,;")
        if u and u not in out and not u.endswith("#"):
            out.append(u)
    return out


def title_overlap(qtok: set, p) -> bool:
    return bool(qtok & set(tokens_of(p.title.split("|")[0] + " " + " ".join(p.path[:1]))))


def answer_passages(q: Query, index, proper_nouns: List[str]) -> Optional[Draft]:
    if not q.tokens:
        return None
    vocab = index.vocabulary()
    pn_tokens = []
    for pn in proper_nouns:
        toks = [t for t in tokens_of(pn) if t not in GENERIC_Q]
        if not all(t in vocab for t in toks):
            return refusal(f"'{pn}' does not appear on the website")
        pn_tokens.extend(toks)
    qtok = set(q.tokens)
    want = [val for qre, val in ANSWER_TYPES if qre.search(q.text)]
    is_hours_q = bool(ANSWER_TYPES[0][0].search(q.text))
    # Candidates come from block-level BM25; they are then judged on their section context
    # (a "Lobby" label plus the lines under it), weighted by page authority and title/heading match.
    cands = index.search(q.tokens, k=80)
    if not cands:
        return None
    ranked = []
    want_pages = []
    for score, p, _ in cands:
        ctx, md = index.context(p)
        ctx_tokens = set(tokens_of(ctx + " " + " ".join(p.path[-2:])))
        if want and all(v.search(ctx) for v in want) and p.page_type in ("page", "home"):
            if p.url not in want_pages:
                want_pages.append(p.url)
        if pn_tokens and not all(t in ctx_tokens | set(tokens_of(p.title)) for t in pn_tokens):
            continue
        if want and not all(v.search(ctx) for v in want):
            continue
        covered = qtok & (ctx_tokens | set(tokens_of(p.title)))
        if len(covered) < max(1, round(0.5 * len(qtok))):
            continue
        cover = sum(index.idf.get(t, 0.0) for t in covered)
        title_hits = len(qtok & set(tokens_of(p.title + (" " + " ".join(p.path) if p.page_type == "page" and not pn_tokens else ""))))
        pn_in_text = bool(pn_tokens) and all(t in ctx_tokens for t in pn_tokens)
        full = 1.25 if covered >= qtok else 1.0        # every question word is addressed
        final = cover * index._weight(p) * (1 + 0.3 * title_hits) * (1.5 if pn_in_text else 1.0) * full + 0.01 * score
        ranked.append((final, p, ctx, md))
    ranked.sort(key=lambda r: (-r[0], r[1].url, r[1].block_i))
    for final, p, ctx, md in ranked[:1]:
        has_bullets = len(re.findall(r"^\s*(?:[-*+]|\d+[.)])\s+", ctx, re.M)) >= 2
        body = _best_sentences(ctx, qtok, limit=5) if (len(ctx) > 600 and not has_bullets) else " ".join(ctx.split())
        if p.page_type in ("news", "blog"):
            lede = index.lede(p.url)
            if lede and lede[:80] not in ctx:
                lead = " ".join([x for x in _SENT.split(lede.replace("\n", " ")) if x.strip()][:2])
                body = f"{lead} {body}"
        if is_hours_q and not pn_tokens and p.page_type == "news":
            # General branch-hour questions: include a second branch schedule when branches differ.
            for _, p2, ctx2, _ in ranked[1:8]:
                if p2.url != p.url and ("noon" in ctx2.lower()) != ("noon" in body.lower()):
                    extra = " ".join(ctx2.split())
                    body = f"{body} Other branch schedule: {extra}"
                    break
        if re.search(r"\blast year\b", q.text, re.I):
            for _, p2, ctx2, _ in ranked[1:]:
                if p2.url != p.url and p2.title == p.title:
                    extra = _best_sentences(ctx2, qtok, limit=3) if len(ctx2) > 400 else " ".join(ctx2.split())
                    body = f"{body} {extra}"
                    break
        if "contact" in qtok and not want and not pn_tokens and not ANSWER_TYPES[2][1].search(body):
            for u in sorted(index.by_url):
                if u.rstrip("/").endswith("/contact"):
                    c_lede = index.lede(u)
                    if c_lede:
                        body = f"{c_lede} {body}"
                    break
        if q.is_rate_q and re.search(r"\brates?\b|\bapr\b|\bapy\b", q.text, re.I) and "%" not in body:
            return refusal("the website does not publish this rate")
        if q.wants_link:
            links = [u for u in _links(md) if any(t in u.lower() for t in qtok)] or _links(md)[:2]
            # The page itself is often the answer ("the branch and ATM locator" is /contact).
            page_url = p.url.split("#")[0]
            links = [page_url] + [u for u in links if u.rstrip("/") != page_url.rstrip("/")]
            body = f"{body} Link: {', '.join(links[:3])}"
        sources = [(p.url, None, body[:200])]
        for u in want_pages:
            if u != p.url and len(sources) < 4:
                sources.append((u, None, None))
        for _, p2, _, _ in ranked[1:6]:
            if all(p2.url != u for u, _, _ in sources) and len(sources) < 4:
                sources.append((p2.url, None, None))
        return Draft(body, sources, True)
    if pn_tokens or want:
        return refusal("no page gives this " + ("detail for " + ", ".join(proper_nouns) if pn_tokens else "detail"))
    return None
