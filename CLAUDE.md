# CLAUDE.md: Knowledge Hackathon ("a knowledge system that knows what's true now")

Source of truth: `Knowledge-Hackathon-Assignment.pdf`, `README.md`, `harness/contract.py`, `harness/scoring.py`, `harness/run_eval.py`. If anything below disagrees with those files, the files win; fix this document.

## 1. The task in one paragraph

Build a Python `solution.py` exposing `build()`. It returns an object with exactly three methods: `ingest(snapshot)`, `answer(question, as_of=None)`, `conflicts()`. The data is five crawls of a credit union's website (Dupaco, dupaco.com) taken May to Sep 2026. Pages contradict each other across and within snapshots. Answers must give the **current** value, the **right tier**, a **source URL**, and an honest refusal when the site does not say. Graded on a larger hidden question set with the same scorer.

## 2. Repository layout

```text
Knowledge-Hackathon-Assignment.pdf   assignment brief (do not edit)
README.md                            kit README (do not edit)
harness/                             organizer scorer. NEVER modify (graders use their own copy)
  contract.py                        Page, Snapshot, Source, Answer, Conflict, KnowledgeSystem
  run_eval.py                        loads snapshots, plugs in submission, scores
  scoring.py                         exact scoring rules (read before tuning)
  selftest/                          tiny fixture: 2 snapshots, eval.jsonl, conflicts_gold.json
eval/public_eval.jsonl               40 practice questions. NEVER modify
snapshots_zip/                       5 zips, oldest first (auto-unpacked by the scorer)
snapshots/                           unpacked folders (gitignored: snapshots/0*/)
starter/solution.py                  naive baseline (~0.09). Do NOT put the submission here
submission/                          OUR SOLUTION LIVES HERE
  solution.py                        build() + the three methods
  requirements.txt                   every non-stdlib package (installed in clean Python 3.11)
  NOTES.md                           approach, "what is current" rules, API keys needed
```

The submission may live in any folder except `starter/`. Use `submission/`.

## 3. The contract (exact, do not rename anything)

Import the contract the same way the starter does, so the folder works when the graders plug it in:

```python
import sys
from pathlib import Path
sys.path.insert(0, str(next(d / "harness" for d in Path(__file__).resolve().parents
                            if (d / "harness" / "contract.py").exists())))
from contract import Answer, Conflict, Snapshot, Source
```

Types (from `harness/contract.py`):

- `Page(url, title, markdown, fetched_at)` frozen
- `Snapshot(snapshot_id, taken_on, pages)` frozen; `taken_on` is ISO date; `pages` is the FULL site as of that pull
- `Source(url, snapshot_id=None, quote=None)`
- `Answer(text, sources=[], confident=True, conflict_note=None)`; `confident=False` means "I don't know / please contact us"
- `Conflict(topic, values, sources, resolution=None, reason=None)`

Harness call order: `ks = build()`; `ks.ingest(s)` for each snapshot sorted by `taken_on` ascending; `ks.answer(q, as_of=q.as_of)` per question (single worker thread, 60 s hard timeout each); repeat pass on a sample of ~20 questions; then `ks.conflicts()` (only scored when `--conflicts-gold` is passed, which graders do).

`as_of=None` means answer from the latest snapshot (`05_2026-09-28_latest`). `as_of="YYYY-MM-DD"` means answer from the newest snapshot with `taken_on <= as_of`.

## 4. How scoring actually works (from `harness/scoring.py`)

Final score = weighted pillars: accuracy 0.55, conflicts 0.15, consistency 0.15, speed 0.15. Consistency and speed are multiplied by accuracy.

Per question item score = `0.85 * correctness + 0.15 * source_hit` (source term only when `expected_sources` is non-empty). Items are weighted by their `weight` field (1.0 to 2.0; hard/trap items weigh more).

- **correctness** = fraction of `must_include` tokens found in `answer.text`.
- **trap**: if ANY `must_not_include` token appears in `answer.text`, correctness becomes 0. Listing every number you found is a guaranteed zero.
- Numeric tokens that are pure numbers/rates (e.g. `"3.90%"`, `"$2.50"`, `"7.13"`, `"5.39% APR"`, at most 20 chars) match **by value and unit**: `3.9%` == `3.90 %`. A bare number token (`"7.13"`) matches any unit. Tokens with other words (`"24 branch"`, `"March 31, 2026"`, `"Apple Pay"`) match as normalized case-insensitive substrings (`a.m.` becomes `am`, en/em dash becomes `-`, whitespace collapsed).
- **should_refuse** items: full credit only if the answer is a refusal (`confident=False` OR text matches the refusal regex) AND the text contains **no numbers** beyond those already in the question. A refusal must not mention any rate, phone number, address number, or year that is not in the question. Safe refusal text: `"That isn't listed on our website. Please contact us for details."` with `confident=False`.
- Refusal regex phrases: "I don't know", "I can't find", "I cannot confirm", "not sure", "not able to confirm", "no longer available/offered", "isn't listed", "is not listed", "please contact/call/visit", "no information". Do NOT use these phrases in a normal confident answer for a non-refusal item unless intended; they do not zero correctness, but keep answers clean.
- **source_hit**: any cited URL matches an expected URL at path level (host lowercased, `www.` stripped, trailing `/` stripped; fragments like `#rates` and query strings are ignored). Always cite the authoritative product/rate page URL first.
- **consistency**: (a) paraphrase groups (`group` field): pass if all members are fully correct OR all members produce the identical set of numeric values; (b) repeat pass: same question again must produce the identical set of numbers. So answers must be deterministic: no randomness, no temperature > 0, no time-dependent text, no varying number of examples. If an LLM is used, cache by normalized question and use temperature 0.
- **speed**: p95 latency over answers. <= 2 s is full marks, linear to 0 at 20 s. Target p95 well under 2 s. Do heavy work in `ingest` (untimed for scoring, but total ingest must finish within 30 minutes).
- **conflicts**: gold entry `{id, topic_keywords, values, correct_value}`. A submitted conflict matches if its `values` (joined) contain >= 2 gold values, or >= 1 gold value plus a topic keyword appearing in `topic`. Each submitted conflict can match at most one gold entry. Score = `0.7 * F1 + 0.3 * resolution_accuracy` (resolution matches `correct_value` by value). Precision counts, so do NOT dump thousands of noisy conflicts; report real contradictions (same fact, same qualifiers, different values) with clear topics that include product name and term (e.g. "10-month jumbo certificate APY") and `resolution` set to the winning value.

Eval item fields: `id, question, as_of, expected_answer, must_include, must_not_include, category, difficulty, weight, expected_sources, group`.

Public categories (40 items): stale_trap 7, tier_disambiguation 6, branch_info 6, list_completeness 4, entity_attribution 4, temporal_as_of 4, conflict_resolution 3, current_value 3, should_refuse 3. The hidden set adds rewordings, more `as_of` questions, and questions about things that changed between snapshots.

## 5. The snapshots

| Folder | Date | Notes |
|---|---|---|
| `01_2026-05-12_baseline` | 2026-05-12 | ~637 pages, starting point |
| `02_2026-05-19_recrawl` | 2026-05-19 | nearly every page changed; most new contradictions |
| `03_2026-06-09_recrawl` | 2026-06-09 | rates moved again |
| `04_2026-08-27_rebaseline` | 2026-08-27 | after 10-week gap, ~50 new pages |
| `05_2026-09-28_latest` | 2026-09-28 | "current" means this one |

Each folder: `manifest.json` (`snapshot_id`, `taken_on`, `label`, `description`, `pages[]` with `file`, `url`, `title`, `fetched_at`) and `pages/*.md`. Unpack once with `python harness/run_eval.py --submission starter --eval eval/public_eval.jsonl`. Known mess: old pages still showing old rates, stale calculators, ended promos never removed, rate vs APY on different pages, tiered tables (balance, term, loan amount, model year), old press releases/blogs with historical counts, offers and hours, pages only present in some snapshots.

## 6. Required behaviour of the solution

1. **Keep full history.** Store every fact with `(snapshot_id, taken_on, url, page type, qualifiers, value, quote)`. Never overwrite with only the latest copy; `as_of` needs earlier states.
2. **Resolve `as_of`.** Use the `as_of` argument when given. ALSO parse dates inside the question text ("as of May 2026", "in June", "today (October 2026)"). A month-only date maps to the end of that month (May 2026 -> 2026-05-31, so the 05-19 snapshot). A date after the latest snapshot means latest. A date before the first snapshot: use the earliest snapshot or refuse if the fact did not exist.
3. **Source authority ranking** (write the final rules into NOTES.md): official rate pages / rate tables (`/rates`, product pages with "effective" dates) > product pages > FAQ/disclosure pages > calculators > blog posts, news, press releases, newsletters, events. Newer snapshot beats older for the same authoritative page. A stale calculator or old blog never overrides a current rate page (e.g. 60-month auto 5.39% from the rate page, not 5.34% from the affordability calculator).
4. **Respect qualifiers as separate facts**: term (6/10/12/17/48/60-month), rate vs APR vs APY, standard vs jumbo vs special, balance tiers, loan-amount tiers ($100k vs $300k mortgage tier), model year, personal vs business, product name (e.g. "Platinum Visa" vs "Business Platinum"). Different qualifiers are NOT conflicts.
5. **Default tier**: when the question does not name a tier, lead with the base/standard tier (lowest minimum balance, base loan amount, e.g. the $100k mortgage tier) and may add other tiers only if none of them is a stale/trap value. Never mention a value from an older snapshot or a non-authoritative page in the answer text.
6. **Answer text discipline**: put only current, correct values in `text`. Do not echo history ("it used to be 3.90%"), because any stale number in the text zeroes the item. Put the explanation in `conflict_note` instead (conflict_note is not scored for traps, `text` is).
7. **Lists**: for "what X do you offer" questions, enumerate all current items with their values (e.g. all four credit cards with APR ranges; Apple Pay, Google Pay, Samsung Pay).
8. **Never ask a clarifying question.** Eval traps include "Which certificate term would you like". Answer with the full current table or the default tier instead.
9. **Ignore conversational noise** in the question ("I'm not asking again", "after a couple of tries"); never repeat it back.
10. **Refuse honestly** when the site has no answer (e.g. 7/1 ARM rate, construction loan rate, lobby hours for a branch the site does not list). Return `confident=False`, a refusal phrase, and no numbers.
11. **Entity attribution**: answer about the entity asked (Dupaco, the specific branch, the specific product). Do not attribute a partner's or another branch's data.
12. **Branch info**: closures and dates (e.g. Hy-Vee branch closed March 31, 2026), hours, current branch count (22, not "24 branch" from old pages). Old counts in press releases are traps.
13. **Determinism and speed**: same input, same output, every time. Precompute indexes in `ingest`. No network calls to the live website, ever. If using an LLM API, it must be optional or documented in NOTES.md, deterministic (temperature 0, cached), and fit inside the 2 s p95 target; a fully offline path is preferred.
14. **conflicts()**: return one entry per real contradiction (same fact and qualifiers, different values) across or within snapshots, with all competing values, a source per value, `resolution` = the value believed correct as of the latest snapshot, and `reason` (newer snapshot, authoritative rate page, stale calculator, expired promo, old press release).

## 7. Hard rules

- Never edit `harness/`, `eval/`, `snapshots_zip/`, `starter/`, the PDF or the kit README.
- Never hard-code answers to the 40 public questions or match on their exact wording. The hidden set rewords them. General rules and extraction only.
- Answer only from the provided snapshots. No live website calls.
- Each `answer()` call < 60 s (hard), aim for < 2 s p95. Ingest of all five snapshots < 30 min.
- `requirements.txt` must list every non-stdlib package; target Python 3.11 (code must also run on 3.9+; avoid 3.12+ only syntax).
- The data is a real credit union's website shared for this event only. Do not redistribute it; keep the GitHub repo **private** and share read access only with organizers.

## 8. Commands

```bash
# score our submission on the public set (unpacks snapshots on first run)
python harness/run_eval.py --submission submission --eval eval/public_eval.jsonl --out results/sub

# harness self-test fixture (includes a conflicts gold file)
python harness/run_eval.py --submission submission --snapshots harness/selftest/snapshots \
  --eval harness/selftest/eval.jsonl --conflicts-gold harness/selftest/conflicts_gold.json --out results/selftest

# baseline for comparison (~0.09)
python harness/run_eval.py --submission starter --eval eval/public_eval.jsonl --out results/starter
```

After each run read `results/<name>/per_question.jsonl`: inspect `missed`, `trap_hits`, `source_hit`, `latency_s`, and `error` for every item below 1.0. Improve rules for the failure class, not the single question.

## 9. Submission checklist

- [ ] `submission/solution.py` with `build()` returning an object with `ingest`, `answer`, `conflicts`
- [ ] `submission/requirements.txt` (empty file is fine if stdlib only)
- [ ] `submission/NOTES.md`: a few paragraphs on the approach, how "current" is decided (authority ranking, recency, as_of, tiers), and which API keys are needed (state "none" if none; flag any paid API)
- [ ] From a fresh clone: `python harness/run_eval.py --submission submission --eval eval/public_eval.jsonl` runs cleanly with 0 errors
- [ ] Repo pushed, private, organizers given read access
- [ ] Share repo URL and the commit SHA to be graded before the deadline (TBA)

## 10. Writing style for NOTES.md and commit messages

No em dashes. Plain, human prose. Author byline: Prasad MK.
