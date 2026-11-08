"""Temporal ("as of") behaviour, source authority and conflict detection.

Two kinds of tests live here:

- Synthetic tests build tiny snapshots in memory, so they always run, including in the public
  repository, which does not ship the supplied website snapshots.
- Real-snapshot tests run only when the five kit snapshots are unpacked in snapshots/ (the scorer
  does this on its first run). Their expected values were read by hand from the raw rate pages of
  each crawl, not from this system's output, so they check the system against the site itself.

    python3 -m unittest discover -s tests -v
"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in ("harness", "submission"):
    if str(ROOT / p) not in sys.path:
        sys.path.insert(0, str(ROOT / p))

from contract import Page, Snapshot  # noqa: E402
import solution  # noqa: E402
from scoring import contains, score_conflicts  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures"
SNAPSHOT_DIRS = sorted(d for d in (ROOT / "snapshots").glob("0*") if (d / "manifest.json").exists())
HAVE_SNAPSHOTS = len(SNAPSHOT_DIRS) == 5
SKIP_REASON = "kit snapshots not unpacked in snapshots/ (copy the zips into snapshots_zip/ and run the scorer once)"

CRAWL_DATES = ["2026-05-12", "2026-05-19", "2026-06-09", "2026-08-27", "2026-09-28"]


def _rate_page(apy: str, effective: str) -> str:
    return ("# Certificate Rates\n\n| Certificate | Dividend Rate | APY |\n|---|---|---|\n"
            f"| 6-Month Certificate | {apy} | {apy} |\n\nRates are effective as of {effective}.")


class TestAsOfSynthetic(unittest.TestCase):
    """A 6-month certificate APY that moves 2.95% -> 3.20% -> 3.50%, with a calculator that still
    shows the first value in the newest crawl."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.ks = solution.build()
        crawls = [("c1", "2026-05-12", "2.95%", "05/01/2026"),
                  ("c2", "2026-06-09", "3.20%", "06/01/2026"),
                  ("c3", "2026-09-28", "3.50%", "09/15/2026")]
        for sid, taken, apy, eff in crawls:
            pages = [Page("https://example.org/rates", "Rates", _rate_page(apy, eff), taken)]
            if sid == "c3":
                pages.append(Page("https://example.org/calculators/certificate-calculator", "Certificate Calculator",
                                  "# Certificate Calculator\n\n| Certificate | APY |\n|---|---|\n"
                                  "| 6-Month Certificate | 2.95% |\n", taken))
            cls.ks.ingest(Snapshot(sid, taken, pages))
        cls.q = "What is the 6-month certificate APY?"

    def _says(self, as_of, want, question=None):
        a = self.ks.answer(question or self.q, as_of=as_of)
        self.assertTrue(contains(a.text, want), f"as_of={as_of}: expected {want} in {a.text!r}")
        for other in {"2.95%", "3.20%", "3.50%"} - {want}:
            self.assertFalse(contains(a.text, other), f"as_of={as_of}: stale {other} in {a.text!r}")

    def test_as_of_argument_picks_newest_crawl_on_or_before_the_date(self) -> None:
        self._says("2026-05-12", "2.95%")      # exact crawl date
        self._says("2026-06-08", "2.95%")      # day before the next crawl
        self._says("2026-06-09", "3.20%")
        self._says("2026-07-15", "3.20%")      # between crawls
        self._says("2026-09-28", "3.50%")
        self._says("2026-12-31", "3.50%")      # after the latest crawl
        self._says(None, "3.50%")              # no date means the latest crawl

    def test_date_before_first_crawl_uses_earliest(self) -> None:
        self._says("2026-01-15", "2.95%")

    def test_dates_written_in_the_question(self) -> None:
        self._says(None, "2.95%", "What was the 6-month certificate APY as of May 2026?")
        self._says(None, "3.20%", "What was the 6-month certificate APY in June 2026?")
        self._says(None, "3.50%", "What is the 6-month certificate APY today (October 2026)?")

    def test_stale_calculator_never_beats_the_rate_sheet(self) -> None:
        self._says(None, "3.50%")
        a = self.ks.answer(self.q)
        self.assertTrue(a.sources and a.sources[0].url.endswith("/rates"), a.sources)

    def test_refusal_states_no_numbers(self) -> None:
        a = self.ks.answer("What is the 7/1 adjustable-rate mortgage rate?")
        self.assertFalse(a.confident)
        self.assertNotRegex(a.text, r"\d")

    def test_conflict_reports_replaced_and_stale_values_with_current_winner(self) -> None:
        cs = [c for c in self.ks.conflicts() if "6-month" in c.topic.lower()]
        self.assertEqual(len(cs), 1, [c.topic for c in self.ks.conflicts()])
        self.assertTrue(all(any(contains(v, x) for v in cs[0].values) for x in ("2.95%", "3.20%", "3.50%")))
        self.assertTrue(contains(cs[0].resolution or "", "3.50%"))


@unittest.skipUnless(HAVE_SNAPSHOTS, SKIP_REASON)
class TestRealSnapshots(unittest.TestCase):
    """Timelines read by hand from each crawl's raw pages (see the comments for where)."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.ks = solution.build()
        for d in SNAPSHOT_DIRS:
            m = json.loads((d / "manifest.json").read_text(encoding="utf-8"))
            pages = [Page(p["url"], p.get("title", ""), (d / p["file"]).read_text(encoding="utf-8"),
                          p.get("fetched_at", m["taken_on"])) for p in m["pages"]]
            cls.ks.ingest(Snapshot(m["snapshot_id"], m["taken_on"], pages))

    def _timeline(self, question, values):
        for taken, want in zip(CRAWL_DATES, values):
            with self.subTest(as_of=taken):
                a = self.ks.answer(question, as_of=taken)
                self.assertTrue(contains(a.text, want), f"{taken}: expected {want} in {a.text!r}")
                for other in set(values) - {want}:
                    self.assertFalse(contains(a.text, other), f"{taken}: other-crawl value {other} in {a.text!r}")

    def test_every_page_ingests_without_error(self) -> None:
        errors = {d.snapshot_id: d.stats.get("page_errors", 0) for d in self.ks.ingestor.snapshots}
        self.assertEqual(set(errors.values()), {0}, errors)

    def test_10_month_jumbo_special_apy_timeline(self) -> None:
        # /rates: "10 Month Fixed Jumbo Certificate Special" APY column, crawls 1 to 5
        self._timeline("What is the APY on the 10-month fixed jumbo certificate special?",
                       ["3.90%", "3.90%", "3.90%", "3.90%", "4.00%"])

    def test_30_year_100k_purchase_mortgage_rate_timeline(self) -> None:
        # /personal/loans/home-loans: "Purchase: 30-Year Fixed Conventional $100,000 or less" rate column
        self._timeline("What is the rate on a 30-year fixed purchase mortgage for $100,000?",
                       ["5.875%", "6.250%", "6.125%", "6.375%", "7.13%"])

    def test_48_month_auto_apr_timeline_across_model_year_rename(self) -> None:
        # /personal/loans/auto-motorcycle-loans: newest model-year row, "2023-26" then "2024-27"
        self._timeline("What's the APR for a 48-month auto loan on a 2025 model-year vehicle?",
                       ["4.99%", "4.99%", "4.99%", "4.99%", "5.19%"])

    def test_conflicts_against_independent_public_gold(self) -> None:
        # Gold entries come from the organizers' must_include / must_not_include labels on the
        # public questions, each confirmed in the raw pages. Floors guard against regressions.
        gold = json.loads((FIXTURES / "conflicts_gold_public.json").read_text(encoding="utf-8"))
        s = score_conflicts(gold, self.ks.conflicts())
        self.assertGreaterEqual(s["recall"], 0.875, s)
        self.assertGreaterEqual(s["resolution_accuracy"], 0.625, s)

    def test_conflict_list_matches_recorded_baseline(self) -> None:
        # A regression snapshot of this system's own output, not ground truth: it fails when the
        # conflict list changes, so any change is reviewed on purpose.
        baseline = json.loads((FIXTURES / "conflicts_baseline.json").read_text(encoding="utf-8"))
        got = sorted((c.topic, tuple(sorted(c.values))) for c in self.ks.conflicts())
        want = sorted((b["topic"], tuple(sorted(b["values"]))) for b in baseline)
        self.assertEqual(got, want)


if __name__ == "__main__":
    unittest.main()
