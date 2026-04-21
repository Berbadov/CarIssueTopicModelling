# Project Context (Condensed)

This is the shared rulebook for Claude, Gemini, and Copilot in this repo. Keep this file compact and current.

## 1) Core Principle (Non-Negotiable)

Goal: discover **unknown** car issues from broad YouTube/forum data using only a car model seed (for example, "VW Golf MK7").

Do **not** presuppose specific failures in search queries or prompts. If we already name the issue, discovery value is lost.

## 2) Hard Prohibitions

1. No issue-specific discovery queries (component/failure-level targeting).
2. Do not reintroduce `topic_buckets`-style hardcoded issue queries in `scrapers/fetch_youtube_car_issues.py`.
3. Do not overwrite `data/scaffolds/vw_golf.yaml` blindly; it is authoritative.

Rule of thumb: if removing the car model from a query still leaves a specific fault (for example "PCV failure"), it is too specific.

## 3) Query Rules

Allowed (model-level):
- "{car} problems"
- "{car} common issues"
- "{car} review"
- "{car} ownership experience"
- "{car} mechanic workshop"
- "{car} things that break"

Not allowed (issue-level):
- "{car} 1.4 TSI oil consumption problem"
- "{car} PCV valve failure"
- "{car} DSG mechatronic failure"

## 4) Pipeline Contract

1. Discover broad videos/posts by model name.
2. Fetch transcripts/text.
3. Run topic modeling (STM/BERTopic).
4. Label/extract structured issues with LLM.
5. Output evidence-linked knowledge base (CSV/JSON).

## 5) Current Status (High Signal)

- Turkish forum STM pipeline: complete and stable; do not retrain without explicit reason.
- UK STM pipeline: in progress.
- UK STM bug to remember: remove empty DFM rows **before** `convert(..., to="stm")` to keep document/covariate alignment.

## 6) Non-Revisit Decisions

1. Keep Turkish corpus in Turkish.
2. Do not translate forum text for STM.
3. Use displacement+year (TR) and MK-generation labels (UK) instead of sparse engine-code resolution.
4. UK mileage is in miles (convert only when explicitly comparing cross-corpus).
5. Metadata quality comes primarily from ad/platform metadata, not noisy forum prose.

## 7) YouTube Bias Guardrails (Required)

In `scripts/extract_youtube_issues.py`:

1. Normalize evidence from `source_videos` (or fallback single-source fields) before scoring.
2. If `video_type_category` is missing, infer from title signals:
   - `list_format` (buyer's guide/common issues/avoid buying/etc.)
   - `organic` (owner/mechanic/experience content)
3. Keep separate counters:
   - `mention_count`: distinct video mentions
   - `distinct_channel_count`: distinct channels
   - `corroboration_count`: independent corroboration (`organic` mentions + one `list_format` credit per channel/source)
4. Use `corroboration_count` for confirmed filtering; do not treat `mention_count` alone as confidence.
5. In post-process, infer per-source `trim` from video title and emit per-issue `trim_evidence` plus `dominant_trim` (`mixed` if top trim <= 50%).
6. If an issue is mono-trim GTI/R evidence on Golf Mk7, scope it to `golf_gti_mk7` or `golf_r_mk7`, restrict engine scope to `2.0_TSI`, and mark `trim_scope_warning: true`.
7. Keep `corroboration_count` unchanged in meaning; also emit `cross_trim_corroboration_count` for independent corroboration from non-dominant trims.

## 8) Key Files

- `scrapers/fetch_youtube_car_issues.py` - broad model-level video discovery
- `scripts/extract_youtube_issues.py` - extraction/consolidation and corroboration logic
- `scripts/generate_issue_knowledge.py` - STM topic -> issue knowledge generation
- `data/scaffolds/vw_golf.yaml` - authoritative scaffold
- `data/raw/videos/` - raw video/transcript dumps
- `data/processed/` - generated outputs

## 9) Operational Notes

- DeepSeek endpoint/model: `https://api.deepseek.com` / `deepseek-chat`
- LLM responses should be JSON-only (no markdown fences)
- Use retry logic and continue-on-topic-failure behavior for batch robustness
- Use Gemini CLI as a secondary reviewer for factuality checks and explicit "missing issues" prompts (ask it what likely issues may be missing from current output).

## 10) Maintenance Rule

When project behavior or constraints change, update this file in-place with a concise delta.

## 11) RAG Path

Pass-1 LLM extraction (`extract_youtube_issues.py`) is deprecated for the YouTube pipeline but kept on disk for the TR forum STM path.

**Chunk store:** `data/processed/chunks/{slug}_chunks.jsonl` → `{slug}_chunks_tagged.jsonl`
**Vector store:** `data/vector_store/chroma/` (ChromaDB, persistent)
**Embedding model:** `intfloat/multilingual-e5-base` — requires prefix `"passage: "` at index time, `"query: "` at query time.

**Component knowledge layer:** each engine family code (K9K, EA211, EA288, DQ200…) and transmission code gets its own Chroma collection (`component_K9K`, `component_DQ200`, etc.) scraped without a model prefix. `rag_answer.py` queries these at tier 0 (capped to tier 2) before car-level collections, providing cross-brand engine evidence.

Build a component corpus:
```
python scripts/build_component.py --code K9K --scaffold renault_clio_mk4 --lang en --max-per-term 30
```

Build all component corpora defined in a scaffold:
```
python scripts/build_component.py --all-from-scaffold --scaffold renault_clio_mk4 --lang en --max-per-term 30
```

`build_component.py` now scopes scraping terms per target component code (instead of all scaffold entities) and expands neutral entity query templates for better component coverage.
It also supports automation/perf flags: `--workers`, `--search-workers`, `--transcript-workers`, `--chunk-workers`, `--resume`, and `--continue-on-error`.
For generation-split families (e.g. EA111 vs EA211), component search terms now include `family + displacement alias` combinations (e.g. `EA211 1.4 TSI`) to reduce cross-generation mixing.

**Tier definitions for retrieval:**
  - tier 1: chunk.engines ∩ spec.engines (exact displacement match)
  - tier 2: chunk.engine_families ∩ spec.engine_families (family match, also used for component hits)
  - tier 3: chunk.fuel_types ∩ spec.fuel_types
  - tier 4: no filter (general model content)
