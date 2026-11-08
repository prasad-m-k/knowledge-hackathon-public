"""Dev check for ingest step 6 (resolution and conflicts). Not part of the submission.

    python tools/check_resolve.py [snapshots_dir]

Prints winners for probe keys in each snapshot, conflict counts, and a sample of conflicts.
With harness/selftest/snapshots it also scores conflicts against the self-test gold file.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in ("harness", "submission", "tools"):
    sys.path.insert(0, str(ROOT / p))

from check_boilerplate import load  # noqa: E402
from contract import Conflict, Snapshot, Source  # noqa: E402
from ksys.history import History, key_str  # noqa: E402
from ksys.ingest import Ingestor  # noqa: E402
from ksys.resolve import build_conflicts, resolve_snapshot  # noqa: E402
from scoring import score_conflicts  # noqa: E402

PROBES = ["certificate|-|10mo|fixed+jumbo+special|apy", "certificate|-|17mo|fixed+special|apy",
          "auto_loan|-|60mo|my0|apr", "auto_loan|-|84mo|my0|apr", "checking|st|$5000-25000|apy",
          "mortgage|-|360mo|$0-100000|conventional+fixed+purchase|rate", "credit_card|-|platinum|apr",
          "org_count|branches|count"]


def main() -> None:
    snap_root = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "snapshots"
    ing, hist = Ingestor(), History()
    site = {}
    for d in sorted(p for p in snap_root.iterdir() if (p / "manifest.json").exists()):
        m = json.loads((d / "manifest.json").read_text())
        _, pages = load(d)
        doc = ing.ingest(Snapshot(m["snapshot_id"], m["taken_on"], pages))
        for url, page in site.items():
            doc.pages.setdefault(url, page)
        site = dict(doc.pages)
        hist.add_snapshot(doc)
    views = {sid: resolve_snapshot(hist, sid) for sid, _ in hist.snapshot_order}
    print("== winners per snapshot")
    for probe in PROBES:
        line = []
        for sid, taken in hist.snapshot_order:
            w = next((w for k, w in views[sid].items() if key_str(k) == probe), None)
            line.append(f"{taken[5:]}={w.value if w else '-'}")
        print(f"  {probe:62s} " + "  ".join(line))
    latest_id = hist.snapshot_order[-1][0]
    conflicts = build_conflicts(hist, views[latest_id])
    print(f"\n== conflicts: {len(conflicts)}")
    for c in conflicts[:12]:
        print(f"  {c['topic'][:80]}\n     values={c['values']} -> {c['resolution']}\n     why: {c['reason'][:150]}")
    gold = snap_root.parent / "conflicts_gold.json"
    if not gold.exists():
        gold = ROOT / "eval" / "conflicts_gold.json"
    if gold.exists():
        sub = [Conflict(c["topic"], c["values"], [Source(**s) for s in c["sources"]], c["resolution"], c["reason"])
               for c in conflicts]
        print(f"\n== conflict score ({gold.relative_to(ROOT)}):", score_conflicts(json.loads(gold.read_text()), sub))


if __name__ == "__main__":
    main()
