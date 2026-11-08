"""Dev check: reworded versions of the practice questions, scored against the original
expected tokens (the hidden set rewords questions). Not part of the submission.

    python tools/check_paraphrases.py
"""
import sys, json
from pathlib import Path
root = Path(__file__).resolve().parents[1]; sys.path[:0] = [str(root/'harness'), str(root/'submission'), str(root/'tools')]
from check_boilerplate import load
from contract import Snapshot
from scoring import contains
import solution
ks = solution.build()
for d in sorted((root/'snapshots').glob('0*')):
    m = json.loads((d/'manifest.json').read_text()); _, pages = load(d)
    ks.ingest(Snapshot(m['snapshot_id'], m['taken_on'], pages))
ev = {json.loads(l)['id']: json.loads(l) for l in open(root/'eval/public_eval.jsonl')}
P = [
 ("dup-001", "How much does the seventeen month certificate special yield?", None),
 ("dup-001", "17 month CD special APY?", None),
 ("dup-016", "I'm buying a 2025 car with a 60 month loan, what's the APR?", None),
 ("dup-017", "APR on an 84 month car loan for a 2024 model year", None),
 ("dup-009", "30 year fixed mortgage interest rate?", None),
 ("dup-045", "Share Savings dividend rate if I keep $15,000 in it?", None),
 ("dup-028", "personal loan APR for three years (36 months)?", None),
 ("dup-035", "Platinum Visa purchase APR?", None),
 ("dup-050", "Bright Savings APY?", None),
 ("dup-052", "What does 1st Rate Checking pay?", None),
 ("dup-006", "10 month jumbo certificate special rate in May 2026?", None),
 ("dup-006", "What was the 10-month jumbo special APY?", "2026-05-20"),
 ("dup-054", "Dupaco ABA routing number?", None),
 ("dup-073", "How many branch locations does Dupaco have?", None),
 ("dup-074", "When will the Hy-Vee branch close?", None),
 ("dup-068", "Galena branch address?", None),
 ("dup-066", "When is the drive-up open?", None),
 ("dup-094", "Does Dupaco support Apple Pay or Google Pay?", None),
 ("dup-082", "Can I join Dupaco online? What's the link?", None),
 ("dup-145", "Do you offer a 5/1 ARM? What is the rate?", None),
 ("dup-147", "Rate for a commercial construction loan?", None),
 ("dup-102", "What time does the Mullan Avenue branch lobby open?", None),
]
ok = 0
for gid, q, as_of in P:
    e = ev[gid]; a = ks.answer(q, as_of); t = a.text
    if e['category'] == 'should_refuse':
        good = not a.confident
    else:
        good = all(contains(t, m) for m in e['must_include']) and not any(contains(t, m) for m in e['must_not_include'])
    ok += good
    print('OK ' if good else 'BAD', gid, '|', q, '\n     ->', repr(t[:160]))
print(f'{ok}/{len(P)}')
