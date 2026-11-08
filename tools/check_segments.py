"""Dev check for ingest step 2 (segmentation). Not part of the submission.

    python tools/check_segments.py [snapshots_dir]

Set KSYS_CONFIG to a config file to exercise the SQLite cache (run twice: the second run
should segment nothing).
"""
from __future__ import annotations

import collections
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "harness"))
sys.path.insert(0, str(ROOT / "submission"))
sys.path.insert(0, str(ROOT / "tools"))

from check_boilerplate import load  # noqa: E402
from contract import Snapshot  # noqa: E402
from ksys.ingest import Ingestor  # noqa: E402

WATCH = ("/personal/loans/auto-loans", "/business/rates", "/learn/blog/how-to-refinance-your-auto-loan")


def main() -> None:
    snap_root = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "snapshots"
    ing = Ingestor()
    print("store backend:", ing.store.backend)
    t0 = time.time()
    for d in sorted(p for p in snap_root.iterdir() if (p / "manifest.json").exists()):
        import json
        m = json.loads((d / "manifest.json").read_text())
        _, pages = load(d)
        doc = ing.ingest(Snapshot(m["snapshot_id"], m["taken_on"], pages))
        kinds = collections.Counter(b["kind"] for p in doc.pages.values() for b in p.blocks)
        tables = [b for p in doc.pages.values() for b in p.blocks if b["kind"] == "table"]
        bad = [b for b in tables if b["header"] and any(len(r) != len(b["header"]) for r in b["rows"])]
        print(f"{d.name}: {doc.stats} blocks={dict(kinds)} tables_with_ragged_rows={len(bad)}")
    print(f"total ingest {time.time() - t0:.1f}s")

    last = ing.snapshots[-1]
    for url, p in last.pages.items():
        if any(w in url for w in WATCH):
            print(f"\n== {url}  ({len(p.blocks)} blocks)")
            for b in p.blocks:
                if b["kind"] == "table":
                    print(f"  TABLE path={b['path']} caption={b.get('caption')!r}\n        header={b['header']}"
                          f"\n        row0={b['rows'][0] if b['rows'] else None}")
            print("  first blocks:")
            for b in p.blocks[:6]:
                print(f"   [{b['kind']}] {' > '.join(b['path']) or '(top)'} :: {b['text'][:80]!r}")


if __name__ == "__main__":
    main()
