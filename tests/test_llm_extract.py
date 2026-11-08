"""Optional LLM extraction (ksys/llm.py), tested offline with a stand-in for the API.

These tests never call a real model: `llm.set_client` replaces the network call with a function
that returns what a model would. They check the guards (off by default, allow-listed domains
only), the grounding check (values the page does not state are dropped), the cache (a rerun
makes no calls) and that grounded facts fix the hard layouts in tests/fixtures/hard_layouts.py.
The live check against Gemini is tools/check_llm.py.

    python3 -m unittest discover -s tests -v
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
for p in ("harness", "submission", "tests/fixtures"):
    if str(ROOT / p) not in sys.path:
        sys.path.insert(0, str(ROOT / p))

from contract import Page, Snapshot  # noqa: E402
import hard_layouts as H  # noqa: E402
import solution  # noqa: E402
from ksys import llm  # noqa: E402
from scoring import contains  # noqa: E402

# What a correct model returns for each hard-layout page, keyed by page title.
GOOD = {
    "Savings Accounts": [
        {"product": "Holiday Club Savings", "qualifier": "", "term_months": None, "metric": "apy", "value": "1.25%",
         "quote": "Holiday Club Savings earns 1.25% APY, Youth Savings earns 2.00% APY for members under 18, and a Health Savings Account earns 0.50% APY."},
        {"product": "Youth Savings", "qualifier": "", "term_months": None, "metric": "apy", "value": "2.00%",
         "quote": "Holiday Club Savings earns 1.25% APY, Youth Savings earns 2.00% APY for members under 18, and a Health Savings Account earns 0.50% APY."},
        {"product": "Health Savings Account", "qualifier": "", "term_months": None, "metric": "apy", "value": "0.50%",
         "quote": "Holiday Club Savings earns 1.25% APY, Youth Savings earns 2.00% APY for members under 18, and a Health Savings Account earns 0.50% APY."},
    ],
    "Certificates": [
        {"product": "6-Month Certificate", "qualifier": "", "term_months": 6, "metric": "apy", "value": "2.90%", "quote": "2.90%"},
        {"product": "24-Month Certificate", "qualifier": "", "term_months": 24, "metric": "apy", "value": "3.15%", "quote": "3.15%"},
    ],
    "Visa Platinum": [
        {"product": "Visa Platinum", "qualifier": "purchase", "term_months": None, "metric": "apr", "value": "11.99% to 17.99%",
         "quote": "The purchase APR is 11.99% to 17.99% based on credit, balance transfers are 2.99% APR for the first 12 months, and there is no annual fee."},
        {"product": "Visa Platinum", "qualifier": "balance transfer", "term_months": None, "metric": "apr", "value": "2.99%",
         "quote": "The purchase APR is 11.99% to 17.99% based on credit, balance transfers are 2.99% APR for the first 12 months, and there is no annual fee."},
    ],
}


class FakeModel:
    def __init__(self, answers):
        self.answers, self.prompts = answers, []

    def __call__(self, prompt: str) -> str:
        self.prompts.append(prompt)
        title = prompt.split("Page title: ", 1)[1].split(" | ", 1)[0]
        return json.dumps(self.answers.get(title, []))


class LlmTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.env = mock.patch.dict(os.environ, {"KSYS_LLM_CACHE": self.tmp.name}, clear=False)
        self.env.start()
        for k in ("KSYS_LLM", "KSYS_LLM_ALLOW_DOMAINS", "GOOGLE_API_KEY"):
            os.environ.pop(k, None)

    def tearDown(self) -> None:
        llm.set_client(None)
        self.env.stop()
        self.tmp.cleanup()

    def _enable(self, model, domains=H.DOMAIN) -> None:
        os.environ["KSYS_LLM"] = "gemini"
        os.environ["KSYS_LLM_ALLOW_DOMAINS"] = domains
        llm.set_client(model)

    def _score(self, ks) -> int:
        ok = 0
        for q, want, bad in H.QUESTIONS:
            a = ks.answer(q)
            ok += a.confident and contains(a.text, want) and not any(contains(a.text, b) for b in bad)
        return ok

    def _build(self):
        ks = solution.build()
        ks.ingest(H.SNAPSHOT)
        return ks


class TestGuards(LlmTestCase):
    def test_off_by_default_even_with_a_key(self) -> None:
        os.environ["GOOGLE_API_KEY"] = "not-a-real-key"
        model = FakeModel(GOOD)
        llm.set_client(None)
        self.assertFalse(llm.enabled())
        with mock.patch.object(llm, "_call_gemini", side_effect=AssertionError("network call while off")):
            self._build()
        self.assertEqual(model.prompts, [])

    def test_no_allow_list_means_nothing_is_sent(self) -> None:
        model = FakeModel(GOOD)
        self._enable(model, domains="")
        self._build()
        self.assertEqual(model.prompts, [])

    def test_pages_outside_the_allow_list_are_never_sent(self) -> None:
        model = FakeModel(GOOD)
        self._enable(model, domains="example.org")
        other = Snapshot("x", H.TAKEN, [Page("https://www.dupaco.com/personal/savings", "Savings | Dupaco",
                                             "# Savings\n\nShare Savings earns 0.20% APY.", H.TAKEN)])
        ks = solution.build()
        ks.ingest(other)
        ks.ingest(H.SNAPSHOT)
        self.assertEqual(model.prompts, [])

    def test_rule_based_answers_without_llm(self) -> None:
        self.assertEqual(self._score(self._build()), 1)   # the baseline this module improves on


class TestGroundedExtraction(LlmTestCase):
    def test_grounded_facts_fix_the_hard_layouts(self) -> None:
        model = FakeModel(GOOD)
        self._enable(model)
        ks = self._build()
        self.assertEqual(self._score(ks), len(H.QUESTIONS))
        self.assertEqual(len(model.prompts), 3)   # only the three prose-only rate pages

    def test_values_the_page_does_not_state_are_dropped(self) -> None:
        bad = {"Savings Accounts": [
            {"product": "Holiday Club Savings", "metric": "apy", "value": "1.50%",   # not on the page
             "quote": "Holiday Club Savings earns 1.50% APY"},
            {"product": "Youth Savings", "metric": "apy", "value": "2.00%",
             "quote": "Youth Savings earns 2.00% APY, made up sentence"},           # quote not on the page
        ]}
        self._enable(FakeModel(bad))
        before = dict(llm.STATS)
        ks = self._build()
        self.assertEqual(llm.STATS["rejected"] - before["rejected"], 2)
        self.assertFalse(contains(ks.answer("What is the Holiday Club Savings APY?").text, "1.50%"))

    def test_rerun_uses_the_cache_and_gives_identical_answers(self) -> None:
        first = FakeModel(GOOD)
        self._enable(first)
        a1 = [self._build().answer(q).text for q, _, _ in H.QUESTIONS]
        second = FakeModel({})          # would return nothing if it were asked
        llm.set_client(second)
        a2 = [self._build().answer(q).text for q, _, _ in H.QUESTIONS]
        self.assertEqual(second.prompts, [])
        self.assertEqual(a1, a2)

    def test_api_failure_keeps_rule_based_facts(self) -> None:
        def broken(prompt):
            raise OSError("network down")
        self._enable(broken)
        self.assertEqual(self._score(self._build()), 1)


if __name__ == "__main__":
    unittest.main()
