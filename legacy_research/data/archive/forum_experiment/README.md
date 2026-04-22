# Forum Experiment Archive

This folder preserves legacy artifacts from the forum-first phase.

## Why this exists
- Forum data remains useful for issue frequency and symptom prevalence.
- The project is now moving to a video-transcript source strategy for richer root-cause detail.
- These files are retained for final report comparisons and reproducibility.

## Contents
- `root_legacy/`: original root-level exports moved here during project reorganization.
- Canonical forum inputs now live under `data/processed/forums/`.

## Notes
- STM and BERTopic scripts now resolve forum CSVs from `data/processed/forums/` first.
- Legacy root paths are still supported as fallback for compatibility.
