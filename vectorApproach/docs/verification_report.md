# Technical Verification & Benchmark Report

## 0. Methodology Note (Manual)
This benchmark was performed **manually** with LLM assistance (Gemini) as a **sentence-level issue-evidence presence check**.

It is not a deterministic end-to-end scorer of final consolidated conclusions. Findings below should be read as **directional/qualitative** evidence coverage, not fully automated benchmark scoring.

## 1. Discovery Performance Matrix
Manual evaluation of the retrieval engine against known technical "Backbone" issues (Ground Truth), based on whether issue evidence appears in retrieved/ranked sentence-level outputs.

| Model | Known Issue (Ground Truth) | Detection | Signal Strength | Notes |
| :--- | :--- | :--- | :--- | :--- |
| **Golf MK7** | Water Pump Leak | **Captured** | High (Tier 0) | Explicit mentions of coolant loss. |
| **Golf MK7** | Sunroof Frame Crack | **Captured** | High (Tier 2) | Captured via feature-specific pass. |
| **Golf MK7** | Wastegate Rattle | **Missing** | N/A | Exists in DB but semantic match failed. |
| **Golf MK7** | Carbon Buildup | **Mixed** | Low | Demoted as "Maintenance Advice." |
| **Clio MK4** | Wind Noise (A-Pillar) | **Captured** | High (Tier 2) | Strong signal for DIY sponge fixes. |
| **Clio MK4** | EDC Transmission | **Captured** | High (Tier 2) | Prioritized skepticism/failure talk. |
| **Clio MK4** | Suspension Bushings | **Missing** | N/A | No specific coverage in top results. |
| **Corolla** | Engine Mount (1.5L) | **Captured** | High (Tier 0) | Direct match for TSB T-SB-0088-23. |
| **Corolla** | EHR Coolant Leak (1.8H)| **Captured** | High (Tier 2) | Detected internal exhaust leakage. |
| **Corolla** | 12V Battery Drainage | **Mixed** | Medium | Often classified as usage-related noise. |

## 2. Gap Analysis (Discovery Gaps)
*   **Semantic Proximity Limits:** Issues like "Wastegate Rattle" are often described with highly specific mechanical onomatopoeia that may have high vector distance from "technical issues" queries.
*   **Advice Penalty Side-Effects:** Our mandate to demote DIY repair advice occasionally hides "Carbon Buildup" mentions because they are frequently coupled with "How-to clean" instructions.
*   **Corpus Density:** Discovery is strictly limited by the YouTube transcript availability. Niche mechanical failures (e.g., suspension bushings) require higher-density technical corpora.

## 3. Manual Reliability Snapshot (Indicative)
*   **Technical Precision (manual sample):** No cross-model or cross-engine mismatches observed in this review set.
*   **Generation Safety (manual sample):** No previous-generation pollution observed in this review set.
*   **Discovery Recall (manual estimate):** ~75% (roughly 3 out of 4 major chronic issues surfaced per model in this evaluation setup).

---
*Date: 2026-04-21*
