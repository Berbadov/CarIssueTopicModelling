#!/usr/bin/env python3
"""
bertopic_uk.py
──────────────
BERTopic pipeline for UK Golf GTI forum topic modelling.

Phases:
  1. Thread aggregation (port of R_code_STM_uk.R lines 117-196)
  2. Text cleaning & stopword strategy
  3. Sentence embedding (all-mpnet-base-v2, GPU)
  4. BERTopic fit (UMAP → HDBSCAN → c-TF-IDF)
  5. Output CSVs compatible with generate_issue_knowledge.py

Usage:
    python scripts/bertopic_uk.py [--skip-embed] [--min-cluster-size 30]
"""

import argparse
import json
import logging
import os
import re
from pathlib import Path

# Prevent TensorFlow import conflicts (not needed for this pipeline)
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
INPUT_CSV = ROOT / "cleaned_messages_uk.csv"
EMBEDDING_PATH = DATA_DIR / "uk_thread_embeddings.npy"
EMBEDDING_FILTERED_PATH = DATA_DIR / "uk_thread_embeddings_filtered.npy"
PREPARED_PATH = DATA_DIR / "uk_threads_prepared.csv"

# ── Pattern sets (ported from R_code_STM_uk.R lines 77-109) ─────────────────

TECHNICAL_PATTERNS = [
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
]

CHRONIC_PATTERNS = [
    r"\bkeeps?\b", r"\bstill\b", r"\brecurring\b", r"\bpersistent\b",
    r"\bongoing\b", r"\bagain\b", r"\brepeat\b", r"\bunresolved\b",
    r"\bnever fixed\b", r"\bkeep having\b", r"\bhappens again\b",
    r"\bback again\b", r"\bstill happening\b",
]

COSMETIC_PATTERNS = [
    r"\brespray\b", r"\bpaintwork\b", r"\bbodywork\b",
    r"\bdent\b", r"\bscratch\b", r"\bscuff\b",
    r"\bppf\b", r"\bdetailing\b", r"\bpolish\b",
    r"\balloy refurb\b", r"\bpanel\b",
]

INFOTAINMENT_PATTERNS = [
    r"\bcarplay\b", r"\bandroid auto\b", r"\bbluetooth\b",
    r"\bsat nav\b", r"\binfotainment\b", r"\bhead unit\b",
    r"\btouchscreen\b", r"\bdab\b", r"\bsd card\b",
    r"\busb\b", r"\bapple music\b", r"\bspotify\b",
    r"\bnavigation\b", r"\bmaps?\b", r"\bstreaming\b",
]

PURCHASE_PATTERNS = [
    # Finance
    r"\bfinance\b", r"\bpcp\b", r"\blease\b", r"\bleasing\b",
    r"\bdeposit\b", r"\bmonthly payment\b", r"\bequity\b",
    r"\bballoon\b", r"\bhire purchase\b", r"\bapr\b",
    r"\btrade.?in\b", r"\bpart.?exchange\b",
    # Order tracking / delivery
    r"\bbuild week\b", r"\ballocation\b", r"\blead time\b",
    r"\bin transit\b", r"\bdelivery date\b", r"\border number\b",
    r"\border status\b", r"\bshipped\b",
    # Insurance
    r"\binsurance\b", r"\bpolicy\b", r"\bpremium\b",
    r"\bclaim(?:s)?\b", r"\binsurer\b", r"\bunderwriter\b",
]

APPEARANCE_PATTERNS = [
    r"\bcolou?rs?\b", r"\bmetallic\b", r"\bpearl\b",
    r"\bwrap(?:ped|s)?\b", r"\btint(?:s|ed)?\b",
    r"\bvinyl\b", r"\bplasti.?dip\b",
    r"\bbadge\b", r"\bdecal\b", r"\bstripe\b", r"\bsticker\b",
    r"\bemblem\b", r"\bmudflaps?\b", r"\bmud flaps?\b",
    r"\bboot liner\b", r"\bfloor mats?\b", r"\brubber mats?\b",
    r"\bcarpet\b",
]

TECHNICAL_REASON_TAGS = [
    "engine", "gearbox", "transmission", "brake", "electrical",
    "cooling", "suspension", "exhaust", "turbo", "clutch",
]

_COMPILED_TECHNICAL = [re.compile(p, re.IGNORECASE) for p in TECHNICAL_PATTERNS]
_COMPILED_CHRONIC = [re.compile(p, re.IGNORECASE) for p in CHRONIC_PATTERNS]
_COMPILED_COSMETIC = [re.compile(p, re.IGNORECASE) for p in COSMETIC_PATTERNS]
_COMPILED_INFOTAINMENT = [re.compile(p, re.IGNORECASE) for p in INFOTAINMENT_PATTERNS]
_COMPILED_PURCHASE = [re.compile(p, re.IGNORECASE) for p in PURCHASE_PATTERNS]
_COMPILED_APPEARANCE = [re.compile(p, re.IGNORECASE) for p in APPEARANCE_PATTERNS]

# ── Mileage extraction (ported from R_code_STM_uk.R lines 42-73) ────────────

def extract_mileage_info(text: str) -> dict:
    if not text or pd.isna(text):
        return {"miles": None, "confidence": "none"}
    t = text.lower()

    # "50k miles", "50k mls", "50k mi", "50K"
    m = re.search(r"\b(\d{1,3})\s*k\s*(?:miles?|mls?|mi)?\b", t)
    if m:
        return {"miles": int(m.group(1)) * 1000, "confidence": "high"}

    # "50,000 miles", "50000 miles"
    m = re.search(r"\b(\d{1,3}(?:[,.]\d{3})+|\d{4,})\s*(?:miles?|mls?)\b", t)
    if m:
        return {"miles": int(re.sub(r"[^0-9]", "", m.group(1))), "confidence": "high"}

    # "65000 on the clock"
    m = re.search(r"\b(\d{4,})\s+on\s+(?:the\s+)?clock\b", t)
    if m:
        return {"miles": int(m.group(1)), "confidence": "medium"}

    # "mileage: 65000"
    m = re.search(r"\bmileage\s*[:=]?\s*(\d{4,})\b", t)
    if m:
        return {"miles": int(m.group(1)), "confidence": "medium"}

    # km fallback (convert to miles / 1.609)
    m = re.search(r"\b(\d{1,3}(?:[,.]\d{3})+|\d{4,})\s*km\b", t)
    if m:
        km = int(re.sub(r"[^0-9]", "", m.group(1)))
        return {"miles": int(km / 1.609), "confidence": "low"}

    return {"miles": None, "confidence": "none"}


def count_pattern_hits(text: str, compiled_patterns: list) -> int:
    if not text or pd.isna(text):
        return 0
    return sum(1 for p in compiled_patterns if p.search(text))


# ── Engine group mapping (legacy MK-gen, kept as secondary tag) ───────────────

ENGINE_GROUP_MAP = {
    "MK8": "MK8", "MK7.5": "MK7.5", "MK7": "MK7",
    "MK6": "MK6", "MK5": "MK5",
    "2.0_TSI": "2.0_TSI", "EA888": "2.0_TSI",
    "1.4_TSI": "1.4_TSI", "EA211": "1.4_TSI",
    "Golf_R": "Golf_R",
    "unknown": "unknown",
}


def map_engine_group(code: str) -> str:
    if pd.isna(code):
        return "unknown"
    return ENGINE_GROUP_MAP.get(code, "other")


# ── Engine spec extraction (displacement + fuel type) ─────────────────────────
# Scans full aggregated thread text for displacement+fuel mentions.
# This supplements the cleaner-level extraction which only sees title + 5 msgs.

_ENGINE_SPEC_PATTERNS = [
    (re.compile(r"\b2\.0\s*tdi\b", re.IGNORECASE),   "2.0_TDI"),
    (re.compile(r"\b2\.0\s*tsi\b", re.IGNORECASE),   "2.0_TSI"),
    (re.compile(r"\b2\.0\s*tfsi\b", re.IGNORECASE),  "2.0_TSI"),
    (re.compile(r"\b1\.6\s*tdi\b", re.IGNORECASE),   "1.6_TDI"),
    (re.compile(r"\b1\.5\s*tsi\b", re.IGNORECASE),   "1.5_TSI"),
    (re.compile(r"\b1\.5\s*tfsi\b", re.IGNORECASE),  "1.5_TSI"),
    (re.compile(r"\b1\.4\s*tsi\b", re.IGNORECASE),   "1.4_TSI"),
    (re.compile(r"\b1\.4\s*tfsi\b", re.IGNORECASE),  "1.4_TSI"),
    (re.compile(r"\b1\.2\s*tsi\b", re.IGNORECASE),   "1.2_TSI"),
    (re.compile(r"\b1\.8\s*tsi\b", re.IGNORECASE),   "1.8_TSI"),
    (re.compile(r"\b1\.8\s*tfsi\b", re.IGNORECASE),  "1.8_TSI"),
    (re.compile(r"\b1\.9\s*tdi\b", re.IGNORECASE),   "1.9_TDI"),
    (re.compile(r"\b1\.0\s*tsi\b", re.IGNORECASE),   "1.0_TSI"),
    (re.compile(r"\bea888\b", re.IGNORECASE),         "2.0_TSI"),
    (re.compile(r"\bea211\b", re.IGNORECASE),         "1.4_TSI"),
    (re.compile(r"\bea189\b", re.IGNORECASE),         "2.0_TDI"),
    (re.compile(r"\bea288\b", re.IGNORECASE),         "2.0_TDI"),
]

_PROD_YEAR_RE = re.compile(r"\b(200[3-9]|201\d|202[0-6])\b")


# Inference rules for implicit engine spec from model variant names.
# On golfgtiforum.co.uk, "GTI" always means 2.0 TSI, "GTD" always means 2.0 TDI, etc.
_VARIANT_INFERENCE = [
    (re.compile(r"\bgti\b", re.IGNORECASE),     "2.0_TSI"),
    (re.compile(r"\bgtd\b", re.IGNORECASE),     "2.0_TDI"),
    (re.compile(r"\bgolf\s*r\b", re.IGNORECASE), "2.0_TSI"),
    (re.compile(r"\br32\b", re.IGNORECASE),      "3.2_VR6"),
    (re.compile(r"\bgte\b", re.IGNORECASE),      "1.4_GTE"),
]

# Bare fuel-type mentions without displacement (weaker signal, kept as partial tag)
_BARE_FUEL_INFERENCE = [
    (re.compile(r"\btdi\b", re.IGNORECASE), "TDI_unknown"),
    (re.compile(r"\btsi\b", re.IGNORECASE), "TSI_unknown"),
]


def extract_engine_spec_from_text(text: str) -> str:
    """Extract displacement+fuel from arbitrary text block.

    Priority: explicit displacement+fuel > EA-family code > variant inference > bare fuel type.
    """
    if not text or pd.isna(text):
        return "unknown"
    # 1. Explicit displacement+fuel or EA code
    for pattern, spec in _ENGINE_SPEC_PATTERNS:
        if pattern.search(text):
            return spec
    # 2. Infer from variant name (GTI → 2.0_TSI, GTD → 2.0_TDI, etc.)
    for pattern, spec in _VARIANT_INFERENCE:
        if pattern.search(text):
            return spec
    # 3. Bare fuel type (TDI/TSI without displacement)
    for pattern, spec in _BARE_FUEL_INFERENCE:
        if pattern.search(text):
            return spec
    return "unknown"


def extract_prod_year_from_text(text: str) -> str | None:
    """Extract the most likely production year from text (most frequent mention)."""
    if not text or pd.isna(text):
        return None
    from collections import Counter
    matches = _PROD_YEAR_RE.findall(text)
    if not matches:
        return None
    counts = Counter(matches)
    return counts.most_common(1)[0][0]


# ── Quote stripping (from cleaner_uk.py) ─────────────────────────────────────

_QUOTE_PREFIX = re.compile(r"^quote\s+from\s*:[^.!?\n]{0,80}", re.IGNORECASE)


def strip_quote_prefix(text: str) -> str:
    return _QUOTE_PREFIX.sub("", text).strip()


# ═════════════════════════════════════════════════════════════════════════════
# PHASE 1: Thread aggregation
# ═════════════════════════════════════════════════════════════════════════════

def aggregate_threads(df_raw: pd.DataFrame) -> pd.DataFrame:
    log.info("Aggregating %d messages into threads ...", len(df_raw))

    groups = df_raw.groupby(["thread_name", "thread_url"], sort=False)
    rows = []

    # Check if cleaner-level engine_spec/prod_year columns exist
    has_engine_spec_col = "engine_spec" in df_raw.columns
    has_prod_year_col = "prod_year" in df_raw.columns

    for (tname, turl), grp in groups:
        msgs = grp["message"].tolist()
        reasons = grp["reason"].tolist()
        engine_codes = grp["engine_code"].tolist()

        # Filter follow-up messages: keep first always, then keep if
        # cosmetic_hits < 2 OR technical_hits > 0  (R line 131)
        if len(msgs) <= 1:
            kept = msgs
        else:
            kept = [msgs[0]]
            for msg in msgs[1:]:
                cosm = count_pattern_hits(msg, _COMPILED_COSMETIC)
                tech = count_pattern_hits(msg, _COMPILED_TECHNICAL)
                if cosm < 2 or tech > 0:
                    kept.append(msg)
            if not kept:
                kept = [msgs[0]]

        txt = " ".join(str(m) for m in kept if m and not pd.isna(m))

        # Mileage: first non-missing across all messages
        mileage_info = {"miles": None, "confidence": "none"}
        for msg in msgs:
            info = extract_mileage_info(str(msg) if msg else "")
            if info["miles"] is not None:
                mileage_info = info
                break

        # Engine spec: try full thread text first (more signal), fall back to
        # cleaner-level column, then "unknown"
        engine_spec = extract_engine_spec_from_text(txt)
        if engine_spec == "unknown" and has_engine_spec_col:
            cleaner_specs = grp["engine_spec"].dropna().tolist()
            if cleaner_specs and str(cleaner_specs[0]) != "unknown":
                engine_spec = str(cleaner_specs[0])

        # Production year: try full thread text, fall back to cleaner column
        prod_year = extract_prod_year_from_text(txt)
        if prod_year is None and has_prod_year_col:
            cleaner_years = grp["prod_year"].dropna().tolist()
            if cleaner_years:
                prod_year = str(int(float(cleaner_years[0])))

        rows.append({
            "thread_name": tname,
            "thread_url": turl,
            "txt": txt,
            "reason": reasons[0] if reasons else None,
            "engine_code": engine_codes[0] if engine_codes else "unknown",
            "engine_spec": engine_spec,
            "prod_year": prod_year,
            "mileage_miles": mileage_info["miles"],
            "mileage_confidence": mileage_info["confidence"],
            "n_messages": len(msgs),
        })

    df = pd.DataFrame(rows)
    df["doc_id"] = range(1, len(df) + 1)
    df["doc_name"] = df["doc_id"].apply(lambda x: f"doc_{x:05d}")

    log.info("Aggregated into %d threads", len(df))
    return df


def compute_scores(df: pd.DataFrame) -> pd.DataFrame:
    log.info("Computing pattern scores ...")
    df["technical_score"] = df["txt"].apply(
        lambda t: count_pattern_hits(t, _COMPILED_TECHNICAL))
    df["chronic_score"] = df["txt"].apply(
        lambda t: count_pattern_hits(t, _COMPILED_CHRONIC))
    df["cosmetic_score"] = df["txt"].apply(
        lambda t: count_pattern_hits(t, _COMPILED_COSMETIC))
    df["infotainment_score"] = df["txt"].apply(
        lambda t: count_pattern_hits(t, _COMPILED_INFOTAINMENT))
    df["purchase_score"] = df["txt"].apply(
        lambda t: count_pattern_hits(t, _COMPILED_PURCHASE))
    df["appearance_score"] = df["txt"].apply(
        lambda t: count_pattern_hits(t, _COMPILED_APPEARANCE))

    # Reason-based technical hint
    reason_lower = df["reason"].fillna("").str.lower()
    tag_pattern = "|".join(TECHNICAL_REASON_TAGS)
    df["reason_technical_hint"] = reason_lower.str.contains(
        tag_pattern, regex=True).astype(int)

    # Focus score: reward mechanical signal, penalise all non-mechanical categories.
    # Chronic terms ("still", "keeps", "again") only count when technical_score > 0,
    # otherwise they inflate non-mechanical threads ("still waiting for delivery").
    effective_chronic = df["chronic_score"].where(df["technical_score"] > 0, 0)

    # Non-mechanical penalty = sum of all non-mech categories (uncapped).
    # A thread hitting multiple non-mech categories is genuinely less mechanical.
    non_mech_penalty = (
        df["cosmetic_score"]
        + df["infotainment_score"]
        + df["purchase_score"]
        + df["appearance_score"]
    )
    df["focus_score"] = (
        df["technical_score"]
        + 2 * effective_chronic
        + df["reason_technical_hint"]
        - non_mech_penalty
    )
    df["technical_bucket"] = pd.Categorical(
        np.where(df["focus_score"] >= 4, "high",
                 np.where(df["focus_score"] >= 2, "medium", "low")),
        categories=["low", "medium", "high"],
        ordered=True,
    )

    # Engine group (legacy MK-gen, kept as secondary tag)
    df["engine_group"] = df["engine_code"].apply(map_engine_group)

    # Engine spec should already be set from aggregate_threads(); ensure column exists
    if "engine_spec" not in df.columns:
        df["engine_spec"] = df["txt"].apply(extract_engine_spec_from_text)
    if "prod_year" not in df.columns:
        df["prod_year"] = df["txt"].apply(extract_prod_year_from_text)

    return df


def filter_threads(df: pd.DataFrame) -> pd.DataFrame:
    n_before = len(df)
    # R lines 200-201: remove cosmetic-dominated and infotainment-dominated
    mask_cosm = (df["cosmetic_score"] > df[["technical_score"]].clip(lower=1).iloc[:, 0]) & (df["technical_score"] < 2)
    mask_info = (df["infotainment_score"] > 3) & (df["technical_score"] < 1)
    df = df[~mask_cosm & ~mask_info].copy()
    log.info("Filtered: %d -> %d threads (removed %d)", n_before, len(df), n_before - len(df))
    return df


def prepare_data() -> pd.DataFrame:
    df_raw = pd.read_csv(INPUT_CSV)
    log.info("Loaded %d raw messages from %s", len(df_raw), INPUT_CSV.name)

    df = aggregate_threads(df_raw)
    df = compute_scores(df)
    df = filter_threads(df)

    # Reset doc IDs after filtering
    df["doc_id"] = range(1, len(df) + 1)
    df["doc_name"] = df["doc_id"].apply(lambda x: f"doc_{x:05d}")

    log.info("Engine spec distribution:\n%s", df["engine_spec"].value_counts().to_string())
    log.info("Production year distribution:\n%s", df["prod_year"].value_counts().to_string())
    log.info("Engine group (legacy) distribution:\n%s", df["engine_group"].value_counts().to_string())
    log.info("Technical bucket distribution:\n%s", df["technical_bucket"].value_counts().to_string())

    df.to_csv(PREPARED_PATH, index=False)
    log.info("Saved prepared data to %s", PREPARED_PATH)
    return df


# ═════════════════════════════════════════════════════════════════════════════
# PHASE 2: Stopwords & text cleaning
# ═════════════════════════════════════════════════════════════════════════════

FORUM_STOPWORDS = {
    # Forum meta
    "post", "thread", "forum", "reply", "quote", "edited", "page",
    "member", "joined", "posts", "golfgtiforum", "topic", "board",
    "moderator", "admin", "sticky", "locked", "moved", "index",
    # Generic filler (from R_code_STM_uk.R lines 237-248)
    "just", "also", "get", "got", "know", "think", "would", "could",
    "really", "thing", "bit", "lot", "way", "time", "one", "two",
    "going", "like", "use", "used", "using", "new", "old",
    "actually", "probably", "maybe", "seems", "quite", "still",
    "well", "much", "even", "though", "around", "back", "good",
    "need", "want", "make", "look", "come", "right", "left",
    "put", "run", "try", "tried", "doing", "done", "went", "said",
    "say", "let", "see", "day", "days", "year", "years", "ago",
    "bought", "buy", "buying", "sell", "selling", "sold", "price",
    # Generic car terms (don't differentiate topics)
    "car", "cars", "golf", "gti", "vw", "volkswagen",
    "mk5", "mk6", "mk7", "mk8", "mk7.5",
    "drive", "driving", "drove", "road", "vehicle",
    # Forum social
    "anyone", "lol", "cheers", "thanks", "thank", "mate", "guys",
    "tbh", "imo", "afaik", "iirc", "fwiw", "imho",
    "hi", "hello", "hey", "great", "nice", "sorry",
    "people", "chap", "chaps", "folk", "folks",
    "hope", "help", "helps", "question", "advice",
}

ALL_STOPWORDS = list(ENGLISH_STOP_WORDS | FORUM_STOPWORDS)

# ── Guided BERTopic seed topics (from Turkish STM mechanical categories) ─────

SEED_TOPIC_LIST = [
    # T1 Turkish: Diesel injector issues
    ["diesel", "injector", "injection", "tdi", "fuel", "fuelling", "nozzle"],
    # T2 Turkish: Cooling system
    ["coolant", "water pump", "thermostat", "radiator", "overheating", "temperature"],
    # T3 Turkish: Timing / turbo
    ["timing chain", "timing belt", "cambelt", "turbo", "wastegate", "boost"],
    # T4 Turkish: Suspension / steering
    ["suspension", "shock", "wishbone", "steering", "control arm", "bearing"],
    # T5 Turkish: DSG / gearbox
    ["dsg", "gearbox", "clutch", "flywheel", "mechatronic", "gear", "shudder"],
    # T6 Turkish: DPF / idle vibration
    ["dpf", "regen", "regeneration", "egr", "idle", "vibration", "particulate"],
    # T7 Turkish: Brakes
    ["brakes", "discs", "pads", "caliper", "brembo", "brake fluid"],
    # T8 Turkish: Warning lights / electrics
    ["epc", "warning light", "fault code", "limp mode", "check engine", "sensor", "vcds"],
    # T9 Turkish: Battery
    ["battery", "alternator", "starter", "agm", "charging", "voltage"],
    # T10 Turkish: Lighting / sensors
    ["headlight", "led", "bulb", "xenon", "sensor", "wiring"],
    # Additional UK-specific
    ["oil", "consumption", "leak", "sump", "dipstick", "burning oil"],
    ["exhaust", "cat", "gpf", "downpipe", "manifold", "emissions"],
    ["rattle", "noise", "knock", "creak", "squeak", "vibration"],
    ["water leak", "seal", "drain", "damp", "condensation"],
]

_URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)


def clean_text_for_embedding(text: str) -> str:
    """Light cleaning before sentence embedding — keep natural English."""
    if not text or pd.isna(text):
        return ""
    t = str(text)
    t = _URL_RE.sub("", t)
    t = strip_quote_prefix(t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


# ═════════════════════════════════════════════════════════════════════════════
# PHASE 3: Embedding
# ═════════════════════════════════════════════════════════════════════════════

def compute_embeddings(docs: list[str], force: bool = False,
                       filtered: bool = False) -> np.ndarray:
    cache_path = EMBEDDING_FILTERED_PATH if filtered else EMBEDDING_PATH
    if cache_path.exists() and not force:
        log.info("Loading cached embeddings from %s", cache_path)
        emb = np.load(cache_path)
        if emb.shape[0] == len(docs):
            return emb
        log.warning("Cached embeddings shape %s != doc count %d, recomputing",
                     emb.shape, len(docs))

    from sentence_transformers import SentenceTransformer

    log.info("Computing embeddings with all-mpnet-base-v2 on GPU ...")
    model = SentenceTransformer("all-mpnet-base-v2", device="cuda")
    embeddings = model.encode(docs, show_progress_bar=True, batch_size=128)
    np.save(cache_path, embeddings)
    log.info("Saved embeddings (%s) to %s", embeddings.shape, cache_path)
    return embeddings


# ═════════════════════════════════════════════════════════════════════════════
# PHASE 4: BERTopic
# ═════════════════════════════════════════════════════════════════════════════

def fit_bertopic(docs: list[str], embeddings: np.ndarray,
                 min_cluster_size: int = 30,
                 seed_topics: list[list[str]] | None = None) -> tuple:
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
        min_cluster_size=min_cluster_size, min_samples=10,
        metric="euclidean", cluster_selection_method="eom",
        prediction_data=True,
    )
    vectorizer_model = CountVectorizer(
        stop_words=ALL_STOPWORDS,
        ngram_range=(1, 2), min_df=3, max_df=0.85,
    )
    representation_model = KeyBERTInspired()

    # Need embedding model for KeyBERTInspired to compute word embeddings
    embedding_model = SentenceTransformer("all-mpnet-base-v2", device="cuda")

    topic_model = BERTopic(
        embedding_model=embedding_model,
        umap_model=umap_model,
        hdbscan_model=hdbscan_model,
        vectorizer_model=vectorizer_model,
        representation_model=representation_model,
        seed_topic_list=seed_topics,
        top_n_words=15,
        verbose=True,
        calculate_probabilities=True,
    )

    topics, probs = topic_model.fit_transform(docs, embeddings=embeddings)

    # Stats
    n_topics = len(set(topics)) - (1 if -1 in topics else 0)
    n_outliers = sum(1 for t in topics if t == -1)
    outlier_pct = n_outliers / len(topics) * 100
    log.info("Topics: %d | Outliers: %d (%.1f%%)", n_topics, n_outliers, outlier_pct)

    # Reassign outliers using distributions strategy
    if n_outliers > 0:
        log.info("Reassigning outliers with 'distributions' strategy ...")
        new_topics = topic_model.reduce_outliers(
            docs, topics, strategy="distributions")
        topic_model.update_topics(
            docs, topics=new_topics, vectorizer_model=vectorizer_model)
        topics = new_topics
        n_remaining = sum(1 for t in topics if t == -1)
        log.info("Outliers after reassignment: %d (%.1f%%)",
                 n_remaining, n_remaining / len(topics) * 100)

    return topic_model, topics, probs


# ═════════════════════════════════════════════════════════════════════════════
# PHASE 5: Output generation
# ═════════════════════════════════════════════════════════════════════════════

def save_outputs(df: pd.DataFrame, topic_model, topics: list,
                 probs: np.ndarray) -> None:
    log.info("Generating output files ...")

    # Align topics with df
    df = df.copy()
    df["dominant_topic"] = [t + 1 for t in topics]  # 1-indexed like STM

    # Probability of dominant topic
    if probs is not None and probs.ndim == 2:
        df["topic_gamma"] = [
            float(probs[i, t]) if t >= 0 else 0.0
            for i, t in enumerate(topics)
        ]
        df["gamma_vector"] = [
            json.dumps(probs[i].tolist()) for i in range(len(probs))
        ]
    else:
        df["topic_gamma"] = 0.0
        df["gamma_vector"] = "[]"

    # ── bertopic_thread_enriched_uk.csv ──────────────────────────────────────
    enriched_cols = [
        "doc_name", "thread_name", "thread_url", "dominant_topic",
        "topic_gamma", "engine_spec", "prod_year", "engine_group",
        "mileage_miles", "mileage_confidence", "technical_bucket",
        "chronic_score", "n_messages", "gamma_vector",
    ]
    enriched_path = DATA_DIR / "bertopic_thread_enriched_uk.csv"
    df[enriched_cols].to_csv(enriched_path, index=False)
    log.info("Saved %s (%d rows)", enriched_path.name, len(df))

    # ── bertopic_top_terms_uk.csv ────────────────────────────────────────────
    topic_info = topic_model.get_topic_info()
    term_rows = []
    for tid in sorted(topic_info["Topic"].unique()):
        if tid == -1:
            continue
        words = topic_model.get_topic(tid)
        terms_str = ", ".join(w for w, _ in words[:15])
        term_rows.append({
            "topic": tid + 1,
            "terms_prob": terms_str,
            "terms_ctfidf": terms_str,
        })
    terms_df = pd.DataFrame(term_rows)
    terms_path = DATA_DIR / "bertopic_top_terms_uk.csv"
    terms_df.to_csv(terms_path, index=False)
    log.info("Saved %s (%d topics)", terms_path.name, len(terms_df))

    # ── llm_issue_input_uk.csv ───────────────────────────────────────────────
    llm_rows = []
    total_docs = len(df)
    for _, trow in terms_df.iterrows():
        tid = int(trow["topic"])
        topic_threads = df[df["dominant_topic"] == tid]
        thread_count = len(topic_threads)
        prevalence_pct = round(thread_count / total_docs * 100, 1)
        chronic_signal = round(topic_threads["chronic_score"].mean(), 3) if thread_count > 0 else 0.0

        miles = topic_threads["mileage_miles"].dropna()
        if len(miles) >= 5:
            mileage_median = int(miles.median())
            mileage_p20 = int(miles.quantile(0.2))
            mileage_p80 = int(miles.quantile(0.8))
        else:
            mileage_median = mileage_p20 = mileage_p80 = None

        # Top engine specs for this topic (e.g. "2.0_TSI: 65%, 2.0_TDI: 20%")
        spec_counts = topic_threads["engine_spec"].value_counts()
        top_specs = ", ".join(
            f"{spec}: {cnt/thread_count*100:.0f}%"
            for spec, cnt in spec_counts.head(4).items()
            if spec != "unknown"
        )

        # Top production years
        year_counts = topic_threads["prod_year"].dropna().value_counts()
        top_years = ", ".join(
            f"{int(float(yr))}" for yr in year_counts.head(5).index
        )

        llm_rows.append({
            "topic": tid,
            "terms_frex": trow["terms_prob"],
            "terms_prob": trow["terms_prob"],
            "prevalence_pct": prevalence_pct,
            "chronic_signal": chronic_signal,
            "thread_count": thread_count,
            "top_engine_specs": top_specs,
            "top_prod_years": top_years,
            "mileage_median_miles": mileage_median,
            "mileage_p20_miles": mileage_p20,
            "mileage_p80_miles": mileage_p80,
        })
    llm_df = pd.DataFrame(llm_rows)
    llm_path = DATA_DIR / "llm_issue_input_uk.csv"
    llm_df.to_csv(llm_path, index=False)
    log.info("Saved %s", llm_path.name)

    # ── bertopic_topic_engine_effects_uk.csv ─────────────────────────────────
    # Primary breakdown by engine_spec (displacement+fuel), not MK-gen
    effect_rows = []
    spec_totals = df["engine_spec"].value_counts()
    for tid in sorted(df["dominant_topic"].unique()):
        if tid == 0:  # outlier bucket (was -1, now 0 after +1)
            continue
        topic_threads = df[df["dominant_topic"] == tid]
        spec_counts = topic_threads["engine_spec"].value_counts()
        for spec, cnt in spec_counts.items():
            effect_rows.append({
                "topic": tid,
                "engine_spec": spec,
                "count": cnt,
                "pct_of_topic": round(cnt / len(topic_threads) * 100, 1),
                "pct_of_engine_spec": round(
                    cnt / spec_totals.get(spec, 1) * 100, 1),
            })
    effects_df = pd.DataFrame(effect_rows)
    effects_path = DATA_DIR / "bertopic_topic_engine_effects_uk.csv"
    effects_df.to_csv(effects_path, index=False)
    log.info("Saved %s", effects_path.name)

    # ── Save model ───────────────────────────────────────────────────────────
    model_path = DATA_DIR / "bertopic_model_uk"
    topic_model.save(str(model_path), serialization="safetensors",
                     save_ctfidf=True, save_embedding_model="all-mpnet-base-v2")
    log.info("Saved BERTopic model to %s", model_path)

    # ── Print topic overview ─────────────────────────────────────────────────
    log.info("\n=== TOPIC OVERVIEW ===")
    for _, row in terms_df.iterrows():
        tid = int(row["topic"])
        llm_row = llm_df[llm_df["topic"] == tid].iloc[0]
        log.info("  T%d (%.1f%%, %d threads): %s",
                 tid, llm_row["prevalence_pct"],
                 int(llm_row["thread_count"]),
                 row["terms_prob"][:80])


# ═════════════════════════════════════════════════════════════════════════════
# PHASE 6: Post-hoc covariate regression
# ═════════════════════════════════════════════════════════════════════════════

def covariate_regression(df: pd.DataFrame, topics: list) -> None:
    """Multinomial logistic regression: P(topic | engine_spec, prod_year, log_mileage, bucket)."""
    from sklearn.linear_model import LogisticRegression
    from sklearn.preprocessing import OneHotEncoder

    log.info("Running post-hoc covariate regression ...")

    df_reg = df.copy()
    df_reg["topic"] = topics

    # Drop outlier topic (-1)
    df_reg = df_reg[df_reg["topic"] != -1].copy()

    # Only keep topics with enough samples
    topic_counts = df_reg["topic"].value_counts()
    valid_topics = topic_counts[topic_counts >= 5].index
    df_reg = df_reg[df_reg["topic"].isin(valid_topics)].copy()

    if len(valid_topics) < 2:
        log.warning("Not enough topics for regression, skipping")
        return

    # Prepare features
    # Log-transform mileage (fill missing with median, add 1 to avoid log(0))
    miles = df_reg["mileage_miles"].copy()
    miles = miles.fillna(miles.median() if miles.median() is not np.nan else 50000)
    df_reg["mileage_log"] = np.log1p(miles.clip(lower=0))

    # Production year as numeric (fill missing with median, center around 2015)
    year_series = pd.to_numeric(df_reg["prod_year"], errors="coerce")
    year_median = year_series.median()
    if pd.isna(year_median):
        year_median = 2016.0
    year_series = year_series.fillna(year_median)
    df_reg["prod_year_centered"] = year_series - 2015  # center so coefficients are interpretable

    # One-hot encode engine_spec and technical_bucket
    # Filter out rare engine_specs (< 10 threads) to avoid one-hot explosion
    spec_counts = df_reg["engine_spec"].value_counts()
    rare_specs = spec_counts[spec_counts < 10].index
    df_reg["engine_spec_reg"] = df_reg["engine_spec"].replace(
        {s: "other" for s in rare_specs})

    cat_cols = df_reg[["engine_spec_reg", "technical_bucket"]].astype(str)
    ohe = OneHotEncoder(sparse_output=False, drop="first", handle_unknown="ignore")
    cat_encoded = ohe.fit_transform(cat_cols)
    cat_names = ohe.get_feature_names_out(["engine_spec_reg", "technical_bucket"])

    X = np.column_stack([
        df_reg["mileage_log"].values,
        df_reg["prod_year_centered"].values,
        cat_encoded,
    ])
    feature_names = ["mileage_log", "prod_year_centered"] + list(cat_names)
    y = df_reg["topic"].values

    # Fit multinomial logistic regression
    model = LogisticRegression(
        multi_class="multinomial", solver="lbfgs",
        max_iter=1000, C=1.0,
    )
    model.fit(X, y)
    log.info("Regression accuracy: %.1f%%", model.score(X, y) * 100)

    # Build coefficient table: one row per (topic, feature)
    rows = []
    classes = model.classes_
    for i, topic_id in enumerate(classes):
        for j, feat in enumerate(feature_names):
            rows.append({
                "topic": int(topic_id) + 1,  # 1-indexed
                "feature": feat,
                "coefficient": round(float(model.coef_[i, j]), 4),
            })

    coeff_df = pd.DataFrame(rows)
    coeff_path = DATA_DIR / "bertopic_covariate_effects_uk.csv"
    coeff_df.to_csv(coeff_path, index=False)
    log.info("Saved covariate effects to %s (%d rows)", coeff_path.name, len(coeff_df))


# ═════════════════════════════════════════════════════════════════════════════
# MAIN
# ═════════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="BERTopic UK forum pipeline")
    parser.add_argument("--skip-embed", action="store_true",
                        help="Reuse cached embeddings (skip recomputation)")
    parser.add_argument("--min-cluster-size", type=int, default=30,
                        help="HDBSCAN min_cluster_size (default: 30)")
    parser.add_argument("--force-embed", action="store_true",
                        help="Force recompute embeddings even if cached")
    parser.add_argument("--filter-bucket", type=str, default="medium",
                        choices=["low", "medium", "high"],
                        help="Min technical_bucket to keep (default: medium)")
    parser.add_argument("--no-guided", action="store_true",
                        help="Disable guided BERTopic (no seed topics)")
    parser.add_argument("--force-prepare", action="store_true",
                        help="Force re-aggregation and re-scoring (ignore cached prepared data)")
    args = parser.parse_args()

    # Phase 1: Prepare data
    if PREPARED_PATH.exists() and not args.force_prepare:
        log.info("Loading cached prepared data from %s", PREPARED_PATH)
        df = pd.read_csv(PREPARED_PATH)
        log.info("Loaded %d threads", len(df))
    else:
        df = prepare_data()

    # Phase 1b: Pre-filter by technical_bucket
    bucket_order = {"low": 0, "medium": 1, "high": 2}
    min_bucket = bucket_order[args.filter_bucket]
    df["_bucket_ord"] = df["technical_bucket"].map(bucket_order)
    n_before = len(df)
    df = df[df["_bucket_ord"] >= min_bucket].drop(columns=["_bucket_ord"]).reset_index(drop=True)
    log.info("Pre-filter (bucket >= %s): %d -> %d threads", args.filter_bucket, n_before, len(df))
    is_filtered = args.filter_bucket != "low"

    # Phase 2: Clean text for embedding
    docs = df["txt"].apply(clean_text_for_embedding).tolist()

    # Remove empty docs
    valid_mask = [bool(d.strip()) for d in docs]
    if not all(valid_mask):
        n_empty = sum(1 for v in valid_mask if not v)
        log.warning("Removing %d empty documents", n_empty)
        df = df[valid_mask].reset_index(drop=True)
        docs = [d for d, v in zip(docs, valid_mask) if v]

    # Phase 3: Embeddings
    embeddings = compute_embeddings(docs, force=args.force_embed, filtered=is_filtered)

    # Phase 4: BERTopic
    seed_topics = None if args.no_guided else SEED_TOPIC_LIST
    topic_model, topics, probs = fit_bertopic(
        docs, embeddings, min_cluster_size=args.min_cluster_size,
        seed_topics=seed_topics)

    # Phase 5: Outputs
    save_outputs(df, topic_model, topics, probs)

    # Phase 6: Covariate regression
    covariate_regression(df, topics)

    log.info("Done.")


if __name__ == "__main__":
    main()
