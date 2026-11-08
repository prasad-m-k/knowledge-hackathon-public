"""Dev check for ingest step 4 (fact extraction). Not part of the submission.

    python tools/check_extract.py [snapshots_dir]

Prints fact counts, then probes: for a few product/qualifier filters, every value found in the
latest snapshot with its page type, so current values and stale traps can be compared by eye.
"""
from __future__ import annotations

import collections
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in ("harness", "submission", "tools"):
    sys.path.insert(0, str(ROOT / p))

from check_boilerplate import load  # noqa: E402
from contract import Snapshot  # noqa: E402
from ksys.ingest import Ingestor  # noqa: E402

PROBES = [
    ("17-month special certificate APY", lambda f: "certificate" in f["product_key"] + f["label"].lower()
     and f["quals"].get("term_months") == 17 and f["metric"] == "apy"),
    ("10-month jumbo special APY", lambda f: f["quals"].get("term_months") == 10 and "jumbo" in f["quals"].get("flags", [])
     and f["metric"] == "apy"),
    ("60-month auto APR, model year 2025", lambda f: f["quals"].get("term_months") == 60 and f["metric"] == "apr"
     and (f["quals"].get("model_year") or [0, 0])[0] <= 2025 <= (f["quals"].get("model_year") or [0, 0])[1]),
    ("84-month auto APR (any source)", lambda f: f["quals"].get("term_months") == 84 and f["metric"] in ("apr", "rate")
     and "auto" in (f["product_key"] + f.get("context", "").lower() + f["quote"].lower())),
    ("Share Savings rate, tier incl. $15,000", lambda f: f["product_key"].endswith("share savings") and f["metric"] == "rate"
     and (f["quals"].get("amount") or [None])[0] is not None and f["quals"]["amount"][0] <= 15000
     <= (f["quals"]["amount"][1] or 1e18)),
    ("Platinum Visa APR", lambda f: "platinum" in (f["product_key"] + " " + f["label"].lower()) and f["metric"] in ("apr", "rate")),
    ("36-month personal loan APR", lambda f: f["product_key"] == "personal loan" and f["quals"].get("term_months") == 36),
    ("30-year mortgage rate", lambda f: f["quals"].get("term_months") == 360 and f["metric"] == "rate"),
    ("branch counts", lambda f: f["metric"] == "count" and "branch" in f["product"]),
]


def main() -> None:
    snap_root = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "snapshots"
    ing = Ingestor()
    t0 = time.time()
    for d in sorted(p for p in snap_root.iterdir() if (p / "manifest.json").exists()):
        m = json.loads((d / "manifest.json").read_text())
        _, pages = load(d)
        doc = ing.ingest(Snapshot(m["snapshot_id"], m["taken_on"], pages))
        c = collections.Counter((f["source"], f["metric"]) for p in doc.pages.values() for f in p.facts)
        print(f"{d.name}: facts={sum(c.values())} " + " ".join(f"{s}/{k}={n}" for (s, k), n in sorted(c.items())))
    print(f"ingest {time.time() - t0:.1f}s")
    last = ing.snapshots[-1]
    for name, pred in PROBES:
        hits = collections.Counter()
        for u, p in last.pages.items():
            for f in p.facts:
                try:
                    ok = pred(f)
                except (TypeError, KeyError):
                    ok = False
                if ok:
                    hits[(f["value"], p.meta.page_type, f["source"])] += 1
        print(f"\n== {name}")
        for (val, pt, src), n in sorted(hits.items(), key=lambda kv: (-{"rate_sheet": 9, "product": 8}.get(kv[0][1], 0), kv[0])):
            print(f"   {val:18s} {pt:10s} {src:6s} x{n}")


if __name__ == "__main__":
    main()
