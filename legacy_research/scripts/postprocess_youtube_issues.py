#!/usr/bin/env python3
"""
postprocess_youtube_issues.py
─────────────────────────────
Post-process the LLM-extracted YouTube issue knowledge:

  1. Dedup  — collapse the same failure when the model minted multiple slugs.
  2. Scope  — separate engine-scoped powertrain issues from car-wide issues;
              validate engine scope against a feature allowlist; add model_scope.
  3. Years  — triangulate affected_years from three independent sources
              (transcript evidence, source-video titles, engine production windows)
              and emit a confidence label. The video upload date is NEVER used.

Input  : data/processed/issue_knowledge_youtube_{slug}_year_enriched.json
Output : data/processed/issue_knowledge_youtube_{slug}_final.json (+ .csv)
         reports/youtube_postprocess_audit_{slug}.md

Usage:
    python scripts/postprocess_youtube_issues.py --slug vw_golf_mk7
"""

from __future__ import annotations

import argparse
import json
import logging
import re
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

import pandas as pd
import yaml

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent


# ── Scaffold-derived builders ─────────────────────────────────────────────────
# All model-specific constants (engine windows, feature rules, facelift years)
# now live in the scaffold YAML (data/scaffolds/{slug}.yaml).
# Adding a new car model requires only a YAML file — no Python changes.

def _build_engine_windows(scaffold: dict) -> dict[str, tuple[int, int]]:
    """Derive {displacement_code: (start_year, end_year)} from scaffold YAML.

    Handles two `displacements` formats:
    - New (generation-specific):  list of {code, year_range} dicts
    - Legacy (family-wide):       flat list of strings; uses family year_range
    """
    windows: dict[str, tuple[int, int]] = {}
    for family in scaffold.get("engine_families") or []:
        family_yr = family.get("year_range") or []
        for d in family.get("displacements") or []:
            if isinstance(d, dict):
                code = str(d.get("code", "")).strip()
                yr   = d.get("year_range") or family_yr
            else:
                code = str(d).strip()
                yr   = family_yr
            if code and len(yr) >= 2:
                windows[code] = (int(yr[0]), int(yr[1]))
    return windows


def _get_model_window(scaffold: dict) -> tuple[int, int]:
    """Return the overall (start, end) year window from scaffold corpus_years."""
    cy = (scaffold.get("meta") or {}).get("corpus_years") or []
    if len(cy) >= 2:
        return (int(cy[0]), int(cy[1]))
    wins = _build_engine_windows(scaffold)
    if wins:
        return (min(w[0] for w in wins.values()), max(w[1] for w in wins.values()))
    return (2013, 2021)  # last-resort fallback


def _build_semantic_phrases(scaffold: dict) -> dict[str, tuple[int, int]]:
    """Build year-phrase → span map from scaffold facelifts + generic early/late terms."""
    model_window = _get_model_window(scaffold)
    lo, hi = model_window
    phrases: dict[str, tuple[int, int]] = {}

    for fl in scaffold.get("facelifts") or []:
        yr = int(fl["year"])
        pre_span  = (lo, yr - 1)
        post_span = (yr, hi)
        phrases["before facelift"] = pre_span
        phrases["pre-facelift"]    = pre_span
        phrases["pre facelift"]    = pre_span
        phrases["facelift"]        = post_span
        phrases["post-facelift"]   = post_span
        phrases["post facelift"]   = post_span

    # Generic early/late anchors — last third of pre-facelift window
    mid = lo + max(1, (hi - lo) // 3)
    phrases["early model"]   = (lo, mid)
    phrases["early cars"]    = (lo, mid)
    phrases["earlier model"] = (lo, mid)
    phrases["earlier cars"]  = (lo, mid)
    return phrases


# Which system_components are genuinely engine-scoped.
# Everything else is car-wide unless an explicit variant cue appears.
POWERTRAIN_COMPONENTS: set[str] = {"engine", "fuel", "exhaust", "cooling"}
DRIVETRAIN_COMPONENTS: set[str] = {"gearbox"}
# body / electrical / suspension / brakes / other → car-wide by default

_LIST_FORMAT_SIGNALS = (
    "buyer's guide",
    "buyers guide",
    "common problems",
    "common issues",
    "common faults",
    "avoid buying",
    "what to look for",
    "things that break",
    "known faults",
    "reliability review",
    "problems with",
)

_TRIM_ORDER = ("GTI", "R", "GTD", "R-Line", "TDI", "base", "unknown")


# ── Dedup tokenisation ───────────────────────────────────────────────────────

# Stopwords we strip before comparing issue_id tokens. These are filler words
# the LLM adds that don't carry semantic identity.
_STOPWORDS: set[str] = {
    "failure", "failures", "fail", "failing", "faulty",
    "fault", "faults",
    "issue", "issues", "problem", "problems",
    "assembly", "system", "systems",
    "defect", "defective", "bad",
    "on", "of", "the", "a", "for", "in", "and", "or", "to",
    "with", "by", "at", "from",
    "premature",
}

# Token-level normalisation applied BEFORE stopword filtering.
_SYNONYMS: dict[str, str] = {
    "cooling": "coolant",
    "waterpump": "waterpump",  # canonical; composite split below
    "tstat": "thermostat",
    "ac": "aircon",
    "hvac": "aircon",
    "airconditioning": "aircon",
    "airconditioner": "aircon",
    "air": "aircon",  # rough; usually paired with _conditioning
    "turbocharger": "turbo",
    "gearbox": "gearbox",
    "transmission": "gearbox",
    "leaking": "leak",
    "leakage": "leak",
    "leaks": "leak",
    "cracking": "crack",
    "cracks": "crack",
    "cracked": "crack",
    "seals": "seal",
    "sealing": "seal",
    "wearing": "wear",
    "worn": "wear",
    "sticking": "stick",
    "stuck": "stick",
    "clogging": "clog",
    "clogged": "clog",
    "disintegration": "disintegrate",
    "disintegrating": "disintegrate",
    "loosening": "loose",
    "loosen": "loose",
    "rattling": "rattle",
    "rattles": "rattle",
    "squeaking": "squeak",
    "squeaks": "squeak",
    "knocking": "knock",
    "knocks": "knock",
    "malfunction": "fault",  # pre-stopword
    "housing": "housing",
    "unit": "unit",
    # Common multi-token collapses — the _split_composite helper catches these.
}

# Tokens that, once seen, map a composite word → split tokens (before synonym pass).
# e.g. "waterpump" → ["water", "pump"].
_COMPOSITE_SPLITS: dict[str, list[str]] = {
    "waterpump": ["water", "pump"],
}


def _tokenise(text: str) -> list[str]:
    """Split on non-word characters, lower-case, apply composite splits + synonyms,
    drop stopwords and very short tokens."""
    if not text:
        return []
    toks = re.split(r"[^a-z0-9]+", text.lower())
    out: list[str] = []
    for t in toks:
        if not t:
            continue
        for piece in _COMPOSITE_SPLITS.get(t, [t]):
            piece = _SYNONYMS.get(piece, piece)
            if piece in _STOPWORDS:
                continue
            if len(piece) < 2:
                continue
            out.append(piece)
    return out


def _issue_token_bag(issue: dict) -> frozenset[str]:
    """The identity bag we cluster on. Derived from issue_id primarily, with
    label as a secondary signal when issue_id is thin."""
    bag: set[str] = set()
    bag.update(_tokenise(issue.get("issue_id") or ""))
    # Include label for cases where issue_id is very short.
    if len(bag) < 3:
        bag.update(_tokenise(issue.get("label") or ""))
    return frozenset(bag)


def _jaccard(a: frozenset, b: frozenset) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


# ── Merge logic ──────────────────────────────────────────────────────────────

_SEV_RANK = {"low": 1, "medium": 2, "high": 3}
_CONF_RANK = {"low": 1, "medium": 2, "high": 3}


def _pick_longest(rows: list[dict], field: str) -> Any:
    vals = [r.get(field) for r in rows if r.get(field)]
    if not vals:
        return None
    return max(vals, key=lambda v: len(str(v)))


def _merge_engine_year_context(rows: list[dict]) -> list[dict]:
    """Union years per engine, sum evidence_hits."""
    agg: dict[str, dict[str, Any]] = {}
    for r in rows:
        for ctx in r.get("engine_year_context") or []:
            eng = ctx.get("engine")
            if not eng:
                continue
            slot = agg.setdefault(eng, {"years": set(), "evidence_hits": 0})
            years_str = ctx.get("years")
            if years_str:
                if "-" in str(years_str):
                    a, b = str(years_str).split("-", 1)
                    try:
                        slot["years"].update(range(int(a), int(b) + 1))
                    except ValueError:
                        pass
                else:
                    try:
                        slot["years"].add(int(years_str))
                    except ValueError:
                        pass
            slot["evidence_hits"] += int(ctx.get("evidence_hits") or 0)

    out = []
    for eng, slot in agg.items():
        years = sorted(y for y in slot["years"] if 1990 <= y <= 2030)
        if not years:
            continue
        span = str(years[0]) if len(years) == 1 else f"{years[0]}-{years[-1]}"
        out.append({"engine": eng, "years": span, "evidence_hits": slot["evidence_hits"]})
    return out


def _merge_cluster(rows: list[dict]) -> dict:
    """Merge N duplicate issue rows into one canonical row."""
    if len(rows) == 1:
        return dict(rows[0])

    # Canonical = row with most source_videos, then highest mention_count.
    canon = max(
        rows,
        key=lambda r: (len(r.get("source_videos") or []), r.get("mention_count") or 0),
    )
    out = dict(canon)

    # Union source_videos by video_id.
    sv_by_id: dict[str, dict] = {}
    for r in rows:
        for sv in r.get("source_videos") or []:
            if isinstance(sv, dict):
                vid = sv.get("video_id")
                if vid and vid not in sv_by_id:
                    sv_by_id[vid] = sv
    out["source_videos"] = list(sv_by_id.values())
    out["mention_count"] = len(sv_by_id) or out.get("mention_count") or len(rows)

    # Union engines (drop "all" if we have specific codes).
    engines: set[str] = set()
    had_all = False
    for r in rows:
        for e in r.get("affected_engines") or []:
            e = str(e).strip()
            if not e:
                continue
            if e.lower() == "all":
                had_all = True
                continue
            engines.add(e)
    if engines:
        out["affected_engines"] = sorted(engines)
    elif had_all:
        out["affected_engines"] = ["all"]
    else:
        out["affected_engines"] = []

    # Union warning_signs, case-insensitive dedup.
    seen: set[str] = set()
    signs: list[str] = []
    for r in rows:
        for s in r.get("warning_signs") or []:
            k = str(s).strip().lower()
            if k and k not in seen:
                seen.add(k)
                signs.append(s)
    out["warning_signs"] = signs

    # Max severity / confidence.
    out["severity"] = max(
        (r.get("severity") or "low" for r in rows), key=lambda s: _SEV_RANK.get(s, 0)
    )
    out["confidence"] = max(
        (r.get("confidence") or "low" for r in rows), key=lambda s: _CONF_RANK.get(s, 0)
    )

    # Longest non-empty for descriptive fields.
    for field in ("symptom", "cause", "fix", "inspection_advice", "notes",
                  "onset_km_range", "label"):
        best = _pick_longest(rows, field)
        if best:
            out[field] = best

    shorts = [r.get("label_short") for r in rows if r.get("label_short")]
    if shorts:
        out["label_short"] = min(shorts, key=len)

    # Provenance.
    merged_ids = sorted({r.get("issue_id", "") for r in rows if r.get("issue_id")})
    if len(merged_ids) > 1:
        out["merged_from_issue_ids"] = merged_ids

    # engine_year_context
    merged_ctx = _merge_engine_year_context(rows)
    if merged_ctx:
        out["engine_year_context"] = merged_ctx
    elif "engine_year_context" in out:
        del out["engine_year_context"]

    return out


# ── Dedup driver ─────────────────────────────────────────────────────────────

def dedup_issues(issues: list[dict], jaccard_threshold: float = 0.55) -> tuple[list[dict], list[list[str]]]:
    """Collapse near-duplicate issues. Returns (deduped_issues, merge_groups)."""
    if not issues:
        return [], []

    # Step 1: exact-bag collapse within same system_component.
    exact_key: dict[tuple, list[dict]] = defaultdict(list)
    for it in issues:
        bag = _issue_token_bag(it)
        key = (bag, it.get("system_component") or "")
        exact_key[key].append(it)
    stage1 = [_merge_cluster(rows) for rows in exact_key.values()]
    log.info("Dedup stage 1 (exact-bag): %d → %d", len(issues), len(stage1))

    # Step 2: pairwise Jaccard within same system_component.
    n = len(stage1)
    parent = list(range(n))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    bags = [_issue_token_bag(it) for it in stage1]
    comps = [it.get("system_component") or "" for it in stage1]

    for i in range(n):
        if not bags[i]:
            continue
        for j in range(i + 1, n):
            if comps[i] != comps[j]:
                continue
            if not bags[j]:
                continue
            overlap = bags[i] & bags[j]
            if len(overlap) < 2:
                continue
            # Subset cases merge regardless of Jaccard (e.g. {water,pump,thermostat,leak}
            # subset of {coolant,water,pump,thermostat,housing,leak}).
            if bags[i] <= bags[j] or bags[j] <= bags[i]:
                union(i, j)
                continue
            if _jaccard(bags[i], bags[j]) >= jaccard_threshold:
                union(i, j)

    clusters: dict[int, list[dict]] = defaultdict(list)
    for i in range(n):
        clusters[find(i)].append(stage1[i])

    merged = [_merge_cluster(rows) for rows in clusters.values()]
    merge_groups = [
        sorted({r.get("issue_id", "") for r in rows if r.get("issue_id")})
        for rows in clusters.values()
        if len(rows) > 1
    ]
    log.info("Dedup stage 2 (Jaccard ≥ %.2f): %d → %d", jaccard_threshold, len(stage1), len(merged))
    return merged, merge_groups


# ── Scope classification ─────────────────────────────────────────────────────

def _trigger_blob(issue: dict) -> str:
    parts = [
        issue.get("issue_id") or "",
        issue.get("label") or "",
        issue.get("label_short") or "",
        issue.get("cause") or "",
        issue.get("symptom") or "",
    ]
    return " ".join(parts).lower().replace("_", " ")


def _infer_video_type_category(title: str | None) -> str:
    text = (title or "").lower()
    if any(sig in text for sig in _LIST_FORMAT_SIGNALS):
        return "list_format"
    return "organic"


def _infer_trim_from_title(title: str | None) -> str:
    text = (title or "").strip()
    if not text:
        return "unknown"
    low = text.lower()

    if re.search(r"\bgtd\b", low):
        return "GTD"
    if re.search(r"\br[- ]?line\b", low):
        return "R-Line"
    if re.search(r"\bgti\b", low) and not re.search(r"\bgtd\b", low):
        return "GTI"
    if re.search(r"\bgolf\s*r\b", low) or re.search(r"\bmk7(?:\.5)?\s*r\b", low):
        return "R"
    if re.search(r"\btdi\b|\bdiesel\b", low):
        return "TDI"
    return "base"


def _normalize_source_videos(issue: dict, videos_by_id: dict[str, dict]) -> list[dict]:
    normalized: list[dict] = []
    seen: set[tuple[str, str, str]] = set()
    raw_sources = issue.get("source_videos")
    if not isinstance(raw_sources, list):
        raw_sources = []

    if not raw_sources:
        sid = str(issue.get("source_video_id", "")).strip()
        stitle = str(issue.get("source_title", "")).strip()
        schannel = str(issue.get("source_channel", "")).strip()
        if sid or stitle or schannel:
            raw_sources = [
                {
                    "video_id": sid,
                    "title": stitle,
                    "channel": schannel,
                }
            ]

    for row in raw_sources:
        if not isinstance(row, dict):
            continue
        video_id = str(row.get("video_id", "")).strip()
        fallback = videos_by_id.get(video_id) or {}
        title = str(row.get("title") or fallback.get("title") or "").strip()
        channel = str(row.get("channel") or fallback.get("channel") or "").strip()
        category = (
            str(row.get("video_type_category") or fallback.get("video_type_category") or "").strip()
            or _infer_video_type_category(title)
        )
        trim = str(row.get("trim") or "").strip() or _infer_trim_from_title(title)
        key = (video_id, title.lower(), channel.lower())
        if key in seen:
            continue
        seen.add(key)
        normalized.append(
            {
                "video_id": video_id,
                "title": title,
                "channel": channel,
                "video_type_category": category,
                "trim": trim,
            }
        )
    return normalized


def _apply_trim_bias_controls(issue: dict, videos_by_id: dict[str, dict], slug: str) -> dict:
    sources = _normalize_source_videos(issue, videos_by_id)
    issue["source_videos"] = sources

    unique_video_mentions: set[str] = set()
    unique_channels: set[str] = set()
    organic_mentions: set[str] = set()
    list_channels: set[str] = set()
    trim_evidence: dict[str, int] = defaultdict(int)
    trim_organic_mentions: dict[str, set[str]] = defaultdict(set)
    trim_list_channels: dict[str, set[str]] = defaultdict(set)

    for src in sources:
        video_id = str(src.get("video_id", "")).strip()
        title = str(src.get("title", "")).strip()
        channel = str(src.get("channel", "")).strip().lower()
        category = str(src.get("video_type_category", "")).strip() or _infer_video_type_category(title)
        trim = str(src.get("trim", "")).strip() or _infer_trim_from_title(title)
        src["video_type_category"] = category
        src["trim"] = trim

        mention_key = video_id or f"{title.lower()}|{channel}"
        if mention_key:
            unique_video_mentions.add(mention_key)
        channel_key = channel or mention_key
        if channel_key:
            unique_channels.add(channel_key)

        trim_evidence[trim] += 1
        if category == "list_format":
            if channel_key:
                list_channels.add(channel_key)
                trim_list_channels[trim].add(channel_key)
        else:
            if mention_key:
                organic_mentions.add(mention_key)
                trim_organic_mentions[trim].add(mention_key)

    if unique_video_mentions:
        issue["mention_count"] = len(unique_video_mentions)
    if unique_channels:
        issue["distinct_channel_count"] = len(unique_channels)
    if organic_mentions or list_channels:
        issue["corroboration_count"] = len(organic_mentions) + len(list_channels)

    ordered_trim_evidence = {
        k: trim_evidence[k]
        for k in _TRIM_ORDER
        if trim_evidence.get(k)
    }
    issue["trim_evidence"] = ordered_trim_evidence
    issue["distinct_trim_count"] = len(ordered_trim_evidence)

    dominant_trim = "unknown"
    dominant_trim_raw = ""
    if ordered_trim_evidence:
        dominant_trim_raw, dominant_count = max(
            ordered_trim_evidence.items(),
            key=lambda kv: (kv[1], -_TRIM_ORDER.index(kv[0])),
        )
        total = sum(ordered_trim_evidence.values())
        dominant_trim = (
            dominant_trim_raw if total and (dominant_count / total) > 0.5 else "mixed"
        )
    issue["dominant_trim"] = dominant_trim

    cross_trim_corroboration_count = 0
    if dominant_trim_raw:
        for trim in ordered_trim_evidence:
            if trim == dominant_trim_raw:
                continue
            cross_trim_corroboration_count += len(trim_organic_mentions.get(trim, set()))
            cross_trim_corroboration_count += len(trim_list_channels.get(trim, set()))
    issue["cross_trim_corroboration_count"] = cross_trim_corroboration_count

    observed_trims = set(ordered_trim_evidence.keys())
    issue["trim_scope_warning"] = False
    if (
        slug == "vw_golf_mk7"
        and dominant_trim in {"GTI", "R"}
        and observed_trims
        and observed_trims.issubset({"GTI", "R"})
    ):
        issue["model_scope"] = ["golf_gti_mk7"] if dominant_trim == "GTI" else ["golf_r_mk7"]
        comp = (issue.get("system_component") or "").lower()
        engines = [str(e).strip() for e in (issue.get("affected_engines") or []) if str(e).strip()]
        if comp in POWERTRAIN_COMPONENTS or comp in DRIVETRAIN_COMPONENTS or engines:
            if engines and engines != ["2.0_TSI"]:
                issue["affected_engines_trim_original"] = engines
            issue["affected_engines"] = ["2.0_TSI"]
        issue["trim_scope_warning"] = True

    confidence = str(issue.get("confidence") or "low").lower()
    if (
        issue.get("distinct_trim_count") == 1
        and dominant_trim in {"GTI", "R"}
        and _CONF_RANK.get(confidence, 0) > _CONF_RANK["medium"]
    ):
        issue["confidence"] = "medium"
    elif (
        dominant_trim == "base"
        and int(issue.get("distinct_channel_count") or 0) >= 2
    ):
        issue["confidence"] = "high"

    return issue


def _build_variant_detector(scaffold: dict):
    """Build a generic scope detector from scaffold data.

    Returns a callable (blob: str, component: str) → list[str].
    All detection logic derives from the scaffold YAML — no car-specific code.

    Produced scope labels are generic:
      "diesel_only"    — diesel keywords in the issue text
      "auto_only"      — auto/DCT transmission keywords
      "pre_facelift"   — pre-facelift language (year from scaffold facelifts)
      "post_facelift"  — post-facelift language
      "all_{make}_{model}" — default catch-all when nothing else matches
    """
    meta = scaffold.get("meta") or {}
    make  = meta.get("make",  "").lower().replace(" ", "_")
    model = meta.get("model", "car").lower().replace(" ", "_").replace("-", "_")
    default_scope = f"all_{make}_{model}" if make else f"all_{model}"

    # Diesel presence
    fuel_types = {
        (ef.get("fuel_type") or "").lower()
        for ef in scaffold.get("engine_families") or []
    }
    has_diesel = "diesel" in fuel_types

    # Auto transmission codes + known aliases from scaffold (lower-cased)
    auto_tx_codes: list[str] = []
    for tx in scaffold.get("transmissions") or []:
        tx_type = (tx.get("type") or "").lower()
        if any(k in tx_type for k in ("dual_clutch", "automatic", "cvt", "dct")):
            code = (tx.get("code") or "").lower()
            if code:
                auto_tx_codes.append(code)
            # Include any short-name aliases defined in the scaffold
            for alias in tx.get("known_names_tr") or []:
                a = alias.lower().strip()
                if a and len(a) >= 2:
                    auto_tx_codes.append(a)

    # Facelift years for pre/post detection
    facelift_years: list[int] = [
        int(fl["year"]) for fl in (scaffold.get("facelifts") or []) if fl.get("year")
    ]

    def _detect(blob: str, component: str) -> list[str]:
        scopes: list[str] = []

        # Diesel scope — generic diesel fuel-type keywords
        if has_diesel and re.search(
            r"\bdiesel\b|\bdci\b|\btdi\b|\bcdi\b|\bhdi\b|\bblue ?hdi\b", blob
        ):
            scopes.append("diesel_only")

        # Auto transmission scope
        auto_hit = any(code in blob for code in auto_tx_codes)
        if not auto_hit:
            auto_hit = bool(re.search(r"\bdual.clutch\b|\bdct\b", blob))
        if not auto_hit and component == "gearbox":
            auto_hit = bool(re.search(r"\bautomatic\b|\bauto\b", blob))
        if auto_hit:
            scopes.append("auto_only")

        # Pre/post facelift — anchored to scaffold facelift year(s).
        # Pre takes priority: "pre facelift" contains "facelift" so we check
        # explicit pre-markers first and only fall back to post if no pre match.
        for yr in facelift_years:
            pre_terms  = ["pre facelift", "pre-facelift",
                          f"pre {yr}", f"pre-{yr}", f"before {yr}"]
            post_terms = ["post facelift", "post-facelift",
                          f"post {yr}", f"after {yr}"]
            is_pre = any(t in blob for t in pre_terms)
            if is_pre:
                scopes.append("pre_facelift")
            elif any(t in blob for t in post_terms) or (
                "facelift" in blob and not is_pre
            ):
                scopes.append("post_facelift")

        # Deduplicate, preserve order
        seen: set[str] = set()
        out = [s for s in scopes if s not in seen and not seen.add(s)]  # type: ignore[func-returns-value]
        return out if out else [default_scope]

    return _detect


def apply_model_scope(issue: dict, scope_detector=None) -> dict:
    """Add model_scope. For non-powertrain issues, clear engine scope (noise).

    Args:
        scope_detector: Callable(blob, component) → list[str], built via
            _build_variant_detector(scaffold). Falls back to ["all"] if None.
    """
    comp = (issue.get("system_component") or "").lower()
    blob = _trigger_blob(issue)
    scopes = scope_detector(blob, comp) if scope_detector is not None else ["all"]
    issue["model_scope"] = scopes

    if comp in POWERTRAIN_COMPONENTS or comp in DRIVETRAIN_COMPONENTS:
        return issue  # engines stay

    engines = issue.get("affected_engines") or []
    if engines:
        issue["affected_engines_original"] = list(engines)
        issue["affected_engines"] = []
        issue.setdefault("_scope_notes", []).append(
            f"system_component={comp} is not engine-scoped; cleared affected_engines "
            f"(original preserved in affected_engines_original)."
        )
    return issue


# ── Year triangulation ───────────────────────────────────────────────────────

_YEAR_RANGE_RE = re.compile(r"\b(20[0-2]\d)\s*(?:-|–|to)\s*(20[0-2]\d)\b")
_PRE_RE = re.compile(r"\b(?:pre|before|up\s*to|until)\s*[-–]?\s*(20[0-2]\d)\b", re.IGNORECASE)
_POST_RE = re.compile(r"\b(?:post|after|from|since)\s*[-–]?\s*(20[0-2]\d)\b", re.IGNORECASE)
_BARE_YEAR_RE = re.compile(r"\b(20[0-2]\d)\b")

# Extended pre-year regex that also handles "made to (mid-)YYYY" — mirrors the
# fix applied to extract_youtube_issues.py so verbatim LLM phrases parse correctly.
_PRE_LLM_RE = re.compile(
    r"\b(?:pre|before|up\s*to|until|made\s*(?:before|to))"
    r"[\s\-–]*"
    r"(?:(?:early|mid|late)[\s\-–]*)?"
    r"(20[0-2]\d)\b",
    re.IGNORECASE,
)

def _parse_spans(text: str) -> list[tuple[int, int]]:
    if not text:
        return []
    spans: list[tuple[int, int]] = []
    consumed: list[tuple[int, int]] = []  # byte offsets eaten by range matches
    for m in _YEAR_RANGE_RE.finditer(text):
        a, b = int(m.group(1)), int(m.group(2))
        if a > b:
            a, b = b, a
        spans.append((a, b))
        consumed.append(m.span())
    for m in _PRE_RE.finditer(text):
        y = int(m.group(1))
        spans.append((2000, y))
        consumed.append(m.span())
    for m in _POST_RE.finditer(text):
        y = int(m.group(1))
        spans.append((y, 2030))
        consumed.append(m.span())

    # Bare year mentions — skip any that sit inside a span we already consumed.
    for m in _BARE_YEAR_RE.finditer(text):
        pos = m.start()
        if any(a <= pos < b for a, b in consumed):
            continue
        y = int(m.group(1))
        spans.append((y, y))
    return spans


def _parse_llm_year_phrase(
    phrase: str,
    eng_window: tuple[int, int],
    model_window: tuple[int, int],
    semantic_phrases: dict[str, tuple[int, int]] | None = None,
) -> list[tuple[int, int]]:
    """Parse a verbatim year phrase captured by the LLM in Pass 1.

    Unlike _parse_spans (which uses dummy 2000/2030 as pre/post bounds),
    this uses the actual engine production window so "up to mid-2014" on a
    1.2 TSI becomes (2013, 2014) rather than (2000, 2014).

    Args:
        semantic_phrases: Model-specific mapping of shorthand phrases to year
            spans, built from scaffold via _build_semantic_phrases(scaffold).
            Defaults to empty dict (no semantic shorthand recognised).

    Returns an empty list when the phrase is too vague to pin to a year.
    """
    if not phrase:
        return []
    phrase_str = str(phrase).strip()
    if phrase_str.lower() in ("null", "none", ""):
        return []

    lo, hi = eng_window

    # Semantic shorthand first (e.g. "before facelift" → model-specific span).
    active_phrases = semantic_phrases if semantic_phrases is not None else {}
    phrase_lower = phrase_str.lower()
    for keyword, span in active_phrases.items():
        if keyword in phrase_lower:
            return [span]

    spans: list[tuple[int, int]] = []
    consumed: set[int] = set()

    # Explicit ranges: "2013 to 2017", "2013-2017".
    for m in _YEAR_RANGE_RE.finditer(phrase_str):
        a, b = int(m.group(1)), int(m.group(2))
        if a > b:
            a, b = b, a
        spans.append((a, b))
        consumed.update(range(m.start(), m.end()))

    # Pre-year markers: "up to mid-2014", "made to 2014", "before 2016".
    # Lower bound = engine window start (not the dummy 2000).
    for m in _PRE_LLM_RE.finditer(phrase_str):
        if any(i in consumed for i in range(m.start(), m.end())):
            continue
        y = int(m.group(1))
        spans.append((lo, y))
        consumed.update(range(m.start(), m.end()))

    # Post-year markers: "from 2017", "after 2015".
    # Upper bound = engine window end (not the dummy 2030).
    for m in _POST_RE.finditer(phrase_str):
        if any(i in consumed for i in range(m.start(), m.end())):
            continue
        y = int(m.group(1))
        spans.append((y, hi))
        consumed.update(range(m.start(), m.end()))

    # Bare year mentions not already consumed by the above.
    for m in _BARE_YEAR_RE.finditer(phrase_str):
        if m.start() in consumed:
            continue
        y = int(m.group(1))
        spans.append((y, y))

    return spans


def _clamp(spans: list[tuple[int, int]], window: tuple[int, int]) -> list[tuple[int, int]]:
    lo, hi = window
    out = []
    for a, b in spans:
        if b < lo or a > hi:
            continue
        out.append((max(a, lo), min(b, hi)))
    return out


def _union_spans(spans: list[tuple[int, int]]) -> list[tuple[int, int]]:
    if not spans:
        return []
    srt = sorted(spans)
    out = [srt[0]]
    for a, b in srt[1:]:
        la, lb = out[-1]
        if a <= lb + 1:
            out[-1] = (la, max(lb, b))
        else:
            out.append((a, b))
    return out


def _intersect_spans(A: list[tuple[int, int]], B: list[tuple[int, int]]) -> list[tuple[int, int]]:
    out = []
    for a1, a2 in A:
        for b1, b2 in B:
            lo = max(a1, b1)
            hi = min(a2, b2)
            if lo <= hi:
                out.append((lo, hi))
    return _union_spans(out)


def _span_label(spans: list[tuple[int, int]]) -> str | None:
    if not spans:
        return None
    lo = min(a for a, _ in spans)
    hi = max(b for _, b in spans)
    return str(lo) if lo == hi else f"{lo}-{hi}"


def triangulate_years(
    issue: dict,
    videos_by_id: dict[str, dict],
    engine_windows: dict[str, tuple[int, int]] | None = None,
    model_window: tuple[int, int] = (2013, 2021),
    semantic_phrases: dict[str, tuple[int, int]] | None = None,
) -> dict:
    """Derive affected_years from three independent sources.

    - Source A (transcript): existing engine_year_context rows, filtered to
      engines that survived the allowlist validation. Hallucinated engine
      mappings don't get to contribute year evidence.
    - Source B (title): year spans parsed from source_video titles.
    - Source C (engine window): production window per validated engine, clamped
      to the model window. For non-powertrain issues with no engine scope,
      model_window is used as the conservative fallback.

    Combination rule:
      - If transcript AND title both have content → INTERSECT them. Keeps
        transcript precision intact when title is vaguely wide.
      - If only one of transcript/title has content → use it directly.
      - Intersect the content span with the engine/scope window.
      - Emit only when content evidence exists. Window-alone is not enough.

    Args:
        engine_windows: {displacement_code: (start, end)} from scaffold.
            Built via _build_engine_windows(scaffold). Pass None to skip.
        model_window: Overall (start, end) year range for this model/generation.
            Built via _get_model_window(scaffold).
        semantic_phrases: Shorthand phrase → year span map from scaffold.
            Built via _build_semantic_phrases(scaffold).
    """
    ew = engine_windows or {}
    validated_engines = [
        e for e in (issue.get("affected_engines") or []) if e != "all"
    ]
    if not validated_engines:
        validated_engines = [
            e for e in (issue.get("affected_engines_original") or []) if e != "all"
        ]
    validated_engines_set = {str(e) for e in validated_engines}

    # A0) LLM verbatim year phrase from Pass 1 extraction — primary transcript signal.
    #     The LLM copied this directly from the transcript ("up to mid-2014",
    #     "2013 to 2017", "before facelift", etc.) so it already has the correct
    #     semantics. Parse it with engine window bounds so "up to mid-2014" on a
    #     1.2 TSI → (2013, 2014), not (2000, 2014).
    llm_year_phrase = issue.get("affected_years")
    llm_year_spans: list[tuple[int, int]] = []
    if llm_year_phrase and str(llm_year_phrase).strip().lower() not in ("null", "none", ""):
        eng_win_union: tuple[int, int] = (
            min(
                (ew[e][0] for e in validated_engines if e in ew),
                default=model_window[0],
            ),
            max(
                (ew[e][1] for e in validated_engines if e in ew),
                default=model_window[1],
            ),
        )
        llm_year_spans = _parse_llm_year_phrase(
            str(llm_year_phrase), eng_win_union, model_window, semantic_phrases
        )
    llm_union = _clamp(_union_spans(llm_year_spans), model_window)

    # A1) engine_year_context regex enrichment — fallback when LLM found no year.
    #     Only from validated engines so hallucinated-engine year evidence doesn't
    #     survive validation.
    #
    #     When the engine_year_context entry carries directional markers
    #     (pre_years = upper bounds like "made to 2014",
    #     post_years = lower bounds like "from 2017"), use them to build a
    #     correctly-oriented span rather than treating both as plain years.
    #     Example: pre_years=[2014] on 1.2 TSI → span (2013, 2014), not (2014, 2017).
    transcript_spans: list[tuple[int, int]] = []
    transcript_dropped: list[str] = []
    for ctx in issue.get("engine_year_context") or []:
        eng = str(ctx.get("engine") or "")
        ys = ctx.get("years")
        pre_ys: list[int] = [y for y in (ctx.get("pre_years") or []) if isinstance(y, int)]
        post_ys: list[int] = [y for y in (ctx.get("post_years") or []) if isinstance(y, int)]

        if not ys and not pre_ys and not post_ys:
            continue
        # Filter against validated engines when the field was explicitly set.
        # An explicit [] means *all* LLM engines were invalid — no engine
        # should contribute transcript years. (Empty set short-circuits the old
        # `if validated_engines_set and …` guard, letting invalid entries through.)
        if validated_engines_set and eng not in validated_engines_set:
            transcript_dropped.append(eng)
            continue

        if pre_ys or post_ys:
            # Directional markers found — build a bounded span.
            # Use the engine production window as the outer envelope.
            eng_win = ew.get(eng, model_window)
            lo = max(post_ys) if post_ys else eng_win[0]
            hi = min(pre_ys) if pre_ys else eng_win[1]
            if lo <= hi:
                transcript_spans.append((lo, hi))
        elif ys:
            # No directional info — use the plain year span as before.
            if "-" in str(ys):
                a, b = str(ys).split("-", 1)
                try:
                    transcript_spans.append((int(a), int(b)))
                except ValueError:
                    pass
            else:
                try:
                    y = int(ys)
                    transcript_spans.append((y, y))
                except ValueError:
                    pass
    transcript_union = _clamp(_union_spans(transcript_spans), model_window)

    # B) title text of source videos
    title_spans: list[tuple[int, int]] = []
    for sv in issue.get("source_videos") or []:
        vid = sv.get("video_id") if isinstance(sv, dict) else None
        if not vid:
            continue
        v = videos_by_id.get(vid) or {}
        title_text = str(v.get("title") or sv.get("title") or "")
        matched_qs = " ".join(str(q) for q in v.get("matched_queries", []) if q)
        title_spans.extend(_parse_spans(title_text + " " + matched_qs))
    title_union = _clamp(_union_spans(title_spans), model_window)

    # C) engine production windows as outer bound.
    # For validated-engine issues, union the engine windows.
    # For non-powertrain issues with no engine scope, fall back to model_window.
    eng_windows_spans: list[tuple[int, int]] = []
    for e in validated_engines:
        w = ew.get(e)
        if w:
            eng_windows_spans.append(w)

    if eng_windows_spans:
        window_union = _union_spans(eng_windows_spans)
        window_source = "engine"
    else:
        window_union = [model_window]
        window_source = "model_window"

    # Effective transcript signal: LLM phrase (A0) takes priority; regex
    # enrichment (A1) is the fallback when the LLM found no explicit year.
    effective_transcript = llm_union if llm_union else transcript_union
    transcript_source = "llm_phrase" if llm_union else ("regex_enrichment" if transcript_union else "none")

    # Combine content: intersect when both present, else whichever exists.
    if effective_transcript and title_union:
        content_union = _intersect_spans(effective_transcript, title_union)
        content_rule = f"intersect({transcript_source}, title)"
        if not content_union:
            # Real disagreement between narrator and on-screen scope — prefer
            # transcript (finer-grained claim).
            content_union = effective_transcript
            content_rule = f"prefer_{transcript_source}_on_conflict"
    elif effective_transcript:
        content_union = effective_transcript
        content_rule = transcript_source + "_only"
    elif title_union:
        content_union = title_union
        content_rule = "title_only"
    else:
        content_union = []
        content_rule = "no_content"

    evidence = {
        "from_llm_year_phrase": str(llm_year_phrase) if llm_year_phrase else None,
        "from_llm_year_parsed": [
            f"{a}-{b}" if a != b else str(a) for a, b in llm_union
        ],
        "from_transcript_context": [
            f"{a}-{b}" if a != b else str(a) for a, b in transcript_union
        ],
        "from_source_video_titles": [
            f"{a}-{b}" if a != b else str(a) for a, b in title_union
        ],
        "from_engine_production_windows": [
            f"{a}-{b}" for a, b in _union_spans(eng_windows_spans)
        ],
        "from_model_scope_window": [
            f"{a}-{b}" for a, b in window_union
        ],
        "window_source": window_source,
        "content_combine_rule": content_rule,
    }
    if transcript_dropped:
        evidence["transcript_context_dropped_engines"] = sorted(set(transcript_dropped))

    if content_union and window_union:
        final_spans = _intersect_spans(content_union, window_union)
        if not final_spans:
            evidence["conflict"] = (
                "content evidence does not overlap engine/scope window"
            )
            evidence["confidence"] = "conflict"
        else:
            content_sources = (1 if effective_transcript else 0) + (
                1 if title_union else 0
            )
            evidence["confidence"] = "high" if content_sources >= 2 else "medium"
            evidence["triangulated"] = _span_label(final_spans)
    elif content_union and not window_union:
        content_sources = (1 if effective_transcript else 0) + (1 if title_union else 0)
        evidence["confidence"] = "high" if content_sources >= 2 else "medium"
        evidence["triangulated"] = _span_label(content_union)
    elif window_union and not content_union:
        evidence["confidence"] = "low"
        evidence["fallback_window"] = _span_label(window_union)
        evidence["fallback_window_source"] = window_source
    else:
        evidence["confidence"] = "none"

    issue["affected_years_evidence"] = evidence
    if "triangulated" in evidence:
        issue["affected_years_triangulated"] = evidence["triangulated"]
    return issue


# ── Driver ───────────────────────────────────────────────────────────────────

# ── Cross-brand contamination filter ─────────────────────────────────────────
#
# The LLM sometimes borrows wording from similar failure modes in other OEMs
# (e.g. Ford's 1.0 EcoBoost "wet belt" leaking into a Renault 1.2 TCe entry).
# We group brands by shared-platform/engine-alliance so genuine overlaps (VAG
# engines shared across VW/Audi/Seat/Skoda) aren't flagged.
_BRAND_GROUPS: list[set[str]] = [
    {"vw", "volkswagen", "audi", "seat", "skoda", "cupra", "porsche", "bentley"},
    {"renault", "dacia", "nissan", "infiniti", "mitsubishi"},
    {"ford", "lincoln"},
    {"toyota", "lexus", "subaru"},
    {"honda", "acura"},
    {"hyundai", "kia", "genesis"},
    {"stellantis", "peugeot", "citroen", "citroën", "opel", "vauxhall",
     "fiat", "alfa", "lancia", "chrysler", "dodge", "jeep", "ram", "maserati", "ds"},
    {"bmw", "mini", "rolls-royce"},
    {"mercedes", "mercedes-benz", "smart"},
    {"volvo", "polestar", "geely", "lynk"},
    {"mazda"},
    {"tesla"},
    {"jaguar", "land rover", "range rover"},
]
# Engine-family tokens that signal another OEM's powertrain; used to catch
# descriptions that don't name the brand directly (e.g. "EcoBoost", "Prince").
_FOREIGN_ENGINE_TOKENS: dict[str, set[str]] = {
    "ford":     {"ecoboost", "duratec", "duratorq"},
    "bmw":      {"prince", "n20", "n47", "n54", "n55", "b48", "b58"},
    "toyota":   {"2ar-fe", "1zz", "2zz", "1nz", "2nz"},
    "honda":    {"earth dreams", "k20", "k24"},
    "peugeot":  {"prince", "puretech", "hdi", "bluehdi"},
    "mazda":    {"skyactiv"},
    "hyundai":  {"theta", "gamma", "nu engine"},
    "mercedes": {"kompressor", "cdi", "bluetec"},
    "vw":       {"tsi", "tdi", "tfsi"},
}


def _scaffold_allowed_brands(scaffold: dict) -> set[str]:
    make = (scaffold.get("meta") or {}).get("make", "").lower().strip()
    if not make:
        return set()
    for group in _BRAND_GROUPS:
        if make in group:
            return group
    return {make}


def _check_cross_brand_contamination(
    issue: dict, allowed: set[str], own_make: str
) -> str | None:
    """Return a reason string when the issue text mentions a foreign OEM /
    foreign engine family; None if clean.
    """
    if not allowed:
        return None
    parts = [
        issue.get("label") or "",
        issue.get("symptom") or "",
        issue.get("cause") or "",
        issue.get("notes") or "",
        issue.get("fix") or "",
        issue.get("inspection_advice") or "",
    ]
    blob = " ".join(str(p) for p in parts).lower()
    if not blob.strip():
        return None

    # Word-boundary brand mentions.
    for group in _BRAND_GROUPS:
        if group == allowed:
            continue
        for brand in group:
            pat = r"\b" + re.escape(brand) + r"\b"
            if re.search(pat, blob):
                return f"foreign_brand:{brand}"

    # Engine-family tokens tied to a specific foreign OEM.
    for brand, tokens in _FOREIGN_ENGINE_TOKENS.items():
        if brand in allowed:
            continue
        for tok in tokens:
            pat = r"\b" + re.escape(tok) + r"\b"
            if re.search(pat, blob):
                return f"foreign_engine_family:{tok}"
    return None


def drop_cross_brand_contamination(
    issues: list[dict], scaffold: dict
) -> tuple[list[dict], list[dict]]:
    """Return (kept, dropped). Drops issues whose descriptive text names a
    foreign OEM (outside the scaffold's platform group) or a foreign
    engine-family token. Logs each drop for audit.
    """
    allowed = _scaffold_allowed_brands(scaffold)
    own_make = (scaffold.get("meta") or {}).get("make", "").lower().strip()
    kept, dropped = [], []
    for it in issues:
        reason = _check_cross_brand_contamination(it, allowed, own_make)
        if reason is None:
            kept.append(it)
        else:
            it = dict(it)
            it["_drop_reason"] = reason
            dropped.append(it)
            log.info("  [Contamination] Dropping %s — %s", it.get("issue_id"), reason)
    if dropped:
        log.info("Cross-brand contamination filter: dropped %d / %d", len(dropped), len(issues))
    return kept, dropped


def validate_hardware_alignment(issue: dict, scaffold: dict):
    """
    Fact-check the LLM's engine attribution against the scaffold.
    Automatically removes engines that don't match the technical description.
    """
    label = str(issue.get("label", "")).lower()
    symptom = str(issue.get("symptom", "")).lower()
    text = f"{label} {symptom}"
    
    affected = issue.get("affected_engines", [])
    if not isinstance(affected, list):
        affected = [affected]
    if not affected or "all" in [str(e).lower() for e in affected]:
        return

    # Map engine codes to their hardware attributes from scaffold
    engine_meta = {}
    for ef in scaffold.get("engine_families", []):
        drive = str(ef.get("timing_drive", "")).lower()
        for d in ef.get("displacements", []):
            code = d.get("code") if isinstance(d, dict) else d
            if code:
                engine_meta[str(code)] = {"drive": drive}

    # Guardrail A: Timing Drive Alignment
    is_chain_issue = "chain" in text
    is_belt_issue = "belt" in text and "chain" not in text
    
    if is_chain_issue or is_belt_issue:
        new_affected = []
        for eng in affected:
            eng_str = str(eng)
            meta = engine_meta.get(eng_str)
            if not meta:
                new_affected.append(eng)
                continue
                
            if is_chain_issue and meta["drive"] == "belt":
                log.info("  [Guardrail] Removing %s from Chain issue '%s' (Engine is Belt-driven)", eng_str, issue['issue_id'])
                continue
            if is_belt_issue and meta["drive"] == "chain":
                log.info("  [Guardrail] Removing %s from Belt issue '%s' (Engine is Chain-driven)", eng_str, issue['issue_id'])
                continue
            new_affected.append(eng)
        
        # If we stripped everything, don't leave it empty; try to find a valid one
        if not new_affected and affected:
            chain_engines = [code for code, m in engine_meta.items() if m["drive"] == "chain"]
            if is_chain_issue and chain_engines:
                new_affected = chain_engines
            else:
                new_affected = affected
        
        issue["affected_engines"] = new_affected

    # Guardrail B: Transmission Alignment
    if any(kw in text for kw in ["dsg", "mechatronic", "dual clutch", "edc"]):
        dsg_engines = set()
        for tx in scaffold.get("transmissions", []):
            tx_type = str(tx.get("type", "")).lower()
            if any(kw in tx_type for kw in ["dual", "dsg", "dct", "edc"]):
                compat = tx.get("compatible_displacements") or tx.get("compatible_engines") or []
                dsg_engines.update([str(e) for e in compat])
        
        if dsg_engines:
            new_affected = [e for e in affected if str(e) in dsg_engines]
            if not new_affected and affected:
                issue["affected_engines"] = list(dsg_engines)
            else:
                issue["affected_engines"] = new_affected


def _save(final: list[dict], out_json: Path, out_csv: Path) -> None:
    out_json.parent.mkdir(parents=True, exist_ok=True)
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(final, f, ensure_ascii=False, indent=2)
    log.info("Saved JSON: %s (%d issues)", out_json, len(final))

    flat = [
        {k: (json.dumps(v, ensure_ascii=False) if isinstance(v, (list, dict)) else v)
         for k, v in row.items()}
        for row in final
    ]
    try:
        pd.DataFrame(flat).to_csv(out_csv, index=False)
        log.info("Saved CSV:  %s", out_csv)
    except PermissionError:
        alt = out_csv.with_stem(out_csv.stem + "_tmp")
        pd.DataFrame(flat).to_csv(alt, index=False)
        log.warning("CSV locked — saved to %s instead", alt)


def _write_audit(
    slug: str,
    orig_count: int,
    merge_groups: list[list[str]],
    final: list[dict],
    out_md: Path,
    contam_dropped: list[dict] | None = None,
) -> None:
    warnings = [
        (it.get("issue_id"), w)
        for it in final
        for w in it.get("engine_scope_warnings") or []
    ]
    cleared = [it for it in final if it.get("affected_engines_original")]
    conf_counts: dict[str, int] = defaultdict(int)
    for it in final:
        c = (it.get("affected_years_evidence") or {}).get("confidence", "none")
        conf_counts[c] += 1

    triangulated = [it for it in final if it.get("affected_years_triangulated")]
    trim_scope_warnings = [it for it in final if it.get("trim_scope_warning")]

    trim_distribution: dict[str, int] = defaultdict(int)
    mono_trim_count = 0
    total_trim_mentions = 0
    for it in final:
        trim_ev = it.get("trim_evidence") or {}
        if not isinstance(trim_ev, dict):
            trim_ev = {}
        clean_trim_ev = {
            str(k): int(v)
            for k, v in trim_ev.items()
            if isinstance(v, int) and v > 0
        }
        if len(clean_trim_ev) == 1:
            mono_trim_count += 1
        for trim, count in clean_trim_ev.items():
            trim_distribution[trim] += count
            total_trim_mentions += count
    mono_trim_issue_pct = (mono_trim_count / len(final) * 100.0) if final else 0.0

    lines = [
        f"# YouTube Issue Post-Processing Audit — {slug}",
        "",
        "## Summary",
        "",
        f"- Input rows: **{orig_count}**",
        f"- Cross-brand contamination dropped: **{len(contam_dropped or [])}**",
        f"- After dedup: **{len(final)}**",
        f"- Merge groups (> 1 row collapsed): **{len(merge_groups)}**",
        f"- Engine scope warnings: **{len(warnings)}** on "
        f"**{len({iid for iid, _ in warnings})}** issues",
        f"- Trim scope warnings: **{len(trim_scope_warnings)}**",
        f"- Non-powertrain issues with engine scope cleared: **{len(cleared)}**",
        f"- Mono-trim issues: **{mono_trim_count}** / {len(final)} "
        f"({mono_trim_issue_pct:.1f}%)",
        f"- Year-triangulated (emitted): **{len(triangulated)}** / {len(final)}",
        "- Year confidence distribution: "
        + ", ".join(f"{k}={v}" for k, v in sorted(conf_counts.items())),
        "",
        "## Dedup — merged groups",
        "",
    ]
    if not merge_groups:
        lines.append("_(no clusters merged — input was already deduped)_")
    else:
        for grp in sorted(merge_groups, key=lambda g: (-len(g), g[0])):
            lines.append(f"- {len(grp)} rows: " + ", ".join(f"`{i}`" for i in grp))
    lines.append("")

    if contam_dropped:
        lines.append("## Cross-brand contamination — dropped issues")
        lines.append("")
        for it in contam_dropped:
            lines.append(
                f"- `{it.get('issue_id')}` — {it.get('_drop_reason')} "
                f"(label: {str(it.get('label',''))!r})"
            )
        lines.append("")

    lines.append("## Engine-scope warnings")
    lines.append("")
    if not warnings:
        lines.append("_(no engine-scope rules fired)_")
    else:
        for iid, w in warnings:
            lines.append(f"- **`{iid}`** — {w.get('rule')}")
            lines.append(f"  - current: `{w.get('current_engines')}`")
            lines.append(f"  - suggested: `{w.get('suggested_engines')}`")
            if w.get("invalid_engines_flagged"):
                lines.append(f"  - invalid: `{w.get('invalid_engines_flagged')}`")
            lines.append(f"  - note: {w.get('note')}")
    lines.append("")

    lines.append("## Trim distribution")
    lines.append("")
    if not trim_distribution:
        lines.append("_(no trim evidence captured)_")
    else:
        lines.append("| Trim | Count | Share |")
        lines.append("|---|---:|---:|")
        for trim, count in sorted(trim_distribution.items(), key=lambda kv: (-kv[1], kv[0])):
            pct = (count / total_trim_mentions * 100.0) if total_trim_mentions else 0.0
            lines.append(f"| {trim} | {count} | {pct:.1f}% |")
    lines.append("")

    lines.append("## Trim scope warnings")
    lines.append("")
    if not trim_scope_warnings:
        lines.append("_(none)_")
    else:
        for it in trim_scope_warnings:
            lines.append(
                f"- `{it.get('issue_id')}` — dominant_trim={it.get('dominant_trim')}, "
                f"model_scope={it.get('model_scope')}, affected_engines={it.get('affected_engines')}"
            )
    lines.append("")

    lines.append("## Cleared-engine issues (non-powertrain)")
    lines.append("")
    if not cleared:
        lines.append("_(none)_")
    else:
        for it in cleared:
            lines.append(
                f"- `{it.get('issue_id')}` ({it.get('system_component')}) "
                f"— cleared `{it.get('affected_engines_original')}`, "
                f"model_scope={it.get('model_scope')}"
            )
    lines.append("")

    lines.append("## Year triangulation examples")
    lines.append("")
    for it in triangulated[:20]:
        ev = it.get("affected_years_evidence", {})
        lines.append(
            f"- `{it.get('issue_id')}` → **{it.get('affected_years_triangulated')}** "
            f"(confidence={ev.get('confidence')}, sources={ev.get('source_count')})"
        )
        lines.append(
            f"  - transcript={ev.get('from_transcript_context')}, "
            f"titles={ev.get('from_source_video_titles')}, "
            f"engine_windows={ev.get('from_engine_production_windows')}"
        )
    lines.append("")

    out_md.parent.mkdir(parents=True, exist_ok=True)
    out_md.write_text("\n".join(lines), encoding="utf-8")
    log.info("Audit written: %s", out_md)


def _load_videos_by_id(slug: str) -> dict[str, dict]:
    raw = ROOT / "data" / "raw" / "videos" / f"{slug}_raw.json"
    if not raw.exists():
        log.warning("Raw videos not found at %s — title-based year evidence disabled", raw)
        return {}
    with open(raw, encoding="utf-8") as f:
        data = json.load(f)
    out = {}
    for v in data.get("videos", []):
        vid = v.get("video_id")
        if vid:
            out[vid] = v
    log.info("Loaded %d raw videos for title evidence", len(out))
    return out


def _load_scaffold(slug: str) -> dict:
    """Load the scaffold YAML for the given slug.

    Resolution order:
      1. Exact match:  data/scaffolds/{slug}.yaml
      2. Fuzzy match:  find a scaffold whose stem words are all present in slug
         (e.g. slug="renault_clio_mk4" → renault_clio.yaml via "renault"+"clio")
    """
    exact = ROOT / "data" / "scaffolds" / f"{slug}.yaml"
    if exact.exists():
        with open(exact, encoding="utf-8") as f:
            return yaml.safe_load(f) or {}

    slug_lower = slug.lower()
    scaffold_dir = ROOT / "data" / "scaffolds"
    for p in sorted(scaffold_dir.glob("*.yaml")):
        stem_words = [w for w in re.split(r"[_\-\s]+", p.stem.lower()) if len(w) > 2]
        if stem_words and all(w in slug_lower for w in stem_words):
            log.info("Scaffold: fuzzy-matched '%s' for slug '%s'", p.name, slug)
            with open(p, encoding="utf-8") as f:
                return yaml.safe_load(f) or {}

    log.warning("No scaffold found for slug '%s'", slug)
    return {}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    ap.add_argument("--slug", default="vw_golf_mk7")
    ap.add_argument("--input-json", type=Path, default=None)
    ap.add_argument("--output-json", type=Path, default=None)
    ap.add_argument("--audit-md", type=Path, default=None)
    ap.add_argument("--jaccard", type=float, default=0.55,
                    help="Jaccard threshold for Stage-2 clustering (default 0.55)")
    ap.add_argument("--no-dedup", action="store_true")
    ap.add_argument("--no-scope", action="store_true")
    ap.add_argument("--no-years", action="store_true")
    args = ap.parse_args()

    slug = args.slug
    in_json = args.input_json or (
        ROOT / "data" / "processed" / f"issue_knowledge_youtube_{slug}_year_enriched.json"
    )
    if not in_json.exists():
        # fallback to non-enriched
        alt = ROOT / "data" / "processed" / f"issue_knowledge_youtube_{slug}.json"
        if alt.exists():
            log.warning("Year-enriched file missing, falling back to %s", alt)
            in_json = alt
        else:
            raise SystemExit(f"Input not found: {in_json}")

    out_json = args.output_json or (
        ROOT / "data" / "processed" / f"issue_knowledge_youtube_{slug}_final.json"
    )
    out_csv = out_json.with_suffix(".csv")
    audit_md = args.audit_md or (
        ROOT / "reports" / f"youtube_postprocess_audit_{slug}.md"
    )

    with open(in_json, encoding="utf-8") as f:
        issues = json.load(f)
    if not isinstance(issues, list):
        raise SystemExit(f"Expected a list in {in_json}")
    orig_count = len(issues)
    log.info("Loaded %d issues from %s", orig_count, in_json.name)

    videos_by_id = _load_videos_by_id(slug)

    # ── Model config — everything derived from scaffold YAML ─────────────────
    scaffold         = _load_scaffold(slug)
    engine_windows   = _build_engine_windows(scaffold)
    model_window     = _get_model_window(scaffold)
    semantic_phrases = _build_semantic_phrases(scaffold)
    scope_detector   = _build_variant_detector(scaffold)
    log.info(
        "Model config from scaffold: %d engine windows, model_window=%s",
        len(engine_windows), model_window,
    )

    # 0. Cross-brand contamination filter — drop issues whose descriptive
    #    text names a foreign OEM (outside the scaffold's platform group) or
    #    a foreign engine-family token. Runs before dedup so contaminated rows
    #    don't pull valid ones into merged clusters.
    issues, contam_dropped = drop_cross_brand_contamination(issues, scaffold)

    # 1. Dedup
    merge_groups: list[list[str]] = []
    if args.no_dedup:
        log.info("Skipping dedup (--no-dedup)")
        cleaned = issues
    else:
        cleaned, merge_groups = dedup_issues(issues, jaccard_threshold=args.jaccard)

    # 2. Scope classification
    # Apply model_scope (which clears engines for non-powertrain).
    if not args.no_scope:
        cleaned = [apply_model_scope(it, scope_detector=scope_detector) for it in cleaned]
    else:
        log.info("Skipping scope classification (--no-scope)")

    # 2b. Trim-bias guardrails and trim-aware confidence/scoping.
    cleaned = [_apply_trim_bias_controls(it, videos_by_id, slug) for it in cleaned]

    # 2c. Technical hardware guardrails (Chain vs Belt, DSG/EDC compatibility)
    for it in cleaned:
        validate_hardware_alignment(it, scaffold)

    # 3. Year triangulation
    if not args.no_years:
        cleaned = [
            triangulate_years(
                it, videos_by_id,
                engine_windows=engine_windows,
                model_window=model_window,
                semantic_phrases=semantic_phrases,
            )
            for it in cleaned
        ]
    else:
        log.info("Skipping year triangulation (--no-years)")

    # Re-sort: mention_count desc, then issue_id.
    cleaned.sort(key=lambda r: (-int(r.get("mention_count") or 0), r.get("issue_id") or ""))

    _save(cleaned, out_json, out_csv)
    _write_audit(slug, orig_count, merge_groups, cleaned, audit_md,
                 contam_dropped=contam_dropped)

    log.info("Done — %d → %d issues", orig_count, len(cleaned))


if __name__ == "__main__":
    main()
