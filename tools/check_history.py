"""Dev check for ingest step 5 (fact keys, observation log, versions). Not part of the submission.

    python tools/check_history.py [snapshots_dir] [key-substring ...]

Prints key statistics, keys whose values differ across pages or snapshots (conflict candidates),
and timelines for tracked keys.
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
from ksys.history import History, key_str  # noqa: E402
from ksys.ingest import Ingestor  # noqa: E402

TRACK = ["certificate|-|17mo", "certificate|-|10mo", "auto_loan|-|60mo|my0", "auto_loan|-|84mo|my0",
         "savings|-|$10000-24999.99|share|rate", "credit_card|-|platinum|apr", "personal_loan|-|36mo",
         "mortgage|-|360mo|$0-100000|conventional+fixed+purchase|rate"]


def main() -> None:
    args = sys.argv[1:]
    snap_root = Path(args[0]) if args and Path(args[0]).is_dir() else ROOT / "snapshots"
    track = [a for a in args if not Path(a).is_dir()] or TRACK
    ing, hist = Ingestor(), History()
    t0 = time.time()
    for d in sorted(p for p in snap_root.iterdir() if (p / "manifest.json").exists()):
        m = json.loads((d / "manifest.json").read_text())
        _, pages = load(d)
        doc = ing.ingest(Snapshot(m["snapshot_id"], m["taken_on"], pages))
        n = hist.add_snapshot(doc)
        print(f"{d.name}: observations +{n}")
    print(f"ingest+history {time.time() - t0:.1f}s; log={len(hist.log)} unkeyed facts={hist.unkeyed}")

    last = hist.snapshot_order[-1][0]
    bk = hist.by_key(last)
    fams = collections.Counter(k[0] for k in bk)
    print(f"keys in latest snapshot: {len(bk)} by family {dict(fams.most_common())}")
    rateish = {"apy", "apr", "rate"}
    multi = {k: obs for k, obs in bk.items() if k[3] in rateish and len({o.value for o in obs}) > 1
             and any(o.source == "table" for o in obs)}
    print(f"rate keys with >1 value in latest snapshot (table-backed): {len(multi)}")
    for k, obs in sorted(multi.items(), key=lambda kv: key_str(kv[0]))[:25]:
        vals = collections.defaultdict(set)
        for o in obs:
            vals[o.value].add(o.page_type)
        print(f"   {key_str(k):70s} " + "  ".join(f"{v}[{','.join(sorted(t))}]" for v, t in sorted(vals.items())))

    vers = hist.versions()
    print("\n== timelines")
    for t in track:
        for k in sorted((k for k in vers if key_str(k).startswith(t)), key=key_str)[:3]:
            print(f"  {key_str(k)}")
            for url, vs in sorted(vers[k].items()):
                path = url.split(".com")[-1][:44]
                print(f"     {path:44s} " + "  ".join(f"{v.value}@{v.first_taken_on[5:]}..{v.last_taken_on[5:]}"
                                                    for v in vs))


if __name__ == "__main__":
    main()
