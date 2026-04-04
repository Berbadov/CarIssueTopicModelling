#!/usr/bin/env python3
"""
run_stm_uk.py
─────────────
Python+CUDA port of R_code_STM_uk.R.

Corpus : Golf GTI Forum UK (golfgtiforum.co.uk)
K      : 20 (searchK over [10,15,20,25,30])
Mileage: miles, log-transformed
Covars : engine_group_fac + mileage_log + technical_bucket
Output : data/processed/*_uk.{csv,xlsx}

Usage:
    .venv/Scripts/python run_stm_uk.py
"""

import sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from stm.dfm import (
    DFMBuilder,
    BigramDetector,
    aggregate_threads,
    _compile,
    _simple_tokenize,
)
from stm.core import STM
from stm._output import write_outputs_uk
from stm.search_k import search_k

# ── Config ────────────────────────────────────────────────────────────────────

def _resolve_input_csv() -> Path:
    candidates = [
        ROOT / "data" / "processed" / "forums" / "cleaned_messages_uk.csv",
        ROOT / "cleaned_messages_uk.csv",
    ]
    return next((p for p in candidates if p.exists()), candidates[0])


INPUT_CSV = _resolve_input_csv()
OUT_DIR = ROOT / "data" / "processed"
K_FINAL = 20
K_RANGE = [10, 15, 20, 25, 30]
MAX_EM_ITS = 500
DEVICE = "cuda"

# ── Pattern sets (English — from R_code_STM_uk.R lines 76–108) ───────────────

TECHNICAL_PATTERNS = _compile([
    r"\bengine\b", r"\bgearbox\b", r"\btransmission\b", r"\bclutch\b",
    r"\bturbo\b", r"\binjector\b", r"\btiming\b", r"\bcambelt\b",
    r"\btiming chain\b", r"\btiming belt\b", r"\bthermostat\b",
    r"\bwater pump\b", r"\bradiator\b", r"\bdpf\b", r"\begr\b",
    r"\babs\b", r"\besp\b", r"\bspark plug\b", r"\bcoilpack\b",
    r"\bcoil pack\b", r"\bbrakes?\b", r"\bpads?\b", r"\bdisc\b",
    r"\bshock absorber\b", r"\bwishbone\b", r"\bsteering\b",
    r"\bsensor\b", r"\boil\b", r"\bleak\b", r"\bnoise\b",
    r"\bvibration\b", r"\bknock\b", r"\bsmoke\b", r"\bmisfire\b",
    r"\blimp mode\b", r"\bfault code\b", r"\bvcds\b", r"\bdsg\b",
    r"\bflywheel\b", r"\bdmf\b", r"\bcoolant\b", r"\boverheating\b",
])

CHRONIC_PATTERNS = _compile([
    r"\bkeeps?\b", r"\bstill\b", r"\brecurring\b", r"\bpersistent\b",
    r"\bongoing\b", r"\bagain\b", r"\brepeat\b", r"\bunresolved\b",
    r"\bnever fixed\b", r"\bkeep having\b", r"\bhappens again\b",
    r"\bback again\b", r"\bstill happening\b",
])

COSMETIC_PATTERNS = _compile([
    r"\brespray\b", r"\bpaintwork\b", r"\bbodywork\b",
    r"\bdent\b", r"\bscratch\b", r"\bscuff\b",
    r"\bppf\b", r"\bdetailing\b", r"\bpolish\b",
    r"\balloy refurb\b", r"\bpanel\b",
])

INFOTAINMENT_PATTERNS = _compile([
    r"\bcarplay\b", r"\bandroid auto\b", r"\bbluetooth\b",
    r"\bsat nav\b", r"\binfotainment\b", r"\bhead unit\b",
    r"\btouchscreen\b", r"\bdab\b",
])

TECHNICAL_REASON_TAGS = [
    "engine", "gearbox", "transmission", "brake", "electrical",
    "cooling", "suspension", "exhaust", "turbo", "clutch",
]

# ── Engine group mapping (from R_code_STM_uk.R lines 183–195) ────────────────

def engine_group_fn(code: str | None) -> str:
    code = str(code) if code else "unknown"
    if code in ("MK8",):           return "MK8"
    if code in ("MK7.5",):         return "MK7.5"
    if code in ("MK7",):           return "MK7"
    if code in ("MK6",):           return "MK6"
    if code in ("MK5",):           return "MK5"
    if code in ("2.0_TSI", "EA888"): return "2.0_TSI"
    if code in ("1.4_TSI", "EA211"): return "1.4_TSI"
    if code in ("Golf_R",):        return "Golf_R"
    if code == "unknown":          return "unknown"
    return "other"

# ── Stopwords (from R_code_STM_uk.R lines 236–249) ───────────────────────────

try:
    from nltk.corpus import stopwords as _nltk_sw
    EN_STOPWORDS = list(_nltk_sw.words("english"))
except Exception:
    # Minimal fallback (quanteda's English list is ~175 words)
    EN_STOPWORDS = [
        "i", "me", "my", "myself", "we", "our", "ours", "ourselves", "you",
        "your", "yours", "yourself", "yourselves", "he", "him", "his",
        "himself", "she", "her", "hers", "herself", "it", "its", "itself",
        "they", "them", "their", "theirs", "themselves", "what", "which",
        "who", "whom", "this", "that", "these", "those", "am", "is", "are",
        "was", "were", "be", "been", "being", "have", "has", "had", "having",
        "do", "does", "did", "doing", "a", "an", "the", "and", "but", "if",
        "or", "because", "as", "until", "while", "of", "at", "by", "for",
        "with", "about", "against", "between", "into", "through", "during",
        "before", "after", "above", "below", "to", "from", "up", "down",
        "in", "out", "on", "off", "over", "under", "again", "further",
        "then", "once", "here", "there", "when", "where", "why", "how",
        "all", "both", "each", "few", "more", "most", "other", "some",
        "such", "no", "nor", "not", "only", "own", "same", "so", "than",
        "too", "very", "s", "t", "can", "will", "just", "don", "should",
        "now", "d", "ll", "m", "o", "re", "ve", "y", "ain", "aren",
        "couldn", "didn", "doesn", "hadn", "hasn", "haven", "isn", "ma",
        "mightn", "mustn", "needn", "shan", "shouldn", "wasn", "weren",
        "won", "wouldn",
    ]

EXTRA_STOPWORDS = [
    # Forum meta
    "post", "thread", "forum", "reply", "quote", "edited", "page",
    "member", "joined", "posts", "golfgtiforum",
    # Generic filler
    "just", "also", "get", "got", "know", "think", "would", "could",
    "really", "thing", "bit", "lot", "way", "time", "one", "two",
    "going", "like", "use", "used", "using", "new", "old",
    "car", "golf", "gti",
    # Forum phrases
    "anyone", "lol", "cheers", "thanks", "mate",
    "tbh", "imo", "afaik", "iirc", "fwiw",
]

ALL_STOPWORDS = list(set(EN_STOPWORDS + EXTRA_STOPWORDS))


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    print("=" * 60)
    print("run_stm_uk.py — Golf GTI Forum UK STM")
    print("=" * 60)

    # ── 1. Load data ──────────────────────────────────────────────────────────
    print(f"\nLoading {INPUT_CSV}…")
    df_raw = pd.read_csv(INPUT_CSV)
    print(f"  Raw messages: {len(df_raw)}")

    # ── 2. Thread aggregation ─────────────────────────────────────────────────
    print("\nAggregating threads…")
    df = aggregate_threads(
        df_raw,
        mileage_mode="miles",
        technical_patterns=TECHNICAL_PATTERNS,
        chronic_patterns=CHRONIC_PATTERNS,
        cosmetic_patterns=COSMETIC_PATTERNS,
        infotainment_patterns=INFOTAINMENT_PATTERNS,
        technical_reason_tags=TECHNICAL_REASON_TAGS,
        engine_group_fn=engine_group_fn,
        cosmetic_filter=True,
        clio_mode=False,
    )

    # ── 3. UK-specific metadata columns ──────────────────────────────────────
    # mileage_log: log1p of miles (impute 0 for missing)
    df["mileage_has"] = (~df["mileage_mentioned"].isna()).astype(int)
    df["mileage_log"] = np.log1p(df["mileage_mentioned"].fillna(0))
    df["engine_group_fac"] = df["engine_group"].astype(str)

    # ── 4. Bigram discovery ───────────────────────────────────────────────────
    print("\nDiscovering bigrams…")
    tokenized = [
        [t for t in _simple_tokenize(doc, keep_numbers=True)
         if t not in set(ALL_STOPWORDS) and t.isalpha()]
        for doc in df["txt"]
    ]
    bigram_det = BigramDetector(min_count=3, z_threshold=3.0)
    bigram_det.fit(tokenized)
    compound_terms = bigram_det.significant_bigrams()

    # ── 5. Build DFM ──────────────────────────────────────────────────────────
    print("\nBuilding DFM…")
    builder = DFMBuilder(
        stopwords=ALL_STOPWORDS,
        min_termfreq=3,
        min_docfreq=2,
        max_docfreq_prop=0.0,   # no upper limit (UK script doesn't use max_docfreq)
        min_charlen=3,
        keep_numbers=False,
    )
    count_matrix, vocab, kept_idx = builder.fit_transform(
        df["txt"].tolist(),
        compound_terms=compound_terms,
    )

    # Align df with kept_idx (empty-doc removal)
    df = df.iloc[kept_idx].reset_index(drop=True)
    print(f"  Aligned df: {len(df)} rows, vocab: {len(vocab)} terms")

    # ── 6. K selection ────────────────────────────────────────────────────────
    print(f"\nK selection over {K_RANGE}…")
    k_metrics = search_k(
        count_matrix, vocab, df,
        prevalence_formula="~ engine_group_fac + mileage_log + technical_bucket",
        k_range=K_RANGE,
        max_em_its=100,
        device=DEVICE,
        verbose=True,
    )
    print("\nK metrics:")
    print(k_metrics.to_string(index=False))

    # ── 7. Final STM ──────────────────────────────────────────────────────────
    print(f"\nFitting final STM with K={K_FINAL}…")
    stm = STM(
        K=K_FINAL,
        device=DEVICE,
        max_em_its=MAX_EM_ITS,
        verbose=True,
    )
    stm.fit(
        count_matrix,
        vocab,
        df,
        prevalence_formula="~ engine_group_fac + mileage_log + technical_bucket",
    )

    # ── 8. Write outputs ──────────────────────────────────────────────────────
    print("\nWriting outputs…")
    write_outputs_uk(stm, df, vocab, OUT_DIR, k_metrics=k_metrics)

    print("\nDone.")


if __name__ == "__main__":
    main()
