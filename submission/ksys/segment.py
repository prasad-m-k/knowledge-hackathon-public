"""Step 2 of ingest (DECISIONS.md D-012.2): split a cleaned page into blocks with heading paths.

Each block is a paragraph, list, table or label (a heading with no body, e.g. a step title).
Every block carries the heading path above it, which is the main clue to what product or topic
it is about (URLs move between crawls, headings mostly do not).

Rules:
- Heading stack: a heading of level L closes every open heading of level >= L.
- Eyebrow headings: a short heading (at most 4 words, not numbered) immediately followed by a
  higher-rank heading with no content in between (e.g. "##### Rates" then "## Get on the road with low interest rates") is merged
  into that heading as "Rates / Get on the road with low interest rates" instead of being lost.
- Tables are parsed into header and rows. A short line just before a table in the same section
  (e.g. "Auto & Motorcycle Loans") becomes its caption.
- Text is kept twice: `md` (cleaned markdown, for quotes) and `text` (plain: links reduced to
  their text, images removed, escapes and emphasis stripped), for search and extraction.

Output is plain dicts/lists so it can be cached as JSON (ksys/store.py).
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional

from .boilerplate import heading_level, is_table, split_blocks

SEGMENT_VERSION = 1

_IMAGE = re.compile(r"!\[(?:[^\[\]]|\[[^\]]*\])*\]\([^)]*\)")
_LINK = re.compile(r"\[((?:[^\[\]]|\[[^\]]*\])*)\]\([^)]*\)")
_ESCAPE = re.compile(r"\\([\\`*_{}\[\]()#+\-.!|$&~<>])")
_EMPHASIS = re.compile(r"(\*\*|__)(.+?)\1")
_BR = re.compile(r"<br\s*/?>", re.I)
_WS = re.compile(r"[ \t]+")
_TABLE_LINE = re.compile(r"^\s*\|.*\|\s*$")
_SEPARATOR = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)*\|?\s*$")
_LIST_LINE = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+")
CAPTION_MAX = 80
EYEBROW_MAX_WORDS = 4
_NUMBERED = re.compile(r"^\s*(?:\d+|[ivx]+|[a-z])[.)]\s", re.I)


def _is_eyebrow(text: str) -> bool:
    """Short tag-like headings ("Rates", "Get Started") rather than bare step titles ("3. We handle...")."""
    return len(text.split()) <= EYEBROW_MAX_WORDS and not _NUMBERED.match(text)


def plain(md: str) -> str:
    """Markdown to plain text: drop images, keep link text, remove escapes, emphasis and <br>."""
    s = _IMAGE.sub("", md)
    for _ in range(2):  # links can wrap emphasis and vice versa
        s = _LINK.sub(r"\1", s)
        s = _EMPHASIS.sub(r"\2", s)
    s = _BR.sub(" ", s)
    s = _ESCAPE.sub(r"\1", s)
    lines = [_WS.sub(" ", ln).strip() for ln in s.splitlines()]
    return "\n".join(ln for ln in lines if ln)


def heading_text(block: str) -> str:
    return plain(re.sub(r"^#{1,6}\s*", "", block.strip()).rstrip("#").strip())


def _split_cells(line: str) -> List[str]:
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|") and not s.endswith("\\|"):
        s = s[:-1]
    cells = re.split(r"(?<!\\)\|", s)
    return [plain(c) for c in cells]


def parse_table(lines: List[str]) -> Dict[str, List]:
    """Header + rows from markdown table lines. Without a separator line, there is no header."""
    sep = next((i for i, ln in enumerate(lines) if _SEPARATOR.match(ln)), None)
    if sep is not None and sep > 0:
        header = _split_cells(lines[sep - 1])
        body = lines[:sep - 1] + lines[sep + 1:]
    else:
        header, body = [], [ln for ln in lines if not _SEPARATOR.match(ln)]
    rows = [_split_cells(ln) for ln in body]
    rows = [r for r in rows if any(c for c in r)]
    return {"header": header, "rows": rows}


def _pieces(block: str) -> List[tuple]:
    """Split one blank-line block into (kind, markdown) pieces; tables may share a block with text."""
    if not is_table(block):
        lines = [ln for ln in block.splitlines() if ln.strip()]
        kind = "list" if lines and all(_LIST_LINE.match(ln) or ln.startswith((" ", "\t")) for ln in lines) else "paragraph"
        return [(kind, block)]
    out, buf, buf_is_table = [], [], None
    for ln in block.splitlines():
        t = bool(_TABLE_LINE.match(ln) or _SEPARATOR.match(ln))
        if buf and t != buf_is_table:
            out.append(("table" if buf_is_table else "paragraph", "\n".join(buf)))
            buf = []
        buf.append(ln)
        buf_is_table = t
    if buf:
        out.append(("table" if buf_is_table else "paragraph", "\n".join(buf)))
    return [(k, m) for k, m in out if m.strip()]


def _is_caption(text: str) -> bool:
    return 0 < len(text) <= CAPTION_MAX and "\n" not in text and not text.rstrip().endswith((".", "!", "?"))


def segment_page(md: str) -> List[Dict]:
    blocks = split_blocks(md)
    levels = [heading_level(b) for b in blocks]
    stack: List[tuple] = []          # (level, text)
    eyebrow: Optional[str] = None
    out: List[Dict] = []
    for i, b in enumerate(blocks):
        lv = levels[i]
        if lv:
            text = heading_text(b)
            nxt = levels[i + 1] if i + 1 < len(levels) else 0
            has_body_before_next = not (i + 1 < len(blocks) and nxt)
            if not text:
                continue
            if eyebrow:
                text = f"{eyebrow} / {text}"
                eyebrow = None
            if not has_body_before_next and nxt and nxt < lv and _is_eyebrow(text):
                eyebrow = text           # merge into the higher-rank heading that follows
                continue
            while stack and stack[-1][0] >= lv:
                stack.pop()
            stack.append((lv, text))
            # A heading with no body of its own (next block is a same-or-higher heading, or the end)
            # is itself content: emit it as a label so step titles are not lost.
            if i + 1 == len(blocks) or (nxt and nxt <= lv):
                out.append({"kind": "label", "path": [t for _, t in stack[:-1]], "md": b, "text": text})
            continue
        if eyebrow:                      # eyebrow followed by content after all: keep it as a heading
            while stack and stack[-1][0] >= 6:
                stack.pop()
            stack.append((6, eyebrow))
            eyebrow = None
        path = [t for _, t in stack]
        for kind, piece in _pieces(b):
            blk = {"kind": kind, "path": path, "md": piece}
            if kind == "table":
                blk.update(parse_table(piece.splitlines()))
                prev = out[-1] if out else None
                if prev and prev["kind"] == "paragraph" and prev["path"] == path and _is_caption(prev["text"]):
                    blk["caption"] = prev["text"]
                blk["text"] = plain(piece)
            else:
                blk["text"] = plain(piece)
                if not blk["text"]:
                    continue
            out.append(blk)
    for n, blk in enumerate(out):
        blk["i"] = n
    return out
