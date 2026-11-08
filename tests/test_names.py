"""Names in questions: which capitalized words are looked up, and what counts as the site naming them.

A name the site never uses leads to an honest refusal, so two things must hold: common words in
a question ("What", "May", "Saturday", the organisation's own name) are never looked up, and a
brand only counts as mentioned when the site writes it as a name, not when the same word is an
ordinary verb ("discover").

    python3 -m unittest discover -s tests -v
"""
from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in ("harness", "submission"):
    if str(ROOT / p) not in sys.path:
        sys.path.insert(0, str(ROOT / p))

from contract import Page, Snapshot  # noqa: E402
import solution  # noqa: E402
from ksys.passages import lowercase_tokens, name_tokens_in  # noqa: E402
from scoring import contains  # noqa: E402

H = "https://www.lakeshorecu.org"
T = "2026-09-28"


def _p(path, title, md):
    return Page(f"{H}{path}", f"{title} | Lakeshore Credit Union", md, T)


SITE = [
    _p("/", "Home", "# Welcome\n\nLakeshore Credit Union serves the lake region."),
    _p("/learn/blog/2026/09/saving-tips", "Saving tips",
       "# Saving tips\n\nDiscover how a credit card can help you save more each month. You might discover that a card with rewards adds up."),
    _p("/personal/mobile-wallet", "Mobile Wallet",
       "# Mobile Wallet\n\nYour Lakeshore debit and credit cards work with Apple Pay and Google Pay."),
    _p("/community/partners", "Community Partners",
       "# Community Partners\n\nWe support local groups:\n\n- Habitat for Humanity Lake County\n- Lakeshore Food Bank"),
    _p("/locations/main-street", "Main Street Branch",
       "# Main Street Branch\n\nLobby hours: Monday-Friday 9 a.m.-5 p.m."),
]


class TestNamesInQuestions(unittest.TestCase):
    def test_organisation_name_is_dropped_word_by_word(self) -> None:
        org = frozenset({"dupaco"})
        self.assertEqual(solution._names_in("What is the Dupaco Shared Branch network?", org), ["Shared Branch"])
        self.assertEqual(solution._names_in("Can I use my Dupaco Visa with Apple Pay?", org), ["Apple Pay"])

    def test_calendar_and_question_words_are_not_names(self) -> None:
        self.assertEqual(solution._names_in("What are the Saturday hours in May at the branch?"), [])
        self.assertEqual(solution._names_in("Is the branch open on Monday, January 5?"), [])

    def test_calendar_lists_are_in_order(self) -> None:
        self.assertEqual(solution._MONTHS[0], "January")
        self.assertEqual(solution._MONTHS[-1], "December")
        self.assertEqual(solution._WEEKDAYS, ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday",
                                              "Saturday", "Sunday"))

    def test_hyphenated_name_splits_into_parts(self) -> None:
        # The question side and the site side split "Hy-Vee" the same way, so the parts match.
        self.assertEqual(solution._names_in("Where is the Hy-Vee branch?"), ["Hy", "Vee"])
        self.assertTrue({"hy", "vee"} <= name_tokens_in("The Hy-Vee branch closed."))


class TestWhatCountsAsTheSiteNamingSomething(unittest.TestCase):
    def test_mid_sentence_capital_is_a_name(self) -> None:
        self.assertIn("apple", name_tokens_in("Your cards work with Apple Pay."))

    def test_sentence_start_capital_of_an_ordinary_word_is_not(self) -> None:
        body = "Discover how a credit card can help you save. You might discover that rewards add up."
        self.assertNotIn("discover", name_tokens_in(body, "", frozenset(lowercase_tokens(body))))

    def test_list_item_start_counts_when_the_word_is_never_lowercase(self) -> None:
        body = "We support local groups:\n\n- Habitat for Humanity Lake County"
        self.assertIn("habitat", name_tokens_in(body, "", frozenset(lowercase_tokens(body))))

    def test_headings_and_titles_count_every_capital(self) -> None:
        self.assertIn("perk", name_tokens_in("", "Account Perks"))


class TestNamesEndToEnd(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.ks = solution.build()
        cls.ks.ingest(Snapshot("lk", T, SITE))

    def test_brand_the_site_only_uses_as_an_ordinary_word_is_refused(self) -> None:
        a = self.ks.answer("Does Lakeshore offer a Discover card?")
        self.assertFalse(a.confident, a.text)
        self.assertIsNone(re.search(r"\d", a.text), a.text)
        self.assertNotIn("save more", a.text)

    def test_brand_the_site_names_is_answered(self) -> None:
        a = self.ks.answer("Can I use my Lakeshore Visa with Apple Pay?")
        self.assertTrue(a.confident, a.text)
        self.assertTrue(contains(a.text, "Apple Pay"), a.text)

    def test_name_opening_a_list_item_is_found(self) -> None:
        a = self.ks.answer("Do you work with Habitat for Humanity?")
        self.assertTrue(a.confident, a.text)
        self.assertTrue(contains(a.text, "Habitat for Humanity"), a.text)
        self.assertTrue(a.sources[0].url.endswith("/community/partners"), a.sources)

    def test_name_the_site_never_mentions_is_refused(self) -> None:
        a = self.ks.answer("What are the lobby hours at the Elm Avenue branch?")
        self.assertFalse(a.confident, a.text)


if __name__ == "__main__":
    unittest.main()
