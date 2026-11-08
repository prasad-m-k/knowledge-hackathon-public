"""The system on a second, made-up credit union: nothing in the code may name Dupaco.

"Riverbend Credit Union" at riverbendcu.org has two crawls. Its pages differ from Dupaco's in the
ways that matter: tables without a caption line (the product is only in the section heading),
its own news folder name, links written without a scheme, and an organisation name the code
has never seen.

    python3 -m unittest discover -s tests -v
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in ("harness", "submission"):
    if str(ROOT / p) not in sys.path:
        sys.path.insert(0, str(ROOT / p))

from contract import Page, Snapshot  # noqa: E402
import solution  # noqa: E402
from ksys.site import profile_from_pages  # noqa: E402
from scoring import contains  # noqa: E402

H = "https://www.riverbendcu.org"


def _site(taken: str, apy: str, auto60: str, branches: int):
    eff = f"{taken[5:7]}/01/{taken[:4]}"
    return [
        Page(f"{H}/", "Home | Riverbend Credit Union",
             "# Welcome to Riverbend\n\nRiverbend Credit Union serves members across the Ohio Valley.", taken),
        Page(f"{H}/rates", "Rates | Riverbend Credit Union",
             "# Rates\n\n## Certificates\n\n| Certificate | Dividend Rate | APY |\n|---|---|---|\n"
             f"| 12-Month Certificate | {apy} | {apy} |\n\nRates are effective as of {eff}.\n\n"
             f"## Auto Loans\n\n| Term | APR |\n|---|---|\n| 60 Months | {auto60} APR |\n\n"
             f"Rates are effective as of {eff}.", taken),
        Page(f"{H}/calculators/auto-loan-calculator", "Auto Loan Calculator | Riverbend Credit Union",
             "# Auto Loan Calculator\n\n| Term | APR |\n|---|---|\n| 60 Months | 5.10% APR |\n", taken),
        Page(f"{H}/riverbend-news/2021/riverbend-opens-marietta-branch", "Riverbend opens Marietta branch | Riverbend Credit Union",
             "# Riverbend opens Marietta branch\n\nPublished March 3, 2021\n\n"
             "Riverbend Credit Union now has 7 branches after opening its Marietta location.", taken),
        Page(f"{H}/riverbend-news/{taken[:4]}/riverbend-annual-meeting", "Riverbend annual meeting | Riverbend Credit Union",
             f"# Riverbend annual meeting\n\nPublished {taken[5:7]}/02/{taken[:4]}\n\n"
             f"Riverbend Credit Union, with {branches} branches in Ohio and Kentucky, held its annual meeting.", taken),
        Page(f"{H}/personal/mobile-wallet", "Mobile Wallet | Riverbend Credit Union",
             "# Mobile Wallet\n\n- Which wallets work with Riverbend cards? Your Riverbend debit and credit cards "
             "work with Apple Pay, Google Pay and Samsung Pay.\n- Is there a fee? No, there is no fee.", taken),
        Page(f"{H}/contact", "Contact | Riverbend Credit Union",
             "# Contact Us\n\nFind a branch or ATM near you at riverbendcu.org/locations.\n\n"
             "Lobby hours: Monday-Friday 9 a.m.-5 p.m., Saturday 9 a.m.-noon.", taken),
    ]


class TestSecondCreditUnion(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.ks = solution.build()
        cls.ks.ingest(Snapshot("r1", "2026-05-12", _site("2026-05-12", "3.10%", "5.49%", 9)))
        cls.ks.ingest(Snapshot("r2", "2026-09-28", _site("2026-09-28", "3.40%", "5.79%", 10)))

    def _says(self, question, want, not_want=(), as_of=None):
        a = self.ks.answer(question, as_of=as_of)
        self.assertTrue(a.confident, f"{question!r} refused: {a.text!r}")
        self.assertTrue(contains(a.text, want), f"{question!r}: expected {want!r} in {a.text!r}")
        for x in not_want:
            self.assertFalse(contains(a.text, x), f"{question!r}: unexpected {x!r} in {a.text!r}")
        return a

    def test_profile_is_read_from_titles_and_urls(self) -> None:
        prof = profile_from_pages(_site("2026-09-28", "3.40%", "5.79%", 10))
        self.assertEqual((prof.name, prof.short, prof.domain), ("Riverbend Credit Union", "Riverbend", "riverbendcu.org"))
        self.assertEqual(self.ks.health()["site"]["domain"], "riverbendcu.org")

    def test_rates_current_and_as_of(self) -> None:
        self._says("What is the 12-month certificate APY?", "3.40%", ["3.10%"])
        self._says("What was the 12-month certificate APY as of May 2026?", "3.10%", ["3.40%"])

    def test_uncaptioned_table_takes_product_from_section_heading(self) -> None:
        a = self._says("What is the APR for a 60-month auto loan?", "5.79%", ["5.49%", "5.10%"])
        self.assertTrue(a.sources[0].url.endswith("/rates"), a.sources)

    def test_branch_count_names_this_organisation_and_uses_newest_dated_statement(self) -> None:
        a = self._says("How many branches does Riverbend have?", "10", ["7 branch", "9 branch"])
        self.assertTrue(a.text.startswith("Riverbend has"), a.text)

    def test_own_name_is_not_a_name_to_look_up(self) -> None:
        self._says("Can I use my Riverbend Visa with Apple Pay?", "Apple Pay")

    def test_bare_links_on_the_site_domain(self) -> None:
        self._says("What's the URL for the branch and ATM locator?", "riverbendcu.org/locations")

    def test_unlisted_product_is_refused_without_numbers(self) -> None:
        a = self.ks.answer("What is the 7/1 ARM rate?")
        self.assertFalse(a.confident)
        self.assertNotRegex(a.text, r"\d")

    def test_news_folder_named_after_the_organisation_is_news(self) -> None:
        types = self.ks.page_types["r2"]
        self.assertEqual(types[f"{H}/riverbend-news/2021/riverbend-opens-marietta-branch"], "news")

    def test_conflicts_resolve_to_the_rate_sheet_and_newest_count(self) -> None:
        by_topic = {c.topic: c for c in self.ks.conflicts()}
        auto = next(c for t, c in by_topic.items() if "auto" in t)
        self.assertTrue(contains(auto.resolution or "", "5.79%"), auto)
        count = next(c for t, c in by_topic.items() if "branch" in t)
        self.assertTrue(contains(count.resolution or "", "10"), count)


if __name__ == "__main__":
    unittest.main()
