"""Step 4 of ingest (DECISIONS.md D-012.4, D-017): facts from tables and prose.

A fact is one value with everything needed to tell it apart from a similar value:

  product   what it is about (table caption, else the row label, else the section heading)
  label     the row label cells of a table row (e.g. "17 Month Fixed Jumbo Certificate Special")
  quals     qualifiers parsed from label, caption and qualifier columns:
              term_months, model_year [lo, hi], amount [lo, hi] (balance or loan amount tier),
              flags (jumbo, special, fixed, variable, business, roth, ...)
  metric    apy | apr | rate | points | payment | min_open | min_earn | fee | count
  value     display string without footnote markers ("5.39%", "12.50% – 19.50%", "$1,000.00")
  num       number, or [lo, hi] for a range
  unit      "%" or "$" or ""
  footnote  footnote marker that was glued to the value ("1", "2"), if any
  source    "table" or "prose", block index, quote (the row or sentence)

Table facts are the primary source. Prose facts (rates, fees and counts in sentences) rank lower
and exist mainly so stale numbers on calculators, blogs and press releases are seen and can be
reported as conflicts instead of being mistaken for current values.
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple

EXTRACT_VERSION = 2

# ---- value parsing ------------------------------------------------------------------------
_NUM = r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?"
# A value with an optional glued footnote digit: "5.39% APR1", "4.10%2", "$1,000.00", "0.20%1"
_PCT = re.compile(rf"(?P<n>{_NUM})\s*%(?:\s*(?P<m>APY|APR))?(?P<fn>[1-9*†‡]?)(?![\d.])", re.I)
_PCT_RANGE = re.compile(rf"(?P<a>{_NUM})\s*%?\s*(?:[–—-]|to)\s*(?P<b>{_NUM})\s*%(?:\s*(?P<m>APY|APR))?(?P<fn>[1-9*†‡]?)(?![\d.])", re.I)
_MONEY = re.compile(rf"\$\s*(?P<n>{_NUM})(?P<k>\s*(?:k|million|billion)\b)?", re.I)


def _f(s: str) -> float:
    return float(s.replace(",", ""))


def _fmt_pct(x: str) -> str:
    return f"{x}%"


def parse_cell_value(cell: str) -> Optional[Dict]:
    """Parse a table cell into value, num, unit, metric hint and footnote. None for blanks/dashes."""
    c = cell.strip()
    if not c or c in ("—", "-", "–", "N/A", "n/a", "None") or c.startswith("—Not"):
        return None
    m = _PCT_RANGE.search(c)
    if m:
        a, b = m.group("a"), m.group("b")
        return {"value": f"{a}% – {b}%", "num": [_f(a), _f(b)], "unit": "%",
                "hint": (m.group("m") or "").lower() or None, "footnote": m.group("fn") or None}
    m = _PCT.search(c)
    if m:
        return {"value": _fmt_pct(m.group("n")), "num": _f(m.group("n")), "unit": "%",
                "hint": (m.group("m") or "").lower() or None, "footnote": m.group("fn") or None}
    m = _MONEY.search(c)
    if m:
        mult = {"k": 1e3, "million": 1e6, "billion": 1e9}.get((m.group("k") or "").strip().lower(), 1)
        fn = re.match(r"[1-9*]", c[m.end():].strip() or " ")
        return {"value": f"${m.group('n')}{m.group('k') or ''}", "num": _f(m.group("n")) * mult, "unit": "$",
                "hint": None, "footnote": fn.group(0) if fn else None}
    m = re.fullmatch(rf"({_NUM})", c)
    if m:
        return {"value": m.group(1), "num": _f(m.group(1)), "unit": "", "hint": None, "footnote": None}
    return None


# ---- qualifiers ----------------------------------------------------------------------------
_TERM = re.compile(r"\b(\d{1,3})\s*[- ]?\s*(month|mo|year|yr)s?\b", re.I)
_MODEL_YEAR = re.compile(r"\b((?:19|20)\d{2})(?:\s*[-–]\s*(\d{2,4}))?\s+model\s+years?(\s*\(and older\))?", re.I)
_AMT_RANGE = re.compile(rf"\$\s*({_NUM})\s*(?:[–—-]|to)\s*\$?\s*({_NUM})")
_AMT_PLUS = re.compile(rf"\$\s*({_NUM})\s*(?:\+|and (?:up|over|above)|or more)", re.I)
_AMT_CAP = re.compile(rf"\$\s*({_NUM})\s*(?:or less|and under|or under|max(?:imum)?)", re.I)
_AMT_UP_TO = re.compile(rf"(?:up to|under|less than)\s*\$\s*({_NUM})", re.I)
FLAGS = ("jumbo", "special", "fixed", "variable", "standard", "business", "roth", "traditional",
         "introductory", "intro", "balance transfer", "purchase", "refinance", "conventional", "fha", "va",
         "rewards", "platinum", "heloc", "home equity", "student", "new", "used", "ira", "health savings",
         "promotional", "share", "money market", "holiday", "youth", "teen")
_FLAGS_RE = re.compile(r"\b(" + "|".join(re.escape(f) for f in sorted(FLAGS, key=len, reverse=True)) + r")\b")


def parse_quals(text: str) -> Dict:
    q: Dict = {}
    t = text or ""
    m = _TERM.search(t)
    if m:
        n = int(m.group(1))
        q["term_months"] = n * 12 if m.group(2).lower().startswith(("y",)) else n
    m = _MODEL_YEAR.search(t)
    if m:
        lo = int(m.group(1))
        hi = m.group(2)
        hi = lo if not hi else int(hi) if len(hi) == 4 else int(str(lo)[:2] + hi)
        q["model_year"] = [1900 if m.group(3) else lo, hi]
    m = _AMT_RANGE.search(t)
    if m:
        q["amount"] = [_f(m.group(1)), _f(m.group(2))]
    else:
        m = _AMT_PLUS.search(t)
        if m:
            q["amount"] = [_f(m.group(1)), None]
        else:
            m = _AMT_CAP.search(t) or _AMT_UP_TO.search(t)
            if m:
                q["amount"] = [0.0, _f(m.group(1))]
    flags = sorted(set(_FLAGS_RE.findall(t.lower())))
    if flags:
        q["flags"] = flags
    return q


def merge_quals(*qs: Dict) -> Dict:
    out: Dict = {}
    for q in qs:
        for k, v in q.items():
            if k == "flags":
                out["flags"] = sorted(set(out.get("flags", [])) | set(v))
            elif k not in out:
                out[k] = v
    return out


# ---- column roles --------------------------------------------------------------------------
def column_role(header: str) -> Tuple[str, Optional[str]]:
    """('metric', name) | ('qual', name) | ('label', None) | ('skip', None)."""
    h = re.sub(r"[\d*†‡]+$", "", (header or "").strip()).lower()
    if not h:
        return ("label", None)
    if "annual percentage yield" in h or re.search(r"\bapy\b", h):
        return ("metric", "apy")
    if "annual percentage rate" in h or re.search(r"\bapr\b", h):
        return ("metric", "apr")
    if re.search(r"\b(dividend rate|interest rate|rate)\b", h):
        return ("metric", "rate")
    if re.search(r"\bpoints?\b", h):
        return ("metric", "points")
    if "payment" in h:
        return ("metric", "payment")
    if "min" in h and "open" in h:
        return ("metric", "min_open")
    if "min" in h and ("earn" in h or "balance" in h):
        return ("metric", "min_earn")
    if re.search(r"\bfees?\b|\bcost\b|\bcharge\b", h):
        return ("metric", "fee")
    if re.search(r"\b(term|balance|tier|loan amount|amount|model year|year)\b", h):
        return ("qual", h)
    return ("label", None)


def _norm_product(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w$%+ ]+", " ", (s or "").lower())).strip()


def table_facts(block: Dict) -> List[Dict]:
    header = block.get("header") or []
    rows = block.get("rows") or []
    caption = block.get("caption") or ""
    roles = [column_role(h) for h in header] if header else []
    facts: List[Dict] = []
    for r_i, row in enumerate(rows):
        if header and len(row) != len(header):
            continue
        if not header:  # headerless: treat as label | value pairs
            roles_r = [("label", None)] + [("metric", None)] * (len(row) - 1)
        else:
            roles_r = roles
        label_cells = [c for c, (role, _) in zip(row, roles_r) if role == "label" and c]
        qual_cells = [c for c, (role, _) in zip(row, roles_r) if role == "qual" and c]
        # Qualifier-column cells are part of the row label too: a "Term" column can hold the whole
        # product name ("10 Month Fixed Jumbo Certificate Special"), not just "10 Months".
        label = " | ".join(label_cells + qual_cells)
        quals = merge_quals(parse_quals(label), parse_quals(caption))
        product = caption or (label_cells[0] if label_cells else "") or label or " / ".join(block.get("path", [])[-1:])
        quote = " | ".join(f"{h}: {c}" if h else c for h, c in zip(header or [""] * len(row), row) if c)
        for col, (c, (role, metric)) in enumerate(zip(row, roles_r)):
            if role != "metric":
                continue
            v = parse_cell_value(c)
            if not v:
                continue
            m = metric or v["hint"] or ("rate" if v["unit"] == "%" else "fee" if v["unit"] == "$" else None)
            if not m:
                continue
            if v["hint"] in ("apr", "apy"):
                m = v["hint"]   # a metric written in the cell beats a (sometimes mislabeled) header
            facts.append({
                "source": "table", "block": block["i"], "row": r_i, "product": product,
                "product_key": _norm_product(product), "label": label, "quals": quals, "metric": m,
                "value": v["value"], "num": v["num"], "unit": v["unit"], "footnote": v["footnote"],
                "column": header[col] if header else "", "quote": quote[:300],
            })
    return facts


# ---- prose -----------------------------------------------------------------------------------
_SENT = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9$])")
_PCT_CTX = re.compile(r"\b(apy|annual percentage yield|apr|annual percentage rate|dividend|interest|rate)\b", re.I)
COUNT_NOUNS = ("branches", "branch offices", "offices", "locations", "members", "employees", "atms",
               "counties", "states", "learning labs", "member-owners")
_COUNT = re.compile(rf"\b(\d{{1,3}}(?:,\d{{3}})*|\d+)\s+(?:[a-z-]+\s+)?({'|'.join(re.escape(n) for n in COUNT_NOUNS)})\b", re.I)


def prose_facts(block: Dict, page_context: str) -> List[Dict]:
    if block["kind"] not in ("paragraph", "list", "label"):
        return []
    facts: List[Dict] = []
    text = block["text"]
    if "%" not in text and not _COUNT.search(text):
        return []
    path_ctx = " / ".join(block.get("path", []))
    ctx_q = parse_quals(path_ctx)
    for sent in _SENT.split(text.replace("\n", " ")):
        if len(sent) > 600:
            sent = sent[:600]
        if "%" not in sent and not _COUNT.search(sent):
            continue
        quals = parse_quals(sent)
        for m in _PCT_RANGE.finditer(sent):
            facts.append(_prose_fact(block, sent, f"{m.group('a')}% – {m.group('b')}%", [_f(m.group("a")), _f(m.group("b"))],
                                     "%", _metric_near(sent, m.start(), m.group("m")), quals, ctx_q, path_ctx, page_context))
        taken = [m.span() for m in _PCT_RANGE.finditer(sent)]
        for m in _PCT.finditer(sent):
            if any(a <= m.start() < b for a, b in taken):
                continue
            facts.append(_prose_fact(block, sent, _fmt_pct(m.group("n")), _f(m.group("n")), "%",
                                     _metric_near(sent, m.start(), m.group("m")), quals, ctx_q, path_ctx, page_context))
        for m in _COUNT.finditer(sent):
            n = m.group(1)
            facts.append(_prose_fact(block, sent, n, _f(n), "", "count", quals, ctx_q, path_ctx, page_context,
                                     product=m.group(2).lower()))
    return facts


def _metric_near(sent: str, pos: int, explicit: Optional[str]) -> str:
    if explicit:
        return explicit.lower()
    window = sent[max(0, pos - 60):pos + 60].lower()
    if "apy" in window or "annual percentage yield" in window:
        return "apy"
    if "apr" in window or "annual percentage rate" in window:
        return "apr"
    return "rate" if _PCT_CTX.search(window) else "percent"


def _prose_fact(block, sent, value, num, unit, metric, quals, ctx_q, path_ctx, page_context, product=None):
    prod = product or (block.get("path") or [page_context])[-1]
    return {
        "source": "prose", "block": block["i"], "row": None, "product": prod, "product_key": _norm_product(prod),
        "label": "", "quals": merge_quals(quals, ctx_q, parse_quals(page_context) if not quals else {}),
        "metric": metric, "value": value, "num": num, "unit": unit, "footnote": None, "column": "",
        "quote": sent.strip()[:300], "context": path_ctx[:200],
    }


def extract_page(blocks: List[Dict], title: str) -> List[Dict]:
    facts: List[Dict] = []
    for b in blocks:
        if b["kind"] == "table":
            facts.extend(table_facts(b))
        else:
            facts.extend(prose_facts(b, title))
    return facts
