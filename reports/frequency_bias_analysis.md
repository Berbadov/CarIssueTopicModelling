# Frequency Bias in YouTube Issue Extraction

**Date noticed:** 2026-04-17  
**Affects:** `extract_youtube_issues.py` pass-2 consolidation  
**Observed on:** VW Golf MK7 dataset (30 videos, 87 final issues)

---

## What Was Observed

The consolidated issue knowledge base shows a skewed `mention_count` distribution and over-representation of issues from "buyer's guide" style videos. The pipeline treats all video types equally, which inflates confidence scores for issues that come from a single category of source.

---

## Evidence

### Citation distribution (VW Golf MK7 final run)

| Stat | Value |
|---|---|
| Total final issues | 87 |
| Issues with `mention_count = 1` | 68 (78%) |
| Issues with `mention_count ≥ 3` | 5 |
| Only issue with `mention_count ≥ 5` | Coolant leak (mc=14) |

### Top cited videos

```
14x  Golf R buyers guide MK7 & MK7.5 (2013-2021) — Avoid buying broken Golf R
13x  Golf GTI buyers guide MK7 & MK7.5 (2013-2020) — Avoid buying broken VW GTI
 9x  MK7 VW GOLF R BUYERS GUIDE : DO NOT BUY Without Watching This!
 9x  VW Golf MK7 Issues of the Petrol Engines 2012-2020
 8x  Addressing common faults in VW Golf MK7 (2012-2019)
 8x  Why the Mk7 is the best generation of VW Golf
 7x  VW Golf MK7 GTI & R Engine Issues 2013-2020
```

All of the top 3 sources are explicit "buyer's guide / common problems" style videos — intentional enumeration lists, not organic owner experiences.

### OLD vs. NEW issue count

The OLD run produced **26 issues**; the current final run produced **87 issues**. The new pipeline became less aggressive at merging, not more — suggesting the batch consolidation strategy is fragmenting rather than unifying.

---

## Root Causes

### 1. Buyer's guide video inflation

Buyer's guide / "common problems" videos enumerate known issues in bullet-point format. DeepSeek extracts each bullet as a separate issue object, then each of those objects lists the same video as a source. One video contributes 7–14 entries to the issue count.

These videos are structurally different from organic owner experience videos, but the pipeline treats them identically. A video that says "here are 15 known problems" is a secondary curation source, not 15 independent observations.

### 2. `mention_count` is a false confidence signal

The coolant leak issue reaches `mention_count=14`, which looks like strong independent corroboration. But ~11 of those citations come from buyer's guide list videos — effectively one creator category. The field looks like independent corroboration but actually reflects source-type concentration.

### 3. Batch consolidation fragmentation (`CONSOLIDATE_BATCH=10`)

Pass-2 consolidation works in batches of 10 issues. Two issues describing the same failure extracted from different videos may land in different batches and never be compared. Pass-2b is supposed to re-merge the batch outputs, but it re-batches again rather than doing a true global merge.

This directly causes the 78% single-mention rate: many issues are genuine duplicates that were never seen together.

### 4. No minimum corroboration threshold

The final output includes all issues regardless of `mention_count` or `data_quality`. Single-mention, low-confidence issues flood the output with noise.

---

## Recommended Fixes (Priority Order)

### Fix 1 — True global final merge (highest impact)
**File:** `scripts/extract_youtube_issues.py`, `consolidate_issues()` function

Pass-2b currently re-batches if `len(batch_results) > CONSOLIDATE_BATCH`. Instead, it should always do one global merge pass if the set is small enough, or use a cascade that guarantees every pair of related issues is seen together at least once.

```python
# Current (fragmented):
for i in range(0, len(batch_results), CONSOLIDATE_BATCH):
    chunk = batch_results[i: i + CONSOLIDATE_BATCH]
    ...

# Should be: one global pass if < ~50 issues, else overlap windows
```

### Fix 2 — Tag video type at fetch time
**File:** `scrapers/fetch_youtube_car_issues.py` or `fetch_youtube_transcripts.py`

Add a `video_type_category` field to each video object:
- `list_format` — buyer's guide, "X problems with Y", "avoid buying" videos
- `organic` — owner reviews, long-term ownership, mechanic walkthroughs
- Heuristic: title contains "buyer's guide", "avoid buying", "X problems", "X issues", "common faults"

Then pass this to the consolidation prompt so the LLM can weight sources appropriately.

### Fix 3 — Add `distinct_channel_count` to output schema
**File:** `scripts/extract_youtube_issues.py`, consolidation prompt

Alongside `mention_count`, track how many distinct channels mention an issue. This is a better proxy for independent corroboration than raw video count.

Add to consolidation schema:
```json
"distinct_channel_count": <integer>
```

### Fix 4 — Filter output by minimum corroboration
**File:** `scripts/extract_youtube_issues.py`, `main()`

Before writing final output, optionally filter:
```python
# Keep issues with mention_count >= 2, or single-mention only if confidence=high
filtered = [i for i in final if i.get('mention_count', 0) >= 2 
            or i.get('confidence') == 'high']
```

Or write two outputs: `_confirmed.json` (mc≥2) and `_all.json` (full set).

---

## Related Files

- `scripts/extract_youtube_issues.py` — consolidation logic to fix
- `data/processed/issue_knowledge_youtube_vw_golf_mk7_final.json` — affected output
- `data/processed/issue_knowledge_youtube_renault_clio_mk4_final.json` — same pipeline, same bias likely present
- `reports/youtube_postprocess_audit_vw_golf_mk7.md` — prior audit

---

## Notes

- The raw video JSON (`data/raw/videos/vw_golf_mk7_raw.json`) was overwritten after the original run and now only contains 1 video. Any re-run will need the full 30-video dataset re-fetched.
- The Renault Clio MK4 dataset should be audited for the same pattern before trusting its `mention_count` values.
