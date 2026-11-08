"""Optional LLM fact extraction at ingest (D-010 option (b), D-024). Off unless asked for.

Rule-based extraction reads tables well but struggles with rates written in prose about several
products ("Holiday Club earns 1.25% APY, Youth Savings earns 2.00% APY"), values stacked under
labels with no table, and ranges next to intro rates. For such pages an LLM can say which value
belongs to which product. This module asks one, then trusts only what it can check.

Safety and determinism:
- Off by default. It runs only when KSYS_LLM=gemini, GOOGLE_API_KEY is set, and the page's
  domain is listed in KSYS_LLM_ALLOW_DOMAINS. With no allow list nothing is ever sent, so a key
  in the environment alone cannot send a crawl to an API.
- Grounding: a returned value is kept only if it appears in the page text and inside the quoted
  sentence, and the quote itself appears in the page. Anything else is dropped as unsupported.
- Facts get source "llm" and rank like prose: a table on an authoritative page always wins.
- Temperature 0 and a JSON schema; every response is cached on disk by model, prompt version,
  URL and page content, so reruns make no calls and give identical facts.
- Never fails ingest: network or parse errors are logged and the page keeps its rule-based facts.
- Ingest only: answer() never calls an LLM (D-009).

Configuration (environment): KSYS_LLM=gemini, GOOGLE_API_KEY, KSYS_LLM_ALLOW_DOMAINS (comma
separated, e.g. "riverbendcu.org"), KSYS_LLM_MODEL (default gemini-3.5-flash), KSYS_LLM_CACHE
(default submission/cache/llm, gitignored).
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable, Dict, List, Optional
from urllib.parse import urlparse

from .extract import merge_quals, parse_cell_value, parse_quals, _norm_product

logger = logging.getLogger("ksys.llm")

PROMPT_VERSION = 1
DEFAULT_MODEL = "gemini-3.5-flash"
DEFAULT_CACHE = Path(__file__).resolve().parents[1] / "cache" / "llm"
MAX_PAGE_CHARS = 12000
RATE_METRICS = ("apy", "apr", "rate", "percent")
_RATE_TEXT = re.compile(r"\d\s*%.{0,60}\b(?:APY|APR|rate|dividend|yield)\b|\b(?:APY|APR|rate|dividend|yield)\b.{0,60}\d\s*%",
                        re.I | re.S)

PROMPT = """You extract interest rates from one page of a credit union website.
Return every interest rate, APY, APR or dividend rate the page states, one item per value.
Rules:
- product: the product the value belongs to, named as on the page (for example "Holiday Club Savings", "24-Month Certificate", "Visa Platinum").
- qualifier: what kind of rate it is when the page says ("purchase", "balance transfer", "introductory", "jumbo"), else "".
- term_months: the term in months when the value is for a specific term, else null.
- metric: "apy", "apr", "dividend" or "rate".
- value: the number exactly as written on the page, including the % sign; for a range write it exactly as on the page (for example "11.99% to 17.99%").
- quote: the exact sentence or line from the page that contains the value, copied character for character.
Do not infer, convert or round. If the page states no rates, return an empty list.

Page title: {title}

Page:
{text}
"""

SCHEMA = {
    "type": "ARRAY",
    "items": {
        "type": "OBJECT",
        "properties": {
            "product": {"type": "STRING"},
            "qualifier": {"type": "STRING"},
            "term_months": {"type": "INTEGER", "nullable": True},
            "metric": {"type": "STRING", "enum": ["apy", "apr", "dividend", "rate"]},
            "value": {"type": "STRING"},
            "quote": {"type": "STRING"},
        },
        "required": ["product", "metric", "value", "quote"],
    },
}

# A test can replace the network call: fn(prompt) -> response text (a JSON array).
_client_override: Optional[Callable[[str], str]] = None
STATS: Dict[str, int] = {"calls": 0, "cache_hits": 0, "kept": 0, "rejected": 0, "errors": 0}


def set_client(fn: Optional[Callable[[str], str]]) -> None:
    global _client_override
    _client_override = fn


def _allowed_domains() -> List[str]:
    raw = os.environ.get("KSYS_LLM_ALLOW_DOMAINS", "")
    return [d.strip().lower() for d in raw.split(",") if d.strip()]


def enabled() -> bool:
    if os.environ.get("KSYS_LLM", "").lower() != "gemini" or not _allowed_domains():
        return False
    return _client_override is not None or bool(os.environ.get("GOOGLE_API_KEY"))


def allowed(url: str) -> bool:
    host = urlparse(url).netloc.lower().split(":")[0]
    return any(host == d or host.endswith("." + d) for d in _allowed_domains())


def eligible(text: str, facts: List[Dict]) -> bool:
    """Pages that state rates but have no table rates: the cases rules read least reliably."""
    if any(f["source"] == "table" and f["metric"] in RATE_METRICS for f in facts):
        return False
    return bool(_RATE_TEXT.search(text))


def _model() -> str:
    return os.environ.get("KSYS_LLM_MODEL", DEFAULT_MODEL)


def _cache_path(url: str, content_hash: str) -> Path:
    root = Path(os.environ.get("KSYS_LLM_CACHE", str(DEFAULT_CACHE)))
    key = hashlib.sha256(f"{_model()}|p{PROMPT_VERSION}|{url}|{content_hash}".encode()).hexdigest()
    return root / f"{key}.json"


def _call_gemini(prompt: str) -> str:
    if _client_override is not None:
        return _client_override(prompt)
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{_model()}:generateContent"
    body = json.dumps({
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0, "responseMimeType": "application/json", "responseSchema": SCHEMA},
    }).encode()
    headers = {"Content-Type": "application/json", "x-goog-api-key": os.environ["GOOGLE_API_KEY"]}
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, data=body, headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=60) as r:
                data = json.load(r)
            return data["candidates"][0]["content"]["parts"][0]["text"]
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 503) and attempt < 2:
                time.sleep(2 * (attempt + 1))
                continue
            raise
    raise RuntimeError("unreachable")


def _ask(url: str, title: str, text: str, content_hash: str) -> Optional[list]:
    path = _cache_path(url, content_hash)
    if path.is_file():
        STATS["cache_hits"] += 1
        return json.loads(path.read_text(encoding="utf-8"))
    prompt = PROMPT.format(title=title, text=text[:MAX_PAGE_CHARS])
    STATS["calls"] += 1
    raw = _call_gemini(prompt)
    items = json.loads(raw)
    if not isinstance(items, list):
        raise ValueError("response is not a list")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(items, indent=1, sort_keys=True), encoding="utf-8")
    return items


def _flat(s: str) -> str:
    return " ".join(s.replace("**", "").split())


def _block_of(blocks: List[Dict], quote: str) -> Dict:
    q = _flat(quote)
    for b in blocks:
        if q and (q in _flat(b["text"]) or _flat(b["text"]) in q):
            return b
    return blocks[0] if blocks else {"i": 0, "path": []}


def to_facts(items: list, text: str, blocks: List[Dict]) -> List[Dict]:
    """Keep only values the page itself supports; convert them to the extractor's fact shape."""
    flat_page = _flat(text)
    out: List[Dict] = []
    for it in items:
        try:
            value, quote = str(it["value"]).strip(), str(it["quote"]).strip()
            product, metric = str(it["product"]).strip(), str(it["metric"]).lower()
        except (KeyError, TypeError):
            STATS["rejected"] += 1
            continue
        fq = _flat(quote)
        if not value or not product or fq not in flat_page or _flat(value) not in fq:
            STATS["rejected"] += 1
            logger.info("dropped unsupported LLM value %r for %r", value, product)
            continue
        v = parse_cell_value(value.replace(" to ", " – "))
        if not v or v["unit"] != "%":
            STATS["rejected"] += 1
            continue
        qualifier = str(it.get("qualifier") or "").strip()
        term = it.get("term_months")
        term_txt = f" {int(term)} months" if isinstance(term, int) and term > 0 else ""
        label = " ".join(x for x in (product, qualifier) if x)
        b = _block_of(blocks, quote)
        out.append({
            "source": "llm", "block": b["i"], "row": None, "product": label, "product_key": _norm_product(label),
            "label": label, "quals": merge_quals(parse_quals(label + term_txt), {}),
            "metric": "rate" if metric == "dividend" else metric, "value": v["value"], "num": v["num"],
            "unit": "%", "footnote": None, "column": "", "quote": quote[:300],
            "context": " / ".join(b.get("path", [])[-2:])[:200],
        })
        STATS["kept"] += 1
    return out


def augment(url: str, title: str, text: str, blocks: List[Dict], facts: List[Dict], content_hash: str) -> List[Dict]:
    """The page's facts, with prose rates replaced by grounded LLM rates when the LLM path applies."""
    if not (enabled() and allowed(url) and eligible(text, facts)):
        return facts
    try:
        items = _ask(url, title, text, content_hash)
    except Exception as e:      # network, quota, bad JSON: keep the rule-based facts
        STATS["errors"] += 1
        logger.warning("LLM extraction failed for %s: %s", url, e)
        return facts
    llm_facts = to_facts(items or [], text, blocks)
    if not llm_facts:
        return facts
    kept = [f for f in facts if not (f["source"] == "prose" and f["metric"] in RATE_METRICS)]
    return kept + llm_facts
