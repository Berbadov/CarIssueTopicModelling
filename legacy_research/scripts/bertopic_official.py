#!/usr/bin/env python3
"""
bertopic_official.py
────────────────────
BERTopic pipeline on combined official sources:
  - NHTSA TSBs (manufacturer repair bulletins)
  - NHTSA Recalls (safety defect notices)
  - CarComplaints.com (owner complaint narratives)
  - CarProblemZoo (owner complaint descriptions)

Input:   data/raw/nhtsa_vw_golf_tsb.csv
         data/raw/nhtsa_vw_golf_recalls.csv
         data/raw/carcomplaints_vw_golf.csv      (optional)
         data/raw/carproblemzoo_vw_golf.csv     (optional)
Outputs: data/processed/official_*

Usage:
    python scripts/bertopic_official.py
    python scripts/bertopic_official.py --min-cluster-size 15 --skip-embed
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

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger(__name__)

ROOT          = Path(__file__).resolve().parent.parent
DATA_DIR      = ROOT / "data" / "processed"
RAW_DIR       = ROOT / "data" / "raw"
EMBEDDING_PATH = DATA_DIR / "official_embeddings.npy"
PREPARED_PATH  = DATA_DIR / "official_prepared.csv"

# ── Engine spec patterns (same as UK/NHTSA pipelines) ────────────────────────

_ENGINE_SPEC_PATTERNS = [
    (re.compile(r"\b2\.0\s*tdi\b",  re.IGNORECASE), "2.0_TDI"),
    (re.compile(r"\b2\.0\s*tsi\b",  re.IGNORECASE), "2.0_TSI"),
    (re.compile(r"\b2\.0\s*tfsi\b", re.IGNORECASE), "2.0_TSI"),
    (re.compile(r"\b1\.6\s*tdi\b",  re.IGNORECASE), "1.6_TDI"),
    (re.compile(r"\b1\.5\s*tsi\b",  re.IGNORECASE), "1.5_TSI"),
    (re.compile(r"\b1\.4\s*tsi\b",  re.IGNORECASE), "1.4_TSI"),
    (re.compile(r"\b1\.4\s*tfsi\b", re.IGNORECASE), "1.4_TSI"),
    (re.compile(r"\b1\.8\s*tsi\b",  re.IGNORECASE), "1.8_TSI"),
    (re.compile(r"\b1\.8\s*tfsi\b", re.IGNORECASE), "1.8_TSI"),
    (re.compile(r"\b1\.2\s*tsi\b",  re.IGNORECASE), "1.2_TSI"),
    (re.compile(r"\b1\.9\s*tdi\b",  re.IGNORECASE), "1.9_TDI"),
    (re.compile(r"\b1\.0\s*tsi\b",  re.IGNORECASE), "1.0_TSI"),
    (re.compile(r"\bea888\b",        re.IGNORECASE), "2.0_TSI"),
    (re.compile(r"\bea211\b",        re.IGNORECASE), "1.4_TSI"),
    (re.compile(r"\bea189\b",        re.IGNORECASE), "2.0_TDI"),
    (re.compile(r"\bea288\b",        re.IGNORECASE), "2.0_TDI"),
]
_VARIANT_INFERENCE = [
    (re.compile(r"\bgti\b",       re.IGNORECASE), "2.0_TSI"),
    (re.compile(r"\bgtd\b",       re.IGNORECASE), "2.0_TDI"),
    (re.compile(r"\bgolf\s*r\b",  re.IGNORECASE), "2.0_TSI"),
    (re.compile(r"\br32\b",       re.IGNORECASE), "3.2_VR6"),
    (re.compile(r"\btdi\b",       re.IGNORECASE), "TDI_unknown"),
    (re.compile(r"\btsi\b",       re.IGNORECASE), "TSI_unknown"),
]
_PROD_YEAR_RE = re.compile(r"\b(200[0-9]|201\d|202[0-4])\b")
_URL_RE       = re.compile(r"https?://\S+", re.IGNORECASE)


def extract_engine_spec(text: str) -> str:
    if not text or pd.isna(text):
        return "unknown"
    for pat, spec in _ENGINE_SPEC_PATTERNS:
        if pat.search(text):
            return spec
    for pat, spec in _VARIANT_INFERENCE:
        if pat.search(text):
            return spec
    return "unknown"


def extract_prod_year(text: str, model_year=None) -> str | None:
    from collections import Counter
    if text and not pd.isna(text):
        hits = _PROD_YEAR_RE.findall(str(text))
        if hits:
            return Counter(hits).most_common(1)[0][0]
    if model_year and not pd.isna(model_year):
        try:
            yr = int(float(str(model_year)))
            if 2000 <= yr <= 2025:
                return str(yr)
        except (ValueError, TypeError):
            pass
    return None


# ── Stopwords ─────────────────────────────────────────────────────────────────

DOMAIN_STOPWORDS = {
    "vehicle", "vehicles", "car", "cars", "golf", "volkswagen", "vw",
    "dealer", "contact", "nhtsa", "manufacturer", "consumer", "owner",
    "recall", "bulletin", "service", "repair", "complaint",
    "problem", "issue", "failure", "failed", "occurred",
    "just", "also", "get", "got", "know", "think", "would", "could",
    "really", "bit", "lot", "way", "time", "one", "two", "going",
    "like", "use", "used", "new", "old", "well", "much", "even",
    "though", "back", "good", "need", "make", "right", "left",
    "put", "run", "try", "tried", "done", "said", "see", "day",
    "year", "years", "ago", "model", "year", "drive", "driving",
}
ALL_STOPWORDS = list(ENGLISH_STOP_WORDS | DOMAIN_STOPWORDS)

# ── Seed topics ───────────────────────────────────────────────────────────────

SEED_TOPIC_LIST = [
    ["oil", "consumption", "burning", "quart", "excessive", "blue smoke", "oil level"],
    ["timing chain", "tensioner", "rattle", "chain", "timing", "noise", "stretch"],
    ["turbo", "boost", "wastegate", "surge", "power loss", "turbocharger", "actuator"],
    ["coolant", "water pump", "thermostat", "overheating", "temperature", "radiator", "housing"],
    ["dpf", "particulate filter", "regeneration", "egr", "emissions", "diesel", "soot"],
    ["dsg", "transmission", "gearbox", "shudder", "hesitation", "clutch pack", "mechatronic"],
    ["injector", "injection", "fuel", "misfire", "rough idle", "cylinder", "hpfp"],
    ["steer", "steering", "eps", "power steering", "torque steer", "column"],
    ["brakes", "brake", "pedal", "caliper", "vibration", "discs", "abs"],
    ["carbon", "intake", "deposit", "direct injection", "valve", "walnut blast"],
    ["check engine", "warning light", "epc", "fault code", "limp mode", "sensor"],
    ["battery", "alternator", "electrical", "voltage", "charging", "short circuit"],
    ["suspension", "control arm", "bearing", "knock", "strut", "spring", "coilover"],
    ["oil leak", "coolant leak", "seal", "gasket", "leak", "seepage"],
    ["sunroof", "water leak", "panoramic", "drain", "headliner", "seal"],
    ["airbag", "takata", "inflator", "seatbelt", "pretensioner"],
    ["clutch", "flywheel", "dmf", "dual mass", "slip", "judder"],
    ["cam follower", "camshaft", "follower", "wear", "tappet", "lobe"],
]


# ── Data loading ──────────────────────────────────────────────────────────────

def load_sources() -> pd.DataFrame:
    frames = []

    # 1. NHTSA TSBs
    tsb_path = RAW_DIR / "nhtsa_vw_golf_tsb.csv"
    if tsb_path.exists():
        tsb = pd.read_csv(tsb_path, dtype=str, low_memory=False)
        tsb = tsb.rename(columns={"model_yr": "model_year", "components": "component"})
        tsb["source"] = "nhtsa_tsb"
        tsb["txt"] = tsb["summary"].fillna("")
        frames.append(tsb[["source", "model_year", "component", "txt"]])
        log.info("TSBs loaded: %d", len(tsb))

    # 2. NHTSA Recalls
    rcl_path = RAW_DIR / "nhtsa_vw_golf_recalls.csv"
    if rcl_path.exists():
        rcl = pd.read_csv(rcl_path, dtype=str, low_memory=False)
        rcl["source"] = "nhtsa_recall"
        rcl["txt"] = rcl["summary"].fillna("")
        frames.append(rcl[["source", "model_year", "component", "txt"]])
        log.info("Recalls loaded: %d", len(rcl))

    # 3. NHTSA complaints (user narratives — clean, high quality)
    nhtsa_c_path = RAW_DIR / "nhtsa_vw_golf.csv"
    if nhtsa_c_path.exists():
        nc = pd.read_csv(nhtsa_c_path, dtype=str, low_memory=False)
        nc["source"] = "nhtsa_complaint"
        nc["component"] = nc.get("component", pd.Series(dtype=str))
        nc["txt"] = nc.get("description", nc.get("summary", pd.Series(dtype=str))).fillna("")
        frames.append(nc[["source", "model_year", "component", "txt"]])
        log.info("NHTSA complaints loaded: %d", len(nc))

    # 4. CarProblemZoo
    cpz_path = RAW_DIR / "carproblemzoo_vw_golf.csv"
    if cpz_path.exists():
        cpz = pd.read_csv(cpz_path, dtype=str, low_memory=False)
        cpz["component"] = cpz.get("category", pd.Series(dtype=str))
        cpz["txt"] = cpz["summary"].fillna("")
        frames.append(cpz[["source", "model_year", "component", "txt"]])
        log.info("CarProblemZoo loaded: %d", len(cpz))

    if not frames:
        raise FileNotFoundError("No input data found. Run fetch_* scripts first.")

    df = pd.concat(frames, ignore_index=True)
    log.info("Combined corpus: %d documents", len(df))
    return df


def prepare_data() -> pd.DataFrame:
    df = load_sources()

    # Clean text
    df["txt"] = df["txt"].apply(lambda t: _URL_RE.sub("", str(t)).strip())
    df = df[df["txt"].str.len() > 30].copy()

    # Extract engine spec and prod year
    df["engine_spec"] = df["txt"].apply(extract_engine_spec)
    df["prod_year"]   = df.apply(
        lambda r: extract_prod_year(r["txt"], r.get("model_year")), axis=1
    )

    # Technical signal (simple)
    tech_kws = re.compile(
        r"\b(engine|timing|turbo|oil|fuel|inject|trans|gearbox|clutch|brake|"
        r"coolant|water pump|thermostat|dpf|egr|sensor|fault|warning|limp|"
        r"stall|misfire|vibration|knock|leak|smoke|overheating|bearing|suspension)\b",
        re.IGNORECASE
    )
    df["technical_score"] = df["txt"].apply(lambda t: len(tech_kws.findall(t)))

    df = df.reset_index(drop=True)
    df["doc_id"]   = range(1, len(df) + 1)
    df["doc_name"] = df["doc_id"].apply(lambda x: f"doc_{x:05d}")

    log.info("Engine spec:\n%s", df["engine_spec"].value_counts().head(10).to_string())
    log.info("Source:\n%s", df["source"].value_counts().to_string())
    log.info("Prod year (top 10):\n%s", df["prod_year"].value_counts().head(10).to_string())

    df.to_csv(PREPARED_PATH, index=False)
    log.info("Saved prepared: %d rows → %s", len(df), PREPARED_PATH)
    return df


# ── Embedding ─────────────────────────────────────────────────────────────────

def compute_embeddings(docs: list[str], force: bool = False) -> np.ndarray:
    if EMBEDDING_PATH.exists() and not force:
        emb = np.load(EMBEDDING_PATH)
        if emb.shape[0] == len(docs):
            log.info("Loaded cached embeddings %s", emb.shape)
            return emb
    from sentence_transformers import SentenceTransformer
    log.info("Computing embeddings for %d docs ...", len(docs))
    model = SentenceTransformer("all-mpnet-base-v2", device="cuda")
    emb = model.encode(docs, show_progress_bar=True, batch_size=128)
    np.save(EMBEDDING_PATH, emb)
    log.info("Saved embeddings %s", emb.shape)
    return emb


# ── BERTopic ──────────────────────────────────────────────────────────────────

def fit_bertopic(docs, embeddings, min_cluster_size=15):
    from bertopic import BERTopic
    from bertopic.representation import KeyBERTInspired
    from hdbscan import HDBSCAN
    from sentence_transformers import SentenceTransformer
    from umap import UMAP

    topic_model = BERTopic(
        embedding_model=SentenceTransformer("all-mpnet-base-v2", device="cuda"),
        umap_model=UMAP(n_neighbors=15, n_components=5, min_dist=0.0, metric="cosine", random_state=42),
        hdbscan_model=HDBSCAN(min_cluster_size=min_cluster_size, min_samples=5,
                              metric="euclidean", cluster_selection_method="eom", prediction_data=True),
        vectorizer_model=CountVectorizer(stop_words=ALL_STOPWORDS, ngram_range=(1, 2), min_df=2, max_df=0.85),
        representation_model=KeyBERTInspired(),
        seed_topic_list=SEED_TOPIC_LIST,
        top_n_words=15, verbose=True, calculate_probabilities=True,
    )
    topics, probs = topic_model.fit_transform(docs, embeddings=embeddings)

    n_topics   = len(set(topics)) - (1 if -1 in topics else 0)
    n_outliers = sum(1 for t in topics if t == -1)
    log.info("Topics: %d | Outliers: %d (%.1f%%)", n_topics, n_outliers, n_outliers / len(topics) * 100)

    if n_outliers > 0:
        new_topics = topic_model.reduce_outliers(docs, topics, strategy="distributions")
        topic_model.update_topics(
            docs, topics=new_topics,
            vectorizer_model=CountVectorizer(stop_words=ALL_STOPWORDS, ngram_range=(1, 2), min_df=2, max_df=0.85),
        )
        topics = new_topics

    return topic_model, topics, probs


# ── Outputs ───────────────────────────────────────────────────────────────────

def save_outputs(df: pd.DataFrame, topic_model, topics, probs) -> None:
    df = df.copy()
    df["dominant_topic"] = [t + 1 for t in topics]
    if probs is not None and probs.ndim == 2:
        df["topic_gamma"]  = [float(probs[i, t]) if t >= 0 else 0.0 for i, t in enumerate(topics)]
        df["gamma_vector"] = [json.dumps(probs[i].tolist()) for i in range(len(probs))]
    else:
        df["topic_gamma"]  = 0.0
        df["gamma_vector"] = "[]"

    enriched_cols = [c for c in [
        "doc_name", "model_year", "dominant_topic", "topic_gamma",
        "engine_spec", "prod_year", "source", "component",
        "technical_score", "gamma_vector",
    ] if c in df.columns]
    df[enriched_cols].to_csv(DATA_DIR / "official_thread_enriched.csv", index=False)

    topic_info = topic_model.get_topic_info()
    term_rows = []
    for tid in sorted(topic_info["Topic"].unique()):
        if tid == -1:
            continue
        words = topic_model.get_topic(tid)
        terms_str = ", ".join(w for w, _ in words[:15])
        term_rows.append({"topic": tid + 1, "terms_prob": terms_str, "terms_ctfidf": terms_str})
    terms_df = pd.DataFrame(term_rows)
    terms_df.to_csv(DATA_DIR / "official_top_terms.csv", index=False)

    llm_rows = []
    total = len(df)
    for _, trow in terms_df.iterrows():
        tid = int(trow["topic"])
        docs_t = df[df["dominant_topic"] == tid]
        n = len(docs_t)
        miles = pd.to_numeric(docs_t.get("mileage", pd.Series(dtype=float)), errors="coerce").dropna()

        spec_counts = docs_t["engine_spec"].value_counts()
        top_specs = ", ".join(f"{s}: {c/n*100:.0f}%" for s, c in spec_counts.head(4).items() if s != "unknown")

        year_counts = docs_t["prod_year"].dropna().value_counts()
        top_years = ", ".join(f"{int(float(y))}" for y in year_counts.head(5).index)

        src_counts = docs_t["source"].value_counts()
        source_breakdown = ", ".join(f"{s}: {c}" for s, c in src_counts.items())

        llm_rows.append({
            "topic":            tid,
            "terms_prob":       trow["terms_prob"],
            "prevalence_pct":   round(n / total * 100, 1),
            "thread_count":     n,
            "top_engine_specs": top_specs,
            "top_prod_years":   top_years,
            "source_breakdown": source_breakdown,
            "mileage_median_miles": int(miles.median()) if len(miles) >= 5 else None,
            "mileage_p20_miles":  int(miles.quantile(0.2)) if len(miles) >= 5 else None,
            "mileage_p80_miles":  int(miles.quantile(0.8)) if len(miles) >= 5 else None,
            "chronic_signal":   0.0,
        })
    llm_df = pd.DataFrame(llm_rows)
    llm_df.to_csv(DATA_DIR / "official_llm_input.csv", index=False)

    # Engine effects
    effect_rows = []
    for tid in sorted(df["dominant_topic"].unique()):
        docs_t = df[df["dominant_topic"] == tid]
        for spec, cnt in docs_t["engine_spec"].value_counts().items():
            effect_rows.append({"topic": tid, "engine_spec": spec, "count": cnt,
                                 "pct_of_topic": round(cnt / len(docs_t) * 100, 1)})
    pd.DataFrame(effect_rows).to_csv(DATA_DIR / "official_topic_engine_effects.csv", index=False)

    # Also save a covariate effects stub (needed by generate script)
    pd.DataFrame(columns=["topic", "feature", "coefficient"]).to_csv(
        DATA_DIR / "official_covariate_effects.csv", index=False)

    topic_model.save(str(DATA_DIR / "bertopic_model_official"), serialization="safetensors",
                     save_ctfidf=True, save_embedding_model="all-mpnet-base-v2")

    log.info("\n=== TOPIC OVERVIEW ===")
    for _, row in terms_df.iterrows():
        tid = int(row["topic"])
        lr = llm_df[llm_df["topic"] == tid].iloc[0]
        log.info("  T%d (%.1f%%, %d docs): %s", tid, lr["prevalence_pct"], int(lr["thread_count"]), row["terms_prob"][:80])


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-embed",        action="store_true")
    parser.add_argument("--force-embed",       action="store_true")
    parser.add_argument("--force-prepare",     action="store_true")
    parser.add_argument("--min-cluster-size",  type=int, default=15)
    parser.add_argument("--no-guided",         action="store_true")
    args = parser.parse_args()

    if PREPARED_PATH.exists() and not args.force_prepare:
        log.info("Loading cached prepared data ...")
        df = pd.read_csv(PREPARED_PATH, dtype=str, low_memory=False)
        df["technical_score"] = pd.to_numeric(df.get("technical_score", 0), errors="coerce").fillna(0).astype(int)
        log.info("Loaded %d rows", len(df))
    else:
        df = prepare_data()

    docs = df["txt"].fillna("").tolist()
    valid = [bool(d.strip()) for d in docs]
    df   = df[valid].reset_index(drop=True)
    docs = [d for d, v in zip(docs, valid) if v]
    log.info("Documents for BERTopic: %d", len(docs))

    embeddings  = compute_embeddings(docs, force=args.force_embed)
    topic_model, topics, probs = fit_bertopic(
        docs, embeddings, min_cluster_size=args.min_cluster_size)
    save_outputs(df, topic_model, topics, probs)


if __name__ == "__main__":
    main()
