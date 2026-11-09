"""Repeated-claim sentences (ksys/ordinals.py, D-026), on made-up text only."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
for p in ("harness", "submission"):
    if str(ROOT / p) not in sys.path:
        sys.path.insert(0, str(ROOT / p))

from ksys.ordinals import build_ordinal_conflicts, claims_in  # noqa: E402

ORG = {"riverbend"}


def _page(text: str, published: str, page_type: str = "news"):
    meta = SimpleNamespace(page_type=page_type, published=published, url_date=None)
    return SimpleNamespace(meta=meta, blocks=[{"text": text}])


class TestClaims(unittest.TestCase):
    def test_recognition_sentence_keys_on_who_and_verb(self) -> None:
        got = claims_in("This was the fifth time Kiplinger named Riverbend a top credit union. Kiplinger said so.", ORG)
        self.assertEqual([(k, o) for k, o, _ in got], [("times Kiplinger named", "fifth")])
        self.assertTrue(got[0][2].startswith("This was the fifth time"))

    def test_numeric_ordinal_and_has(self) -> None:
        got = claims_in("It is the 3rd time Money Magazine has ranked Riverbend.", ORG)
        self.assertEqual([(k, o) for k, o, _ in got], [("times Money Magazine ranked", "3rd")])

    def test_window_counts_and_the_organisation_itself_are_ignored(self) -> None:
        self.assertEqual(claims_in("For the second time in just a month, Kiplinger has recognized Riverbend.", ORG), [])
        self.assertEqual(claims_in("It was the fifth time Riverbend named a scholarship winner.", ORG), [])
        self.assertEqual(claims_in("For a third year in a row, Kiplinger named Riverbend.", ORG), [])

    def test_consecutive_year_clause_drops_filler_words(self) -> None:
        got = claims_in("This is the eighth consecutive year a bonus dividend has been paid to members.", ORG)
        self.assertEqual([(k, o) for k, o, _ in got], [("consecutive years bonus dividend paid members", "eighth")])


class TestConflicts(unittest.TestCase):
    def test_newest_dated_release_wins_and_single_values_are_not_conflicts(self) -> None:
        pages = {
            "https://x.org/news/a": _page("It was the fourth time Kiplinger named Riverbend.", "2023-07-18"),
            "https://x.org/news/b": _page("This was the fifth time Kiplinger named Riverbend.", "2024-06-18"),
            "https://x.org/news/c": _page("It was the second time Money ranked Riverbend.", "2024-01-01"),
        }
        out = build_ordinal_conflicts(pages, ORG, "s5")
        self.assertEqual(len(out), 1, out)
        self.assertEqual(out[0]["values"], ["fourth", "fifth"])
        self.assertEqual(out[0]["resolution"], "fifth")
        self.assertIn("Kiplinger", out[0]["topic"])
        self.assertEqual({s["url"] for s in out[0]["sources"]}, {"https://x.org/news/a", "https://x.org/news/b"})

    def test_an_older_release_with_a_higher_count_does_not_win(self) -> None:
        pages = {"https://x.org/a": _page("It was the sixth time Kiplinger named Riverbend.", "2022-01-01"),
                 "https://x.org/b": _page("It was the fifth time Kiplinger named Riverbend.", "2025-01-01")}
        self.assertEqual(build_ordinal_conflicts(pages, ORG, "s")[0]["resolution"], "fifth")

    def test_listing_pages_are_skipped(self) -> None:
        pages = {"https://x.org/a": _page("It was the fourth time Kiplinger named Riverbend.", "2023-01-01"),
                 "https://x.org/news": _page("This was the fifth time Kiplinger named Riverbend.", "2024-01-01", "listing")}
        self.assertEqual(build_ordinal_conflicts(pages, ORG, "s"), [])


if __name__ == "__main__":
    unittest.main()
