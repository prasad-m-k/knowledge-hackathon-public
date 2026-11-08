"""What the crawl says about the organisation itself: its name and its web domain.

Both come from the pages, not from the code: the name is the suffix most page titles share
("Auto Loans | Dupaco", "Rates | Riverbend Credit Union"), the domain is the host most pages live
on. The rest of the system uses the profile wherever it would otherwise name one credit union:
the organisation's own name is not a search word or a product-name word, "how many branches does
<name> have" is a size question, bare links on its domain are links, and a count answer says who
it is about.

The name words are registered process-wide (`ORG_WORDS`, union only) because tokenisation is a
module-level function used at ingest and at answer time. Registering is idempotent, and a word
only ever stops being a search word, so a second site in the same process cannot change the
first site's facts beyond also ignoring that site's name.
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from typing import FrozenSet, Iterable
from urllib.parse import urlparse

# Words that describe the kind of institution rather than name it.
_INSTITUTION_WORDS = {"credit", "union", "community", "federal", "fcu", "cu", "bank", "savings",
                      "financial", "the", "of", "and"}
_TITLE_SEP = re.compile(r"\s+[|\-–—]\s+")
_WORD = re.compile(r"[A-Za-z][A-Za-z'’]*")
MIN_TITLE_SHARE = 0.2      # the name must close at least this share of page titles

# Lowercase words of every organisation name seen in this process (see module docstring).
ORG_WORDS: set = set()


@dataclass(frozen=True)
class SiteProfile:
    name: str = ""                     # "Dupaco", "Riverbend Credit Union"
    short: str = ""                    # "Dupaco", "Riverbend"
    domain: str = ""                   # "dupaco.com", "riverbendcu.org"
    words: FrozenSet[str] = field(default_factory=frozenset)   # {"dupaco"}, {"riverbend"}

    def subject(self) -> str:
        """Who a count answer is about."""
        return self.short or "The credit union"


def _registrable(host: str) -> str:
    host = host.lower().split(":")[0]
    if host.startswith("www."):
        host = host[4:]
    parts = host.split(".")
    return ".".join(parts[-2:]) if len(parts) >= 2 else host


def profile_from_pages(pages: Iterable) -> SiteProfile:
    pages = list(pages)
    suffixes: Counter = Counter()
    hosts: Counter = Counter()
    for p in pages:
        parts = _TITLE_SEP.split((getattr(p, "title", "") or "").strip())
        if len(parts) > 1 and parts[-1].strip():
            suffixes[parts[-1].strip()] += 1
        host = urlparse(getattr(p, "url", "") or "").netloc
        if host:
            hosts[_registrable(host)] += 1
    name = ""
    if suffixes:
        top, n = sorted(suffixes.items(), key=lambda kv: (-kv[1], kv[0]))[0]
        if n >= MIN_TITLE_SHARE * len(pages):
            name = top
    distinctive = [w for w in _WORD.findall(name) if w.lower() not in _INSTITUTION_WORDS]
    short = distinctive[0] if distinctive else ""
    domain = sorted(hosts.items(), key=lambda kv: (-kv[1], kv[0]))[0][0] if hosts else ""
    words = frozenset(w.lower() for w in distinctive)
    return SiteProfile(name=name, short=short, domain=domain, words=words)


def register(profile: SiteProfile) -> None:
    ORG_WORDS.update(profile.words)
