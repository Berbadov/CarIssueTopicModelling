#!/usr/bin/env python3
"""
run_stm_clio.py
───────────────
Python+CUDA port of R_code_STM_clio.R.

Corpus : Renault Clio forums (Turkish language)
K      : dynamic (10–15 based on document count)
Mileage: km
Covars : engine_group + technical_bucket (conditional)
Output : data/processed/*_clio.{csv,xlsx}

Usage:
    .venv/Scripts/python pipelines/stm/python/run_stm_clio.py
"""

import sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from stm.dfm import (
    DFMBuilder,
    aggregate_threads,
    _compile,
    extract_year,
)
from stm.core import STM
from stm._output import write_outputs_clio
from stm.search_k import search_k

# ── Config ────────────────────────────────────────────────────────────────────

def _resolve_input_csv() -> Path:
    candidates = [
        ROOT / "data" / "processed" / "forums" / "cleaned_messages_clio.csv",
        ROOT / "cleaned_messages_clio.csv",
    ]
    return next((p for p in candidates if p.exists()), candidates[0])


INPUT_CSV = _resolve_input_csv()
STOPWORDS_FILE = ROOT / "turkce-stop-words.txt"
OUT_DIR = ROOT / "data" / "processed"
MAX_EM_ITS = 300
DEVICE = "cuda"

# ── Clio engine ordering (from R_code_STM_clio.R line 111–115) ───────────────

ENGINE_ORDER = [
    "0.9_TCE", "1.0_TCE", "1.2_TCE", "1.3_TCE",
    "1.5_DCI", "1.6_DCI", "1.4_NA", "1.6_NA",
    "TCE_unknown", "DCI_unknown", "CLIO_II", "CLIO_III", "CLIO_IV", "CLIO_V", "unknown",
]

# ── Pattern sets (Clio — from R_code_STM_clio.R lines 87–109) ────────────────

TECHNICAL_PATTERNS = _compile([
    r"\bmotor\b", r"\byag\b", r"\beksiltme\b", r"\bturbo\b", r"\bintercooler\b",
    r"\btriger\b", r"\bzincir\b", r"\bdevirdaim\b", r"\btermostat\b",
    r"\bhararet\b", r"\bradyator\b", r"\bsogutma\b", r"\benjektor\b",
    r"\bdpf\b", r"\begr\b", r"\badblue\b", r"\bkizdirma\b",
    r"\bsanziman\b", r"\bvites\b", r"\bdebriyaj\b", r"\bkavrama\b", r"\bmekatronik\b",
    r"\bbobin\b", r"\bbuji\b", r"\bsensor\b", r"\brolanti\b", r"\btekleme\b",
])

CHRONIC_PATTERNS = _compile([
    r"\bkronik\b", r"\bsurekli\b", r"\btekrar\b", r"\btekrarlayan\b",
    r"\bduzelmedi\b", r"\bcozulmedi\b", r"\bdevam\s+ediyor\b",
])

COSMETIC_PATTERNS = _compile([
    r"\bkaporta\b", r"\bboya\b", r"\bgocuk\b", r"\bcizik\b", r"\btramer\b",
    r"\bpasta\s*cila\b", r"\bdetailing\b", r"\bppf\b",
])

INFOTAINMENT_PATTERNS = _compile([
    r"\bmultimedya\b", r"\bcarplay\b", r"\bandroid\s*auto\b",
    r"\bbluetooth\b", r"\bnavigasyon\b", r"\bteyp\b",
])

TECHNICAL_REASON_TAGS = [
    "engine", "motor", "transmission", "brake", "electrical", "cooling",
]

CUSTOM_STOPWORDS_CLIO = [
    "clio", "renault", "arac", "araba", "forum", "arkadaslar", "arkadas",
    "merhaba", "tesekkur", "hocam", "abi", "model", "kasa",
]

# ── Engine group mapping (from R_code_STM_clio.R lines 162–167) ──────────────

def engine_group_fn(code: str | None, engine_spec: str | None = None) -> str:
    spec = str(engine_spec) if engine_spec and engine_spec != "nan" else None
    c = str(code) if code and code != "nan" else "unknown"

    if spec and spec in ENGINE_ORDER:
        return spec
    if c in ("CLIO_II", "CLIO_III", "CLIO_IV", "CLIO_V"):
        return c
    return "unknown"


# Wrapper that uses engine_spec column when available
_EG_FN_SIMPLE = lambda code: engine_group_fn(code)


# ── Dynamic K selection (from R_code_STM_clio.R lines 256–267) ───────────────

def determine_k(n_docs: int) -> tuple[int, list[int]]:
    if n_docs >= 500:
        k_final = 15
    elif n_docs >= 250:
        k_final = 12
    else:
        k_final = 10
    k_final = min(k_final, max(5, n_docs // 4))
    k_final = max(5, k_final)
    k_candidates = sorted(set([max(5, k_final - 3), k_final]))
    return k_final, k_candidates


# ── Dynamic prevalence formula (from R_code_STM_clio.R lines 244–254) ────────

def build_prevalence_formula(df: pd.DataFrame) -> str:
    has_engine = df["engine_group"].nunique() > 1
    has_bucket = df["technical_bucket"].nunique() > 1
    if has_engine and has_bucket:
        return "~ engine_group + technical_bucket"
    if has_engine:
        return "~ engine_group"
    if has_bucket:
        return "~ technical_bucket"
    return "~ 1"


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    print("=" * 60)
    print("run_stm_clio.py — Renault Clio STM")
    print("=" * 60)

    if not INPUT_CSV.exists():
        print(f"Error: {INPUT_CSV} not found.")
        sys.exit(1)

    # ── 1. Load data ──────────────────────────────────────────────────────────
    print(f"\nLoading {INPUT_CSV}…")
    df_raw = pd.read_csv(INPUT_CSV)

    # Ensure required columns exist
    for col in ("engine_code", "engine_spec", "prod_year", "reason"):
        if col not in df_raw.columns:
            df_raw[col] = None
    print(f"  Raw messages: {len(df_raw)}")

    # ── 2. Load stopwords ─────────────────────────────────────────────────────
    tr_stopwords: list[str] = []
    if STOPWORDS_FILE.exists():
        tr_stopwords = [
            ln.strip() for ln in STOPWORDS_FILE.read_text(encoding="utf-8").splitlines()
            if ln.strip()
        ]
    all_stopwords = list(set(tr_stopwords + CUSTOM_STOPWORDS_CLIO))

    # ── 3. Thread aggregation ─────────────────────────────────────────────────
    print("\nAggregating threads…")
    df = aggregate_threads(
        df_raw,
        mileage_mode="km",
        technical_patterns=TECHNICAL_PATTERNS,
        chronic_patterns=CHRONIC_PATTERNS,
        cosmetic_patterns=COSMETIC_PATTERNS,
        infotainment_patterns=INFOTAINMENT_PATTERNS,
        technical_reason_tags=TECHNICAL_REASON_TAGS,
        engine_group_fn=_EG_FN_SIMPLE,
        cosmetic_filter=True,
        clio_mode=True,
    )

    # Apply engine_spec-based engine_group correction (Clio uses engine_spec column)
    if "engine_spec" in df.columns:
        df["engine_group"] = df.apply(
            lambda r: engine_group_fn(r["engine_code"], r.get("engine_spec")),
            axis=1,
        )

    # Rename mileage column to mileage_km for Clio
    if "mileage_mentioned" in df.columns:
        df = df.rename(columns={"mileage_mentioned": "mileage_km"})

    # Extract year from prod_year or text
    if "prod_year" in df.columns:
        df["year"] = df.apply(
            lambda r: (
                int(r["prod_year"]) if pd.notna(r.get("prod_year")) and str(r["prod_year"]).isdigit()
                else extract_year(r["txt"])
            ),
            axis=1,
        )

    if len(df) < 20:
        print(f"Error: only {len(df)} threads after filtering — need ≥ 20. Scrape more data.")
        sys.exit(1)

    # ── 4. Dynamic K selection ────────────────────────────────────────────────
    prevalence_formula = build_prevalence_formula(df)
    k_final, k_candidates = determine_k(len(df))
    print(f"\nDocuments: {len(df)} | K final: {k_final} | K candidates: {k_candidates}")
    print(f"Prevalence formula: {prevalence_formula}")

    # ── 5. Build DFM ──────────────────────────────────────────────────────────
    print("\nBuilding DFM…")
    min_tf = 3 if len(df) >= 400 else 2
    min_df = 2 if len(df) >= 250 else 1

    builder = DFMBuilder(
        stopwords=all_stopwords,
        min_termfreq=min_tf,
        min_docfreq=min_df,
        max_docfreq_prop=0.0,
        min_charlen=0,
        keep_numbers=True,
    )
    count_matrix, vocab, kept_idx = builder.fit_transform(df["txt"].tolist())
    df = df.iloc[kept_idx].reset_index(drop=True)
    print(f"  Aligned df: {len(df)} rows, vocab: {len(vocab)} terms")

    if len(df) < 20:
        print("Error: too few documents after DFM build (<20).")
        sys.exit(1)

    # Recompute K and formula after potential doc removal
    prevalence_formula = build_prevalence_formula(df)
    k_final, k_candidates = determine_k(len(df))

    # ── 6. K metrics (searchK) ────────────────────────────────────────────────
    if len(df) >= 120 and len(k_candidates) > 1:
        print(f"\nRunning searchK over {k_candidates}…")
        k_metrics = search_k(
            count_matrix, vocab, df,
            prevalence_formula=prevalence_formula,
            k_range=k_candidates,
            max_em_its=150,
            device=DEVICE,
        )
    else:
        k_metrics = pd.DataFrame({
            "K": k_candidates,
            "exclusivity": [None] * len(k_candidates),
            "semcoh": [None] * len(k_candidates),
            "heldout": [None] * len(k_candidates),
            "bound": [None] * len(k_candidates),
            "em_its": [None] * len(k_candidates),
        })

    # ── 7. Final STM ──────────────────────────────────────────────────────────
    print(f"\nFitting final STM with K={k_final}…")
    stm = STM(
        K=k_final,
        device=DEVICE,
        max_em_its=MAX_EM_ITS,
        verbose=True,
    )
    stm.fit(count_matrix, vocab, df, prevalence_formula)

    # ── 8. Write outputs ──────────────────────────────────────────────────────
    print("\nWriting outputs…")
    write_outputs_clio(stm, df, vocab, OUT_DIR, k_metrics=k_metrics)

    print("\nDone.")


if __name__ == "__main__":
    main()
