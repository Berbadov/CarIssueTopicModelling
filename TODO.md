# TODO — 2026-04-18

## Make `scripts/extract_youtube_issues.py` faster & more efficient

Context from 2026-04-17 run (PID 10888, vw_golf_mk7): Pass 1 finished ~21:48 with 124 raw issues from 23 videos. Process then sat idle on a single HTTPS socket for 1h+ — Pass 2 consolidation is a single blocking LLM call with no timeout, no progress signal, and no partial persistence.

### Problems to fix
1. **Pass 2 is one giant blocking call** over all raw issues → no timeout, no retry, no progress. If the API stalls, the whole run is wasted.
2. **Pass 1 long-video loop is sequential** — one LLM call per video, awaited serially. 23 videos = 23 round-trips.
3. **Cache only written after each video/batch** — fine, but no resume inside Pass 2.
4. **Triage runs after the expensive cache-miss path** is already set up; confirm it's gating correctly before any LLM spend.
5. No wall-clock timing / per-stage metrics logged.

### Proposed changes (in priority order)
- [ ] Add a hard timeout + retry-with-backoff wrapper around every Anthropic call (Pass 1 long, Pass 1 shorts-batch, Pass 2). Fail loud, don't hang.
- [ ] Parallelize Pass 1 long-video extraction with a bounded `ThreadPoolExecutor` (e.g. 4–8 workers); keep cache writes serialized behind a lock. Expect ~4–6× speedup on this stage.
- [ ] Chunk Pass 2 consolidation: split raw issues into groups (by rough topic/keyword or fixed size), consolidate each chunk, then do a final merge pass. Persist intermediate chunk results so a stall doesn't lose everything.
- [ ] Add `--resume-consolidation` using a `_youtube_pass2_<slug>.json` cache analogous to pass1.
- [ ] Log per-stage timings + token counts; print a summary at the end.
- [ ] Consider prompt caching for the scaffold/context block (it's reused across every Pass 1 call) — big cost + latency win if not already enabled.
- [ ] Verify triage (`triage_video`) is cheap/local and runs before `extract_issues_from_video`; if it uses an LLM, make it optional or batch it.

### Verification
- [ ] Re-run on `vw_golf_mk7` and compare: total wall time, #issues, final output diff vs today's baseline.
- [ ] Dry-run on `renault_clio_mk4` to confirm no regressions on a smaller corpus.

### Reference artifacts from today
- Cache: `data/processed/_youtube_pass1_vw_golf_mk7.json` (124 issues, 23 videos, last write 21:48:06)
- Script: `scripts/extract_youtube_issues.py` — Pass 1 loop around line 1265, Pass 2 call at line 1310

---

## TODO-002 — Solving Model Bias (trim / variant over-representation)

**ID:** `TODO-002-model-bias`
**Owner:** any agent (Claude = design, Gemini/Copilot = implementation)
**Affects:** `scripts/extract_youtube_issues.py`, `scripts/postprocess_youtube_issues.py`, downstream reports

### Problem (quantified on `vw_golf_mk7_final.json`, 2026-04-18)

Source-video title composition — 124 total `source_videos` entries:

| Variant signal in title | Count | Share |
|---|---|---|
| GTI | 49 | 40% |
| Golf R | 37 | 30% |
| Plain TSI (non-GTI) | 14 | 11% |
| **TDI (diesel)** | **0** | **0%** |

Yet `affected_engines` in the same file spreads evidence across `1.4_TSI (21)`, `2.0_TSI (20)`, `1.2_TSI (9)`, `1.8_TSI (9)`, `1.5_TSI (8)`, `2.0_TDI (6)`, `1.6_TDI (5)`. The LLM back-fills scaffold engines with no evidence. Low-signal GTI/R chatter gets presented as broad-trim coverage. Clio Mk4 is clean (RS in 1/59) — this is Golf-nameplate-specific English-YouTube enthusiast skew.

### Non-goals

- Do not re-introduce issue-specific or trim-specific discovery queries (violates `agents.md` §2).
- Do not hide GTI/R issues — they are real; just don't let them mask base-trim issues or get laundered onto non-GTI engines.

### Solution design (for implementing agents)

**Stage A — Tag every source video with inferred trim** (pure local, no LLM cost)

In `postprocess_youtube_issues.py` (or a new `tag_trim()` helper called by the post-processor), add `source_video.trim` derived from `title`:

- `GTI` if `/\bGTI\b/i` and not `\bGTD\b`
- `R` if `/\bGolf ?R\b/i` or `/MK7\.?5? ?R\b/i`
- `GTD` if `/\bGTD\b/i`
- `R-Line` if `/R[- ]?Line/i` (cosmetic trim on base engines — keep separate)
- `TDI` if `/\bTDI\b/i` or `/diesel/i`
- `base` otherwise
- `unknown` if title missing

Emit per issue: `trim_evidence: { "GTI": n1, "R": n2, ... }` and `dominant_trim` (argmax, or `mixed` if top ≤ 50%).

**Stage B — Variant-scoped engine attribution**

When `dominant_trim ∈ {GTI, R}` and the only cited videos are GTI/R:
1. Restrict `affected_engines` to `2.0_TSI` (the only engine those trims ship with in Mk7).
2. Set `model_scope` to `["golf_gti_mk7"]` or `["golf_r_mk7"]` (not `all_vw_golf_mk7`).
3. Emit `trim_scope_warning: true` so downstream can flag it.

When `dominant_trim == mixed` or `base`, leave engine list as-is.

**Stage C — Confidence down-weighting**

Add to scoring in post-process:
- If `distinct_trim_count == 1` and evidence is GTI/R only → cap `confidence` at `medium`.
- If `dominant_trim == base` with ≥ 2 distinct channels → allow `high`.
- Keep `corroboration_count` as-is but add `cross_trim_corroboration_count` (independent mentions from ≠ dominant trim).

**Stage D — Discovery-side rebalance (model-level only, scaffold-allowed)**

In `scrapers/fetch_youtube_car_issues.py`, keep queries model-level per `agents.md` §3 but diversify seed phrasing to pull non-enthusiast content:
- `"{car} daily driver review"`
- `"{car} long term ownership"`
- `"{car} mechanic workshop"` (already allowed)
- `"{car} family car review"`
- Locale-expand: append queries in `de`, `fr`, `es` for EU models when `geo` supports it (still pure model-level).

Do **not** add `"{car} TDI problems"` — that's engine-level targeting.

**Stage E — Reporting**

Extend `benchmark_knowledge.py` output and `reports/youtube_postprocess_audit_*.md` with:
- `trim_distribution` table (per dataset)
- `trim_scope_warning` count
- `mono_trim_issue_pct` — fraction of issues where all evidence comes from one trim

### Acceptance criteria

1. Re-run VW Golf Mk7: `mono_trim_issue_pct` reported; at least the 6 explicit "Golf R Problems" / "GTI Engine Issues" titled issues are scoped to GTI/R not `all_vw_golf_mk7`.
2. Re-run Clio Mk4: no regressions (trim_distribution stays dominated by `base`, recall ≥ 85.7%, precision ≥ 39.6%).
3. Benchmark JSON gains `trim_stats` block; recall on Golf ≥ 85.7% (no loss), precision ideally > 28.7%.
4. New / changed fields documented in `agents.md` §7 (YouTube Bias Guardrails).

### Files to touch

- `scripts/postprocess_youtube_issues.py` — stages A/B/C
- `scrapers/fetch_youtube_car_issues.py` — stage D (query list only)
- `benchmark_knowledge.py` — stage E
- `agents.md` §7 — update guardrails
- `reports/youtube_postprocess_audit_*.md` — regenerate

### Out of scope (follow-up TODOs)

- Cross-language transcript extraction for EU-market diesel coverage.
- Forum-signal fusion to offset YouTube skew (already partly covered by STM-UK work).

---

## TODO-003 — Discovery-layer bias reduction (view cap + relevancy pre-filter)

**ID:** `TODO-003-discovery-prefilter`
**Status:** in progress (2026-04-18, Claude)
**Affects:** `scrapers/fetch_youtube_car_issues.py`

### Why

`TODO-002` fixes bias downstream. This TODO fixes it upstream so we don't pay transcript bandwidth and LLM tokens on low-signal videos in the first place. On `vw_golf_mk7`, viral "buyer's guide" list videos (100k–500k views) contribute 7–14 extracted issues each and dominate the evidence — they should never have entered the transcript queue.

### Changes

1. **Lower default `max_view_count` from 300,000 → 150,000.** Niche mechanic content (20k–100k) is the target; 150k still leaves headroom for legit mid-view content on less-popular models without re-admitting viral list videos.
2. **Add `relevancy_prefilter()`** in `scrapers/fetch_youtube_car_issues.py`, runs inside `filter_and_rank_candidates` after view-cap, before ranking. Model-agnostic rules only (model-specific trim rules belong in scaffolds per `agents.md` §2):
   - **reject** if title matches `_LIST_FORMAT_SIGNALS` AND `view_count > 100_000` AND NOT `_is_mechanic_niche` (kills viral buyer's guides; keeps niche list content).
   - **reject** if title matches hype/entertainment markers (`drag race`, ` vs `, `0-60`, `0 to 60`, `top speed`, `stage 1|2|3`, `tuned`, `modified`, `dyno`, `acceleration`) AND NOT any fault/ownership marker.
   - **always accept** if `_is_mechanic_niche` fires (overrides all rejects).
   - Log `Pre-filter rejected N/M candidates` with reason counts.
3. **CLI flag** `--disable-prefilter` for A/B comparison runs.
4. **Emit rejected list** to `out_dir / f"{slug}_rejected.json"` so we can audit.

### Acceptance

- Dry-run on `vw_golf_mk7`: `_rejected.json` contains at least the three "14x/13x/9x buyer's guide" titles from `reports/frequency_bias_analysis.md`.
- Dry-run on `renault_clio_mk4`: ≤ 20% of candidates rejected (the model's candidate pool is mostly organic already — high reject rate would mean the filter is too aggressive).
- Re-run full pipeline on `vw_golf_mk7`: `mention_count=1` share drops below the current 78%.

### Out of scope

- Trim/variant filters (GTI/R) — those are scaffold-driven and handled in TODO-002.
- Language-side rebalancing.

---

## TODO-004 — Token Efficiency (Pass 1 & Pass 2 optimization)

**ID:** `TODO-004-token-efficiency`
**Owner:** Gemini/Copilot
**Affects:** `scripts/extract_youtube_issues.py`

### Problem
Knowledge extraction currently consumes significant tokens due to redundant scaffold context and verbose JSON structures in intermediate stages. Pass 1 sends the full scaffold for every video (~1k-2k tokens), and Pass 2 sends a massive raw JSON blob that often contains duplicate strings and long descriptions.

### Proposed changes
1. **Optimize Scaffold Injection (Pass 1):** 
   - Move `scaffold_context` to the **System Prompt** to leverage DeepSeek's prompt caching more effectively (already started, but ensure it's the *first* block).
   - Create a `min_scaffold_context` (engine/tx codes only) for Pass 1, and only use the full descriptive scaffold in Pass 2.
2. **Compact Pass 2 Input Format:**
   - Instead of sending a full JSON array of raw issues to Pass 2, convert them to a **headerless CSV or a Minified JSON-without-keys** (e.g., a list of values if the schema is fixed). 
   - Remove redundant `source_title` and `source_channel` from Pass 2 *input* (they are already in the Pass 1 cache; Pass 2 only needs `source_video_id` to link them).
3. **Refine Output Schema (Pass 1):**
   - Reduce Pass 1 output to absolute essentials: `issue_id`, `system`, `affected_engines`, `verbatim_year`, `symptom`. 
   - Let Pass 2 (the "Editor" phase) handle the generation of `label`, `cause`, and `fix` by looking at the combined evidence.
4. **Adaptive Context Window:**
   - If the `triage_video` hit ratio is high (e.g., > 0.15), use a *smaller* transcript window (e.g., 1500 words instead of 2500) as the signal is likely concentrated.

### Acceptance
- Total token cost for `vw_golf_mk7` run decreases by ≥ 30% compared to 2026-04-18 baseline.
- No loss in Ground Truth recall (stays ≥ 85.7%).
- Metrics summary confirms lower `tokens_per_video` average.

---

## TODO-005 — Unified pipeline orchestrator

**ID:** `TODO-005-run-pipeline`
**Owner:** Claude (cross-agent contract)
**Affects:** new `scripts/run_pipeline.py`

### Why
Every agent (Claude / Gemini / Copilot) currently invokes the four pipeline stages (scrape → extract → postprocess → benchmark) with ad-hoc flags. Runs diverge. We need a single canonical entry-point so outputs are comparable across agents and runs are reproducible.

### Design
Single driver shelling out to existing scripts — **no logic duplication**, no framework.

Stages (all opt-out-able, all skip-if-output-exists unless `--force`):
1. **scrape** → `scrapers/fetch_youtube_car_issues.py --car "{car}" --slug {slug}` → `data/raw/videos/{slug}_raw.json`
2. **extract** → `scripts/extract_youtube_issues.py --slug {slug}` → `data/processed/issue_knowledge_youtube_{slug}.json` (+ `_confirmed`, `_year_enriched`)
3. **postprocess** → `scripts/postprocess_youtube_issues.py --slug {slug}` → `_final.json` + `reports/youtube_postprocess_audit_{slug}.md`
4. **benchmark** → `python benchmark_knowledge.py` (global, runs over all known datasets)

### CLI
```
python scripts/run_pipeline.py --car "VW Golf MK7" [--slug vw_golf_mk7]
    [--skip scrape,extract,postprocess,benchmark]
    [--resume-from extract]
    [--force]
    [--disable-prefilter]     # passthrough to scrape
    [--max-views 150000]      # passthrough to scrape
    [--max-videos 30]         # passthrough to scrape
```

### Behaviour
- Logs to `data/processed/_pipeline_{slug}.log` + stdout.
- Writes `data/processed/_pipeline_{slug}_manifest.json`: per-stage start/end, exit code, command used, output-file mtimes.
- Fail fast: if any stage exits non-zero, stop and report.
- Skip-if-exists: if target output already newer than input, skip unless `--force`.

### Acceptance
- One command rebuilds a car's outputs end-to-end.
- Manifest JSON allows another agent to diff two runs.
- No new dependencies (`subprocess` + `pathlib` + `argparse` only).
