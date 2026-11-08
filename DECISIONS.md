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
| D-017 | 2026-11-07 | Fact schema: product, label, parsed qualifiers, metric, value; table facts primary, prose facts secondary | Accepted |
| D-018 | 2026-11-07 | Fact keys (family, name, signature, metric), observation log and version timelines | Accepted |
| D-019 | 2026-11-07 | Resolution ranking per snapshot and conflict list rules | Accepted |
| D-020 | 2026-11-07 | Question parsing, fact and passage answering, refusals, page carry-forward | Accepted |

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

## D-017: Fact extraction schema (refines D-003, D-012.4 and D-012.5)

- **Date:** 2026-11-07
- **Status:** Accepted
- **Context:** About half the practice questions are rates from tables, hinging on qualifiers (17-month standard vs jumbo special, model year 2025 inside "2024-27 Model Year", a $15,000 balance inside "$10,000 – $24,999.99", 30-year mortgage loan-amount caps). The rest are text facts (routing number, hours, addresses, URLs, eligibility), which go through the passage path (D-008), not this step. Cells carry glued footnotes ("5.39% APR1", "12.50% – 19.50%2"), headers are sometimes wrong (a calculator labels an APR column "Annual Percentage Yield"), and stale tables survive on calculators and older landing pages ("2023-26 Model Year" at 5.34% on `/calculators/vehicle-affordability` and `/switch-and-earn`; 5.750% 30-year rows on `/homebuying-guidance` and `/mortgage-refi`).
- **Decision:** `ksys/extract.py` emits facts with `product` (caption, else row label, else section heading), `label` (row label cells), `quals` parsed from label, caption and qualifier columns (`term_months`, `model_year` range, `amount` range for balance or loan-amount tiers, `flags` such as jumbo, special, business, traditional), `metric` (apy, apr, rate, points, payment, min_open, min_earn, fee, count, percent), `value` without footnote markers, `num` (number or range), `unit`, `footnote` and `quote`. Column roles come from header keywords; a metric written in the cell overrides the header. Table facts are primary. Prose facts (percentages, ranges and counts of branches, members, employees and similar nouns in sentences) are kept as secondary evidence so stale numbers are visible for conflict reporting. Product identity is not canonicalised here; the canonical key and matching are built in steps 5 and 6. Facts are cached per page by cleaned content hash plus segment and extractor versions.
- **Consequences:** Stale values are extracted, not filtered, at this step. Choosing between them is resolution's job (D-016 ranking), which keeps every competing value available for `conflicts()`.

## D-018: Fact keys, observation log and versions (refines D-012.5 and D-012.6)

- **Date:** 2026-11-07
- **Status:** Accepted
- **Context:** The same fact is labelled differently across pages and crawls: the auto table caption is "Auto Loan Rates" in May and "Auto & Motorcycle Loans" in September; "Share Savings Account" vs "Share Savings"; a stale calculator still lists "2023-26 Model Year" while the rate sheet lists "2024-27"; the May certificate table heads its label column "Term" while September heads it "Certificate"; older `/business-rates` captions omit "Business".
- **Decision:** `ksys/history.py` keys each fact by (family, name, signature, metric). Family comes from a generic product vocabulary in `ksys/taxonomy.py` (ira, home_equity, mortgage, auto_loan, certificate, savings, checking, credit_card and others; `org_count` for counts of branches, members, employees). Name is the distinguishing words left after removing generic, family and flag words. Signature is term, model-year rank within the table (newest bucket = 0), amount tier and identity flags; a business URL adds the business flag. Name variants merge when one is a non-empty subset of another within the same family, signature and metric. Qualifier-column cells are included in the row label, so a "Term" column holding the product name still identifies the product. An append-only observation log records every fact per snapshot with page type, authority, effective date and publication date; versions collapse consecutive snapshots with the same value per key and page.
- **Results:** 10-month jumbo certificate special APY reads 3.90% from May to August and 4.00% in September; the 60-month auto APR for the newest model years reads 5.19% then 5.39% on the rate sheet and product page, while the calculator, `/switch-and-earn` and (until August) `/personal/checking-accounts` keep 5.34%; the 30-year $100k purchase rate moves 5.875%, 6.250%, 6.125%, 6.375%, 7.13% across the five crawls while `/homebuying-guidance` stays at 5.750%.

## D-019: Resolution and conflicts (refines D-005 and D-016)

- **Date:** 2026-11-07
- **Status:** Accepted
- **Context:** The self-test gold conflict (6-month certificate 2.95% vs 3.50%, correct 3.50%) mixes a value that changed between crawls with an ended promotion still on the site, so a conflict is any key whose values differ anywhere in history. Conflict scoring is 0.7 x F1 + 0.3 x correct winner, so precision matters. Branch counts appear in the "About Dupaco" boilerplate of each press release with the count of its day (20 to 24 branches), in a staff bio on `/about` (18) and in network-wide figures (5,600 shared branches, 100,000 U.S. branches).
- **Decision:** `ksys/resolve.py` resolves each snapshot from its own observations. Rates rank by authority tier (A: rate sheet and product pages, B: other first-party pages, promos, documents, C: the rest), then effective date, publication date, table over prose, authority score, support (pages agreeing), and value string for determinism. Expired pages never win. Counts rank by publication date first, so the newest dated statement wins; network-wide counts are not extracted. Conflicts: one entry per product slot (rate, APR and APY folded together) whose values differ in any crawl; for rates only table values compete when the key has any, otherwise prose values; values found only in the winner's own sentence are not counted; only branch counts are reported among counts. Each entry carries the competing values, one source per value, the resolution (winning values with metric) and a reason (lower-authority page type, expired offer, replaced in earlier crawls, effective date of the winner).
- **Results:** winners per crawl match the timelines (10-month jumbo special 3.90% then 4.00%; 60-month auto 5.19% then 5.39%; 1st Rate Checking 3.00% then 2.50%; 30-year $100k purchase rate across all five moves); branch count resolves to 22 in every crawl. 72 conflicts in total, most in recreational loans, mortgages, auto loans, certificates, home equity and IRAs. Self-test conflict score: F1 1.0, resolution accuracy 1.0.
- **Amendment (2026-11-07):** amount tiers and model-year buckets of one product and term are folded into one entry (values and winning tiers all listed), and prose-only keys are left out of groups that have table values. This cut the list from 73 to 44 entries. Against a mock gold list built from the contradictions named in the practice questions (stale auto rates, the 3% checking promo, branch counts, the 10-month jumbo change, the 0.35% savings claim, the 9.9% card rate, stale mortgage APRs), merged and unmerged lists both matched 8 of 8 with resolution accuracy 0.625, and F1 rose from 0.20 to 0.30. Ordering the list differently (fewest values first, live contradictions first) lowered resolution accuracy, so entries stay in key order.
- **Open point:** the hidden gold list size is unknown. The remaining resolution misses come from the scorer pairing a gold item with the first entry that shares one value and a topic word, which broad entries make more likely.

## D-020: Answering (question parsing, facts, passages, refusals)

- **Date:** 2026-11-07
- **Status:** Accepted
- **Context:** About half the practice questions are rates with qualifiers, the rest are text facts (hours, addresses, routing number, links, eligibility, program details). Scoring zeroes any answer containing a stale value, gives refusals credit only without numbers, and needs p95 latency under 2 s. The self-test's second snapshot omits a page whose value is still expected, and states rates only in sentences.
- **Decision:**
  1. `ksys/question.py` parses as-of dates (argument, else full date or month-year in the text, month-year mapped to end of month), product family with everyday synonyms, term (digits or number words), model year, amount, metric (plural forms included), identity flags, superlatives and link intent. Search words come from the member's own wording; synonyms only help find the family.
  2. The snapshot used is the newest one taken on or before the as-of date. The site as of a snapshot is every page seen so far in its newest version (pages missing from a crawl are carried forward).
  3. Rate questions with a family (`ksys/answer.py`): candidate slots are current winners from tables on pages with authority >= 50 (prose winners only when the family has no tables); once rate-sheet or product pages publish the family, weaker pages are dropped. Specific questions keep the best-scoring slots; unspecific ones list the whole family (up to 14 lines). Question words that would narrow the product (adjustable, construction, ...) but appear in no rate fact of the family lead to a refusal. Sources cite the winning page and agreeing product pages. Link questions about a family return the product pages that publish its rates.
  4. Counts ("how many branches") use the newest dated count, only for plain size questions.
  5. Other questions use BM25 over blocks (tables included as "header: cell" rows, long blocks chunked), candidates judged on their section context with idf-weighted coverage, page authority, recency of dated pages, title matches and proper-noun presence. Hours, address, phone and routing questions require a matching value pattern in the context. News and blog answers start with the opening paragraph. Link questions return the page URL first.
  6. Refusal (`confident=False`, no numbers) when a proper noun from the question is absent from the site or the chosen context, when a rate question finds no published rate, or when nothing matches.
  7. Answers are cached by normalised question and as-of date, so repeats are identical.
- **Results:** public eval accuracy 0.864 (starter 0.093), later 0.879 after a full-coverage bonus in passage ranking; 22/22 on reworded practice questions (`tools/check_paraphrases.py`), paraphrase and repeat consistency 1.0, p95 latency 0.01 s, ingest 5.4 s. Self-test: final score 1.0 including conflicts F1 1.0. Remaining public misses: general lobby hours cite a newsroom page instead of `/` or `/contact`; eligibility (the states are in a different section than the eligibility list), contact-information update (no page states a process), branch hour variations ("noon"), Volunteer Time Off count (expects the 2023 figure); `dup-005` has no must-include tokens and scores zero without the LLM judge.
