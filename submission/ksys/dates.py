"""Date parsing helpers shared by classification, extraction and question parsing.

All functions return ISO dates ("YYYY-MM-DD") or None. Month-only dates resolve to the last day
of the month (used for "as of May 2026"); a year alone resolves to Dec 31 of that year.
"""
from __future__ import annotations

import calendar
import re
from datetime import date
from typing import List, Optional, Tuple

MONTHS = {m.lower(): i for i, m in enumerate(calendar.month_name) if m}
MONTHS.update({m.lower(): i for i, m in enumerate(calendar.month_abbr) if m})
MONTHS["sept"] = 9
_MON = r"(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|sept?(?:ember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"

# "July 01, 2025", "Jul 1 2025", "Sept. 3, 2024"
MDY_TEXT = re.compile(rf"\b{_MON}\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?,?\s+(\d{{4}})\b", re.I)
# "08/31/2026", "8/31/26"
MDY_NUM = re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4}|\d{2})\b")
# "2026-09-25"
ISO = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
# "May 2026", "May of 2026"
MONTH_YEAR = re.compile(rf"\b{_MON}\.?\s+(?:of\s+)?(\d{{4}})\b", re.I)
# URL forms: "/2018/09/25/", "/2017/06/", "jan-15-2025", "202502"
URL_YMD = re.compile(r"/((?:19|20)\d{2})/(\d{2})(?:/(\d{2}))?/")
URL_MON_D_Y = re.compile(rf"{_MON}-(\d{{1,2}})-((?:19|20)\d{{2}})", re.I)
URL_YYYYMM = re.compile(r"(?<!\d)((?:19|20)\d{2})(0[1-9]|1[0-2])(?!\d)")


def _iso(y: int, m: int, d: int) -> Optional[str]:
    try:
        return date(y, m, d).isoformat()
    except ValueError:
        return None


def month_num(name: str) -> int:
    n = name.lower().rstrip(".")
    return MONTHS.get(n) or MONTHS.get(n[:3], 0)


def end_of_month(y: int, m: int) -> str:
    return date(y, m, calendar.monthrange(y, m)[1]).isoformat()


def find_dates(text: str) -> List[Tuple[int, str]]:
    """All full dates in text as (position, iso), in order of appearance."""
    out = []
    for m in MDY_TEXT.finditer(text):
        d = _iso(int(m.group(3)), month_num(m.group(1)), int(m.group(2)))
        if d:
            out.append((m.start(), d))
    for m in MDY_NUM.finditer(text):
        y = int(m.group(3))
        y = y + 2000 if y < 100 else y
        d = _iso(y, int(m.group(1)), int(m.group(2)))
        if d:
            out.append((m.start(), d))
    for m in ISO.finditer(text):
        d = _iso(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        if d:
            out.append((m.start(), d))
    return sorted(out)


def first_date(text: str) -> Optional[str]:
    found = find_dates(text)
    return found[0][1] if found else None


def url_date(url: str) -> Optional[str]:
    m = URL_YMD.search(url)
    if m:
        y, mo = int(m.group(1)), int(m.group(2))
        return _iso(y, mo, int(m.group(3))) if m.group(3) else end_of_month(y, mo) if 1 <= mo <= 12 else None
    m = URL_MON_D_Y.search(url)
    if m:
        return _iso(int(m.group(3)), month_num(m.group(1)), int(m.group(2)))
    m = URL_YYYYMM.search(url)
    if m:
        return end_of_month(int(m.group(1)), int(m.group(2)))
    return None
