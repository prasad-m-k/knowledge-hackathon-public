"""Unit and integration test suite for the knowledge system (submission/).

Runs with Python's built-in unittest (no external dependencies required):

    python3 -m unittest discover -s tests -v
"""
from __future__ import annotations

import concurrent.futures as cf
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in ("harness", "submission"):
    if str(ROOT / p) not in sys.path:
        sys.path.insert(0, str(ROOT / p))

from contract import Answer, Conflict, Page, Snapshot  # noqa: E402
import solution  # noqa: E402
from ksys.boilerplate import clean_snapshot, split_blocks  # noqa: E402
from ksys.classify import classify_page, page_type  # noqa: E402
from ksys.config import Config, load_config  # noqa: E402
from ksys.dates import end_of_month, find_dates, first_date, url_date  # noqa: E402
from ksys.extract import extract_page, parse_cell_value, parse_quals  # noqa: E402
from ksys.history import History, key_str  # noqa: E402
from ksys.ingest import Ingestor  # noqa: E402
from ksys.passages import PassageIndex  # noqa: E402
from ksys.question import parse as parse_question  # noqa: E402
from ksys.resolve import build_conflicts, resolve_snapshot  # noqa: E402
from ksys.segment import segment_page  # noqa: E402
from ksys.store import MemoryStore, SQLiteStore, open_store  # noqa: E402
from scoring import contains, score_conflicts  # noqa: E402


class TestDatesAndClassification(unittest.TestCase):
    def test_date_parsing_formats(self) -> None:
        self.assertEqual(first_date("Published July 1, 2025 by Staff"), "2025-07-01")
        self.assertEqual(first_date("Rates are effective as of 08/31/2026."), "2026-08-31")
        self.assertEqual(first_date("Effective 2026-09-25"), "2026-09-25")
        self.assertEqual(end_of_month(2026, 2), "2026-02-28")
        self.assertEqual(end_of_month(2024, 2), "2024-02-29")
        self.assertEqual(url_date("https://example.com/2022/05/14/post"), "2022-05-14")
        self.assertEqual(url_date("https://example.com/hubfs/Visa-Chart-202502.pdf"), "2025-02-28")
        self.assertEqual(find_dates("No dates here"), [])

    def test_page_classification_and_authority(self) -> None:
        blocks = segment_page("# Auto Loan Rates\n\n| Term | APR |\n|---|---|\n| 60 Months | 5.39% APR |\n\nRates are effective as of 08/31/2026.")
        meta_rates = classify_page("https://www.dupaco.com/rates", "Rates | Dupaco", blocks)
        self.assertEqual(meta_rates.page_type, "rate_sheet")
        self.assertEqual(meta_rates.authority, 100)
        self.assertEqual(meta_rates.page_effective, "2026-08-31")

        meta_calc = classify_page("https://www.dupaco.com/calculators/auto", "Calculator", blocks)
        self.assertEqual(meta_calc.page_type, "calculator")
        self.assertLess(meta_calc.authority, 50)

        exp_blocks = segment_page("# Oops! This Offer Has Expired\n\nEarn 3.00% APY.")
        meta_exp = classify_page("https://www.dupaco.com/promo-lp", "Oops... Offer Has Expired", exp_blocks)
        self.assertEqual(meta_exp.page_type, "expired")
        self.assertEqual(meta_exp.authority, 0)

        self.assertEqual(page_type("https://www.dupaco.com/hubfs/terms.pdf", "Terms", []), "legal")
        self.assertEqual(page_type("https://www.dupaco.com/hubfs/sheet.xlsx", "Sheet", []), "document")


class TestBoilerplateAndSegmentation(unittest.TestCase):
    def test_boilerplate_strips_repeated_widgets_and_keeps_tables(self) -> None:
        widget = "Chat with us now! Click here to launch messenger."
        pages = [
            Page(url=f"https://example.com/p{i}", title=f"Page {i}",
                 markdown=f"# Page {i}\n\nUnique paragraph {i}.\n\n{widget}\n\n| Col1 | Col2 |\n|---|---|\n| A | 5.00% |",
                 fetched_at="2026-05-12")
            for i in range(6)
        ]
        cleaned = clean_snapshot(pages)
        for p in cleaned.values():
            self.assertNotIn(widget, p.text)
            self.assertIn("5.00%", p.text)
            self.assertGreaterEqual(p.removed_blocks, 1)

    def test_eyebrow_heading_and_table_caption(self) -> None:
        md = "##### Rates\n\n## Auto & Motorcycle Loans\n\nSpecial Auto Rates\n\n| Term | APR |\n|---|---|\n| 60 Months | 5.39% |"
        blocks = segment_page(md)
        tables = [b for b in blocks if b["kind"] == "table"]
        self.assertEqual(len(tables), 1)
        self.assertEqual(tables[0]["caption"], "Special Auto Rates")
        self.assertIn("Rates / Auto & Motorcycle Loans", tables[0]["path"])


class TestExtractionAndQuestionParsing(unittest.TestCase):
    def test_cell_value_strips_glued_footnotes(self) -> None:
        v1 = parse_cell_value("5.39% APR1")
        self.assertIsNotNone(v1)
        self.assertEqual(v1["value"], "5.39%")
        self.assertEqual(v1["hint"], "apr")
        self.assertEqual(v1["footnote"], "1")

        v2 = parse_cell_value("12.50% – 19.50%2")
        self.assertIsNotNone(v2)
        self.assertEqual(v2["value"], "12.50% – 19.50%")
        self.assertEqual(v2["num"], [12.5, 19.5])
        self.assertEqual(v2["footnote"], "2")

        self.assertIsNone(parse_cell_value("—"))
        self.assertIsNone(parse_cell_value("N/A"))

    def test_parse_qualifiers(self) -> None:
        q = parse_quals("2024-27 Model Year | 60 Months | $10,000 – $24,999.99 | Jumbo Special")
        self.assertEqual(q["term_months"], 60)
        self.assertEqual(q["model_year"], [2024, 2027])
        self.assertEqual(q["amount"], [10000.0, 24999.99])
        self.assertIn("jumbo", q["flags"])
        self.assertIn("special", q["flags"])

        q_rev = parse_quals("Model Year 2026-23 | $100,000 or less")
        self.assertEqual(q_rev["model_year"], [2023, 2026])
        self.assertEqual(q_rev["amount"], [0.0, 100000.0])

    def test_question_parsing(self) -> None:
        q = parse_question("What was the APY on the seventeen-month jumbo CD special as of May 2026?", None)
        self.assertEqual(q.as_of, "2026-05-31")
        self.assertEqual(q.family, "certificate")
        self.assertEqual(q.term_months, 17)
        self.assertEqual(q.metric, "apy")
        self.assertIn("jumbo", q.flags)
        self.assertIn("special", q.flags)

        q2 = parse_question("What's the APR for a 60-month car loan on a 2025 vehicle?", None)
        self.assertEqual(q2.family, "auto_loan")
        self.assertEqual(q2.term_months, 60)
        self.assertEqual(q2.model_year, 2025)
        self.assertEqual(q2.metric, "apr")


class TestPassageIndexAndListCompleteness(unittest.TestCase):
    def test_long_table_and_bullet_list_preserve_all_items(self) -> None:
        rows = "\n".join(f"| Item {i} | ${i * 10}.00 |" for i in range(1, 80))
        bullets = "\n".join(f"- Feature {i}: detailed description of feature number {i} for members." for i in range(1, 20))
        md = f"# Fee Schedule\n\n| Service | Fee |\n|---|---|\n{rows}\n\n# Account Perks\n\n{bullets}"
        s = Snapshot("s1", "2026-09-28", [Page("https://example.com/fees", "Fees & Perks", md, "2026-09-28")])
        ks = solution.build()
        ks.ingest(s)
        idx = ks.indexes["s1"]
        # Late rows past 1500 chars are indexed and searchable
        hits = idx.search(["item", "75"], k=5)
        self.assertTrue(any("Item 75" in p.text for _, p, _ in hits))
        # Multi-item bullet list is not truncated when answering a general question
        ans = ks.answer("What are the Account Perks features?")
        self.assertIn("Feature 1", ans.text)
        self.assertIn("Feature 15", ans.text)


class TestStoreAndProductionResilience(unittest.TestCase):
    def test_sqlite_and_memory_store_parity_and_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "sub" / "cache.sqlite3"
            store = open_store(Config(cache_backend="sqlite", cache_path=db_path))
            self.assertIsInstance(store, SQLiteStore)
            store.put("ns", "k1", {"a": [1, 2, 3]})
            store.flush()
            self.assertEqual(store.get("ns", "k1"), {"a": [1, 2, 3]})
            store.close()

            # Reopen and verify persistence
            store2 = open_store(Config(cache_backend="sqlite", cache_path=db_path))
            self.assertEqual(store2.get("ns", "k1"), {"a": [1, 2, 3]})
            store2.close()

            # Unwritable path falls back gracefully to MemoryStore
            bad_path = Path(tmp) / "cache.sqlite3"
            bad_path.write_text("not a directory")
            fallback = open_store(Config(cache_backend="sqlite", cache_path=bad_path / "nested.db"))
            self.assertIsInstance(fallback, MemoryStore)

    def test_edge_inputs_and_idempotent_reingest(self) -> None:
        ks = solution.build()
        self.assertEqual(ks.health()["status"], "empty")
        # Answering before any snapshot is ingested returns an honest refusal
        ans_empty = ks.answer("What are your mortgage rates?")
        self.assertFalse(ans_empty.confident)

        # Empty or whitespace question returns refusal with no numbers
        ans_blank = ks.answer("   ")
        self.assertFalse(ans_blank.confident)

        s1 = Snapshot("s1", "2026-05-12", [
            Page("https://example.com/rates", "Rates",
                 "Certificate Rates\n\n| Certificate | APY |\n|---|---|\n| 6-Month Certificate | 2.95% |\n\nRates are effective as of 05/01/2026.",
                 "2026-05-12"),
        ])
        ks.ingest(s1)
        obs_count = len(ks.history.log)
        # Re-ingesting the same snapshot is idempotent and does not duplicate observations
        ks.ingest(s1)
        self.assertEqual(len(ks.history.log), obs_count)
        self.assertEqual(ks.health()["snapshots_ingested"], 1)

    def test_thread_safe_concurrent_answers(self) -> None:
        selftest_dir = ROOT / "harness" / "selftest" / "snapshots"
        ks = solution.build()
        for d in sorted(p for p in selftest_dir.iterdir() if (p / "manifest.json").exists()):
            m = json.loads((d / "manifest.json").read_text())
            pages = [Page(p["url"], p.get("title", ""), (d / p["file"]).read_text(), p.get("fetched_at", m["taken_on"]))
                     for p in m["pages"]]
            ks.ingest(Snapshot(m["snapshot_id"], m["taken_on"], pages))

        questions = [
            ("What is the 6-month certificate APY?", None),
            ("What was the 6-month certificate APY in January 2026?", "2026-01-31"),
            ("How much is a lost debit card replacement?", None),
            ("What is the 60-month jumbo certificate rate?", None),
        ] * 5

        with cf.ThreadPoolExecutor(max_workers=4) as pool:
            futures = [pool.submit(ks.answer, q, as_of) for q, as_of in questions]
            results = [f.result(timeout=10) for f in futures]

        self.assertEqual(len(results), len(questions))
        self.assertTrue(contains(results[0].text, "3.50%"))
        self.assertTrue(contains(results[1].text, "2.95%"))
        self.assertTrue(contains(results[2].text, "$2.50"))
        self.assertFalse(results[3].confident)

        gold = json.loads((ROOT / "harness" / "selftest" / "conflicts_gold.json").read_text())
        c_score = score_conflicts(gold, ks.conflicts())
        self.assertEqual(c_score["f1"], 1.0)
        self.assertEqual(c_score["resolution_accuracy"], 1.0)
        ks.close()


if __name__ == "__main__":
    unittest.main()
