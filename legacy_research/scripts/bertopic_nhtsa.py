#!/usr/bin/env python3
"""
bertopic_nhtsa.py
─────────────────
BERTopic pipeline for NHTSA VW Golf complaint text.

Input:   data/raw/nhtsa_vw_golf.csv  (from fetch_nhtsa.py)
Outputs: data/processed/nhtsa_*

Each NHTSA complaint is one "document" (description field).
Engine spec is extracted from the description text.
COMPDESC (component category) is used as a covariate.

Usage:
    python scripts/bertopic_nhtsa.py
    python scripts/bertopic_nhtsa.py --min-cluster-size 20 --skip-embed
"""

import argparse
import json
import logging
import os
import re
from pathlib import Path

os.environ["USE_TF"] = "NO"
os.environ["TRANSFORMERS_NO_TF"] = "1"

import numpy as np
import pandas as pd
from sklearn.feature_extraction.text import CountVectorizer, ENGLISH_STOP_WORDS

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data" / "processed"
RAW_DIR  = ROOT / "data" / "raw"
INPUT_CSV = RAW_DIR / "nhtsa_vw_golf.csv"
EMBEDDING_PATH = DATA_DIR / "nhtsa_embeddings.npy"
PREPARED_PATH  = DATA_DIR / "nhtsa_prepared.csv"

# ── Engine spec patterns (same as UK pipeline) ────────────────────────────────

_ENGINE_SPEC_PATTERNS = [
    (re.compile(r"\b2\.0\s*tdi\b",   re.IGNORECASE), "2.0_TDI"),
    (re.compile(r"\b2\.0\s*tsi\b",   re.IGNORECASE), "2.0_TSI"),
    (re.compile(r"\b2\.0\s*tfsi\b",  re.IGNORECASE), "2.0_TSI"),
    (re.compile(r"\b1\.6\s*tdi\b",   re.IGNORECASE), "1.6_TDI"),
    (re.compile(r"\b1\.5\s*tsi\b",   re.IGNORECASE), "1.5_TSI"),
    (re.compile(r"\b1\.5\s*tfsi\b",  re.IGNORECASE), "1.5_TSI"),
    (re.compile(r"\b1\.4\s*tsi\b",   re.IGNORECASE), "1.4_TSI"),
    (re.compile(r"\b1\.4\s*tfsi\b",  re.IGNORECASE), "1.4_TSI"),
    (re.compile(r"\b1\.8\s*tsi\b",   re.IGNORECASE), "1.8_TSI"),
    (re.compile(r"\b1\.8\s*tfsi\b",  re.IGNORECASE), "1.8_TSI"),
    (re.compile(r"\b1\.2\s*tsi\b",   re.IGNORECASE), "1.2_TSI"),
    (re.compile(r"\b1\.9\s*tdi\b",   re.IGNORECASE), "1.9_TDI"),
    (re.compile(r"\b1\.0\s*tsi\b",   re.IGNORECASE), "1.0_TSI"),
    (re.compile(r"\bea888\b",         re.IGNORECASE), "2.0_TSI"),
    (re.compile(r"\bea211\b",         re.IGNORECASE), "1.4_TSI"),
    (re.compile(r"\bea189\b",         re.IGNORECASE), "2.0_TDI"),
    (re.compile(r"\bea288\b",         re.IGNORECASE), "2.0_TDI"),
]

_VARIANT_INFERENCE = [
    (re.compile(r"\bgti\b",          re.IGNORECASE), "2.0_TSI"),
    (re.compile(r"\bgtd\b",          re.IGNORECASE), "2.0_TDI"),
    (re.compile(r"\bgolf\s*r\b",     re.IGNORECASE), "2.0_TSI"),
    (re.compile(r"\br32\b",          re.IGNORECASE), "3.2_VR6"),
    (re.compile(r"\bgte\b",          re.IGNORECASE), "1.4_GTE"),
    (re.compile(r"\btdi\b",          re.IGNORECASE), "TDI_unknown"),
    (re.compile(r"\btsi\b",          re.IGNORECASE), "TSI_unknown"),
]

_PROD_YEAR_RE = re.compile(r"\b(200[3-9]|201\d|202[0-4])\b")

_URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)


def extract_engine_spec(text: str) -> str:
    if not text or pd.isna(text):
        return "unknown"
    for pattern, spec in _ENGINE_SPEC_PATTERNS:
        if pattern.search(text):
            return spec
    for pattern, spec in _VARIANT_INFERENCE:
        if pattern.search(text):
            return spec
    return "unknown"


def extract_prod_year(text: str, model_year=None) -> str | None:
    """Try text extraction first; fall back to model_year column."""
    if text and not pd.isna(text):
        from collections import Counter
        matches = _PROD_YEAR_RE.findall(str(text))
        if matches:
            return Counter(matches).most_common(1)[0][0]
    if model_year and not pd.isna(model_year):
        try:
            yr = int(float(str(model_year)))
            if 2000 <= yr <= 2025:
                return str(yr)
        except (ValueError, TypeError):
            pass
    return None


# ── Technical patterns (tuned for NHTSA diagnostic language) ─────────────────

TECHNICAL_PATTERNS = [
    r"\bengine\b", r"\bgearbox\b", r"\btransmission\b", r"\bclutch\b",
    r"\bturbo\b", r"\binjector\b", r"\btiming\b", r"\bcambelt\b",
    r"\btiming chain\b", r"\btiming belt\b", r"\bthermostat\b",
    r"\bwater pump\b", r"\bradiator\b", r"\bdpf\b", r"\begr\b",
    r"\babs\b", r"\besp\b", r"\bspark plug\b", r"\bcoil\b",
    r"\bbrakes?\b", r"\bpads?\b", r"\bdisc\b", r"\bcaliper\b",
    r"\bshock absorber\b", r"\bcontrol arm\b", r"\bsteering\b",
    r"\bsensor\b", r"\boil\b", r"\bleak\b", r"\bnoise\b",
    r"\bvibration\b", r"\bknock\b", r"\bsmoke\b", r"\bmisfire\b",
    r"\blimp\b", r"\bfault\b", r"\bwarning light\b", r"\bcheck engine\b",
    r"\bflywheel\b", r"\bdmf\b", r"\bcoolant\b", r"\boverheating\b",
    r"\bstall(?:ed|ing|s)?\b", r"\bsurge\b", r"\bhesitat\b",
    r"\bexhaust\b", r"\bcatalytic\b", r"\bcat\b",
    r"\bdsg\b", r"\bdual.?clutch\b",
    r"\bconsumption\b", r"\bburning oil\b", r"\boil consumption\b",
    r"\bcarbon\b", r"\bdeposit\b",
]

CHRONIC_PATTERNS = [
    r"\bkeeps?\b", r"\bstill\b", r"\brecurring\b", r"\bpersistent\b",
    r"\bongoing\b", r"\bagain\b", r"\brepeat\b", r"\bunresolved\b",
    r"\bnever fixed\b", r"\bkeep having\b", r"\bhappens again\b",
    r"\bmultiple times\b", r"\bseveral times\b", r"\breoccurr\b",
]

_COMPILED_TECHNICAL = [re.compile(p, re.IGNORECASE) for p in TECHNICAL_PATTERNS]
_COMPILED_CHRONIC   = [re.compile(p, re.IGNORECASE) for p in CHRONIC_PATTERNS]


def count_hits(text: str, compiled: list) -> int:
    if not text or pd.isna(text):
        return 0
    return sum(1 for p in compiled if p.search(text))


# ── Stopwords ─────────────────────────────────────────────────────────────────

NHTSA_STOPWORDS = {
    # NHTSA boilerplate
    "vehicle", "dealer", "contact", "nhtsa", "manufacturer", "notified",
    "consumer", "states", "owner", "purchased", "complaint",
    # Generic car terms that don't differentiate topics
    "car", "cars", "golf", "gti", "vw", "volkswagen",
    "drive", "driving", "drove", "road",
    # Generic filler
    "just", "also", "get", "got", "know", "think", "would", "could",
    "really", "thing", "bit", "lot", "way", "time", "one", "two",
    "going", "like", "use", "used", "using", "new", "old",
    "actually", "probably", "maybe", "seems", "quite", "still",
    "well", "much", "even", "though", "around", "back", "good",
    "need", "want", "make", "look", "right", "left",
    "put", "run", "try", "tried", "doing", "done", "went", "said",
    "say", "let", "see", "day", "days", "year", "years", "ago",
    "failure", "failed", "issue", "problem", "occurred",  # too generic
}

ALL_STOPWORDS = list(ENGLISH_STOP_WORDS | NHTSA_STOPWORDS)

# ── Guided seed topics ────────────────────────────────────────────────────────

SEED_TOPIC_LIST = [
    ["oil", "consumption", "burning", "dipstick", "quart", "blue smoke"],
    ["timing chain", "timing", "rattle", "tensioner", "chain", "noise"],
    ["turbo", "boost", "wastegate", "surge", "power loss", "turbocharger"],
    ["coolant", "water pump", "thermostat", "overheating", "temperature", "radiator"],
    ["dpf", "particulate filter", "regeneration", "egr", "emissions", "diesel"],
    ["dsg", "transmission", "gearbox", "shudder", "hesitation", "clutch"],
    ["injector", "injection", "fuel", "misfire", "rough idle", "cylinder"],
    ["steer", "steering", "power steering", "eps", "torque steer"],
    ["abs", "brakes", "brake", "pedal", "caliper", "vibration"],
    ["carbon", "intake", "deposit", "direct injection", "valve"],
    ["check engine", "warning light", "epc", "fault code", "limp mode"],
    ["battery", "alternator", "electrical", "voltage", "charging"],
    ["suspension", "control arm", "bearing", "noise", "knock", "strut"],
    ["leak", "oil leak", "coolant leak", "seal", "gasket"],
]


# ── Data preparation ──────────────────────────────────────────────────────────

def prepare_data() -> pd.DataFrame:
    log.info("Loading %s ...", INPUT_CSV)
    df = pd.read_csv(INPUT_CSV, dtype=str, low_memory=False)
    log.info("Loaded %d complaints", len(df))

    # Ensure description column exists
    desc_col = next(
        (c for c in df.columns if c.lower() in ("description", "cdescr")),
        None
    )
    if desc_col is None:
        raise ValueError(f"No description column found. Columns: {list(df.columns)}")
    if desc_col != "description":
        df = df.rename(columns={desc_col: "description"})

    # Drop empty descriptions
    df = df[df["description"].notna() & (df["description"].str.strip() != "")].copy()
    log.info("After dropping empty descriptions: %d rows", len(df))

    # Clean text
    df["txt"] = df["description"].apply(lambda t: _URL_RE.sub("", str(t)).strip())

    # Extract metadata
    model_year_col = next(
        (c for c in df.columns if "year" in c.lower()), None)
    df["engine_spec"] = df["txt"].apply(extract_engine_spec)
    df["prod_year"]   = df.apply(
        lambda r: extract_prod_year(r["txt"], r.get(model_year_col)),
        axis=1
    )

    # Use COMPDESC as component category covariate
    comp_col = next(
        (c for c in df.columns if c.lower() in ("component", "compdesc")), None)
    if comp_col:
        if comp_col != "component":
            df = df.rename(columns={comp_col: "component"})
        # Normalise component labels
        df["component"] = df["component"].str.strip().str.upper().fillna("UNKNOWN")
    else:
        df["component"] = "UNKNOWN"

    # Miles
    miles_col = next(
        (c for c in df.columns if c.lower() == "miles"), None)
    if miles_col:
        df["mileage_miles"] = pd.to_numeric(df[miles_col], errors="coerce")
    else:
        df["mileage_miles"] = None

    # Technical + chronic scores
    df["technical_score"] = df["txt"].apply(lambda t: count_hits(t, _COMPILED_TECHNICAL))
    df["chronic_score"]   = df["txt"].apply(lambda t: count_hits(t, _COMPILED_CHRONIC))

    focus = df["technical_score"] + 2 * df["chronic_score"].where(df["technical_score"] > 0, 0)
    df["technical_bucket"] = pd.Categorical(
        np.where(focus >= 4, "high", np.where(focus >= 2, "medium", "low")),
        categories=["low", "medium", "high"],
        ordered=True,
    )

    # doc IDs
    df = df.reset_index(drop=True)
    df["doc_id"]   = range(1, len(df) + 1)
    df["doc_name"] = df["doc_id"].apply(lambda x: f"doc_{x:05d}")

    # Log distributions
    log.info("Engine spec:\n%s", df["engine_spec"].value_counts().head(15).to_string())
    log.info("Component (top 15):\n%s", df["component"].value_counts().head(15).to_string())
    log.info("Technical bucket:\n%s", df["technical_bucket"].value_counts().to_string())

    df.to_csv(PREPARED_PATH, index=False)
    log.info("Saved prepared data (%d rows) to %s", len(df), PREPARED_PATH)
    return df


# ── Embedding ─────────────────────────────────────────────────────────────────

def compute_embeddings(docs: list[str], force: bool = False) -> np.ndarray:
    if EMBEDDING_PATH.exists() and not force:
        emb = np.load(EMBEDDING_PATH)
        if emb.shape[0] == len(docs):
            log.info("Loaded cached embeddings %s", emb.shape)
            return emb
        log.warning("Cached shape %s != %d docs, recomputing", emb.shape, len(docs))

    from sentence_transformers import SentenceTransformer
    log.info("Computing embeddings (all-mpnet-base-v2, GPU) for %d docs ...", len(docs))
    model = SentenceTransformer("all-mpnet-base-v2", device="cuda")
    embeddings = model.encode(docs, show_progress_bar=True, batch_size=128)
    np.save(EMBEDDING_PATH, embeddings)
    log.info("Saved embeddings %s to %s", embeddings.shape, EMBEDDING_PATH)
    return embeddings


# ── BERTopic ──────────────────────────────────────────────────────────────────

def fit_bertopic(docs: list[str], embeddings: np.ndarray,
                 min_cluster_size: int = 20) -> tuple:
    from bertopic import BERTopic
    from bertopic.representation import KeyBERTInspired
    from hdbscan import HDBSCAN
    from sentence_transformers import SentenceTransformer
    from umap import UMAP

    umap_model = UMAP(
        n_neighbors=15, n_components=5, min_dist=0.0,
        metric="cosine", random_state=42,
    )
    hdbscan_model = HDBSCAN(
        min_cluster_size=min_cluster_size, min_samples=5,
        metric="euclidean", cluster_selection_method="eom",
        prediction_data=True,
    )
    vectorizer_model = CountVectorizer(
        stop_words=ALL_STOPWORDS,
        ngram_range=(1, 2), min_df=3, max_df=0.85,
    )
    embedding_model = SentenceTransformer("all-mpnet-base-v2", device="cuda")

    topic_model = BERTopic(
        embedding_model=embedding_model,
        umap_model=umap_model,
        hdbscan_model=hdbscan_model,
        vectorizer_model=vectorizer_model,
        representation_model=KeyBERTInspired(),
        seed_topic_list=SEED_TOPIC_LIST,
        top_n_words=15,
        verbose=True,
        calculate_probabilities=True,
    )

    topics, probs = topic_model.fit_transform(docs, embeddings=embeddings)

    n_topics   = len(set(topics)) - (1 if -1 in topics else 0)
    n_outliers = sum(1 for t in topics if t == -1)
    log.info("Topics: %d | Outliers: %d (%.1f%%)", n_topics, n_outliers,
             n_outliers / len(topics) * 100)

    if n_outliers > 0:
        log.info("Reassigning outliers ...")
        new_topics = topic_model.reduce_outliers(docs, topics, strategy="distributions")
        topic_model.update_topics(docs, topics=new_topics, vectorizer_model=vectorizer_model)
        topics = new_topics
        log.info("Outliers after reassignment: %d", sum(1 for t in topics if t == -1))

    return topic_model, topics, probs


# ── Outputs ───────────────────────────────────────────────────────────────────

def save_outputs(df: pd.DataFrame, topic_model, topics: list, probs: np.ndarray) -> None:
    log.info("Saving outputs ...")
    df = df.copy()
    df["dominant_topic"] = [t + 1 for t in topics]

    if probs is not None and probs.ndim == 2:
        df["topic_gamma"]  = [float(probs[i, t]) if t >= 0 else 0.0 for i, t in enumerate(topics)]
        df["gamma_vector"] = [json.dumps(probs[i].tolist()) for i in range(len(probs))]
    else:
        df["topic_gamma"]  = 0.0
        df["gamma_vector"] = "[]"

    # Enriched
    enriched_cols = [
        "doc_name", "complaint_id" if "complaint_id" in df.columns else "doc_id",
        "model_year" if "model_year" in df.columns else "doc_id",
        "dominant_topic", "topic_gamma",
        "engine_spec", "prod_year", "component",
        "mileage_miles", "technical_bucket", "chronic_score", "gamma_vector",
    ]
    enriched_cols = [c for c in enriched_cols if c in df.columns]
    enriched_path = DATA_DIR / "nhtsa_thread_enriched.csv"
    df[enriched_cols].to_csv(enriched_path, index=False)
    log.info("Saved enriched: %s (%d rows)", enriched_path.name, len(df))

    # Top terms
    topic_info = topic_model.get_topic_info()
    term_rows = []
    for tid in sorted(topic_info["Topic"].unique()):
        if tid == -1:
            continue
        words = topic_model.get_topic(tid)
        terms_str = ", ".join(w for w, _ in words[:15])
        term_rows.append({"topic": tid + 1, "terms_prob": terms_str, "terms_ctfidf": terms_str})
    terms_df = pd.DataFrame(term_rows)
    terms_path = DATA_DIR / "nhtsa_top_terms.csv"
    terms_df.to_csv(terms_path, index=False)
    log.info("Saved terms: %s (%d topics)", terms_path.name, len(terms_df))

    # LLM input
    llm_rows = []
    total_docs = len(df)
    for _, trow in terms_df.iterrows():
        tid = int(trow["topic"])
        topic_docs = df[df["dominant_topic"] == tid]
        n = len(topic_docs)
        chronic_sig = round(topic_docs["chronic_score"].mean(), 3) if n > 0 else 0.0

        miles = topic_docs["mileage_miles"].dropna()
        mileage_median = int(miles.median()) if len(miles) >= 5 else None
        mileage_p20    = int(miles.quantile(0.2)) if len(miles) >= 5 else None
        mileage_p80    = int(miles.quantile(0.8)) if len(miles) >= 5 else None

        spec_counts = topic_docs["engine_spec"].value_counts()
        top_specs = ", ".join(
            f"{s}: {c/n*100:.0f}%" for s, c in spec_counts.head(4).items()
            if s != "unknown"
        )

        year_counts = topic_docs["prod_year"].dropna().value_counts()
        top_years = ", ".join(
            f"{int(float(y))}" for y in year_counts.head(5).index
        )

        comp_counts = topic_docs["component"].value_counts()
        top_comps = ", ".join(f"{c}: {n2}" for c, n2 in comp_counts.head(4).items())

        llm_rows.append({
            "topic":              tid,
            "terms_frex":         trow["terms_prob"],
            "terms_prob":         trow["terms_prob"],
            "prevalence_pct":     round(n / total_docs * 100, 1),
            "chronic_signal":     chronic_sig,
            "thread_count":       n,
            "top_engine_specs":   top_specs,
            "top_prod_years":     top_years,
            "top_components":     top_comps,
            "mileage_median_miles": mileage_median,
            "mileage_p20_miles":  mileage_p20,
            "mileage_p80_miles":  mileage_p80,
        })
    llm_df = pd.DataFrame(llm_rows)
    llm_path = DATA_DIR / "nhtsa_llm_input.csv"
    llm_df.to_csv(llm_path, index=False)
    log.info("Saved LLM input: %s", llm_path.name)

    # Engine effects
    effect_rows = []
    spec_totals = df["engine_spec"].value_counts()
    for tid in sorted(df["dominant_topic"].unique()):
        topic_docs = df[df["dominant_topic"] == tid]
        for spec, cnt in topic_docs["engine_spec"].value_counts().items():
            effect_rows.append({
                "topic":             tid,
                "engine_spec":       spec,
                "count":             cnt,
                "pct_of_topic":      round(cnt / len(topic_docs) * 100, 1),
                "pct_of_engine_spec": round(cnt / spec_totals.get(spec, 1) * 100, 1),
            })
    effects_df = pd.DataFrame(effect_rows)
    effects_path = DATA_DIR / "nhtsa_topic_engine_effects.csv"
    effects_df.to_csv(effects_path, index=False)
    log.info("Saved engine effects: %s", effects_path.name)

    # Save model
    model_path = DATA_DIR / "bertopic_model_nhtsa"
    topic_model.save(str(model_path), serialization="safetensors",
                     save_ctfidf=True, save_embedding_model="all-mpnet-base-v2")
    log.info("Saved BERTopic model to %s", model_path)

    # Topic overview
    log.info("\n=== TOPIC OVERVIEW ===")
    for _, row in terms_df.iterrows():
        tid = int(row["topic"])
        llm_row = llm_df[llm_df["topic"] == tid].iloc[0]
        log.info("  T%d (%.1f%%, %d docs): %s",
                 tid, llm_row["prevalence_pct"], int(llm_row["thread_count"]),
                 row["terms_prob"][:80])


# ── Covariate regression ──────────────────────────────────────────────────────

def covariate_regression(df: pd.DataFrame, topics: list) -> None:
    from sklearn.linear_model import LogisticRegression
    from sklearn.preprocessing import OneHotEncoder

    log.info("Running covariate regression ...")
    df_reg = df.copy()
    df_reg["topic"] = topics
    df_reg = df_reg[df_reg["topic"] != -1].copy()

    topic_counts = df_reg["topic"].value_counts()
    valid_topics = topic_counts[topic_counts >= 5].index
    df_reg = df_reg[df_reg["topic"].isin(valid_topics)].copy()

    if len(valid_topics) < 2:
        log.warning("Not enough topics for regression, skipping")
        return

    miles = df_reg["mileage_miles"].copy()
    miles = miles.fillna(miles.median() if not pd.isna(miles.median()) else 50000)
    df_reg["mileage_log"] = np.log1p(miles.clip(lower=0))

    year_series = pd.to_numeric(df_reg["prod_year"], errors="coerce")
    year_series = year_series.fillna(year_series.median() if not pd.isna(year_series.median()) else 2016.0)
    df_reg["prod_year_centered"] = year_series - 2015

    spec_counts = df_reg["engine_spec"].value_counts()
    rare_specs  = spec_counts[spec_counts < 10].index
    df_reg["engine_spec_reg"] = df_reg["engine_spec"].replace({s: "other" for s in rare_specs})

    # Shorten component labels for regression
    df_reg["component_short"] = df_reg["component"].str[:30]

    cat_cols = df_reg[["engine_spec_reg", "component_short"]].astype(str)
    ohe = OneHotEncoder(sparse_output=False, drop="first", handle_unknown="ignore")
    cat_encoded = ohe.fit_transform(cat_cols)
    cat_names   = ohe.get_feature_names_out(["engine_spec_reg", "component_short"])

    X = np.column_stack([
        df_reg["mileage_log"].values,
        df_reg["prod_year_centered"].values,
        cat_encoded,
    ])
    feature_names = ["mileage_log", "prod_year_centered"] + list(cat_names)
    y = df_reg["topic"].values

    model = LogisticRegression(multi_class="multinomial", solver="lbfgs",
                               max_iter=1000, C=1.0)
    model.fit(X, y)
    log.info("Regression accuracy: %.1f%%", model.score(X, y) * 100)

    rows = []
    for i, topic_id in enumerate(model.classes_):
        for j, feat in enumerate(feature_names):
            rows.append({
                "topic":       int(topic_id) + 1,
                "feature":     feat,
                "coefficient": round(float(model.coef_[i, j]), 4),
            })

    coeff_df = pd.DataFrame(rows)
    coeff_path = DATA_DIR / "nhtsa_covariate_effects.csv"
    coeff_df.to_csv(coeff_path, index=False)
    log.info("Saved covariate effects: %s (%d rows)", coeff_path.name, len(coeff_df))


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="BERTopic pipeline for NHTSA VW Golf complaints")
    parser.add_argument("--skip-embed", action="store_true")
    parser.add_argument("--force-embed", action="store_true")
    parser.add_argument("--force-prepare", action="store_true")
    parser.add_argument("--min-cluster-size", type=int, default=20)
    parser.add_argument("--filter-bucket", type=str, default="low",
                        choices=["low", "medium", "high"],
                        help="Min technical bucket (default: low — NHTSA is already complaint-filtered)")
    parser.add_argument("--no-guided", action="store_true")
    args = parser.parse_args()

    # Prepare
    if PREPARED_PATH.exists() and not args.force_prepare:
        log.info("Loading cached prepared data from %s", PREPARED_PATH)
        df = pd.read_csv(PREPARED_PATH, dtype=str, low_memory=False)
        df["mileage_miles"]   = pd.to_numeric(df.get("mileage_miles", pd.Series(dtype=float)), errors="coerce")
        df["technical_score"] = pd.to_numeric(df.get("technical_score", pd.Series(dtype=int)), errors="coerce").fillna(0).astype(int)
        df["chronic_score"]   = pd.to_numeric(df.get("chronic_score", pd.Series(dtype=int)), errors="coerce").fillna(0).astype(int)
        log.info("Loaded %d rows", len(df))
    else:
        df = prepare_data()

    # Optional bucket filter
    if args.filter_bucket != "low":
        bucket_order = {"low": 0, "medium": 1, "high": 2}
        min_b = bucket_order[args.filter_bucket]
        df["_b"] = df["technical_bucket"].map(bucket_order)
        n_before = len(df)
        df = df[df["_b"] >= min_b].drop(columns=["_b"]).reset_index(drop=True)
        log.info("Bucket filter (%s+): %d -> %d", args.filter_bucket, n_before, len(df))

    docs = df["txt"].fillna("").tolist()

    # Remove empties
    valid_mask = [bool(d.strip()) for d in docs]
    if not all(valid_mask):
        df   = df[valid_mask].reset_index(drop=True)
        docs = [d for d, v in zip(docs, valid_mask) if v]

    log.info("Documents for BERTopic: %d", len(docs))

    # Embed
    embeddings = compute_embeddings(docs, force=args.force_embed)

    # Fit
    seed_topics = None if args.no_guided else SEED_TOPIC_LIST
    topic_model, topics, probs = fit_bertopic(
        docs, embeddings, min_cluster_size=args.min_cluster_size)

    # Save
    save_outputs(df, topic_model, topics, probs)

    # Regression
    covariate_regression(df, topics)


if __name__ == "__main__":
    main()
