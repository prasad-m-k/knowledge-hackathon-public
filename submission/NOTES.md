# Notes: a knowledge system that knows what's true now

Prasad MK

![Pipeline Architecture](architecture.svg)

*(An editable 2-slide PowerPoint version of this diagram is also included in [`architecture.pptx`](architecture.pptx).)*

## How it works

The system runs entirely on the Python standard library and needs no API keys, no network access and no extra packages (`requirements.txt` is empty). All heavy work happens in `ingest()`: each snapshot is cleaned, split into blocks, classified and turned into facts, and the winning value for every fact is computed per snapshot. `answer()` only reads in-memory structures, so answers take a few milliseconds and the same question always gets the same answer.

Ingest runs in six stages (code in `ksys/`):

1. **Boilerplate removal** (`boilerplate.py`). Text repeated across many pages of a snapshot (forms, widgets, chat launchers, "Handpicked for You" blog teasers) is learned from that snapshot and removed, so a teaser's date or rate is never credited to the page it sits on.
2. **Segmentation** (`segment.py`). Pages become paragraphs, lists, labels and tables, each tagged with the headings above it. Tables are parsed into header and rows, and the short line above a table becomes its caption, which usually names the product.
3. **Page classification** (`classify.py`). Each page gets a type and an authority score from general URL, title and text signals: rate sheet 100, product page 80, other first-party page 70, promotion 60, document 50, calculator 25, news 20, blog 15, listing 5, expired offer 0. Each page also gets its byline date, and every rate table gets the "Rates are effective as of" date written next to it.
4. **Fact extraction** (`extract.py`). Table cells and sentences become facts with a product, qualifiers (term, model year, balance or loan-amount tier, flags such as jumbo, special, business, Roth), a metric (APY, APR, dividend or interest rate) and a value with footnote markers removed.
5. **Keys and history** (`history.py`, `taxonomy.py`). Facts get a key that stays stable across pages and crawls even when captions are renamed or model-year buckets shift. Every observation is logged with its snapshot, page type, authority and dates.
6. **Resolution and conflicts** (`resolve.py`). For each snapshot and key, one value wins; every key that ever showed more than one value becomes a conflict entry with all values, a source per value, the winner and the reason.

## How "current" is decided

The site as of a snapshot is every page seen so far, each in its newest version (a page missing from one crawl has not necessarily been taken down). Without a date, answers come from the newest snapshot. With `as_of`, or with a date in the question such as "as of May 2026", they come from the newest snapshot taken on or before that date, and a month on its own means the end of that month.

Within a snapshot, a rate wins by these rules, in order: pages in a higher authority tier (rate sheets and product pages, then other first-party pages and promotions, then everything else), then a newer effective date, then a newer publication date, then a table value over a sentence, then the number of pages agreeing. Expired offers never win. So a stale calculator or a landing page that still lists last year's model-year table cannot beat the auto loan rate page, and a 2022 press release cannot beat a current product page. Counts such as the number of branches change over time and are restated in every press release, so for counts the newest dated statement wins.

Different qualifiers are different facts, never conflicts: 48-month vs 60-month, rate vs APY, standard vs jumbo, personal vs business, one balance tier vs another.

## How answers are built

Rate questions are matched against the winning facts of the chosen snapshot. A question that names a term, tier, model year or product gets that one value; a broad question ("what are your mortgage rates") gets the whole current table. Only current winners from tables on authoritative pages are ever stated, and replaced values are mentioned only in `conflict_note`, never in the answer text, because repeating an old value is what the scorer penalises.

Other questions (hours, addresses, routing number, links, programs) use keyword search (BM25) over page blocks and table rows, ranked by page authority, recency and how well the surrounding section covers the question. Questions about hours, addresses, phone or routing numbers must find that kind of value in the passage.

The system says "I don't know" (`confident=False`, no numbers) when the question names something the site never mentions (a branch, a product variant such as an adjustable-rate mortgage), when a rate question finds no published rate, or when nothing matches.

## Configuration

None is needed. Optionally, a SQLite cache of extracted pages can be enabled for repeated development runs by copying `ksys.config.example.json` to `ksys.config.json`; without that file everything stays in memory and nothing is written to disk. Design decisions are logged in `DECISIONS.md` at the repository root.
