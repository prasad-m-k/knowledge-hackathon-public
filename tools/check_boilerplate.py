"""Dev check for ingest step 1 (boilerplate stripping). Not part of the submission.

    python tools/check_boilerplate.py [snapshots_dir]
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "harness"))
sys.path.insert(0, str(ROOT / "submission"))

from contract import Page  # noqa: E402
from ksys.boilerplate import clean_snapshot, is_table, split_blocks  # noqa: E402

PCT = re.compile(r"\d+\.\d+\s*%")


def load(folder: Path):
    m = json.loads((folder / "manifest.json").read_text())
    return m["taken_on"], [Page(p["url"], p.get("title", ""), (folder / p["file"]).read_text(encoding="utf-8"),
                                p.get("fetched_at", m["taken_on"])) for p in m["pages"]]


def main() -> None:
    snap_root = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "snapshots"
    prev_raw, prev_clean = {}, {}
    failures = 0
    for d in sorted(p for p in snap_root.iterdir() if (p / "manifest.json").exists()):
        taken_on, pages = load(d)
        clean = clean_snapshot(pages)
        raw_chars = sum(len(p.markdown) for p in pages)
        clean_chars = sum(len(c.text) for c in clean.values())
        tables_raw = sum(sum(is_table(b) for b in split_blocks(p.markdown)) for p in pages)
        tables_clean = sum(sum(is_table(b) for b in split_blocks(c.text)) for c in clean.values())
        raw_same = sum(1 for p in pages if prev_raw.get(p.url) == p.markdown)
        clean_same = sum(1 for u, c in clean.items() if prev_clean.get(u) == c.content_hash)
        print(f"{d.name}: pages={len(pages)} size {raw_chars:,} -> {clean_chars:,} "
              f"({100 * clean_chars / max(1, raw_chars):.0f}%) tables {tables_raw}->{tables_clean} "
              f"unchanged vs prev: raw={raw_same} clean={clean_same}")
        if tables_raw != tables_clean:
            failures += 1
            print("  FAIL: a table was dropped")
        prev_raw = {p.url: p.markdown for p in pages}
        prev_clean = {u: c.content_hash for u, c in clean.items()}
        last = (pages, clean)

    pages, clean = last
    for p in pages:
        u = p.url.rstrip("/")
        if u.endswith("/personal/loans/auto-loans") or "/learn/blog/how-to-refinance-your-auto-loan" in u:
            t = clean[p.url].text
            print(f"\n== {p.url}\n   handpicked kept: {'Handpicked' in t}  form kept: {'First Name' in t}  "
                  f"rates in text: {sorted(set(PCT.findall(t)))[:8]}")
            print("   head:", " | ".join(t.splitlines()[:4])[:200])
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
