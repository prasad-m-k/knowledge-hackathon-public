"""Step 1 of ingest (DECISIONS.md D-012.1): per-snapshot boilerplate detection and stripping.

Boilerplate is learned from each snapshot on its own, using frequency across pages, so the
rules carry over to a different site or dataset (D-014). Two passes:

1. Teaser sections: a heading that repeats across many pages and whose body is mostly
   link-only lines, bare dates, read-time labels or "..." excerpts (e.g. "Handpicked for You").
   The whole section is dropped, because its dates and numbers belong to other pages.
2. Template blocks: any non-heading block that appears on a large share of the snapshot's
   pages (widgets, form labels, modal text, country-code lists, chat launcher text). Block
   frequency is learned after pass 1. Blocks carrying a rate or money amount need a higher share.

Markdown tables are never dropped. The output text is hashed so unchanged pages can be
recognised across snapshots (D-013 layer 1).
"""
from __future__ import annotations

import hashlib
import re
from collections import Counter
from dataclasses import dataclass
from typing import Dict, Iterable, List, Sequence, Tuple

BOILERPLATE_VERSION = 1

# A block is template when it appears on at least this share of pages (and at least MIN_PAGES).
# Blocks that carry a rate or money amount need the higher share, so a disclosure or fact
# repeated on many product pages is not mistaken for a widget.
BLOCK_SHARE = 0.05
FACT_BLOCK_SHARE = 0.20
# A repeated heading qualifies its section for teaser checks at this share (and MIN_PAGES).
HEADING_SHARE = 0.02
MIN_PAGES = 5
# Share of a section's body blocks that must look like teaser material.
TEASER_RATIO = 0.6
MIN_TEASER_BLOCKS = 3

_WS = re.compile(r"\s+")
_HEADING = re.compile(r"^(#{1,6})(?:\s+(.*))?$")
_LINK = r"!?\[(?:[^\[\]]|\[[^\]]*\])*\]\([^)]*\)"
_LINK_ONLY = re.compile(rf"^(?:#{{1,6}}\s*)?(?:\s*[-*+]?\s*(?:\*\*)?{_LINK}(?:\*\*)?\s*)+$", re.S)
_MONTH = r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?"
_DATE_ONLY = re.compile(rf"^{_MONTH}\s+\d{{1,2}},?\s+\d{{4}}$", re.I)
_READ_TIME = re.compile(r"^\d+\s+min(?:ute)?s?\s+read$", re.I)
_EXCERPT = re.compile(r"(?:\.\.\.|…)$")
_TABLE_ROW = re.compile(r"^\s*\|.*\|\s*$", re.M)
# rates, money, clock times (branch hours repeat across branch pages and must survive)
_FACTISH = re.compile(r"\d\s*%|\$\s*\d|\d\s*(?:a\.?m\.?|p\.?m\.?)(?![a-z])", re.I)


@dataclass(frozen=True)
class CleanPage:
    url: str
    title: str
    fetched_at: str
    text: str            # page markdown with boilerplate removed
    content_hash: str    # sha256 of text, plus BOILERPLATE_VERSION
    removed_blocks: int


def split_blocks(markdown: str) -> List[str]:
    """Split markdown into blocks separated by blank lines. Tables and lists stay contiguous."""
    return [b.strip("\n") for b in re.split(r"\n[ \t]*\n", markdown) if b.strip()]


def norm(block: str) -> str:
    return _WS.sub(" ", block).strip()


def heading_level(block: str) -> int:
    """Heading level 1-6 for a single-line heading block, else 0."""
    if "\n" in block.strip():
        return 0
    m = _HEADING.match(block.strip())
    return len(m.group(1)) if m else 0


def is_table(block: str) -> bool:
    return len(_TABLE_ROW.findall(block)) >= 2


def is_teaser_block(block: str) -> bool:
    b = norm(block)
    return bool(_LINK_ONLY.match(b) or _DATE_ONLY.match(b) or _READ_TIME.match(b) or _EXCERPT.search(b))


def _section_spans(blocks: Sequence[str]) -> List[Tuple[int, int]]:
    """(start, end) for each heading block: up to the next heading of the same or higher level."""
    levels = [heading_level(b) for b in blocks]
    spans = []
    for i, lv in enumerate(levels):
        if not lv:
            continue
        j = i + 1
        while j < len(blocks) and not (levels[j] and levels[j] <= lv):
            j += 1
        spans.append((i, j))
    return spans


def learn_repeated_headings(pages_blocks: Iterable[Sequence[str]], n_pages: int) -> set:
    df: Counter = Counter()
    for blocks in pages_blocks:
        df.update({norm(b).lower() for b in blocks if heading_level(b)})
    h_min = max(MIN_PAGES, HEADING_SHARE * n_pages)
    return {k for k, c in df.items() if c >= h_min}


def strip_teaser_sections(blocks: Sequence[str], repeated_headings: set) -> List[str]:
    drop = [False] * len(blocks)
    for start, end in _section_spans(blocks):
        if norm(blocks[start]).lower() not in repeated_headings:
            continue
        # Body = content blocks plus link-only headings (teaser titles are often "#### [title](url)").
        body = [b for b in blocks[start + 1:end] if not heading_level(b) or _LINK_ONLY.match(norm(b))]
        if any(is_table(b) for b in body) or len(body) < MIN_TEASER_BLOCKS:
            continue
        if sum(is_teaser_block(b) for b in body) / len(body) >= TEASER_RATIO:
            for k in range(start, end):
                drop[k] = True
    return [b for b, d in zip(blocks, drop) if not d]


def learn_template_blocks(pages_blocks: Iterable[Sequence[str]], n_pages: int) -> set:
    """Run after teaser sections are removed, so teaser dates do not count against a post's own date."""
    df: Counter = Counter()
    for blocks in pages_blocks:
        df.update({norm(b) for b in blocks if not heading_level(b) and not is_table(b)})
    lo, hi = max(MIN_PAGES, BLOCK_SHARE * n_pages), max(MIN_PAGES, FACT_BLOCK_SHARE * n_pages)
    return {k for k, c in df.items() if c >= (hi if _FACTISH.search(k) else lo)}


def _empty_headings(blocks: Sequence[str]) -> set:
    """Indices of headings with no content before the next heading of the same or higher level."""
    out = set()
    for i, b in enumerate(blocks):
        lv = heading_level(b)
        if lv:
            nxt = next((x for x in blocks[i + 1:] if not heading_level(x) or heading_level(x) <= lv), None)
            if nxt is None or heading_level(nxt):
                out.add(i)
    return out


def strip_template_blocks(blocks: Sequence[str], template_blocks: set) -> List[str]:
    keep = [bool(heading_level(b) or is_table(b) or norm(b) not in template_blocks) for b in blocks]
    # A heading emptied by the stripping goes too; a heading that was already bare (a step
    # title, a label) is content and stays.
    was_empty = {norm(blocks[i]) for i in _empty_headings(blocks)}
    kept = [b for b, k in zip(blocks, keep) if k]
    now_empty = _empty_headings(kept)
    return [b for i, b in enumerate(kept) if i not in now_empty or norm(b) in was_empty]


def content_hash(text: str) -> str:
    return hashlib.sha256(f"bp{BOILERPLATE_VERSION}\n{text}".encode("utf-8")).hexdigest()


def clean_snapshot(pages) -> Dict[str, CleanPage]:
    """Clean every page of one snapshot. `pages` are contract.Page objects. Keyed by URL."""
    pages = list(pages)
    raw = [split_blocks(p.markdown or "") for p in pages]
    headings = learn_repeated_headings(raw, len(pages))
    no_teasers = [strip_teaser_sections(b, headings) for b in raw]
    template = learn_template_blocks(no_teasers, len(pages))
    out: Dict[str, CleanPage] = {}
    for p, r, b in zip(pages, raw, no_teasers):
        kept = strip_template_blocks(b, template)
        text = "\n\n".join(kept)
        out[p.url] = CleanPage(p.url, p.title or "", p.fetched_at or "", text, content_hash(text), len(r) - len(kept))
    return out
