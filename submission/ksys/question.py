"""Step 7a (DECISIONS.md D-020): parse a member question into what it asks for.

Recognised: an as-of date in the text, product family (with everyday synonyms such as "CD",
"car loan", "home loan"), term (digits or words: "six-month", "30 year"), model year, dollar
amount or balance range, metric (APY, APR, dividend or interest rate), identity flags (jumbo,
special, business, roth, traditional, intro, purchase, refinance ...), superlatives ("highest"),
and whether the question asks for a link.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from .dates import MONTH_YEAR, end_of_month, find_dates, month_num
from .history import family_of, name_tokens
from .taxonomy import IDENTITY_FLAGS

WORD_NUM = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
            "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16,
            "seventeen": 17, "eighteen": 18, "twenty": 20, "twenty-four": 24, "twenty-five": 25, "thirty": 30,
            "thirty-six": 36, "forty-eight": 48, "sixty": 60, "seventy-two": 72, "eighty-four": 84}
_WORD_NUM_RE = re.compile(r"\b(" + "|".join(sorted(map(re.escape, WORD_NUM), key=len, reverse=True)) + r")\b", re.I)

# Everyday words mapped to the vocabulary the site uses (checked before family detection).
SYNONYMS = [
    (r"\bcds?\b", "certificate"), (r"\bshare certificates?\b", "certificate"), (r"\bcar\b|\btruck\b", "auto"),
    (r"\bhome loans?\b|\bhouse\b", "mortgage"), (r"\bline of credit\b", "credit line"),
    (r"\bcredit cards?\b", "credit card visa"), (r"\bsavings? accounts?\b", "savings"),
    (r"\b(\d+)\s*/\s*1\b", r"\1/1 adjustable"), (r"\barm\b", "adjustable"),
]
_TERM = re.compile(r"\b(\d{1,3})\s*[- ]?\s*(month|mo|year|yr)s?\b", re.I)
_MODEL_YEAR = re.compile(r"\b((?:19|20)\d{2})\b(?=[^.?!]{0,25}\b(model|vehicle|car|truck|motorcycle|auto)\b)", re.I)
_MONEY = re.compile(r"\$\s*(\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?\s*(k|thousand)?", re.I)
_LINK_Q = re.compile(r"\b(link|url|website|web site|web address|online|page)\b", re.I)
_TODAY = re.compile(r"\b(today|now|currently|current|right now|still)\b", re.I)
_SUPER_HI = re.compile(r"\b(highest|best|top|max(?:imum)?|most)\b", re.I)
_SUPER_LO = re.compile(r"\b(lowest|cheapest|min(?:imum)?|least)\b", re.I)
_RATEY = re.compile(r"\b(rates?|apys?|aprs?|yields?|dividends?|interest|percent)\b|%", re.I)
FLAG_WORDS = sorted(IDENTITY_FLAGS | {"standard", "intro"}, key=len, reverse=True)
_FLAG_RE = re.compile(r"\b(" + "|".join(re.escape(f) for f in FLAG_WORDS) + r")\b", re.I)
STOP = {"what", "whats", "is", "the", "a", "an", "of", "for", "on", "in", "to", "do", "does", "you", "your", "i",
        "me", "my", "can", "are", "and", "or", "with", "how", "much", "many", "get", "tell", "please", "dupaco",
        "dupacos", "current", "currently", "now", "today", "right", "rate", "rates", "apy", "apr", "interest",
        "dividend", "s", "it", "at", "as", "be", "have", "has", "any", "there", "which", "who", "when", "where",
        "would", "like", "know", "give", "provide", "about", "if", "this", "that", "will", "earn", "pay", "offer",
        "want", "need", "should", "use", "see", "was", "were", "still", "open", "vehicle", "model", "year",
        "aprs", "apys", "their", "they", "them", "we", "us", "our", "would", "could", "let", "all", "some"}


@dataclass
class Query:
    text: str
    norm: str
    as_of: Optional[str]
    family: Optional[str]
    term_months: Optional[int] = None
    model_year: Optional[int] = None
    amount: Optional[float] = None
    metric: Optional[str] = None        # apy | apr | rate | None (unspecified)
    flags: List[str] = field(default_factory=list)
    names: Tuple[str, ...] = ()
    superlative: Optional[str] = None   # "max" | "min"
    wants_link: bool = False
    is_rate_q: bool = False
    tokens: List[str] = field(default_factory=list)


def _numbers_as_digits(q: str) -> str:
    s = q.replace("’", "'")
    return _WORD_NUM_RE.sub(lambda m: str(WORD_NUM[m.group(1).lower()]), s)


def _normalise(q: str) -> str:
    s = _numbers_as_digits(q)
    for pat, rep in SYNONYMS:
        s = re.sub(pat, rep, s, flags=re.I)
    return s


def question_date(q: str) -> Optional[str]:
    """A date the question pins itself to: full date, or month + year (end of that month)."""
    found = find_dates(q)
    if found:
        return found[-1][1]
    m = None
    for m in MONTH_YEAR.finditer(q):
        pass
    if m:
        return end_of_month(int(m.group(2)), month_num(m.group(1)))
    return None


def tokens_of(text: str) -> List[str]:
    out = []
    for t in re.findall(r"[a-z0-9$]+(?:['.][a-z0-9]+)*", text.lower()):
        t = t.strip("'.")
        if t.endswith("'s"):
            t = t[:-2]
        if len(t) > 3 and t.endswith("s") and not t.endswith("ss"):
            t = t[:-1]
        if t and t not in STOP:
            out.append(t)
    return out


def parse(question: str, as_of: Optional[str]) -> Query:
    norm = _normalise(question)
    low = norm.lower()
    date = as_of or question_date(question)
    q = Query(text=question, norm=norm, as_of=date, family=family_of(norm))
    m = _TERM.search(norm)
    if m:
        n = int(m.group(1))
        q.term_months = n * 12 if m.group(2).lower().startswith("y") else n
    m = _MODEL_YEAR.search(norm)
    if m:
        q.model_year = int(m.group(1))
    money = [float(x.group(1).replace(",", "")) * (1000 if x.group(2) else 1) for x in _MONEY.finditer(norm)]
    if money:
        q.amount = min(money) if re.search(r"\bbetween\b", low) else money[0]
    if re.search(r"\bapys?\b|annual percentage yield|\byield\b", low):
        q.metric = "apy"
    elif re.search(r"\baprs?\b|annual percentage rate", low):
        q.metric = "apr"
    elif re.search(r"\b(dividend|interest) rate\b", low):
        q.metric = "rate"
    q.flags = sorted({f.lower() for f in _FLAG_RE.findall(low)})
    q.names = name_tokens(norm)
    q.superlative = "max" if _SUPER_HI.search(low) else "min" if _SUPER_LO.search(low) else None
    q.wants_link = bool(_LINK_Q.search(low))
    q.is_rate_q = bool(_RATEY.search(low))
    # Search words come from the member's own wording; synonyms only help find the family.
    q.tokens = tokens_of(_numbers_as_digits(question))
    return q
