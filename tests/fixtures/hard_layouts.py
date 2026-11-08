"""A made-up credit union site ("Riverbend Credit Union") whose rate pages use layouts that
rule-based extraction handles badly, with the correct answer for each question.

Used by tests/test_llm_extract.py and tools/check_llm.py. Nothing here comes from the supplied
snapshots, so this content may be sent to an LLM API for testing.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "harness") not in sys.path:
    sys.path.insert(0, str(ROOT / "harness"))
from contract import Page, Snapshot  # noqa: E402

HOST = "https://www.riverbendcu.org"
DOMAIN = "riverbendcu.org"
TAKEN = "2026-09-28"


def _page(path: str, title: str, md: str) -> Page:
    return Page(f"{HOST}{path}", f"{title} | Riverbend Credit Union", md, TAKEN)


PAGES = [
    _page("/", "Home", "# Welcome to Riverbend\n\nRiverbend Credit Union serves the Ohio Valley."),
    # Several products in one sentence: rules credit every rate to the section heading.
    _page("/personal/savings", "Savings Accounts",
          "# Savings Accounts\n\nPick the account that fits your goal. Holiday Club Savings earns 1.25% APY, "
          "Youth Savings earns 2.00% APY for members under 18, and a Health Savings Account earns 0.50% APY. "
          "All three can be opened online with $5.\n\nRates updated September 1, 2026."),
    # Product cards: each value sits on its own line under a label, no table.
    _page("/personal/certificates", "Certificates",
          "# Share Certificates\n\nLock in a rate for the term you choose.\n\n"
          "### 6-Month Certificate\n\nAnnual Percentage Yield\n\n2.90%\n\nMinimum deposit\n\n$500\n\n"
          "### 24-Month Certificate\n\nAnnual Percentage Yield\n\n3.15%\n\nMinimum deposit\n\n$500\n\n"
          "Rates updated September 1, 2026."),
    # A range, an intro rate and a fee in one sentence about one card.
    _page("/personal/credit-cards/visa-platinum", "Visa Platinum",
          "# Visa Platinum\n\nOur lowest-rate card. The purchase APR is 11.99% to 17.99% based on credit, balance "
          "transfers are 2.99% APR for the first 12 months, and there is no annual fee."),
    _page("/contact", "Contact", "# Contact Us\n\nCall 800-555-0142 or visit any branch."),
]
SNAPSHOT = Snapshot("rb-hard", TAKEN, PAGES)

# (question, value that must appear, values that must not appear)
QUESTIONS = [
    ("What is the Holiday Club Savings APY?", "1.25%", ["2.00%", "0.50%"]),
    ("What APY does Youth Savings earn?", "2.00%", ["1.25%", "0.50%"]),
    ("What is the Health Savings Account APY?", "0.50%", ["1.25%", "2.00%"]),
    ("What is the 6-month certificate APY?", "2.90%", ["3.15%"]),
    ("What is the 24-month certificate APY?", "3.15%", ["2.90%"]),
    ("What is the purchase APR on the Visa Platinum card?", "11.99%", ["2.99%"]),
    ("What is the balance transfer APR on the Visa Platinum?", "2.99%", ["11.99%"]),
]
