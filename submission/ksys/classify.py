"""Step 3 of ingest (DECISIONS.md D-012.3, D-004, D-014): page type, authority and on-page dates.

Page type comes from general signals in the URL path, title and text, not from one site's exact
URLs. Authority ranks how far a page can be trusted for a current value (higher wins):

  rate_sheet 100  a rates page (path segment containing "rates")
  product     80  a product or service page (loans, checking, savings, cards, ...)
  page        70  any other first-party page
  promo       60  landing or limited-time offer page
  document    50  PDF, spreadsheet or similar download
  home        50  site home page
  legal       40  privacy, disclosures, terms
  guide       35  educational pages that are not dated articles
  calculator  25  calculators (often keep old example rates)
  news        20  newsroom and press releases
  blog        15  blog posts and dated articles
  listing      5  tag, author, category and index pages (teaser lists)
  expired      0  pages that say the offer has expired

Dates recorded per page:
  published   byline date of an article (first date in the blocks before the body)
  url_date    a date in the URL or file name (/2018/09/25/, jan-15-2025, 202502)
  effective   per rate table: the "effective as of" date written next to it
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Dict, List, Optional
from urllib.parse import urlparse

from .dates import find_dates, first_date, url_date

CLASSIFY_VERSION = 1

AUTHORITY = {
    "rate_sheet": 100, "product": 80, "page": 70, "promo": 60, "document": 50, "home": 50,
    "legal": 40, "guide": 35, "calculator": 25, "news": 20, "blog": 15, "listing": 5, "expired": 0,
}

DOC_EXT = (".pdf", ".xls", ".xlsx", ".csv", ".doc", ".docx", ".ppt", ".pptx")
LISTING_LEAVES = {"blog", "news", "newsroom", "resources", "dupaco-news", "personal-resources",
                  "business-resources", "press", "press-releases", "articles"}
PRODUCT_WORDS = ("loan", "checking", "savings", "saving", "card", "certificate", "mortgage", "equity",
                 "ira", "retirement", "money-market", "insurance", "account", "heloc", "cash-management",
                 "credit-line", "lending", "deposit")
LEGAL_WORDS = ("privacy", "disclosure", "terms", "policy", "consumer-act")
_EXPIRED = re.compile(r"\b(offer has expired|offer (?:has )?ended|no longer available|this offer is no longer)\b", re.I)
_LIMITED = re.compile(r"\b(for a limited time|limited[- ]time (?:offer|only)|offer (?:ends|expires|valid through))\b", re.I)
_EFFECTIVE = re.compile(r"\beffective\s+(?:as\s+of|on|date:?)?\s*", re.I)
_FOOTNOTE_LEAD = re.compile(r"^\s*[\d*†‡]+\s*[A-Z]")
_TITLE_YEAR = re.compile(r"\((?:19|20)\d{2}\)")
BYLINE_BLOCKS = 4


@dataclass
class PageMeta:
    page_type: str
    authority: int
    published: Optional[str] = None
    url_date: Optional[str] = None
    title_year: Optional[str] = None
    limited_time: bool = False
    effective: Dict[int, str] = field(default_factory=dict)   # table block index -> ISO date
    page_effective: Optional[str] = None                      # latest effective date on the page

    def to_dict(self) -> Dict:
        return asdict(self)


def _segments(url: str) -> List[str]:
    return [s for s in urlparse(url).path.lower().split("/") if s]


def page_type(url: str, title: str, blocks: List[Dict]) -> str:
    u = urlparse(url)
    segs = _segments(url)
    path = "/" + "/".join(segs)
    head_text = " ".join([title] + [b["text"] for b in blocks[:3]])
    if _EXPIRED.search(title) or _EXPIRED.search(head_text):
        return "expired"
    if path.endswith(DOC_EXT):
        return "document"
    if not segs:
        return "home"
    if any(s in ("tag", "author", "category") for s in segs) or "category=" in u.query.lower() \
            or segs[-1] in LISTING_LEAVES:
        return "listing"
    if any("calculator" in s for s in segs):
        return "calculator"
    if any(s in ("newsroom", "news", "press", "press-releases") for s in segs):
        return "news"
    if any(s in ("blog", "dupacodaily") for s in segs) or re.search(r"/(?:19|20)\d{2}/\d{2}/", path) \
            or (len(segs) >= 3 and segs[-2] == "resources"):
        return "blog"
    if any(re.fullmatch(r"(?:[a-z]+-)?rates", s) for s in segs):
        return "rate_sheet"
    if any(w in s for s in segs for w in LEGAL_WORDS):
        return "legal"
    if segs[-1].endswith("-lp") or "offer" in segs[-1]:
        return "promo"
    if segs[0] == "learn":
        return "guide"
    if any(w in s for s in segs for w in PRODUCT_WORDS):
        return "product"
    return "page"


def _published(blocks: List[Dict]) -> Optional[str]:
    """Byline date: first date in the first few blocks, before the article body starts."""
    for b in blocks[:BYLINE_BLOCKS]:
        if b["kind"] in ("paragraph", "label") and len(b["text"]) <= 120:
            d = first_date(b["text"])
            if d:
                return d
    return None


def _effective_in(text: str) -> Optional[str]:
    m = _EFFECTIVE.search(text)
    if not m:
        return None
    found = find_dates(text[m.end():m.end() + 40])
    return found[0][1] if found and found[0][0] < 15 else None


def table_effective_dates(blocks: List[Dict]) -> Dict[int, str]:
    """For each table: the effective date in the nearest following blocks of the same section
    (before the next table), preferring a plain line over a footnote; else the nearest preceding."""
    out: Dict[int, str] = {}
    for i, b in enumerate(blocks):
        if b["kind"] != "table":
            continue
        plain_d = foot_d = None
        for nb in blocks[i + 1:i + 6]:
            if nb["kind"] == "table" or nb["path"] != b["path"]:
                break
            d = _effective_in(nb["text"])
            if d:
                if _FOOTNOTE_LEAD.match(nb["text"]):
                    foot_d = foot_d or d
                else:
                    plain_d = plain_d or d
        d = plain_d or foot_d
        if d is None:
            for pb in reversed(blocks[max(0, i - 3):i]):
                if pb["kind"] == "table" or pb["path"] != b["path"]:
                    break
                d = _effective_in(pb["text"])
                if d:
                    break
        if d:
            out[i] = d
    return out


def classify_page(url: str, title: str, blocks: List[Dict]) -> PageMeta:
    pt = page_type(url, title, blocks)
    eff = table_effective_dates(blocks)
    text = "\n".join(b["text"] for b in blocks)
    ty = _TITLE_YEAR.search(title or "")
    return PageMeta(
        page_type=pt,
        authority=AUTHORITY[pt],
        published=_published(blocks) if pt in ("blog", "news", "guide", "page", "listing") else None,
        url_date=url_date(url),
        title_year=ty.group(0).strip("()") if ty else None,
        limited_time=bool(_LIMITED.search(text)),
        effective=eff,
        page_effective=max(eff.values()) if eff else None,
    )
