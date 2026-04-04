# CarIssueTopicModelling

Vehicle issue mining pipeline with STM, BERTopic, and structured LLM labeling.

## Current Direction

The active direction is source expansion toward video transcripts for better root-cause detail.

Forum data remains valuable as a frequency baseline and is kept as an experiment archive for the final report.

## Project Layout

### Core Code
- `scrapers/`:
	- Forum ingestion and cleaning scripts
	- Video transcript ingestion (`fetch_youtube_transcripts.py`)
- `scripts/`:
	- Topic modeling and issue-knowledge generation
- `stm/`:
	- Shared STM implementation utilities
- `pipelines/stm/python/`:
	- Python STM runner entry points
- `pipelines/stm/r/`:
	- Original R STM pipelines

### Data
- `data/raw/`:
	- External-source raw pulls
	- New video transcripts go under `data/raw/videos/`
- `data/processed/`:
	- Model-ready and model-output artifacts
	- Forum-cleaned canonical CSVs go under `data/processed/forums/`
- `data/archive/forum_experiment/`:
	- Legacy forum root-level artifacts preserved for reporting and reproducibility

### Reports and Notes
- `reports/`: comparison report source and generated report artifacts
- `docs/`: pipeline runbooks, handoff notes, and debug notes

### Testing
- `tests/`: workspace test and smoke scripts

## Canonical Paths (Post-Organization)

- Turkish forum cleaned CSV: `data/processed/forums/cleaned_messages.csv`
- UK forum cleaned CSV: `data/processed/forums/cleaned_messages_uk.csv`
- Clio forum cleaned CSV: `data/processed/forums/cleaned_messages_clio.csv`
- YouTube transcript dump: `data/raw/videos/youtube_transcripts_raw.csv`

STM scripts retain fallback support for legacy root CSV locations so old runs remain reproducible.

## Common Run Commands

- Python STM (Clio): `python pipelines/stm/python/run_stm_clio.py`
- Python STM (Turkish): `python pipelines/stm/python/run_stm_turkish.py`
- Python STM (UK): `python pipelines/stm/python/run_stm_uk.py`
- R STM (Clio): `Rscript pipelines/stm/r/R_code_STM_clio.R`
- R STM (Turkish): `Rscript pipelines/stm/r/R_code_STM.R`
- R STM (UK): `Rscript pipelines/stm/r/R_code_STM_uk.R`
