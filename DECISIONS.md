# Project Decisions

A running log of design decisions for the knowledge hackathon solution. Newest entries go at the bottom. Never delete an entry: if a decision changes, mark the old one `Superseded by D-xxx` and add a new entry.

Status values: `Accepted`, `Proposed`, `Open`, `Superseded by D-xxx`.

| ID | Date | Decision | Status |
|---|---|---|---|
| D-001 | 2026-11-07 | Repo is private, kit at top level, solution in `submission/` | Accepted |
| D-002 | 2026-11-07 | Architecture: four stages, with ETL as stage one only | Accepted |
| D-003 | 2026-11-07 | Ingest builds a temporal fact store keyed by product, qualifiers, metric | Accepted |
| D-004 | 2026-11-07 | Source authority ranking by page type, then recency | Accepted |
| D-005 | 2026-11-07 | Conflicts computed at ingest from same-key, different-value groups | Accepted |
| D-006 | 2026-11-07 | Question parsing to a fact key; no tuning to public question wording | Accepted |
| D-007 | 2026-11-07 | Answer text holds only current values; refusals carry no numbers | Accepted |
| D-008 | 2026-11-07 | Second path: passage retrieval over authoritative pages for non-rate facts | Accepted |
| D-009 | 2026-11-07 | Deterministic offline core; LLM never required at answer time | Accepted |
| D-010 | 2026-11-07 | Fully offline vs optional Anthropic API at ingest | Open |
| D-011 | 2026-11-07 | Build order and evaluation loop | Accepted |
| D-012 | 2026-11-07 | Ingest algorithm: boilerplate strip, blocks, header-aware tables, observation log to versions | Accepted |
| D-013 | 2026-11-07 | SQLite store with three versioned cache layers; answer path in memory | Superseded by D-015 (storage backend only) |
| D-014 | 2026-11-07 | Dataset-agnostic rules; site-specific hints isolated in config | Accepted |
| D-015 | 2026-11-07 | In-memory store by default; SQLite cache only when a config file enables it | Accepted |
| D-016 | 2026-11-07 | Page types, authority scores and per-table effective dates (refines D-004) | Accepted |

---

## D-001: Repository layout and visibility

- **Date:** 2026-11-07
- **Status:** Accepted
- **Context:** The kit's rules forbid redistributing the credit union's data. Graders run `python harness/run_eval.py --submission <folder>` from a fresh clone.
- **Decision:** Private GitHub repo `prasad-m-k/knowledge-hackathon`. The kit is unpacked at the repo top level so the scorer runs from a fresh clone. The solution lives in `submission/` (never `starter/`). The outer kit zip is gitignored; `snapshots/0*/` stays gitignored per the kit.
- **Consequences:** Organizers must be given read access before the deadline.

## D-002: Overall architecture

- **Date:** 2026-11-07
- **Status:** Accepted
- **Context:** The scorer rewards picking the one true value for a product, tier and date, not having the data loaded. Starter baseline scores 0.093.
- **Decision:** Four stages: (1) ingest into a fact store (the ETL), (2) resolution, (3) question to fact mapping, (4) answer composition. ETL is the starting point, but stages 2 and 3 carry most of the score.

## D-003: Temporal fact store

- **Date:** 2026-11-07
- **Status:** Accepted
- **Context:** The latest snapshot has 705 pages: 254 blog, 117 business resources, 34 newsroom tag pages, about 20 product and rate pages. Rates live in markdown tables, e.g. `| 2024-27 Model Year | 60 Months | 5.39% APR1 |`, where the trailing `1` is a footnote marker glued to the value.
- **Decision:** Every page in every snapshot is parsed into rows of `(snapshot_id, taken_on, url, page_type, product, qualifiers, metric, value, quote)`. Qualifiers cover term, model year, balance tier, loan-amount tier, personal vs business. Metric is one of rate, APR, APY, fee, count, date, hours. Table rows are the primary source; column headers supply qualifiers. Footnote markers are stripped from values. Pages are hashed so unchanged content is parsed once across snapshots. Full history is kept, never only the latest copy.
- **Consequences:** `as_of` questions are answered by selecting the newest snapshot with `taken_on <= as_of`.

## D-004: Source authority ranking

- **Date:** 2026-11-07
- **Status:** Accepted
- **Decision:** Page type is classified from the URL path. Ranking, highest first: rate pages and rate tables (`/rates`, product pages with effective dates) > product pages (`/personal/...`, `/business/...`) > FAQ and disclosure pages > calculators (`/calculators/...`) > blog, newsroom, press releases, newsletters (`/learn/blog/...`, `/newsroom/...`). Within the same authority level, the newer snapshot wins. Expired promotions are dropped.
- **Example:** 60-month auto APR resolves to 5.39% (auto-loan rate page), not 5.34% (vehicle affordability calculator).

## D-005: Conflict detection

- **Date:** 2026-11-07
- **Status:** Accepted
- **Context:** Conflict scoring is `0.7 * F1 + 0.3 * resolution accuracy`, so precision matters as much as recall.
- **Decision:** Group facts by key (product, qualifiers, metric). Same key with different values is a conflict; different qualifiers never are. Resolution and conflicts are computed once at ingest. Each `Conflict` carries all competing values, a source per value, `resolution` set to the winner as of the latest snapshot, and a `reason` (newer snapshot, authoritative page, stale calculator, expired promo, old press release). Topics name the product and term clearly, e.g. "10-month jumbo certificate APY".

## D-006: Question understanding

- **Date:** 2026-11-07
- **Status:** Accepted
- **Context:** The hidden set rewords public questions and adds `as_of` and change questions.
- **Decision:** Parse product, term, tier, metric and date from the question, including dates in the text ("as of May 2026", "today (October 2026)"); a month-only date maps to the end of that month. Use a synonym table plus fuzzy matching against product names found on the site. When no tier is named, use the default tier (base or lowest minimum, e.g. the $100k mortgage tier). Never ask a clarifying question. Ignore conversational noise. No matching tuned to the exact wording of the 40 public questions.

## D-007: Answer composition

- **Date:** 2026-11-07
- **Status:** Accepted
- **Context:** Any stale or wrong value in the answer text zeroes the item, even if the right value is also present.
- **Decision:** `text` contains only current, resolved values, with the authoritative URL cited first in `sources`. History and reasoning go in `conflict_note`, never in `text`. When no fact matches with enough confidence, return `confident=False` with a refusal phrase and no numbers beyond those in the question.

## D-008: Passage path for non-rate facts

- **Date:** 2026-11-07
- **Status:** Accepted
- **Decision:** Branch hours, closures, eligibility, and list questions (credit cards, mobile wallets) go through passage retrieval (BM25, embeddings optional) over authoritative pages only, with the same authority and recency filters as D-004. List questions enumerate all current items.

## D-009: Determinism and speed

- **Date:** 2026-11-07
- **Status:** Accepted
- **Context:** Speed pillar needs p95 answer latency of 2 s or less. Consistency needs identical numbers on paraphrase and repeat. Graders may not supply an API key.
- **Decision:** The answer path is deterministic and offline. Heavy work happens in `ingest` (untimed, 30 minute limit). An LLM is never required at answer time.

## D-010: LLM at ingest (fully offline vs optional API)

- **Date:** 2026-11-07
- **Status:** Open
- **Options:** (a) Fully offline: stdlib, possibly `rank_bm25`. (b) Optional Anthropic API at ingest to extract facts from awkward pages, results cached and committed, declared in NOTES.md, with a working offline fallback.
- **Leaning:** (a) as the baseline; revisit (b) only if extraction misses are a measurable failure class.

## D-011: Build order

- **Date:** 2026-11-07
- **Status:** Accepted
- **Decision:** (1) page classifier and table extractor, validated on auto loan, certificate, savings, mortgage and credit card pages across all five snapshots; (2) resolution and `conflicts()`; (3) question parser; (4) passage path for branch and list questions. Run `python harness/run_eval.py --submission submission --eval eval/public_eval.jsonl` after each step and fix the failure class, not the single question.

## D-012: Ingest algorithm (refines D-003)

- **Date:** 2026-11-07
- **Status:** Accepted
- **Context:** Measured on the five snapshots. A raw content hash finds only 10 to 18 unchanged pages per recrawl, mostly because of site boilerplate (a "Third Party Plugins / Messenger" block added to every page, rotating "Handpicked For You" blog teasers whose numbers would be credited to the host page). After stripping one boilerplate block, 205 pages are unchanged 01 to 02 and 421 are unchanged 04 to 05. Real copy edits also occur (66 changed lines on `about/join` between 01 and 03). URLs move between crawls (`/personal/loans/auto-motorcycle-loans` in 01 became `/personal/loans/auto-loans` by 05). Rate pages carry effective dates ("Rates are effective as of 08/31/2026"). Only 41 to 71 pages per snapshot contain tables.
- **Decision:**
  1. Boilerplate detection per snapshot: blocks appearing on a large share of pages are template and are removed; template sections (e.g. teaser lists under a repeated heading) are removed too. The stripped page is hashed.
  2. Block segmentation with heading paths; each paragraph, list or table carries its heading path.
  3. Page classification by URL, title and on-page dates (effective date, press date, promo end) into authority levels.
  4. Extraction: header-aware table parsing (qualifier columns vs value columns, one fact per value cell, footnote markers stripped and footnote text kept); prose patterns for rates, fees, hours, dates and counts, ranked below table facts.
  5. Canonical fact key (product, qualifiers, metric), with product taken from heading path, caption and title through an alias table, never from the URL.
  6. Append-only observation log, collapsed into versions (first seen, last seen) per key and source page; disappearance is recorded, which detects ended promotions.
  7. Per-snapshot resolution using only facts present in that snapshot: authority, then effective date, then recency.
  8. Validation by printing timelines for about ten known facts before moving to question parsing.

## D-013: Storage and caching

- **Date:** 2026-11-07
- **Status:** Superseded by D-015 for the storage backend. The three cache layers, versioned keys and in-memory answer path still stand.
- **Context:** Graders may run the code on a different dataset, start cold, and run the folder read-only. The harness calls `answer()` from a worker thread, and a `sqlite3` connection is bound to its creating thread by default.
- **Decision:** SQLite (stdlib `sqlite3`) is the store of record, with three cache layers, each keyed by its inputs:
  1. Extracted facts per page: key = stripped content hash + extractor version.
  2. Resolved view per snapshot: key = snapshot content hash (set of page hashes) + resolver version. Append-only, since adding snapshot N never changes views 1 to N-1.
  3. Conflict history: updated incrementally as each snapshot arrives.
  Snapshots are identified by content hash, not folder name. Bumping the extractor or resolver version invalidates only that layer. The database lives under `tempfile.gettempdir()` by default, overridable by an environment variable, with fallback to `:memory:` if the file cannot be opened. The cache file is gitignored and never committed. After ingest, resolved views and the search index are loaded into in-memory dicts; `answer()` never queries SQLite. All SQL queries use explicit ORDER BY.
- **Consequences:** The graders' run is cold but still saves work within the run (unchanged pages are parsed once). The development loop stops re-parsing pages. NOTES.md should describe this incremental design.

## D-014: Dataset-agnostic rules

- **Date:** 2026-11-07
- **Status:** Accepted
- **Decision:** Authority classification, product aliases and boilerplate detection rely on general signals (URL and title words such as rates, calculator, blog, news, press; effective-date lines; table structure; frequency across pages), not on Dupaco's exact URLs. The few site-specific hints live in one config module. `harness/selftest/` serves as a second dataset to check that nothing depends on Dupaco.

## D-015: Optional SQLite through config

- **Date:** 2026-11-07
- **Status:** Accepted
- **Context:** Evaluators should be able to run the submission with no setup, no extra modules and no files written. SQLite persistence only pays off across repeated runs (development, a deployment that receives new crawls).
- **Decision:** Default backend is an in-memory store; nothing is written to disk. SQLite (stdlib `sqlite3`) is used only when a config file enables it: the path in `KSYS_CONFIG`, else `submission/ksys.config.json`, with `{"cache": {"backend": "sqlite", "path": "..."}}` (relative paths resolve against the config file). The real config file and cache files are gitignored; `submission/ksys.config.example.json` documents the format. A missing, unreadable or invalid config, or a SQLite file that cannot be opened, falls back to memory with a note on stderr and never fails ingest. Both backends share one key-value interface (`ksys/store.py`) with JSON values, so behaviour is identical. The three cache layers, versioned keys and in-memory answer path from D-013 are unchanged.
- **Consequences:** Graders run fully in memory. `requirements.txt` stays empty for storage.

## D-016: Page classification and dates (refines D-004)

- **Date:** 2026-11-07
- **Status:** Accepted
- **Context:** URL survey over all snapshots: rate sheets at `/rates` and `/business-rates`; product pages under `/personal`, `/business` and short paths (`/checking`, `/loans`); landing pages ending `-lp`, three titled "Oops ... This Offer Has Expired"; about 140 newsroom releases; blog posts under `/learn/blog`, `/business/resources/<slug>` and dated paths (`/2018/09/25/...`, `/dupacodaily/2017/...`); PDFs and spreadsheets under `/hubfs`; tag, author and category listing pages. Rate pages state "Rates are effective as of MM/DD/YYYY" per table, not per page (the September `/rates` page carries dates from 2026-01-02 to 2026-09-25 across its tables), and footnotes can repeat an older date. In the latest snapshot `/rates` and the auto loan product page show the same table with the same effective date, so effective dates act as version stamps per product group.
- **Decision:** `ksys/classify.py` assigns one page type from general URL, title and text signals, with authority: rate_sheet 100, product 80, page 70, promo 60, document 50, home 50, legal 40, guide 35, calculator 25, news 20, blog 15, listing 5, expired 0. Recorded per page: `published` (byline date in the first blocks of articles), `url_date` (date in the URL or file name), `title_year`, `limited_time`, and `effective` per table (nearest "effective as of" line after the table in the same section, plain line preferred over footnote, else the nearest one before). Resolution (step 7) uses authority first, then effective date, then snapshot recency; expired pages never supply a current value.
- **Results (latest snapshot):** blog 277, news 127, listing 118, calculator 59, product 37, page 36, document 28, legal 12, promo 4, expired 3, rate_sheet 2, home 1, guide 1. Published date found on 275/277 blog and 126/127 news pages.
