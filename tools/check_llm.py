"""Live check of the optional LLM extraction against Gemini, on made-up pages only.

Sends only tests/fixtures/hard_layouts.py (a fictional credit union), never the supplied
snapshots: the allow list is set to that fictional domain for this run.

    GOOGLE_API_KEY=... python3 tools/check_llm.py

Reports: rule-based score, score with Gemini, grounded vs rejected values, whether two fresh
runs of the model agree, and whether a cached rerun makes no calls and matches.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in ("harness", "submission", "tests/fixtures"):
    sys.path.insert(0, str(ROOT / p))

import hard_layouts as H  # noqa: E402
import solution  # noqa: E402
from ksys import llm  # noqa: E402
from ksys.history import key_str  # noqa: E402
from scoring import contains  # noqa: E402


def run(label: str) -> tuple:
    before = dict(llm.STATS)
    ks = solution.build()
    ks.ingest(H.SNAPSHOT)
    ok, lines = 0, []
    for q, want, bad in H.QUESTIONS:
        a = ks.answer(q)
        good = a.confident and contains(a.text, want) and not any(contains(a.text, b) for b in bad)
        ok += good
        lines.append(f"    {'PASS' if good else 'FAIL'}  {q}  ->  {a.text[:90]}")
    facts = sorted(f"{key_str(k)}={w.value} ({w.source})" for k, w in ks.views[H.SNAPSHOT.snapshot_id].items())
    delta = {k: llm.STATS[k] - before[k] for k in llm.STATS}
    print(f"\n== {label}: {ok}/{len(H.QUESTIONS)}  llm {delta}")
    print("\n".join(lines))
    return ok, facts, delta


def main() -> None:
    if not os.environ.get("GOOGLE_API_KEY"):
        sys.exit("set GOOGLE_API_KEY to run the live check")
    print("model:", os.environ.get("KSYS_LLM_MODEL", llm.DEFAULT_MODEL))
    os.environ.pop("KSYS_LLM", None)
    run("rules only")
    os.environ["KSYS_LLM"] = "gemini"
    os.environ["KSYS_LLM_ALLOW_DOMAINS"] = H.DOMAIN
    results = []
    for i in (1, 2):
        with tempfile.TemporaryDirectory() as cache:
            os.environ["KSYS_LLM_CACHE"] = cache
            results.append(run(f"Gemini, fresh cache, run {i}"))
            if i == 2:
                cached = run("Gemini, same cache again (should make no calls)")
    print("\n== summary")
    print("  fresh runs agree on every fact:", results[0][1] == results[1][1])
    print("  cached rerun made no calls:", cached[2]["calls"] == 0, "| matches:", cached[1] == results[1][1])
    if results[0][1] != results[1][1]:
        print("  run 1 only:", sorted(set(results[0][1]) - set(results[1][1])))
        print("  run 2 only:", sorted(set(results[1][1]) - set(results[0][1])))


if __name__ == "__main__":
    main()
