#!/usr/bin/env python3
"""
extract_youtube_issues_topic.py
───────────────────────────────
Topic-driven alternative to extract_youtube_issues.py.

Instead of one LLM call per video, we:
  1. Group transcript segments into sentences (reuse helpers).
  2. Embed sentences with sentence-transformers (CUDA).
  3. Cluster with BERTopic (UMAP + HDBSCAN + c-TF-IDF).
  4. Make ONE LLM call per topic with top terms + representative sentences.
  5. Reconstruct per-issue evidence from the source videos of member sentences,
     then reuse refresh_issue_counters / year-context helpers from the
     per-video pipeline so agents.md §7 guardrails stay intact.

Usage:
    DEEPSEEK_API_KEY=<key> python scripts/extract_youtube_issues_topic.py --slug vw_golf_mk7
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np
import torch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts.trim_balance import downsample_performance_videos  # noqa: E402
from scripts.extract_youtube_issues import (  # noqa: E402
    MODEL,
    _MECH_KEYWORDS_HIGH,
    _MECH_KEYWORDS_LOW,
    _group_into_sentences,
    _score_sentence,
    build_min_scaffold_context,
    build_scaffold_context,
    build_video_engine_year_context,
    call_llm,
    enrich_issues_with_year_context,
    extract_issues_from_video,
    infer_video_type_category,
    load_scaffold,
    refresh_issue_counters,
    save_outputs,
    metrics,
)

# Widen signal coverage for body/interior/trim issues often missed by the
# engine-centric baseline keyword set (sunroof leaks, roof lining water
# ingress, trim peeling, etc.).
_EXTRA_BODY_KEYWORDS = {
    "sunroof", "panoramic roof", "roof lining", "headlining", "water ingress",
    "water leak", "door seal", "trim", "interior trim", "dash trim",
    "wiper", "windscreen", "washer", "heated mirror", "boot seal", "tailgate",
    "sealant", "drainage", "drain channel", "cabin leak",
}

# Curated watchlist of chronic issues we don't want to miss if a transcript
# mentions them even once. Keys are pseudo-topic labels, values are phrase
# fragments (case-insensitive substring match). Any sentence matching a
# fragment goes into that pseudo-topic for LLM evaluation.
_WATCHLIST_TOPICS: dict[str, tuple[str, ...]] = {
    "oil_consumption": (
        "oil consumption", "burning oil", "burns oil", "consumes oil",
        "quart of oil", "litre of oil", "liter of oil", "top up oil",
        "topping up oil", "oil level drops",
    ),
    "timing_chain": (
        "timing chain", "chain stretch", "chain tensioner", "chain rattle",
        "chain guide",
    ),
    "piston_ring": (
        "piston ring", "ring collapse", "ring wear",
    ),
    "dsg_mechatronic": (
        "mechatronic", "mechatronics",
    ),
    "dpf_egr": (
        "dpf", "diesel particulate", "egr valve", "egr cooler",
        "adblue", "nox sensor",
    ),
}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

MIN_TOPIC_SIZE = 3
RESCUE_MIN_TOPIC_SIZE = 2
EMBED_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
TOPIC_EXTRACT_TOKENS = 900
REP_DOCS_PER_TOPIC = 12
TOP_TERMS_PER_TOPIC = 15


# ── Sentence collection ──────────────────────────────────────────────────────

def _score_sentence_ext(text: str, word_count: int) -> float:
    """Same as _score_sentence but with extra body/trim keywords to avoid
    dropping sunroof/water-ingress/interior issues."""
    base = _score_sentence(text, word_count)
    lower = text.lower()
    bonus = 0.0
    for kw in _EXTRA_BODY_KEYWORDS:
        if kw in lower:
            bonus += 1.0
    return base + bonus / max(word_count, 1)


def collect_sentences(videos: list[dict]) -> list[dict]:
    """Flatten videos into sentence docs with source metadata."""
    docs: list[dict] = []
    for v in videos:
        vid_id = v.get("video_id", "")
        title = v.get("title", "")
        channel = v.get("channel", "")
        category = v.get("video_type_category") or infer_video_type_category(title)
        segments = v.get("transcript_segments", [])
        sentences = _group_into_sentences(segments) if segments else []
        if not sentences and v.get("transcript_text"):
            for line in str(v["transcript_text"]).splitlines():
                line = line.strip()
                if line:
                    sentences.append({"text": line, "start": 0.0, "word_count": len(line.split())})
        for s in sentences:
            text = s["text"].strip()
            if len(text.split()) < 4:
                continue
            docs.append({
                "text": text,
                "start": s["start"],
                "word_count": s["word_count"],
                "score": _score_sentence_ext(text, s["word_count"]),
                "video_id": vid_id,
                "title": title,
                "channel": channel,
                "video_type_category": category,
            })
    return docs


# ── Embeddings + clustering ──────────────────────────────────────────────────

def embed_sentences(texts: list[str]) -> np.ndarray:
    from sentence_transformers import SentenceTransformer
    device = "cuda" if torch.cuda.is_available() else "cpu"
    log.info("Loading embed model %s on %s", EMBED_MODEL, device)
    model = SentenceTransformer(EMBED_MODEL, device=device)
    t0 = time.perf_counter()
    emb = model.encode(
        texts,
        batch_size=256,
        show_progress_bar=True,
        convert_to_numpy=True,
        normalize_embeddings=True,
    )
    log.info("Embedded %d sentences in %.1fs", len(texts), time.perf_counter() - t0)
    return emb


def fit_topic_model(texts: list[str], embeddings: np.ndarray, min_topic_size: int, *, label: str = "primary"):
    from bertopic import BERTopic
    from umap import UMAP
    from hdbscan import HDBSCAN
    from sklearn.feature_extraction.text import CountVectorizer

    n_docs = len(texts)
    n_neighbors = max(3, min(15, n_docs // 10))
    umap_model = UMAP(
        n_neighbors=n_neighbors,
        n_components=5,
        min_dist=0.0,
        metric="cosine",
        random_state=42,
    )
    hdbscan_model = HDBSCAN(
        min_cluster_size=min_topic_size,
        min_samples=max(1, min_topic_size - 1),
        metric="euclidean",
        cluster_selection_method="eom",
        prediction_data=True,
    )
    vectorizer = CountVectorizer(
        stop_words="english",
        ngram_range=(1, 2),
        min_df=1 if min_topic_size <= 2 else 2,
    )
    topic_model = BERTopic(
        umap_model=umap_model,
        hdbscan_model=hdbscan_model,
        vectorizer_model=vectorizer,
        calculate_probabilities=False,
        verbose=False,
    )
    t0 = time.perf_counter()
    topics, _ = topic_model.fit_transform(texts, embeddings=embeddings)
    log.info("Fit BERTopic(%s) on %d docs in %.1fs", label, n_docs, time.perf_counter() - t0)
    return topic_model, np.asarray(topics)


def build_watchlist_topics(docs: list[dict]) -> dict[str, list[int]]:
    """Find doc indices matching each watchlist topic's phrase fragments.

    Returns {topic_name: [doc_index, ...]} for topics with >=1 hit.
    """
    out: dict[str, list[int]] = {}
    for name, fragments in _WATCHLIST_TOPICS.items():
        idxs: list[int] = []
        for i, d in enumerate(docs):
            text_lower = d["text"].lower()
            if any(f in text_lower for f in fragments):
                idxs.append(i)
        if idxs:
            out[name] = idxs
    return out


def rescue_outliers(
    docs: list[dict],
    embeddings: np.ndarray,
    topic_ids: np.ndarray,
    min_keyword_score: float = 0.005,
):
    """Recluster outlier (-1) sentences that still carry mechanical signal.

    Returns (rescue_topic_model, rescue_topic_ids_aligned_to_outlier_subset,
    outlier_indices_in_original). Primary-topic ids are kept as-is; rescue
    topic ids are returned separately so callers can offset them (e.g. + 1000).
    """
    outlier_idx = np.where(topic_ids == -1)[0]
    if len(outlier_idx) < RESCUE_MIN_TOPIC_SIZE * 3:
        return None, None, outlier_idx

    # Filter outliers to those with keyword signal — noise sentences are worth
    # leaving as noise, but sunroof-style low-frequency hits get rescued.
    keep_mask = np.array([docs[i]["score"] >= min_keyword_score for i in outlier_idx])
    if keep_mask.sum() < RESCUE_MIN_TOPIC_SIZE * 3:
        return None, None, outlier_idx
    kept = outlier_idx[keep_mask]
    texts_kept = [docs[i]["text"] for i in kept]
    emb_kept = embeddings[kept]

    log.info("Rescue pass: reclustering %d/%d outliers with signal",
             len(kept), len(outlier_idx))

    try:
        model, tids = fit_topic_model(texts_kept, emb_kept, RESCUE_MIN_TOPIC_SIZE, label="rescue")
    except Exception as e:
        log.warning("Rescue clustering failed: %s", e)
        return None, None, outlier_idx
    return model, (tids, kept), outlier_idx


# ── Per-topic LLM extraction ─────────────────────────────────────────────────

TOPIC_SYSTEM_TMPL = (
    "You are an automotive knowledge extraction engine.\n"
    "=== VEHICLE SCAFFOLD ===\n{scaffold_context}\n"
    "=== EXTRACTION RULES ===\n"
    "You will receive representative transcript sentences and top terms from a SINGLE topic "
    "cluster mined from many YouTube videos about this car. "
    "Extract the cluster as an issue if it describes ANY of:\n"
    "  - a design or manufacturing defect,\n"
    "  - a chronic failure pattern (timing chain stretch, oil consumption, DSG wear, carbon buildup, "
    "coolant leak, sunroof leak, water ingress, trim peeling, electrical module faults, etc.),\n"
    "  - an emissions/carbon/DPF/EGR/AdBlue problem,\n"
    "  - a known safety recall / TSB referenced in the sentences.\n"
    "Do NOT reject body/trim/interior issues — sunroof leaks, roof lining water damage, peeling trim, "
    "rear LED water ingress, etc. are all in scope.\n"
    "REJECT only if the cluster is pure marketing talk, general driving impression, or unrelated chatter.\n"
    "\n"
    "ENGINE ASSIGNMENT (critical):\n"
    "  - Use ONLY displacement codes listed in the scaffold above (e.g. 1.4_TSI, 2.0_TSI, 1.6_TDI). "
    "Never invent engine codes.\n"
    "  - If the sentences clearly mention a specific engine (1.4 TSI, 2.0 TDI, etc.), list only that one.\n"
    "  - If sentences discuss the EA888 family, list 1.8_TSI and 2.0_TSI. If EA211, list the EA211 displacements "
    "that overlap the mentioned years.\n"
    "  - Use the production year ranges in the scaffold: if sentences say 'pre-2014' or 'early MK7', "
    "restrict to displacement codes whose year_range overlaps that period.\n"
    "  - If the sentences give no engine cue at all but the issue is body/trim/electrical, return [] for engines.\n"
    "  - Never return [\"all\"] — pick specific codes or leave empty.\n"
    "\n"
    "YEARS: copy the most specific verbatim year phrase from the sentences (e.g. 'pre-2014', '2013-2016', "
    "'first 18 months of production'). If none, null.\n"
    "\n"
    "Return ONE JSON object (or {{}} if genuinely noise). No markdown, no prose."
)

TOPIC_USER_TMPL = """\
=== TOPIC {topic_id} ({n_docs} sentences) ===
Top terms: {top_terms}

Representative sentences:
{rep_sentences}

=== TASK ===
If this cluster represents a real issue, return ONE JSON object with this schema:

{{
  "issue_id": "snake_case",
  "label": "max 7 words",
  "system_component": "engine|gearbox|cooling|electrical|suspension|exhaust|brakes|fuel|body|other",
  "affected_engines": ["scaffold displacement codes, or [] if non-engine/unclear"],
  "affected_years": "verbatim year phrase or null",
  "symptom": "one sentence — what driver notices",
  "cause": "root cause or null",
  "fix": "repair/workaround or null",
  "confidence": "low|medium|high",
  "data_quality": "low|medium|high"
}}

If the cluster is pure noise, return {{}}.
"""


def _pick_representative_sentences(member_docs: list[dict], rep_texts_from_bt: list[str]) -> list[dict]:
    """Prefer BERTopic's representative docs; fall back to highest-scored member docs."""
    by_text = {d["text"]: d for d in member_docs}
    picked: list[dict] = []
    seen: set[str] = set()
    for t in rep_texts_from_bt or []:
        if t in by_text and t not in seen:
            picked.append(by_text[t])
            seen.add(t)
    if len(picked) < REP_DOCS_PER_TOPIC:
        extras = sorted(member_docs, key=lambda d: d["score"], reverse=True)
        for d in extras:
            if d["text"] not in seen:
                picked.append(d)
                seen.add(d["text"])
            if len(picked) >= REP_DOCS_PER_TOPIC:
                break
    return picked[:REP_DOCS_PER_TOPIC]


def _build_engine_year_map(scaffold: dict) -> dict[str, tuple[int, int]]:
    """Map each displacement code to its widest year_range across engine families."""
    out: dict[str, tuple[int, int]] = {}
    for fam in scaffold.get("engine_families", []):
        fam_yr = fam.get("year_range")
        for d in fam.get("displacements", []):
            if isinstance(d, dict):
                code = str(d.get("code", "")).strip().upper()
                yr = d.get("year_range") or fam_yr
            else:
                code = str(d).strip().upper()
                yr = fam_yr
            if not code or not yr or len(yr) != 2:
                continue
            try:
                a, b = int(yr[0]), int(yr[1])
            except (TypeError, ValueError):
                continue
            if code in out:
                a = min(a, out[code][0])
                b = max(b, out[code][1])
            out[code] = (a, b)
    return out


_YEAR_INT_RE = __import__("re").compile(r"\b(19\d{2}|20[0-2]\d)\b")
_PRE_RE = __import__("re").compile(r"\b(?:pre|before|up\s*to|until)[\s\-]*(19\d{2}|20[0-2]\d)", __import__("re").IGNORECASE)
_POST_RE = __import__("re").compile(r"\b(?:post|after|from|since)[\s\-]*(19\d{2}|20[0-2]\d)", __import__("re").IGNORECASE)


def _years_window_from_phrase(phrase: str) -> tuple[int, int] | None:
    if not phrase:
        return None
    years = [int(y) for y in _YEAR_INT_RE.findall(phrase) if 1990 <= int(y) <= 2030]
    pre = [int(y) for y in _PRE_RE.findall(phrase)]
    post = [int(y) for y in _POST_RE.findall(phrase)]
    if pre:
        return (1990, max(pre))
    if post:
        return (min(post), 2030)
    if len(years) >= 2:
        return (min(years), max(years))
    if len(years) == 1:
        return (years[0], years[0])
    return None


_ENGINE_MENTION_PATTERNS: list[tuple[str, "re.Pattern"]] = []  # populated by main


def _detect_engine_mentions(member_docs: list[dict]) -> set[str]:
    if not _ENGINE_MENTION_PATTERNS:
        return set()
    found: set[str] = set()
    for d in member_docs:
        lower = d["text"].lower()
        for code, pat in _ENGINE_MENTION_PATTERNS:
            if pat.search(lower):
                found.add(code)
    return found


def validate_engine_assignment(issue: dict, engine_year_map: dict[str, tuple[int, int]], evidence_engines: set[str] | None = None) -> dict:
    """Drop engines whose year_range does not overlap the extracted affected_years.
    Also normalize 'all' / invalid codes.
    """
    engs = issue.get("affected_engines")
    if isinstance(engs, str):
        engs = [engs]
    if not isinstance(engs, list):
        issue["affected_engines"] = []
        return issue

    # Normalize
    cleaned: list[str] = []
    for e in engs:
        code = str(e).strip().upper()
        if not code or code == "ALL":
            continue
        if code in engine_year_map:
            cleaned.append(code)

    window = _years_window_from_phrase(str(issue.get("affected_years") or ""))
    notes: list[str] = []
    if window and cleaned:
        a, b = window
        filtered = [c for c in cleaned if not (engine_year_map[c][1] < a or engine_year_map[c][0] > b)]
        if filtered and len(filtered) != len(cleaned):
            notes.append(f"dropped {sorted(set(cleaned) - set(filtered))} outside years {a}-{b}")
            cleaned = filtered

    # Evidence-based narrowing: if member sentences explicitly mentioned engine
    # codes, restrict assignment to that family. Sister displacements (same
    # engine family) are kept since issues typically affect whole families.
    if evidence_engines:
        # Group scaffold codes into families by year-range adjacency (simple proxy).
        ev = {c for c in evidence_engines if c in engine_year_map}
        if ev:
            # Keep codes that share at least one evidence family: any with
            # year_range overlapping an evidence code's year_range.
            def _overlaps(c1: str, c2: str) -> bool:
                a1, b1 = engine_year_map[c1]
                a2, b2 = engine_year_map[c2]
                return not (b1 < a2 or b2 < a1)
            narrowed = [c for c in cleaned if any(_overlaps(c, e) for e in ev)]
            # Only apply narrowing if it actually reduces and doesn't empty out.
            if narrowed and len(narrowed) < len(cleaned):
                notes.append(f"narrowed to evidence engines {sorted(ev)}: dropped {sorted(set(cleaned) - set(narrowed))}")
                cleaned = narrowed

    if notes:
        issue["engine_filter_note"] = "; ".join(notes)
    issue["affected_engines"] = cleaned
    return issue


def _parse_object(raw: str) -> dict | None:
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("```", 2)[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()
    try:
        obj = json.loads(raw)
    except json.JSONDecodeError:
        start = raw.find("{")
        end = raw.rfind("}")
        if start < 0 or end < start:
            return None
        try:
            obj = json.loads(raw[start:end + 1])
        except json.JSONDecodeError:
            return None
    if isinstance(obj, list):
        obj = obj[0] if obj else {}
    return obj if isinstance(obj, dict) else None


def extract_issue_for_topic(
    topic_id: int,
    member_docs: list[dict],
    top_terms: list[tuple[str, float]],
    rep_texts: list[str],
    scaffold_context: str,
) -> dict | None:
    rep = _pick_representative_sentences(member_docs, rep_texts)
    rep_block = "\n".join(f"- {d['text']}" for d in rep)
    top_terms_str = ", ".join(t for t, _ in top_terms[:TOP_TERMS_PER_TOPIC])

    sys_prompt = TOPIC_SYSTEM_TMPL.format(scaffold_context=scaffold_context)
    user_prompt = TOPIC_USER_TMPL.format(
        topic_id=topic_id,
        n_docs=len(member_docs),
        top_terms=top_terms_str,
        rep_sentences=rep_block,
    )
    try:
        raw = call_llm(sys_prompt, user_prompt, TOPIC_EXTRACT_TOKENS, label=f"topic:{topic_id}")
    except Exception as e:
        log.warning("  [topic %d] LLM call failed: %s", topic_id, e)
        return None
    obj = _parse_object(raw)
    if not obj or not obj.get("label"):
        log.info("  [topic %d] rejected by LLM or empty", topic_id)
        return None

    # Attach evidence from all member sentences (deduplicated by video).
    sources: dict[str, dict] = {}
    for d in member_docs:
        vid = d["video_id"]
        if vid in sources:
            continue
        sources[vid] = {
            "video_id": vid,
            "title": d["title"],
            "channel": d["channel"],
            "video_type_category": d["video_type_category"],
        }
    obj["source_videos"] = list(sources.values())
    try:
        obj["topic_id"] = int(topic_id)
    except (TypeError, ValueError):
        obj["topic_id"] = str(topic_id)
    obj["topic_size"] = len(member_docs)
    obj["_evidence_engines"] = sorted(_detect_engine_mentions(member_docs))
    obj["topic_top_terms"] = [t for t, _ in top_terms[:TOP_TERMS_PER_TOPIC]]
    obj["source"] = "youtube"
    return obj


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--slug", default="vw_golf_mk7")
    ap.add_argument("--min-topic-size", type=int, default=MIN_TOPIC_SIZE)
    ap.add_argument("--min-score", type=float, default=0.0,
                    help="Drop sentences with _score_sentence <= this before clustering.")
    ap.add_argument("--min-corroboration", type=int, default=2)
    ap.add_argument("--perf-trim-share", type=float, default=None,
                    help="Max share of corpus allowed for scaffold performance_trims "
                         "(overrides scaffold.performance_trims.max_share).")
    ap.add_argument("--output-suffix", default="topic",
                    help="Suffix for output file naming: issue_knowledge_youtube_{slug}_{suffix}.json")
    args = ap.parse_args()

    if not os.environ.get("DEEPSEEK_API_KEY"):
        sys.exit("DEEPSEEK_API_KEY not set")

    in_path = ROOT / "data" / "raw" / "videos" / f"{args.slug}_raw.json"
    out_json = ROOT / "data" / "processed" / f"issue_knowledge_youtube_{args.slug}_{args.output_suffix}.json"
    out_csv = out_json.with_suffix(".csv")

    if not in_path.exists():
        sys.exit(f"Input not found: {in_path}")

    with open(in_path, encoding="utf-8") as f:
        data = json.load(f)
    videos = [v for v in data["videos"] if v.get("transcript_status") == "ok"]
    log.info("Loaded %d usable videos", len(videos))

    scaffold = load_scaffold(args.slug)
    # Performance-trim balancing belongs at discovery (scraper), not here:
    # dropping cached videos at extract time removes unique fault evidence and
    # hurts recall. Only apply if the user explicitly sets --perf-trim-share.
    if args.perf_trim_share is not None:
        videos = downsample_performance_videos(
            videos, scaffold, share_override=args.perf_trim_share,
        )
        log.info("Corpus after performance-trim balancing: %d videos", len(videos))

    scaffold_ctx_full = build_scaffold_context(scaffold)
    scaffold_ctx_min = build_min_scaffold_context(scaffold)
    engine_year_map = _build_engine_year_map(scaffold)
    log.info("Engine-year map: %s", engine_year_map)

    # Populate engine mention patterns for evidence-based narrowing.
    import re as _re_local
    _ENGINE_MENTION_PATTERNS.clear()
    for code in engine_year_map:
        low = code.lower()
        if "_" in low:
            number, fuel = low.split("_", 1)
            num_pat = _re_local.escape(number).replace(r"\.", r"[\.,]")
            pat = _re_local.compile(
                rf"\b{num_pat}\s*(?:l|liter|litre|lt)?\s*[-_/]?\s*{_re_local.escape(fuel)}\b|\b{_re_local.escape(low)}\b",
                _re_local.IGNORECASE,
            )
        else:
            pat = _re_local.compile(rf"\b{_re_local.escape(low)}\b", _re_local.IGNORECASE)
        _ENGINE_MENTION_PATTERNS.append((code, pat))

    t_start = time.perf_counter()
    metrics["start_time"] = t_start

    # 1. Sentences
    docs = collect_sentences(videos)
    log.info("Collected %d sentences", len(docs))
    if args.min_score > 0:
        before = len(docs)
        docs = [d for d in docs if d["score"] >= args.min_score]
        log.info("Filtered by min_score=%.3f: %d → %d", args.min_score, before, len(docs))
    if len(docs) < args.min_topic_size * 3:
        sys.exit(f"Too few sentences ({len(docs)}) for clustering")

    texts = [d["text"] for d in docs]

    # 2. Embeddings
    t_embed = time.perf_counter()
    embeddings = embed_sentences(texts)

    # 3. Cluster (primary)
    t_cluster = time.perf_counter()
    topic_model, topic_ids = fit_topic_model(texts, embeddings, args.min_topic_size, label="primary")
    info_df = topic_model.get_topic_info()
    n_topics = int((info_df["Topic"] >= 0).sum())
    n_outliers = int((topic_ids == -1).sum())
    log.info("Primary: %d topics, %d outlier sentences", n_topics, n_outliers)

    try:
        rep_docs_map = topic_model.get_representative_docs()
    except Exception:
        rep_docs_map = {}

    # 3b. Rescue pass on outliers with signal
    rescue_model = None
    rescue_topic_ids: np.ndarray | None = None
    rescue_kept_idx: np.ndarray | None = None
    rescue_rep_map: dict = {}
    rescue_model, rescue_bundle, _ = rescue_outliers(docs, embeddings, topic_ids)
    if rescue_model is not None and rescue_bundle is not None:
        rescue_topic_ids, rescue_kept_idx = rescue_bundle
        try:
            rescue_rep_map = rescue_model.get_representative_docs()
        except Exception:
            rescue_rep_map = {}
        rescue_info = rescue_model.get_topic_info()
        rescue_n = int((rescue_info["Topic"] >= 0).sum())
        log.info("Rescue: %d additional topics from outliers", rescue_n)

    # 4. Per-topic LLM extraction
    t_llm = time.perf_counter()
    raw_issues: list[dict] = []

    def _run_topic(tid: int, member_docs_local: list[dict], top_terms_local, rep_texts_local, tid_out: int):
        issue = extract_issue_for_topic(tid, member_docs_local, top_terms_local, rep_texts_local, scaffold_ctx_full)
        if issue:
            issue["topic_id"] = tid_out
            raw_issues.append(issue)

    for _, row in info_df.iterrows():
        tid = int(row["Topic"])
        if tid < 0:
            continue
        member_idx = np.where(topic_ids == tid)[0]
        member_docs = [docs[i] for i in member_idx]
        top_terms = topic_model.get_topic(tid) or []
        rep_texts = rep_docs_map.get(tid, []) if isinstance(rep_docs_map, dict) else []
        _run_topic(tid, member_docs, top_terms, rep_texts, tid)

    if rescue_model is not None and rescue_topic_ids is not None and rescue_kept_idx is not None:
        r_info = rescue_model.get_topic_info()
        for _, row in r_info.iterrows():
            rtid = int(row["Topic"])
            if rtid < 0:
                continue
            member_sub_idx = np.where(rescue_topic_ids == rtid)[0]
            member_orig_idx = rescue_kept_idx[member_sub_idx]
            member_docs = [docs[i] for i in member_orig_idx]
            top_terms = rescue_model.get_topic(rtid) or []
            rep_texts = rescue_rep_map.get(rtid, []) if isinstance(rescue_rep_map, dict) else []
            _run_topic(rtid, member_docs, top_terms, rep_texts, 1000 + rtid)

    # Enumeration-video augmentation: for list-format / "issues of" videos,
    # topic clustering discards single-mention issues as HDBSCAN outliers. Send
    # the full transcript through the per-video LLM extractor and merge the
    # results in — the Jaccard dedup stage below will fold overlaps.
    def _is_enumeration_video(v: dict) -> bool:
        blob = f"{v.get('title','')} {v.get('channel','')}".lower()
        enum_markers = (
            "issues of", "issues of the", "problems of", "common problems",
            "goes wrong", "things that break", "things go wrong",
            "avoid buying", "avoid these", "buyer's guide", "buyers guide",
            "known faults", "reliability review", "what goes wrong",
            "used car review", "used review", "buying a used", "problems",
            "chronic", "kronik",
        )
        if v.get("video_type_category") == "list_format":
            return True
        return any(m in blob for m in enum_markers)

    enum_videos = [v for v in videos if _is_enumeration_video(v)]
    log.info("Enumeration videos: %d / %d → running per-video LLM extraction",
             len(enum_videos), len(videos))
    for v in enum_videos:
        v_issues = extract_issues_from_video(v, scaffold, hit_ratio=0.2)
        for iss in v_issues:
            vid = iss.pop("source_video_id", v["video_id"])
            iss["source_videos"] = [{
                "video_id": vid,
                "title": iss.pop("source_title", v.get("title", "")),
                "channel": iss.pop("source_channel", v.get("channel", "")),
                "video_type_category": iss.get("video_type_category")
                    or v.get("video_type_category")
                    or infer_video_type_category(v.get("title", "")),
            }]
            iss["source"] = "youtube"
            iss["topic_id"] = "enum_augment"
            iss["topic_size"] = 1
            iss.setdefault("topic_top_terms", [])
            iss["_evidence_engines"] = []
            raw_issues.append(iss)

    # 4c. Watchlist pass — keyword-guided bundles for must-not-miss issues
    watchlist = build_watchlist_topics(docs)
    log.info("Watchlist hits: %s", {k: len(v) for k, v in watchlist.items()})
    for wl_idx, (name, idxs) in enumerate(watchlist.items()):
        member_docs = [docs[i] for i in idxs]
        # Fake top-terms from the fragments, for the LLM prompt
        top_terms = [(frag, 1.0) for frag in _WATCHLIST_TOPICS[name]]
        rep_texts = [d["text"] for d in sorted(member_docs, key=lambda d: d["score"], reverse=True)[:REP_DOCS_PER_TOPIC]]
        _run_topic(f"watchlist:{name}", member_docs, top_terms, rep_texts, 2000 + wl_idx)

    log.info("LLM extracted %d issues total (pre-dedup)", len(raw_issues))

    # 4b. Engine-year validation + evidence-based narrowing
    for issue in raw_issues:
        ev = set(issue.pop("_evidence_engines", []) or [])
        validate_engine_assignment(issue, engine_year_map, evidence_engines=ev)

    # 4d. Near-duplicate dedup by shared keyword signature
    # Build a signature = {component} + set of content-word tokens from label+symptom.
    import re as _re_dd
    _STOP = {"the", "a", "an", "and", "or", "of", "on", "in", "to", "for",
             "with", "from", "at", "is", "are", "be", "this", "that",
             "causes", "causing", "issues", "problems", "failure", "failures",
             "due", "may", "model", "models", "year", "years"}

    def _signature(issue: dict) -> tuple[str, frozenset]:
        comp = str(issue.get("system_component", "")).lower().strip()
        blob = f"{issue.get('label','')} {issue.get('symptom','')}".lower()
        toks = {t for t in _re_dd.findall(r"[a-z0-9]{3,}", blob) if t not in _STOP}
        return comp, frozenset(toks)

    def _merge_into(target: dict, other: dict) -> None:
        cur_sources = {s.get("video_id"): s for s in target.get("source_videos", []) if isinstance(s, dict)}
        for s in other.get("source_videos", []):
            if isinstance(s, dict) and s.get("video_id") and s["video_id"] not in cur_sources:
                cur_sources[s["video_id"]] = s
        target["source_videos"] = list(cur_sources.values())
        target["topic_size"] = max(target.get("topic_size", 0), other.get("topic_size", 0))
        # Union engines
        engs = list({*(target.get("affected_engines") or []), *(other.get("affected_engines") or [])})
        target["affected_engines"] = engs
        for f in ("cause", "fix", "affected_years"):
            if not target.get(f) and other.get(f):
                target[f] = other[f]

    kept: list[dict] = []
    sigs: list[tuple[str, frozenset]] = []
    for issue in raw_issues:
        comp, toks = _signature(issue)
        merged = False
        for idx, (kcomp, ktoks) in enumerate(sigs):
            if kcomp != comp:
                continue
            if not ktoks or not toks:
                continue
            jaccard = len(ktoks & toks) / len(ktoks | toks)
            if jaccard >= 0.45:
                _merge_into(kept[idx], issue)
                # Union tokens to keep merging similar ones
                sigs[idx] = (kcomp, ktoks | toks)
                merged = True
                break
        if not merged:
            kept.append(issue)
            sigs.append((comp, toks))
    raw_issues = kept
    log.info("After dedup: %d issues", len(raw_issues))

    # 5. Evidence counters + year context
    issues = refresh_issue_counters(raw_issues)
    video_engine_ctx = build_video_engine_year_context(videos, scaffold)
    issues = enrich_issues_with_year_context(issues, video_engine_ctx)

    issues.sort(
        key=lambda x: (
            x.get("corroboration_count", 0),
            x.get("distinct_channel_count", 0),
            x.get("mention_count", 0),
        ),
        reverse=True,
    )

    save_outputs(issues, out_json, out_csv)

    # Confirmed subset (same rule as the per-video pipeline).
    RESCUE_KW = {"dpf", "egr", "edc", "adblue", "injector", "bearing", "timing chain", "timing belt", "turbo"}
    confirmed = []
    for i in issues:
        count = i.get("corroboration_count", 0)
        conf = str(i.get("confidence", "")).lower()
        dq = str(i.get("data_quality", "")).lower()
        text = f"{i.get('label','')} {i.get('symptom','')}".lower()
        if count >= args.min_corroboration or (count >= 1 and conf == "high" and (dq == "high" or any(k in text for k in RESCUE_KW))):
            confirmed.append(i)
    conf_json = out_json.with_stem(out_json.stem + "_confirmed")
    save_outputs(confirmed, conf_json, conf_json.with_suffix(".csv"))

    t_end = time.perf_counter()
    log.info("=== Performance ===")
    log.info("Total: %.1fs | embed: %.1fs | cluster: %.1fs | LLM: %.1fs",
             t_end - t_start, t_cluster - t_embed, t_llm - t_cluster, t_end - t_llm)
    log.info("LLM calls: %d | in tokens: %d | out tokens: %d",
             metrics["llm_calls"], metrics["total_input_tokens"], metrics["total_output_tokens"])
    log.info("Done — %d issues (%d confirmed) written", len(issues), len(confirmed))


if __name__ == "__main__":
    main()
