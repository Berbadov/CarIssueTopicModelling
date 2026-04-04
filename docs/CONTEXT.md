# LemonAid — STM Data Pipeline: Claude Code Handoff

> Note: This is a historical handoff snapshot. Current runnable STM entry points were moved to `pipelines/stm/python/` and `pipelines/stm/r/`, and forum canonical inputs were moved to `data/processed/forums/`.

## What This Project Is

A **data pipeline** for a second-hand car ad analyzer (lemonaid-app). The end goal is a
structured, LLM-interpreted knowledge base of known car issues extracted from car forum data,
linkable to engine/generation and mileage ranges. Two parallel corpora:
- **Turkish** (`golftutkusu.com`) — primary corpus, further along in pipeline
- **UK English** (`golfgtiforum.co.uk`) — secondary corpus, STM in progress

This context covers only the **data building side** — not the app, API, or storage layer.

---

## What Has Already Been Done

### 1. Scraping

**Turkish corpus (`golftutkusu.com`)**
- Scrapers: `scrapers/scrapeMain.py`, `scrapers/cleaner.py`, `scrapers/link_extractor.py`
- Output: `cleaned_messages.csv` (~1,978 threads after cleaning)
- Columns: `thread_name, thread_url, engine_code, message, reason`

**UK corpus (`golfgtiforum.co.uk`)**
- Scrapers: `scrapers/scraper_uk.py`, `scrapers/cleaner_uk.py`, `scrapers/link_extractor_uk.py`
- Output: `cleaned_messages_uk.csv` (~52,077 message rows → ~7,163 threads after aggregation)
- Columns: `thread_name, thread_url, engine_code, message, reason`
- Engine codes use generation labels: `MK5`, `MK6`, `MK7`, `MK7.5`, `MK8`
- Mileage is in **miles** (UK forum); extraction logic handles miles + km fallback

Both corpora:
- Thread name and first message carry most signal
- Later messages are lower-density discussion

### 2. Vehicle Knowledge Scaffold

**File:** `data/scaffolds/vw_golf.yaml`

Structured YAML of VW Golf Mk5–Mk7 known issues, linked to STM topics.
- `meta` — make/model/generation
- `year_cohorts` — named year bands (pre_2014 = EA111, 2014–2018 = EA211, 2018+ = evo)
- `engine_families` — EA111, EA211, EA189, EA288 with `displacements`, `year_range`, `known_issues[]`
- `transmissions` — DQ200 (7-speed dry DSG), DQ250 (6-speed wet DSG), MQ350 (manual)
- `stm_topic` links in known_issues point to Turkish corpus topic IDs (Turkish STM is complete)

Do not overwrite this file; it is the authoritative vehicle domain knowledge base.

### 3. Turkish STM Topic Modeling (R) — COMPLETE

- Script: `R_code_STM.R`
- Preprocessing: Turkish stopwords (`turkce-stop-words.txt`), custom stopword list,
  bigram detection, compound term dictionary, cosmetic/infotainment thread filtering
- Final model: **K=20 topics**, Spectral init, 500 EM iterations
- Prevalence covariates: `reason + engine_group + technical_bucket`
- K selection: custom parallel exclusivity/coherence scan (future_map), K=4,6,8,10,12 candidates
- Outputs in `data/processed/` (no `_uk` suffix):
  - `stm_plots.pdf`, `stm_results.xlsx`, `stm_top_terms_frex.csv`
  - `stm_thread_topics.csv`, `stm_thread_topic_vectors.csv`
  - `llm_issue_input.csv`, `stm_effect_summary.txt`
  - `stm_k_metrics.csv`, `stm_k_summary.csv`

**Turkish topic quality:** Clean and mechanically coherent. Do not retrain.

| Topic | FREX terms (top) | Likely label |
|-------|-----------------|--------------|
| T1 | tdi, enjektor, dizel, mazot | Diesel injector issues |
| T2 | devirdaim, antifriz, sogutma, termostat | Cooling system |
| T3 | triger, turbo, bagaj | Timing / turbo |
| T4 | klima, rot, amortisor, direksiyon | Suspension / steering / HVAC |
| T5 | dsg, vites, sanziman, kavrama | DSG / gearbox |
| T6 | titreme, dpf, rolantide, rejenerasyon | DPF / idle vibration |
| T7 | tsi, balata, eksiltme | TSI petrol / brakes |
| T8 | ariza, lambasi, 1.2 | Warning lights / electrics |
| T9 | aku, varta, efb, agm, sarj | Battery |
| T10 | far, led, sensoru, kablo | Lighting / sensors |

### 4. UK STM Topic Modeling (R) — IN PROGRESS

- Script: `R_code_STM_uk.R`
- Source: `cleaned_messages_uk.csv`
- Preprocessing: quanteda English stopwords + extra forum stopwords, bigram detection,
  compound terms via `tokens_compound`, cosmetic/infotainment filtering (same logic as Turkish)
- K selection: `searchK()` with K ∈ {10, 15, 20, 25, 30}
- Planned K: 20
- Engine groups: `MK5`, `MK6`, `MK7`, `MK7.5`, `MK8`, `2.0_TSI`, `1.4_TSI`, `Golf_R`, `unknown`, `other`
- Mileage: extracted in miles, stored as `mileage_mentioned` (miles), log-transformed for STM
- Prevalence covariates: `engine_group_fac + mileage_log + technical_bucket`
- Outputs (planned, `_uk` suffix): `stm_results_uk.xlsx`, `stm_thread_enriched_uk.csv`,
  `stm_topic_engine_effects_uk.csv`, `llm_issue_input_uk.csv`, `stm_k_metrics_uk.csv`,
  `stm_plots_uk.pdf`

**Key bug fixed (2026-03-27):** `quanteda::convert(dfDfm, to="stm")` silently drops empty
DFM rows inside `dfm2stm()`, causing `out_converted$documents` to be shorter than `df`.
The `prepDocuments$docs.removed` indices then refer to the wrong frame → covariate mismatch
error. Fix: explicitly remove empty rows from both `dfDfm` and `df` before calling `convert()`.

### 5. LLM Issue Knowledge (Python) — COMPLETE for Turkish

- Script: `scripts/generate_issue_knowledge.py`
- Uses DeepSeek API (`deepseek-chat` model via OpenAI-compatible SDK)
- Reads Turkish STM outputs, sends per-topic context bundle to LLM, gets structured JSON back
- Output: `data/processed/issue_knowledge.json`, `data/processed/issue_knowledge.csv`

### 6. Turkish Metadata Extraction Diagnostic

```
Field extraction rates (Turkish corpus):
  year             903 / 1,978  (45.7%)
  hp                75 / 1,978   (3.8%)   ← too low to use
  displacement     535 / 1,978  (27.0%)
  mileage_km       250 / 1,978  (12.6%)

Engine family resolution: 2.1% (42 threads)  ← abandoned
```

Engine family disambiguation was abandoned. Use displacement + year as loose tags.

---

## Key Architectural Decisions (Do Not Revisit)

| Decision | Reason |
|----------|--------|
| Keep Turkish STM output as-is | Topics are coherent, retraining adds no value |
| Drop engine family resolution | 2.1% coverage, statistically useless |
| Use displacement (TR) / MK-gen (UK) not engine code | Sufficient coverage for topic-level patterns |
| Turkish corpus stays in Turkish | Zeyrek handles morphology for RAG |
| Don't translate forum text | Translation adds error layer |
| Metadata comes from the ad, not the forum | Sahibinden ads have clean year/km/displacement |
| UK uses MK-generation labels, not engine codes | UK forum users write MK7/MK8 not EA codes |
| UK mileage in miles, not km | Stored as miles; convert if comparing with Turkish |

---

## What Needs to Be Built

### UK STM — run to completion
1. Fix applied to `R_code_STM_uk.R` (empty-doc alignment bug) — run the script
2. Inspect `stm_k_diagnostics_uk.pdf` and `stm_k_metrics_uk.csv` to confirm K=20
3. Review UK topic FREX terms; update `vw_golf.yaml` `stm_topic` links with UK topic IDs

### UK LLM Issue Knowledge
- Adapt `scripts/generate_issue_knowledge.py` for UK outputs (different mileage unit, MK labels)
- Output: `data/processed/issue_knowledge_uk.json`

### Idea (not to be built yet) — Turkish Morphology for RAG (Zeyrek)
`scripts/lemmatize_threads.py` — lemmatize before Chroma indexing so "motorundan" → "motor".
Not needed for STM. Needed for app pipeline Chroma indexing step.

---

## File Map

```
R_code_STM.R                       ← Turkish STM pipeline (COMPLETE)
R_code_STM_uk.R                    ← UK STM pipeline (in progress, bug fixed)
turkce-stop-words.txt              ← Turkish stopwords
cleaned_messages.csv               ← Turkish scraped messages
cleaned_messages_uk.csv            ← UK scraped messages (~52k rows)
data/scaffolds/vw_golf.yaml        ← Vehicle knowledge scaffold (authoritative)
data/processed/                    ← All STM outputs (Turkish + UK with _uk suffix)
scrapers/                          ← All scraper scripts (TR + UK)
scripts/generate_issue_knowledge.py ← LLM labeller (Turkish, complete)
```

---

## API Details

- Model: `deepseek-chat` on `https://api.deepseek.com`
- One API call per topic (~10–20 total) — cheap, no batching needed
- Response must be JSON only, no markdown fences
- Include retry logic (max 3 attempts) per topic
- If a topic fails, write null record and continue — don't abort the whole run
- Log raw LLM response before parsing in case of JSON errors

---

## Turkish Automotive Domain Notes

- `tıkırtı` = knocking/ticking sound
- `vuruntu` = knocking (usually engine bearing)
- `rölanti` = idle
- `ısınma` = warmup
- `triger` = timing belt/chain
- `devirdaim` = water pump
- `mekatronik` = DSG mechatronic unit (expensive, common Golf 6/7 failure)
- `hata kodu` = fault code / DTC
- `epc lambası` = EPC warning light (common TSI)
- `dpf` = diesel particulate filter
- `rejenerasyon` = DPF regeneration cycle
- `akü` / `aku` = battery (ü/u variants both common in informal writing)
- `balata` = brake pad
- `salıncak` = control arm / wishbone
- Mileage often written as `"150 bin km"`, `"150.000 km"`, or `"150k"`

---

## What NOT to Do

- Do not retrain or rerun the Turkish STM model
- Do not attempt engine family (EA111/EA211) resolution — abandoned, 2.1% coverage
- Do not translate forum text to English
- Do not use BERTopic (tried, too slow, doesn't leverage thread structure)
- Do not add K > 20 for UK — at higher K slots absorbed cosmetic/infotainment noise
- Do not store raw scraped text without PII scrubbing (plates, phones)
- Do not overwrite `data/scaffolds/vw_golf.yaml` — it is the authoritative vehicle knowledge base
