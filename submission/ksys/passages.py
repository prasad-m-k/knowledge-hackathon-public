"""Step 7b (DECISIONS.md D-020): keyword search over page blocks for text facts.

BM25 over the blocks of one snapshot (heading path + block text). Listing and expired pages are
left out. The final score is weighted by page authority so a product or contact page beats a
blog post that happens to use the same words. Built once per snapshot during ingest.
"""
from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Dict, List, Tuple

from .question import tokens_of

K1, B = 1.2, 0.75
EXCLUDED_TYPES = {"listing", "expired"}
MAX_BLOCK_CHARS = 1500


CHUNK_CHARS = 600


# A capitalized word ("Discover", "MasterCard", "Hy-Vee", "DUBUQUE"). Names in a question are
# matched in this form, so the verb "discover" in a blog post never stands in for the brand.
_CAP_WORD = re.compile(r"\b[A-Z][A-Za-z]+")
# The same, but not at the start of a line, sentence or list item, where any word is capitalized.
_MID_CAP_WORD = re.compile(r"(?<!^)(?<![.!?:]\s)(?<![-*+]\s)\b[A-Z][A-Za-z]+", re.M)


def capitalized_tokens(text: str, mid_sentence_only: bool = False) -> set:
    """Normalised tokens of the capitalized words in `text` (same normalisation as tokens_of)."""
    words = (_MID_CAP_WORD if mid_sentence_only else _CAP_WORD).findall(text)
    return set(tokens_of(" ".join(words)))


def _chunks(text: str) -> List[str]:
    if len(text) <= MAX_BLOCK_CHARS:
        return [text]
    out, buf = [], ""
    for line in re.split(r"(?<=\n)|(?<=[.!?]) ", text):
        if buf and len(buf) + len(line) > CHUNK_CHARS:
            out.append(buf.strip())
            buf = ""
        buf += line
    if buf.strip():
        out.append(buf.strip())
    return out


@dataclass
class Passage:
    url: str
    title: str
    page_type: str
    authority: int
    block_i: Tuple[int, int]
    path: List[str]
    text: str
    md: str
    published: str


class PassageIndex:
    def __init__(self, snapshot_doc) -> None:
        self.passages: List[Passage] = []
        self.postings: Dict[str, List[Tuple[int, int]]] = defaultdict(list)
        self.by_url: Dict[str, List[int]] = defaultdict(list)
        # Words the site writes capitalized mid-sentence: the names it actually uses.
        self.name_vocab: set = set()
        lengths: List[int] = []
        for url in sorted(snapshot_doc.pages):
            p = snapshot_doc.pages[url]
            if p.meta.page_type in EXCLUDED_TYPES:
                continue
            for b in p.blocks:
                if not b["text"].strip():
                    continue
                if b["kind"] == "table":
                    # Tables join the index as "header: cell" rows (hours, addresses, fee lists).
                    rows = [" | ".join(f"{h}: {c}" if h else c for h, c in zip(b.get("header") or [""] * len(r), r) if c)
                            for r in b.get("rows", [])]
                    text = "\n".join(rows)
                else:
                    text = b["text"]
                # Long blocks (a branch directory, a long FAQ, a multi-row table) are split into
                # line-aligned chunks instead of being cut off, so facts near the end stay searchable.
                for chunk_no, chunk in enumerate(_chunks(text)):
                    doc_tokens = tokens_of(" ".join(b["path"][-2:]) + " " + p.title.split("|")[0] + " " + chunk)
                    if not doc_tokens:
                        continue
                    i = len(self.passages)
                    self.by_url[url].append(i)
                    md = b["md"] if chunk_no == 0 and len(b["md"]) <= MAX_BLOCK_CHARS * 2 else chunk
                    self.passages.append(Passage(url, p.title, p.meta.page_type, p.meta.authority,
                                                 (b["i"], chunk_no), b["path"], chunk, md, p.meta.published or ""))
                    lengths.append(len(doc_tokens))
                    # Body text counts only mid-sentence capitals; headings and titles are where
                    # the site names its own products and programs, so every capital there counts.
                    self.name_vocab |= capitalized_tokens(chunk, mid_sentence_only=True)
                    self.name_vocab |= capitalized_tokens(" ".join(b["path"]) + " " + p.title)
                    for t, c in Counter(doc_tokens).items():
                        self.postings[t].append((i, c))
        self.n = len(self.passages)
        self.avgdl = (sum(lengths) / self.n) if self.n else 1.0
        self.lengths = lengths
        self.idf = {t: math.log(1 + (self.n - len(ps) + 0.5) / (len(ps) + 0.5)) for t, ps in self.postings.items()}

    def _weight(self, p: Passage) -> float:
        w = 0.4 + p.authority / 100
        if p.published[:4].isdigit():          # newer releases and posts first among dated pages
            w *= 1 + 0.04 * max(0, int(p.published[:4]) - 2018)
        return w

    def search(self, tokens: List[str], k: int = 8, must: str = "") -> List[Tuple[float, Passage, int]]:
        """Top passages as (score, passage, distinct query terms matched). With `must`, only
        passages (or their section context) containing that token qualify."""
        scores: Dict[int, float] = defaultdict(float)
        hits: Dict[int, int] = defaultdict(int)
        for t in set(tokens):
            for i, c in self.postings.get(t, ()):
                dl = self.lengths[i]
                scores[i] += self.idf[t] * c * (K1 + 1) / (c + K1 * (1 - B + B * dl / self.avgdl))
                hits[i] += 1
        if must:
            allowed = {i for i, _ in self.postings.get(must, ())}
            scores = {i: v for i, v in scores.items() if i in allowed}
        nq = max(1, len(set(tokens)))
        final = {i: scores[i] * self._weight(self.passages[i]) * (0.5 + hits[i] / nq) for i in scores}
        ranked = sorted(final, key=lambda i: (-final[i], i))[:k]
        return [(final[i], self.passages[i], hits[i]) for i in ranked]

    def context(self, p: Passage, max_chars: int = 1200) -> Tuple[str, str]:
        """The passage plus its neighbours in the same section: a short block (an FAQ question, a
        "Branch hours are:" label) is usually followed by the actual answer."""
        ids = self.by_url[p.url]
        pos = next(j for j, i in enumerate(ids) if self.passages[i].block_i == p.block_i)
        text, md = [p.text], [p.md]
        j = pos + 1
        while j < len(ids) and sum(map(len, text)) < max_chars:
            nxt = self.passages[ids[j]]
            if nxt.path != p.path and not (len(p.path) < len(nxt.path) and nxt.path[:len(p.path)] == p.path):
                break
            text.append(nxt.text)
            md.append(nxt.md)
            j += 1
        if (len(p.text) < 80 or p.block_i[1] > 0) and pos > 0:
            prev = self.passages[ids[pos - 1]]
            if prev.path == p.path and (len(p.text) < 80 or prev.block_i[0] == p.block_i[0]):
                text.insert(0, prev.text)
                md.insert(0, prev.md)
        if "charter area" in "\n".join(text).lower() and p.path:
            for k in range(pos - 1, -1, -1):
                prev = self.passages[ids[k]]
                if prev.path[:1] == p.path[:1] and "iowa" in prev.text.lower():
                    text.insert(0, prev.text)
                    md.insert(0, prev.md)
                    break
        return "\n".join(text), "\n".join(md)

    def lede(self, url: str) -> str:
        """First substantial paragraph of a page (a press release's opening paragraph)."""
        for i in self.by_url.get(url, ()):
            t = self.passages[i].text
            if len(t) >= 120 and not t.lstrip().startswith(("-", "|")):
                return t
        return ""

    def rarest(self, tokens: List[str]) -> str:
        known = [t for t in set(tokens) if t in self.idf]
        return max(known, key=lambda t: (self.idf[t], t)) if known else ""

    def vocabulary(self) -> set:
        return set(self.postings)
