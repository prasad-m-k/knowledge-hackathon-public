"""Dev check for ingest step 3 (page classification and dates). Not part of the submission.

    python tools/check_classify.py [snapshots_dir]
"""
from __future__ import annotations

import collections
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in ("harness", "submission", "tools"):
    sys.path.insert(0, str(ROOT / p))

from check_boilerplate import load  # noqa: E402
from contract import Snapshot  # noqa: E402
from ksys.ingest import Ingestor  # noqa: E402

TRACK = ("/rates", "/business-rates", "/personal/loans/auto-loans", "/personal/loans/auto-motorcycle-loans",
         "/personal/loans/home-loans", "/personal/credit-cards", "/learn/master-your-money/homeownership")


def main() -> None:
    snap_root = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "snapshots"
    ing = Ingestor()
    for d in sorted(p for p in snap_root.iterdir() if (p / "manifest.json").exists()):
        m = json.loads((d / "manifest.json").read_text())
        _, pages = load(d)
        ing.ingest(Snapshot(m["snapshot_id"], m["taken_on"], pages))

    last = ing.snapshots[-1]
    types = collections.defaultdict(list)
    for u, p in sorted(last.pages.items()):
        types[p.meta.page_type].append(u)
    print(f"== page types in {last.snapshot_id}")
    for t, us in sorted(types.items(), key=lambda kv: -len(kv[1])):
        print(f"  {t:11s} {len(us):4d}  e.g. {', '.join(x.split('dupaco.com')[-1][:45] for x in us[:3])}")
    for t in ("blog", "news"):
        n = sum(1 for u in types[t] if last.pages[u].meta.published)
        print(f"  {t}: published date found on {n}/{len(types[t])}")
    print("  expired:", [u.split('dupaco.com')[-1] for u in types["expired"]])
    print("  limited_time:", [u.split('dupaco.com')[-1] for u, p in last.pages.items() if p.meta.limited_time][:8])
    print("  url_date:", sorted({(u.split('dupaco.com')[-1][:50], p.meta.url_date) for u, p in last.pages.items() if p.meta.url_date})[:8])

    print("\n== effective dates per table, across snapshots")
    for s in ing.snapshots:
        for u, p in sorted(s.pages.items()):
            path = u.split("dupaco.com")[-1].rstrip("/")
            if path in TRACK:
                eff = {p.blocks[i].get("caption") or p.blocks[i]["header"][:1][0] if p.blocks[i]["header"] else i: e
                       for i, e in p.meta.effective.items()}
                print(f"  {s.taken_on} {p.meta.page_type:10s} {path:42s} {eff}")


if __name__ == "__main__":
    main()
