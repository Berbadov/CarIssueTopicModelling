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
