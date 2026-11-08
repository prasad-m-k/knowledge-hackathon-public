"""Print scorer misses with the system's answers.  python tools/show_misses.py <results_dir>"""
import json
import sys

ev = {json.loads(l)["id"]: json.loads(l) for l in open("eval/public_eval.jsonl") if l.strip()}
for l in open(sys.argv[1] + "/per_question.jsonl"):
    r = json.loads(l)
    if r["score"] < 0.99:
        e = ev[r["id"]]
        print(f"[{r['score']:.2f}] {r['id']} {r['category']} | Q: {e['question'][:90]}\n"
              f"   missed={r['missed']} trap={r['trap_hits']} src={r['source_hit']} exp_src={[s.split('.com')[-1] for s in e['expected_sources']]}\n"
              f"   A({r['answer']['confident']}): {r['answer']['text'][:300]!r}\n"
              f"   from: {[s['url'].split('.com')[-1][:50] for s in r['answer']['sources']][:3]}")
