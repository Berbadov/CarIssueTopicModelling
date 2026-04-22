# STM ELBO Divergence — Debug Report
*Date: 2026-04-04*

## Status: Unresolved (source data issue — session paused)

---

## What the Python STM pipeline does

`stm/` is a PyTorch+CUDA port of R's `stm` package.  
Pipeline: spectral init → variational EM (Newton E-step, OLS M-step) → FREX topic labels → LLM interpretation.

Run scripts: `pipelines/stm/python/run_stm_clio.py`, `pipelines/stm/python/run_stm_turkish.py`, `pipelines/stm/python/run_stm_uk.py`

---

## The bug

ELBO diverges catastrophically after iteration 1 on every corpus tested (Clio shown):

```
EM  1: ELBO = -1,557,179   ← best (saved to best_state)
EM  2: ELBO = -15,266,380  ← 10× worse
EM  3: ELBO = -7,998,963
EM  4: ELBO = -8,183,485
...
EM 16: Converged near -14,000,000
Best ELBO = -1,557,179
```

The model "works" because `best_state` tracking saves iter-1 parameters, but EM never improves beyond the first iteration. Effectively running spectral init only.

---

## Root cause (partially diagnosed)

Three contributing factors, all partially fixed:

### 1. ELBO computed after M-step (FIXED in session)
**Old:** ELBO(q_t, θ_t) — q was optimised for θ_{t-1} but evaluated under θ_t. Not monotone.  
**Fix:** Move ELBO computation to before M-step → ELBO(q_t, θ_{t-1}).  
**Result:** Didn't stop divergence, but diagnostic is now correct.

### 2. Beta smoothing near-zero (FIXED in session)
**Old:** `beta_num + 1e-9` — essentially no smoothing. Topics collapse to a handful of words after iter 1's M-step.  
**Fix:** `beta_num + 1.0/K` — matches R STM's Dirichlet prior equivalent.  
**Result:** Insufficient. After M-step 1, rare words still get probability ≈ 5e-6, giving log-prob ≈ -12 nats (below uniform).

### 3. Newton clamp too loose (FIXED in session)
**Old:** `delta.clamp(-2.0, 2.0)` — allows large overshoots when beta is peaked.  
**Fix:** `delta.clamp(-1.0, 1.0)`  
**Result:** Helped, but divergence persists.

### 4. Warm-start mu_init too extreme (FIXED in session)
**Diagnosis:** `mu_init` range was **-13.82 to +13.82** (spectral scores in logit space).  
Documents strongly matching one topic get theta → 0.99, mu → ±7+.  
These near-one-hot assignments make M-step produce hyper-peaked beta.  
**Fix:** `mu = mu_init.clamp(-2.0, 2.0)` — caps initial logits at ±2 (max topic weight ≈ 0.35).  
**Result:** Reduced but didn't eliminate divergence. KL term still explodes at iter 2.

---

## What was NOT tried yet

- **Diagonal Hessian** instead of full Hessian in Newton E-step. R's STM uses diagonal approximation. Full Hessian may produce coupled Newton steps that overshoot despite element-wise clamp.
- **Corpus-frequency beta smoothing**: `pseudocount = word_freq * scale` so common words are never near-zero probability in any topic, regardless of assignment concentration.
- **Reducing Newton iterations** from 5 to 2-3 for more conservative E-step updates.
- **EMA beta update**: blend new beta with previous to prevent sudden topic concentration.

---

## Key numbers (Clio corpus)

| Stat | Value |
|------|-------|
| Documents (threads) | 1,540 |
| Vocabulary | 12,795 terms |
| Total tokens | 187,247 |
| Avg doc length | 121.6 tokens |
| K (topics) | 15 |
| Design matrix | 1,540 × 11 |

---

## Current state of files

All changes in session are **uncommitted**. `stm/` is entirely untracked.

Files modified in session:
- `stm/core.py` — ELBO moved before M-step, beta smoothing 1/K, Newton clamp ±1.0, mu_init clamp ±2.0

Outputs that exist (from previous run, committed):
- `data/processed/issue_knowledge_clio.json` — 15-topic Clio knowledge base (built from iter-1 solution)
- `data/processed/stm_top_terms_frex_clio.csv` — FREX labels

---

## Decision

User paused debugging — Clio forum source data is considered insufficient/low-quality for the intended use. Moving to YouTube video transcripts as the new data source.

Next session should start fresh with the YouTube scraping/transcript pipeline.
