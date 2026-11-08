# Snapshots go here

The supplied website snapshots are not included in this repository. Copy the five zips from the hackathon kit into this folder:

```text
01_2026-05-12_baseline.zip
02_2026-05-19_recrawl.zip
03_2026-06-09_recrawl.zip
04_2026-08-27_rebaseline.zip
05_2026-09-28_latest.zip
```

`python harness/run_eval.py --submission submission --eval eval/public_eval.jsonl` unpacks them into `snapshots/` on the first run. They are gitignored, so they will not be committed.
