#!/usr/bin/env python3
"""
extract_youtube_issues.py
─────────────────────────
Two-pass LLM extraction pipeline for YouTube transcript data.

Pass 1 — per-video:  Send each transcript to DeepSeek and extract a raw list
                     of structured issues (one video can yield many issues).
Pass 2 — consolidate: Send all raw issues together; LLM merges duplicates,
                      counts mentions, and produces a clean knowledge base.

Input:  data/raw/videos/{slug}_raw.json
Output: data/processed/issue_knowledge_youtube_{slug}.json
        data/processed/issue_knowledge_youtube_{slug}.csv

Usage:
    DEEPSEEK_API_KEY=<key> python scripts/extract_youtube_issues.py
    DEEPSEEK_API_KEY=<key> python scripts/extract_youtube_issues.py --slug renault_clio_mk4
"""

import argparse
import json
import logging
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from threading import Lock
from typing import Any

import pandas as pd
import yaml
from openai import OpenAI
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent
MODEL = "deepseek-chat"
MAX_TRANSCRIPT_WORDS = 2500  # hard cap after sentence scoring
FILTER_CONTEXT_SECS = 25    # fallback context window (secondary to sentence scorer)
MAX_EXTRACT_TOKENS = 2000   # compact schema → smaller output
MAX_EXTRACT_TOKENS_SHORT = 500  # for Shorts (<120s) — typically one issue
CONSOLIDATE_BATCH = 10      # issues per consolidation batch
CONSOLIDATE_TOKENS = 8000   # output cap per consolidation call
LLM_TIMEOUT = 180           # 3 minutes hard timeout

# Metrics tracking
metrics = {
    "start_time": 0,
    "pass1_start": 0,
    "pass1_end": 0,
    "pass2_start": 0,
    "pass2_end": 0,
    "total_input_tokens": 0,
    "total_output_tokens": 0,
    "llm_calls": 0,
}
metrics_lock = Lock()


def update_metrics(input_tokens: int, output_tokens: int):
    with metrics_lock:
        metrics["total_input_tokens"] += input_tokens
        metrics["total_output_tokens"] += output_tokens
        metrics["llm_calls"] += 1


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=4, max=20),
    retry=retry_if_exception_type((Exception)),
    reraise=True,
)
def call_llm(system_prompt: str, user_prompt: str, max_tokens: int, label: str = "LLM") -> str:
    """Wrapper around OpenAI client with retries and timeout."""
    client = _require_client()
    try:
        resp = client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.1,
            max_tokens=max_tokens,
            timeout=LLM_TIMEOUT,
        )
        input_tokens = resp.usage.prompt_tokens
        output_tokens = resp.usage.completion_tokens
        update_metrics(input_tokens, output_tokens)
        return (resp.choices[0].message.content or "").strip()
    except Exception as e:
        log.warning("  [%s] LLM call failed: %s", label, e)
        raise

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


def infer_video_type_category(title: str | None) -> str:
    text = (title or "").lower()
    if any(sig in text for sig in _LIST_FORMAT_SIGNALS):
        return "list_format"
    return "organic"


def _normalize_sources(issue: dict) -> list[dict]:
    normalized: list[dict] = []
    seen: set[tuple[str, str, str]] = set()
    raw_sources = issue.get("source_videos")
    if isinstance(raw_sources, list):
        for row in raw_sources:
            if not isinstance(row, dict):
                continue
            video_id = str(row.get("video_id", "")).strip()
            title = str(row.get("title", "")).strip()
            channel = str(row.get("channel", "")).strip()
            category = str(row.get("video_type_category", "")).strip() or infer_video_type_category(title)
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
                }
            )

    # Backward compatibility: synthesize source_videos when only single-source keys exist.
    if not normalized:
        src_id = str(issue.get("source_video_id", "")).strip()
        src_title = str(issue.get("source_title", "")).strip()
        src_channel = str(issue.get("source_channel", "")).strip()
        if src_id or src_title or src_channel:
            normalized.append(
                {
                    "video_id": src_id,
                    "title": src_title,
                    "channel": src_channel,
                    "video_type_category": infer_video_type_category(src_title),
                }
            )

    return normalized


def refresh_issue_counters(issues: list[dict]) -> list[dict]:
    """Recompute evidence counters deterministically from source_videos."""
    refreshed: list[dict] = []
    for issue in issues:
        if not isinstance(issue, dict):
            continue

        sources = _normalize_sources(issue)
        # Handle compact video_id if source_videos list is empty
        if not sources and issue.get("video_id"):
            sources.append({"video_id": issue["video_id"]})
        
        issue["source_videos"] = sources

        unique_video_mentions: set[str] = set()
        unique_channels: set[str] = set()
        organic_video_mentions: set[str] = set()
        list_channels: set[str] = set()

        for src in sources:
            video_id = str(src.get("video_id", "")).strip()
            title = str(src.get("title", "")).strip()
            channel = str(src.get("channel", "")).strip().lower()
            category = str(src.get("video_type_category", "")).strip() or infer_video_type_category(title)
            src["video_type_category"] = category

            mention_key = video_id or f"{title.lower()}|{channel}"
            if mention_key:
                unique_video_mentions.add(mention_key)

            if channel:
                unique_channels.add(channel)
            elif mention_key:
                # Legacy outputs may omit channel; keep a stable fallback bucket.
                unique_channels.add(mention_key)

            if category == "list_format":
                # Treat list-format videos as one curated source per channel.
                list_key = channel or mention_key
                if list_key:
                    list_channels.add(list_key)
            else:
                if mention_key:
                    organic_video_mentions.add(mention_key)

        issue["mention_count"] = len(unique_video_mentions)
        issue["distinct_channel_count"] = len(unique_channels)
        issue["corroboration_count"] = len(organic_video_mentions) + len(list_channels)

        refreshed.append(issue)

    return refreshed

# ── Client ───────────────────────────────────────────────────────────────────

api_key = os.environ.get("DEEPSEEK_API_KEY")
client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com/v1") if api_key else None


def _require_client() -> OpenAI:
    """Return an initialized API client or raise a clear error."""
    if client is None:
        raise RuntimeError("DEEPSEEK_API_KEY not set")
    return client


# ── Scaffold ─────────────────────────────────────────────────────────────────

def load_scaffold(slug: str) -> dict:
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

    log.warning("No scaffold found for slug '%s' — proceeding without", slug)
    return {}


def _disp_codes(displacements: list) -> str:
    """Extract displacement codes from either flat strings or {code, year_range} dicts."""
    codes = []
    for d in displacements:
        if isinstance(d, dict):
            codes.append(str(d.get("code", "?")))
        else:
            codes.append(str(d))
    return ", ".join(codes)


def build_scaffold_context(scaffold: dict) -> str:
    if not scaffold:
        return "(no scaffold available)"
    lines = []
    meta = scaffold.get("meta", {})
    lines.append(
        f"Vehicle: {meta.get('make','?')} {meta.get('model','?')} "
        f"gen {meta.get('generation', meta.get('generations','?'))}, "
        f"corpus years {meta.get('corpus_years','?')}"
    )
    lines.append("\nEngine families:")
    for ef in scaffold.get("engine_families", []):
        raw_disps = ef.get("displacements", [])
        disps = _disp_codes(raw_disps)
        # year_range: prefer family-level; fall back to min/max of displacement ranges
        yr = ef.get("year_range")
        if not yr:
            sub_yrs = [d["year_range"] for d in raw_disps if isinstance(d, dict) and d.get("year_range")]
            yr = [min(y[0] for y in sub_yrs), max(y[1] for y in sub_yrs)] if sub_yrs else ["?", "?"]
        drive = ef.get("timing_drive", "")
        drive_str = f" [{drive}]" if drive else ""
        lines.append(f"  {ef['code']} | {ef['fuel_type']}{drive_str} | {disps} | {yr[0]}–{yr[1]}")
    lines.append("\nTransmissions:")
    for tx in scaffold.get("transmissions", []):
        # support both compatible_engines (old) and compatible_displacements (new)
        compat_raw = tx.get("compatible_displacements") or tx.get("compatible_engines") or []
        compat = ", ".join(str(c) for c in compat_raw)
        yr = tx.get("year_range", ["?", "?"])
        lines.append(
            f"  {tx['code']} | {tx['type']} | {compat} | {yr[0]}–{yr[1]}"
        )
    return "\n".join(lines)


# ── Deterministic year-context enrichment ───────────────────────────────────

_YEAR_RE = re.compile(r"\b(19\d{2}|20[0-2]\d)\b")
_YEAR_RANGE_RE = re.compile(r"\b(19\d{2}|20[0-2]\d)\s*(?:-|–|to)\s*(19\d{2}|20[0-2]\d)\b", re.IGNORECASE)
_PRE_YEAR_RE = re.compile(
    r"\b(?:pre|before|up\s*to|until|made\s*(?:before|to))"  # marker words
    r"[\s\-–]*"                                               # separator (space/hyphen/dash)
    r"(?:(?:early|mid|late)[\s\-–]*)?"                        # optional period word
    r"(19\d{2}|20[0-2]\d)\b",
    re.IGNORECASE,
)
_POST_YEAR_RE = re.compile(r"\b(?:post|after|from|since)\s*(?:-|–)?\s*(19\d{2}|20[0-2]\d)\b", re.IGNORECASE)


def _build_engine_patterns(scaffold: dict) -> dict[str, re.Pattern]:
    """Compile regex patterns from scaffold displacement codes (e.g. 1.4_TSI)."""
    displacements: set[str] = set()
    for family in scaffold.get("engine_families", []):
        if not isinstance(family, dict):
            continue
        for disp in family.get("displacements", []):
            # Handle both flat strings and {code, year_range} dicts
            raw = disp.get("code", "") if isinstance(disp, dict) else disp
            code = str(raw).strip().upper()
            if code:
                displacements.add(code)

    patterns: dict[str, re.Pattern] = {}
    for code in sorted(displacements):
        low = code.lower()
        if "_" in low:
            number, fuel = low.split("_", 1)
            number_pat = re.escape(number).replace(r"\.", r"[\.,]")
            fuel_pat = re.escape(fuel)
            pattern = (
                rf"\b{number_pat}(?:\s*(?:l|liter|litre|lt))?\s*[-_/]?\s*{fuel_pat}\b"
                rf"|\b{re.escape(low)}\b"
            )
        else:
            pattern = rf"\b{re.escape(low)}\b"
        patterns[code] = re.compile(pattern, re.IGNORECASE)
    return patterns


def _iter_transcript_segments(video: dict) -> list[str]:
    segments = video.get("transcript_segments", [])
    if isinstance(segments, list) and segments:
        out = []
        for seg in segments:
            if not isinstance(seg, dict):
                continue
            text = str(seg.get("text", "")).strip()
            if text:
                out.append(text)
        if out:
            return out

    transcript_text = str(video.get("transcript_text", ""))
    if not transcript_text:
        return []
    return [line.strip() for line in transcript_text.splitlines() if line.strip()]


def _parse_year_ranges(text: str) -> list[tuple[int, int]]:
    ranges: list[tuple[int, int]] = []
    for y1, y2 in _YEAR_RANGE_RE.findall(text):
        a = int(y1)
        b = int(y2)
        if a > b:
            a, b = b, a
        ranges.append((a, b))
    return ranges


def _parse_pre_post_markers(text: str) -> tuple[list[int], list[int]]:
    pre = [int(y) for y in _PRE_YEAR_RE.findall(text)]
    post = [int(y) for y in _POST_YEAR_RE.findall(text)]
    return pre, post


def build_video_engine_year_context(videos: list[dict], scaffold: dict) -> dict[str, dict[str, dict]]:
    """
    Build transcript-derived year context per video and engine.

    Captures explicit years, year ranges, and pre/post markers appearing in the
    same segment or a small neighboring window around engine mentions.
    """
    engine_patterns = _build_engine_patterns(scaffold)
    context_by_video: dict[str, dict[str, dict]] = {}

    for video in videos:
        video_id = str(video.get("video_id", "")).strip()
        if not video_id:
            continue

        segs = _iter_transcript_segments(video)
        if not segs:
            continue

        seg_years = [set(int(y) for y in _YEAR_RE.findall(seg)) for seg in segs]
        seg_ranges = [_parse_year_ranges(seg) for seg in segs]
        seg_pre_post = [_parse_pre_post_markers(seg) for seg in segs]

        title_blob = " ".join(
            [
                str(video.get("title", "")),
                " ".join(str(q) for q in video.get("matched_queries", []) if q),
            ]
        )
        title_years = set(int(y) for y in _YEAR_RE.findall(title_blob))
        title_ranges = _parse_year_ranges(title_blob)
        title_pre, title_post = _parse_pre_post_markers(title_blob)

        per_engine: dict[str, dict[str, Any]] = {}
        for code in engine_patterns:
            per_engine[code] = {
                "years": set(),
                "ranges": set(),
                "pre_years": set(),
                "post_years": set(),
                "hit_count": 0,
            }

        for idx, seg in enumerate(segs):
            w0 = max(0, idx - 2)
            w1 = min(len(segs), idx + 3)

            win_years: set[int] = set()
            win_ranges: set[tuple[int, int]] = set()
            win_pre: set[int] = set()
            win_post: set[int] = set()

            for j in range(w0, w1):
                win_years.update(seg_years[j])
                win_ranges.update(seg_ranges[j])
                pre_markers, post_markers = seg_pre_post[j]
                win_pre.update(pre_markers)
                win_post.update(post_markers)

            for code, pattern in engine_patterns.items():
                if not pattern.search(seg):
                    continue
                info = per_engine[code]
                info["hit_count"] = int(info["hit_count"]) + 1
                info["years"].update(win_years)
                info["ranges"].update(win_ranges)
                info["pre_years"].update(win_pre)
                info["post_years"].update(win_post)

        compact: dict[str, dict] = {}
        for code, info in per_engine.items():
            years = sorted(y for y in info["years"] if 1990 <= y <= 2030)
            ranges = sorted(info["ranges"])
            pre_years = sorted(y for y in info["pre_years"] if 1990 <= y <= 2030)
            post_years = sorted(y for y in info["post_years"] if 1990 <= y <= 2030)
            hit_count = int(info["hit_count"])

            if hit_count == 0:
                continue
            if not years and not ranges and not pre_years and not post_years:
                continue

            compact[code] = {
                "years": years,
                "ranges": [f"{a}-{b}" if a != b else str(a) for a, b in ranges],
                "pre_years": pre_years,
                "post_years": post_years,
                "hit_count": hit_count,
            }

        # Fuse title-level cues when the engine is explicitly in the title/query text.
        if title_blob:
            for code, pattern in engine_patterns.items():
                if not pattern.search(title_blob):
                    continue

                entry = compact.setdefault(
                    code,
                    {
                        "years": [],
                        "ranges": [],
                        "pre_years": [],
                        "post_years": [],
                        "hit_count": 0,
                    },
                )

                merged_years = sorted(
                    set(entry.get("years", [])) | {y for y in title_years if 1990 <= y <= 2030}
                )
                merged_ranges = sorted(
                    set(entry.get("ranges", []))
                    | {
                        f"{a}-{b}" if a != b else str(a)
                        for a, b in title_ranges
                        if 1990 <= a <= 2030 and 1990 <= b <= 2030
                    }
                )
                merged_pre = sorted(
                    set(entry.get("pre_years", [])) | {y for y in title_pre if 1990 <= y <= 2030}
                )
                merged_post = sorted(
                    set(entry.get("post_years", [])) | {y for y in title_post if 1990 <= y <= 2030}
                )

                entry["years"] = merged_years
                entry["ranges"] = merged_ranges
                entry["pre_years"] = merged_pre
                entry["post_years"] = merged_post
                entry["hit_count"] = int(entry.get("hit_count", 0)) + 1

        if compact:
            context_by_video[video_id] = compact

    return context_by_video


def _format_year_span(years: list[int]) -> str | None:
    unique = sorted(set(y for y in years if 1990 <= y <= 2030))
    if not unique:
        return None
    if len(unique) == 1:
        return str(unique[0])
    return f"{unique[0]}-{unique[-1]}"


def enrich_issues_with_year_context(
    issues: list[dict],
    video_engine_context: dict[str, dict[str, dict]],
) -> list[dict]:
    """Attach transcript-derived engine/year evidence without overriding model year labels."""
    if not issues:
        return issues

    for issue in issues:
        engines = issue.get("affected_engines", [])
        if isinstance(engines, str):
            engines = [engines]
        if not isinstance(engines, list):
            engines = []

        source_ids: list[str] = []
        if isinstance(issue.get("source_videos"), list):
            for row in issue["source_videos"]:
                if isinstance(row, dict):
                    vid = str(row.get("video_id", "")).strip()
                    if vid:
                        source_ids.append(vid)
        src_single = str(issue.get("source_video_id", "")).strip()
        if src_single:
            source_ids.append(src_single)

        # Preserve order and remove duplicates.
        source_ids = list(dict.fromkeys(source_ids))
        if not source_ids:
            continue

        per_engine_context: list[dict] = []

        for eng in engines:
            eng_code = str(eng).strip()
            if not eng_code or eng_code.lower() == "all":
                continue

            years: set[int] = set()
            pre_years: set[int] = set()   # upper-bound markers ("made to", "before")
            post_years: set[int] = set()  # lower-bound markers ("from", "after")
            evidence_hits = 0
            for vid in source_ids:
                ctx = video_engine_context.get(vid, {}).get(eng_code)
                if not ctx:
                    continue

                years.update(int(y) for y in ctx.get("years", []) if isinstance(y, int))
                for pre_year in ctx.get("pre_years", []):
                    if isinstance(pre_year, int):
                        pre_years.add(pre_year)
                        years.add(pre_year)  # keep in years for backward compat
                for post_year in ctx.get("post_years", []):
                    if isinstance(post_year, int):
                        post_years.add(post_year)
                        years.add(post_year)  # keep in years for backward compat

                for span in ctx.get("ranges", []):
                    if not isinstance(span, str) or "-" not in span:
                        continue
                    left, right = span.split("-", 1)
                    try:
                        years.add(int(left))
                        years.add(int(right))
                    except ValueError:
                        continue

                evidence_hits += int(ctx.get("hit_count", 0))

            years_sorted = sorted(y for y in years if 1990 <= y <= 2030)
            if not years_sorted:
                continue

            entry: dict[str, Any] = {
                "engine": eng_code,
                "years": _format_year_span(years_sorted),
                "evidence_hits": evidence_hits,
            }
            # Preserve directionality so postprocess can build correct bounds.
            if pre_years:
                entry["pre_years"] = sorted(pre_years)
            if post_years:
                entry["post_years"] = sorted(post_years)
            per_engine_context.append(entry)

        if not per_engine_context:
            continue

        issue["engine_year_context"] = per_engine_context

    return issues


def save_outputs(final: list[dict], out_json: Path, out_csv: Path) -> None:
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(final, f, ensure_ascii=False, indent=2)
    log.info("Saved JSON: %s (%d issues)", out_json, len(final))

    flat = []
    for row in final:
        flat.append(
            {
                k: (json.dumps(v, ensure_ascii=False) if isinstance(v, (list, dict)) else v)
                for k, v in row.items()
            }
        )

    try:
        pd.DataFrame(flat).to_csv(out_csv, index=False)
        log.info("Saved CSV:  %s", out_csv)
    except PermissionError:
        alt_csv = out_csv.with_stem(out_csv.stem + "_tmp")
        pd.DataFrame(flat).to_csv(alt_csv, index=False)
        log.warning("CSV locked — saved to %s instead (close Excel and rename)", alt_csv)


# ── Transcript pre-filter ─────────────────────────────────────────────────────

# High-specificity keywords score 2x; generic ones score 1x.
_MECH_KEYWORDS_HIGH = {
    "mechatronic", "dsg", "flywheel", "timing chain", "timing belt", "tensioner",
    "egr", "dpf", "pcv", "crankcase", "turbo", "intercool", "injector",
    "fuel pump", "water pump", "heater core", "swirl flap", "carbon buildup",
    "carbon build", "silica", "misfire", "limp mode", "fault code",
    "recall", "tsb", "campaign",
    # Turkish
    "mekatronik", "volan", "triger", "zincir", "kayış", "gergi",
    "karter", "enjektör", "enjektor", "yakıt pompası", "yakit pompasi",
    "su pompası", "su pompasi", "kalorifer peteği", "kalorifer petegi",
    "kurum", "tekleme", "limp mod", "arıza kodu", "ariza kodu",
    "geri çağırma", "geri cagirma", "servis bülteni", "kampanya",
}
_MECH_KEYWORDS_LOW = {
    # Failure modes
    "fail", "failure", "fault", "broken", "broke", "cracked", "leak", "leaking",
    "seized", "worn", "wear", "clog", "clogged", "blocked",
    "burst", "rupture", "blow", "shatter", "corrode", "corrosion", "rust",
    "vibrat", "knock", "rattle", "squeak", "grind", "whine", "whistle", "shudder",
    "stall", "misfire", "hesitat", "rough idle", "idle", "limp",
    # Systems
    "engine", "gearbox", "transmiss", "clutch", "coolant", "radiator", "thermostat",
    "valve", "piston", "cylinder", "cat", "catalyst",
    "oil", "sump", "gasket", "seal", "diff", "axle", "subframe",
    "suspension", "strut", "shock", "bearing", "hub", "brake",
    "electrical", "wiring", "sensor", "ecu", "module", "alternator", "battery",
    # Cost language
    "expensive", "replace", "repair", "fix", "avoid", "problem", "issue", "warning",
    # Turkish failure modes
    "arıza", "ariza", "hata", "bozuk", "kırık", "kirik", "çatlak", "catlak",
    "kaçak", "kacak", "sızdırma", "sizdirma", "aşınma", "asinma", "tıkalı",
    "tikali", "blok", "patlak", "yırtık", "yirtik", "korozyon", "pas",
    "titreşim", "titresim", "vuruntu", "tıkırtı", "tikirti", "ses", "gıcırtı",
    "gicirti", "uğultu", "ugultu", "ıslık", "islik", "stop etme", "tekleme",
    "rölanti", "rolanti",
    # Turkish systems
    "motor", "şanzıman", "sanziman", "debriyaj", "soğutma", "sogutma",
    "radyatör", "radyator", "termostat", "valf", "piston", "silindir",
    "katalizör", "katalizor", "yağ", "yag", "conta", "keçe", "kece", "dif",
    "aks", "travers", "süspansiyon", "suspansiyon", "amortisör", "amortisort",
    "rulman", "porya", "fren", "elektrik", "tesisat", "sensör", "sensor",
    "beyin", "modül", "modul", "alternatör", "alternator", "akü", "aku",
    # Turkish cost language
    "pahalı", "pahali", "değişim", "degisim", "tamir", "bakım", "bakim",
    "kaçın", "kacin", "sorun", "problem", "uyarı", "uyari",
}
# Combined set for quick membership checks
_ALL_KEYWORDS = _MECH_KEYWORDS_HIGH | _MECH_KEYWORDS_LOW

# System-level keywords used by the triage heuristic
_SYSTEM_KEYWORDS = {
    "engine", "gearbox", "transmiss", "turbo", "coolant", "dsg", "mechatronic",
    "suspension", "electrical", "injector", "egr", "dpf", "timing", "clutch",
    "brake", "exhaust", "fuel pump", "water pump", "alternator", "sensor",
    # Turkish
    "motor", "şanzıman", "sanziman", "vites", "soğutma", "sogutma", "mekatronik",
    "süspansiyon", "suspansiyon", "elektrik", "enjektör", "enjektor", "egzoz",
    "yakıt pompası", "yakit pompasi", "su pompası", "su pompasi", "alternatör",
    "alternator", "sensör", "sensor", "debriyaj",
}


def _group_into_sentences(segments: list[dict]) -> list[dict]:
    """
    Merge consecutive transcript segments into sentence-like chunks,
    splitting on pauses >2s or period boundaries.
    Returns list of {"text": str, "start": float, "word_count": int}.
    """
    if not segments:
        return []

    sentences = []
    buf_text = []
    buf_start = float(segments[0].get("start", 0))
    prev_end = 0.0

    for seg in segments:
        start = float(seg.get("start", 0))
        dur = float(seg.get("duration", 0))
        text = seg.get("text", "").strip()
        if not text:
            continue

        # Start new sentence on pause >2s or if buffer ends with sentence-ending punctuation
        gap = start - prev_end if prev_end > 0 else 0
        if buf_text and (gap > 2.0 or buf_text[-1].rstrip().endswith((".", "!", "?"))):
            merged = " ".join(buf_text)
            sentences.append({"text": merged, "start": buf_start, "word_count": len(merged.split())})
            buf_text = []
            buf_start = start

        buf_text.append(text)
        prev_end = start + dur

    # Flush remaining buffer
    if buf_text:
        merged = " ".join(buf_text)
        sentences.append({"text": merged, "start": buf_start, "word_count": len(merged.split())})

    return sentences


def _score_sentence(text: str, word_count: int) -> float:
    """Score a sentence by keyword density with specificity weighting."""
    lower = text.lower()
    hits = 0.0
    for kw in _MECH_KEYWORDS_HIGH:
        if kw in lower:
            hits += 2.0
    for kw in _MECH_KEYWORDS_LOW:
        if kw in lower:
            hits += 1.0
    return hits / max(word_count, 1)


def score_and_select_sentences(segments: list[dict], max_words: int = 2500) -> str:
    """
    Sentence-level keyword density scorer. Groups segments into sentences,
    scores by keyword density (high-specificity keywords weighted 2x),
    selects top sentences up to max_words, then re-orders chronologically.
    Falls back to full transcript if scoring selects <20% of content.
    """
    if not segments:
        return ""

    sentences = _group_into_sentences(segments)
    if not sentences:
        return "\n".join(s.get("text", "") for s in segments)

    total_words = sum(s["word_count"] for s in sentences)

    # Score each sentence
    scored = []
    for sent in sentences:
        score = _score_sentence(sent["text"], sent["word_count"])
        scored.append({**sent, "score": score})

    # Sort by score descending, accumulate up to budget
    scored.sort(key=lambda s: s["score"], reverse=True)
    selected = []
    budget = 0
    for sent in scored:
        if sent["score"] == 0:
            break  # No point adding zero-score sentences
        if budget + sent["word_count"] > max_words:
            continue
        selected.append(sent)
        budget += sent["word_count"]

    kept_ratio = budget / max(total_words, 1)
    log.info("  Sentence scorer: kept %d/%d words (%.0f%%) from %d sentences",
             budget, total_words, kept_ratio * 100, len(sentences))

    # Fallback: if scoring kept <20% of content, use full text
    if kept_ratio < 0.20:
        full_text = "\n".join(s.get("text", "") for s in segments)
        words = full_text.split()
        if len(words) > max_words:
            return " ".join(words[:max_words]) + "\n[truncated]"
        return full_text

    # Re-order chronologically
    selected.sort(key=lambda s: s["start"])
    return "\n".join(s["text"] for s in selected)


def triage_video(segments: list[dict]) -> tuple[bool, float]:
    """
    Quick local heuristic: decide if a video is worth sending to the LLM.
    Returns (Should_Process, Hit_Ratio).
    """
    if not segments:
        return False, 0.0

    all_words: set[str] = set()
    matched_keywords: set[str] = set()
    matched_systems: set[str] = set()

    for seg in segments:
        txt = seg.get("text", "").lower()
        words = txt.split()
        all_words.update(words)
        for kw in _ALL_KEYWORDS:
            if kw in txt:
                matched_keywords.add(kw)
        for kw in _SYSTEM_KEYWORDS:
            if kw in txt:
                matched_systems.add(kw)

    hit_ratio = len(matched_keywords) / max(len(all_words), 1)

    if hit_ratio < 0.02 and len(matched_systems) < 3:
        log.info("  Triage SKIP: hit_ratio=%.3f, systems=%d — too low relevance",
                 hit_ratio, len(matched_systems))
        return False, hit_ratio

    return True, hit_ratio


def build_min_scaffold_context(scaffold: dict) -> str:
    """A compact version of the scaffold for Pass 1 extraction (codes only)."""
    if not scaffold:
        return "(no scaffold available)"
    meta = scaffold.get("meta", {})
    lines = [f"Vehicle: {meta.get('make','?')} {meta.get('model','?')}"]
    
    eng_codes = []
    for ef in scaffold.get("engine_families", []):
        for d in ef.get("displacements", []):
            code = d.get("code") if isinstance(d, dict) else d
            if code: eng_codes.append(str(code))
    if eng_codes:
        lines.append(f"Engines: {', '.join(sorted(set(eng_codes)))}")
        
    tx_codes = [str(tx.get("code")) for tx in scaffold.get("transmissions", []) if tx.get("code")]
    if tx_codes:
        lines.append(f"Transmissions: {', '.join(sorted(set(tx_codes)))}")
        
    return " | ".join(lines)


# ── Pass 1: per-video extraction ─────────────────────────────────────────────

EXTRACT_SYSTEM_TMPL = (
    "You are an automotive knowledge extraction engine. "
    "CONTEXT: {scaffold_context}\n"
    "Extract only genuine design/manufacturing defects and known chronic failure patterns. "
    "NOTE: Emission control issues (DPF clogging, EGR soot, AdBlue faults) and carbon buildup ARE chronic failure patterns and SHOULD be extracted, even if linked to driving habits (like short trips). "
    "SKIP: general maintenance (oil changes, brake pads), tyre wear, improper-use (accidents, ignoring warning lights). "
    "Return ONLY a valid JSON array. No markdown, no explanation."
)

# Compact schema — 6 core fields.
EXTRACT_USER_TMPL = """\
=== VIDEO: {title} ({duration}) ===
{transcript}

=== TASK ===
Extract genuine defects from the transcript.
One JSON object per distinct issue:

{{
  "issue_id": "snake_case",
  "label": "max 7 words",
  "system_component": "engine|gearbox|cooling|electrical|suspension|exhaust|brakes|fuel|body|other",
  "affected_engines": ["specific scaffold codes only"],
  "affected_years": "verbatim year phrase from transcript or null",
  "symptom": "one sentence — what driver notices"
}}
"""


def extract_issues_from_video(video: dict, scaffold: dict, hit_ratio: float = 0.0) -> list[dict]:
    is_short = video.get("video_type") == "short" or (video.get("duration_seconds") or 9999) < 120
    segments = video.get("transcript_segments", [])

    # Adaptive context window: if hit_ratio is high, the signal is dense — we can use less context.
    word_limit = MAX_TRANSCRIPT_WORDS
    if hit_ratio > 0.15:
        word_limit = 1500
        log.info("  High relevancy (%.2f) — using 1500 word window", hit_ratio)

    if is_short:
        transcript = video.get("transcript_text", "") or "\n".join(s.get("text", "") for s in segments)
    elif segments:
        transcript = score_and_select_sentences(segments, max_words=word_limit)
    else:
        transcript = video.get("transcript_text", "")

    words = transcript.split()
    if len(words) > word_limit:
        transcript = " ".join(words[:word_limit]) + "\n[truncated]"

    sys_prompt = EXTRACT_SYSTEM_TMPL.format(scaffold_context=build_min_scaffold_context(scaffold))
    prompt = EXTRACT_USER_TMPL.format(
        title=video["title"],
        duration=video["duration_raw"],
        transcript=transcript,
    )

    vid_id = video["video_id"]
    try:
        tok_limit = MAX_EXTRACT_TOKENS_SHORT if is_short else MAX_EXTRACT_TOKENS
        raw = call_llm(sys_prompt, prompt, tok_limit, label=vid_id)
        if not raw:
            raise ValueError("Empty model response")
        # (rest of parsing logic remains the same)
        if raw.startswith("```"):
            raw = raw.split("```", 2)[1]
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.strip()
        issues = json.loads(raw)
        if not isinstance(issues, list):
            issues = [issues]
        # Tag each issue with its source
        for issue in issues:
            issue["source_video_id"] = vid_id
            issue["source_title"] = video["title"]
            issue["source_channel"] = video.get("channel", "")
            issue["video_type_category"] = video.get("video_type_category") or infer_video_type_category(video.get("title"))
        log.info("  [%s] extracted %d issues", vid_id, len(issues))
        return issues
    except Exception as e:
        log.error("  [%s] Extraction failed: %s", vid_id, e)
        return []


# ── Batched extraction for short transcripts ─────────────────────────────────

BATCH_WORD_LIMIT = 2500  # max combined words for a batched API call

EXTRACT_BATCH_USER_TMPL = """\
Extract genuine defects from each video transcript below.
Return a single JSON array covering ALL videos.

Schema per issue:
{{
  "issue_id": "snake_case",
  "label": "max 7 words",
  "system_component": "engine|gearbox|cooling|electrical|suspension|exhaust|brakes|fuel|body|other",
  "affected_engines": ["specific scaffold codes only"],
  "affected_years": "verbatim year phrase from transcript or null",
  "symptom": "one sentence — what driver notices",
  "source_video_id": "the video_id from the header below"
}}

{video_sections}
"""


def extract_issues_batched(videos: list[dict], scaffold: dict) -> list[dict]:
    """
    Batch multiple short-transcript videos into a single API call.
    Returns tagged issues from all videos in the batch.
    """
    sections = []
    for v in videos:
        transcript = v.get("transcript_text", "") or "\n".join(
            s.get("text", "") for s in v.get("transcript_segments", []))
        sections.append(
            f"=== VIDEO: {v['title']} (id: {v['video_id']}, "
            f"{v.get('duration_raw', '?')}) ===\n"
            f"{transcript}"
        )

    sys_prompt = EXTRACT_SYSTEM_TMPL.format(scaffold_context=build_min_scaffold_context(scaffold))
    prompt = EXTRACT_BATCH_USER_TMPL.format(video_sections="\n\n".join(sections))

    vid_ids = [v["video_id"] for v in videos]
    log.info("  Batched extraction: %d videos (%s)", len(videos), ", ".join(vid_ids))

    try:
        raw = call_llm(sys_prompt, prompt, MAX_EXTRACT_TOKENS, label="batch")
        if not raw:
            raise ValueError("Empty model response")
        if raw.startswith("```"):
            raw = raw.split("```", 2)[1]
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.strip()
        issues = json.loads(raw)
        if not isinstance(issues, list):
            issues = [issues]
        # Ensure each issue has source tags
        video_lookup = {v["video_id"]: v for v in videos}
        for issue in issues:
            vid = issue.get("source_video_id", "")
            if vid in video_lookup:
                v = video_lookup[vid]
                issue["source_title"] = v["title"]
                issue["source_channel"] = v.get("channel", "")
                issue["video_type_category"] = v.get("video_type_category") or infer_video_type_category(v.get("title"))
            elif not issue.get("source_video_id"):
                v = videos[0]
                issue["source_video_id"] = v["video_id"]
                issue["source_title"] = v["title"]
                issue["source_channel"] = v.get("channel", "")
                issue["video_type_category"] = v.get("video_type_category") or infer_video_type_category(v.get("title"))
        log.info("  [batch] extracted %d issues from %d videos", len(issues), len(videos))
        return issues
    except Exception as e:
        log.error("  [batch] Batched extraction failed: %s", e)
        return []


# ── Pass 2: consolidation ─────────────────────────────────────────────────────

CONSOLIDATE_SYSTEM = (
    "You are an automotive knowledge base editor. "
    "You receive a flat list of car issues extracted from multiple YouTube videos. "
    "Many are duplicates or partial overlaps. "
    "Consolidate them into the cleanest possible knowledge base: "
    "merge duplicates, keep the most complete information, count source mentions. "
    "Return ONLY a valid JSON array. No markdown, no explanation, no code fences."
)

CONSOLIDATE_USER_TMPL = """\
=== VEHICLE REFERENCE ===
{scaffold_context}

=== RAW ISSUES FROM {n_videos} VIDEOS ({n_issues} total raw issues) ===
{raw_issues_json}

=== TASK ===
Consolidate the raw issues above into a clean, deduplicated knowledge base.

Rules:
- Merge issues that describe the same failure (same component + same root cause)
- Keep the most specific/complete information when merging (best symptom, best fix, widest affected_engines)
- If sources disagree on severity, take the higher one
- Count how many distinct source_video_ids mention each merged issue
- Count how many distinct source_channels mention each merged issue (track this as distinct_channel_count)
- SOURCE BIAS: 'list_format' videos (buyer's guides) tend to enumerate many issues at once. Treat them as a single curation source. 'organic' videos (owner reviews/mechanics) are independent corroborations.
- For affected_years: use the verbatim year phrases already captured in the raw issues (e.g. 'pre-2014', '2013-2016'). If multiple raw issues agree on a year phrase, keep it. If they disagree, keep the most specific/narrow one. Set null only if no raw issue has an explicit year phrase.

For each final issue return this exact schema:

{{
  "issue_id": "snake_case_unique_id",
  "label": "concise English label (max 8 words)",
  "label_short": "2-3 word label",
  "system_component": "engine|gearbox|cooling|electrical|suspension|exhaust|brakes|fuel|body|other",
  "issue_type": "chronic_failure|intermittent_fault|wear_item|sensor_fault|fluid_leak|noise|structural|other",
  "severity": "low|medium|high",
  "confidence": "low|medium|high",
  "affected_engines": ["scaffold codes or 'all'"],
  "affected_years": "year range or null",
  "onset_km_range": "e.g. 100k-200k km or null",
  "symptom": "what the driver notices",
  "cause": "root cause or null",
  "fix": "repair/workaround or null",
  "warning_signs": ["sign 1", "sign 2"],
  "inspection_advice": "what to check when buying used, or null",
  "mention_count": <integer — how many distinct videos mentioned this>,
  "distinct_channel_count": <integer — how many distinct channels mentioned this>,
  "source_videos": [
    {{"video_id": "...", "title": "...", "channel": "...", "video_type_category": "..."}}
  ],
  "source": "youtube",
  "data_quality": "low|medium|high",
  "notes": "any caveats or null"
}}

Return the full array, sorted by mention_count descending.
"""


def _consolidate_batch(raw_issues: list[dict], scaffold_context: str, n_videos: int, label: str) -> list[dict]:
    if not raw_issues:
        return []

    def _parse_json_array(payload: str) -> list[dict] | None:
        raw_payload = payload.strip()
        if raw_payload.startswith("```"):
            raw_payload = raw_payload.split("```", 2)[1]
            if raw_payload.startswith("json"):
                raw_payload = raw_payload[4:]
            raw_payload = raw_payload.strip()
        try:
            parsed = json.loads(raw_payload)
        except json.JSONDecodeError:
            start = raw_payload.find("[")
            end = raw_payload.rfind("]")
            if start < 0 or end < start:
                return None
            try:
                parsed = json.loads(raw_payload[start:end + 1])
            except json.JSONDecodeError:
                return None
        if not isinstance(parsed, list):
            parsed = [parsed]
        return [row for row in parsed if isinstance(row, dict)]

    prompt = CONSOLIDATE_USER_TMPL.format(
        scaffold_context=scaffold_context,
        n_videos=n_videos,
        n_issues=len(raw_issues),
        raw_issues_json=json.dumps(raw_issues, ensure_ascii=False, indent=2),
    )
    repair_system = (
        "You are a strict JSON repair tool. "
        "Fix malformed JSON into a valid JSON array only. "
        "Do not add commentary, markdown, or code fences."
    )

    for attempt in range(1, 4):
        raw = call_llm(CONSOLIDATE_SYSTEM, prompt, CONSOLIDATE_TOKENS, label=f"consolidate:{label}:a{attempt}")
        if not raw:
            raise ValueError(f"Empty consolidation response for {label}")
        merged = _parse_json_array(raw)
        if merged is None:
            if attempt < 3:
                log.warning(
                    "  [consolidate:%s] invalid JSON on attempt %d/3; retrying...",
                    label,
                    attempt,
                )
                continue
            repair_prompt = (
                "Repair this malformed JSON into a valid JSON array without changing meaning:\n\n"
                f"{raw}"
            )
            repaired = call_llm(
                repair_system,
                repair_prompt,
                CONSOLIDATE_TOKENS,
                label=f"consolidate:{label}:repair",
            )
            merged = _parse_json_array(repaired)
            if merged is None:
                can_passthrough = any(
                    isinstance(row, dict)
                    and (
                        "system_component" in row
                        or "mention_count" in row
                        or "source_videos" in row
                    )
                    for row in raw_issues
                )
                if not can_passthrough:
                    raise ValueError(f"Unrecoverable malformed consolidation JSON for {label}")
                log.warning(
                    "  [consolidate:%s] using passthrough chunk after JSON repair failure",
                    label,
                )
                merged = [row for row in raw_issues if isinstance(row, dict)]

        merged = refresh_issue_counters(merged)
        log.info("  [consolidate:%s] %d -> %d issues", label, len(raw_issues), len(merged))
        return merged

    return []


def consolidate_issues(all_raw: list[dict], scaffold_context: str, n_videos: int, slug: str = "unknown") -> list[dict]:
    """
    Consolidate raw issues into a clean knowledge base.
    Uses a three-stage approach with intermediate caching to support resume.
    """
    if not all_raw:
        return []

    pass2_cache = ROOT / "data" / "processed" / f"_youtube_pass2_{slug}.json"
    
    # Try to load Pass 2 progress
    progress = {"stage": "initial", "data": []}
    if pass2_cache.exists():
        try:
            with open(pass2_cache, encoding="utf-8") as f:
                progress = json.load(f)
            log.info("Resuming Pass 2 from stage: %s", progress.get("stage"))
        except Exception as e:
            log.warning("Could not load Pass 2 cache: %s", e)

    def save_p2_cache(stage, data):
        try:
            with open(pass2_cache, "w", encoding="utf-8") as f:
                json.dump({"stage": stage, "data": data}, f, ensure_ascii=False, indent=2)
        except Exception as e:
            log.warning("Failed to save Pass 2 cache: %s", e)

    # Ensure bias-aware source tagging exists even for legacy raw JSONs.
    all_raw = refresh_issue_counters(all_raw)

    # Compact input: Remove redundant fields from Pass 1 output before sending to Pass 2.
    # Pass 2 doesn't need source_title, source_channel, or video_type_category for merging logic.
    compact_raw = []
    for issue in all_raw:
        compact_raw.append({
            "issue_id": issue.get("issue_id"),
            "label": issue.get("label"),
            "system": issue.get("system_component"),
            "engines": issue.get("affected_engines"),
            "years": issue.get("affected_years"),
            "symptom": issue.get("symptom"),
            "video_id": issue.get("source_video_id")
        })

    # Stage 1: Initial batch consolidation
    if progress["stage"] == "initial":
        batch_results: list[dict] = []
        for i in range(0, len(compact_raw), CONSOLIDATE_BATCH):
            chunk = compact_raw[i: i + CONSOLIDATE_BATCH]
            label = f"batch[{i}:{i+len(chunk)}]"
            merged = _consolidate_batch(chunk, scaffold_context, n_videos, label)
            batch_results.extend(merged)
        log.info("After initial batching: %d issues (was %d)", len(batch_results), len(all_raw))
        progress = {"stage": "secondary", "data": batch_results}
        save_p2_cache("secondary", batch_results)
    
    # Stage 2: Secondary merge if still large
    batch_results = progress["data"]
    if progress["stage"] == "secondary":
        if len(batch_results) > 30:
            log.info("Set still large (%d), doing secondary batch merge...", len(batch_results))
            secondary_results = []
            # Overlap windows so near-duplicate issues from adjacent chunks are compared.
            secondary_batch_size = 10
            secondary_stride = 5
            for i in range(0, len(batch_results), secondary_stride):
                chunk = batch_results[i: i + secondary_batch_size]
                if not chunk:
                    continue
                merged = _consolidate_batch(chunk, scaffold_context, n_videos, f"secondary[{i}]")
                secondary_results.extend(merged)
            batch_results = secondary_results
        
        progress = {"stage": "final", "data": batch_results}
        save_p2_cache("final", batch_results)

    # Stage 3: Final global pass
    batch_results = progress["data"]
    if progress["stage"] == "final":
        final = _consolidate_batch(batch_results, scaffold_context, n_videos, "global_final")
        # Don't save final to pass2_cache to avoid loops, Pass 2 is "done"
    else:
        final = batch_results

    final = refresh_issue_counters(final)
    final.sort(
        key=lambda x: (
            x.get("corroboration_count", 0),
            x.get("distinct_channel_count", 0),
            x.get("mention_count", 0),
        ),
        reverse=True,
    )

    if pass2_cache.exists():
        pass2_cache.unlink()
        log.info("Removed pass-2 cache")

    log.info("Consolidation complete — %d final issues", len(final))
    return final


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Extract issue knowledge from YouTube transcripts")
    parser.add_argument("--slug", default="vw_golf_mk7", help="Car model slug matching the raw JSON filename")
    parser.add_argument("--skip-consolidation", action="store_true", help="Skip pass 2 (useful for debugging pass 1)")
    parser.add_argument(
        "--filter-confirmed",
        action="store_true",
        default=True,
        help="Only save corroborated issues (on by default).",
    )
    parser.add_argument(
        "--no-filter-confirmed",
        action="store_false",
        dest="filter_confirmed",
        help="Disable confirmed-only output file.",
    )
    parser.add_argument(
        "--min-corroboration",
        type=int,
        default=2,
        help="Minimum corroboration_count for confirmed output (default: 2).",
    )
    parser.add_argument(
        "--enrich-only",
        action="store_true",
        help="Skip LLM extraction and only enrich an existing issue JSON with transcript year context.",
    )
    parser.add_argument(
        "--input-json",
        type=Path,
        default=None,
        help="Input issue JSON path for --enrich-only. Defaults to issue_knowledge_youtube_{slug}.json.",
    )
    parser.add_argument(
        "--output-json",
        type=Path,
        default=None,
        help="Output JSON path. In --enrich-only mode defaults to <input>_year_enriched.json.",
    )
    args = parser.parse_args()

    slug = args.slug
    in_path = ROOT / "data" / "raw" / "videos" / f"{slug}_raw.json"
    default_out_json = ROOT / "data" / "processed" / f"issue_knowledge_youtube_{slug}.json"
    out_json = args.output_json or default_out_json
    out_csv = out_json.with_suffix(".csv")
    pass1_cache = ROOT / "data" / "processed" / f"_youtube_pass1_{slug}.json"

    if not in_path.exists():
        sys.exit(f"Input not found: {in_path}")

    with open(in_path, encoding="utf-8") as f:
        data = json.load(f)

    videos = [v for v in data["videos"] if v["transcript_status"] == "ok"]
    log.info("Loaded %d usable videos from %s", len(videos), in_path.name)

    scaffold = load_scaffold(slug)
    scaffold_context = build_scaffold_context(scaffold)

    if args.enrich_only:
        video_engine_context = build_video_engine_year_context(videos, scaffold)
        log.info(
            "Built transcript year-context for %d/%d videos",
            len(video_engine_context),
            len(videos),
        )

        in_json = args.input_json or default_out_json
        if not in_json.exists():
            sys.exit(f"Input issue JSON not found for --enrich-only: {in_json}")

        if args.output_json:
            enrich_out_json = args.output_json
        else:
            enrich_out_json = in_json.with_stem(in_json.stem + "_year_enriched")
        enrich_out_csv = enrich_out_json.with_suffix(".csv")

        with open(in_json, encoding="utf-8") as f:
            existing = json.load(f)
        if not isinstance(existing, list):
            sys.exit(f"Input issue JSON must be a list of issue objects: {in_json}")

        final = enrich_issues_with_year_context(existing, video_engine_context)
        save_outputs(final, enrich_out_json, enrich_out_csv)
        log.info("Done (enrich-only) — %d issues written", len(final))
        return

    if client is None:
        sys.exit("DEEPSEEK_API_KEY not set")

    # ── Pass 1 ────────────────────────────────────────────────────────────────
    metrics["start_time"] = time.perf_counter()
    metrics["pass1_start"] = time.perf_counter()

    cache_lock = Lock()

    def save_cache():
        # Callers hold cache_lock; avoid nested lock acquisition (deadlock).
        with open(pass1_cache, "w", encoding="utf-8") as f:
            json.dump(all_raw, f, ensure_ascii=False, indent=2)

    # Resume from cache if available
    if pass1_cache.exists():
        with open(pass1_cache, encoding="utf-8") as f:
            all_raw = json.load(f)
        done_ids = {r["source_video_id"] for r in all_raw if "source_video_id" in r}
        remaining = [v for v in videos if v["video_id"] not in done_ids]
        log.info("Resuming pass 1: %d already done, %d remaining", len(done_ids), len(remaining))
    else:
        all_raw = []
        remaining = videos

    # Separate remaining into long videos and shorts for batching
    long_remaining = []
    short_remaining = []
    for v in remaining:
        is_short = v.get("video_type") == "short" or (v.get("duration_seconds") or 9999) < 120
        if is_short:
            short_remaining.append(v)
        else:
            long_remaining.append(v)

    skipped_triage = 0
    # Process long videos in parallel
    if long_remaining:
        log.info("Pass 1 — processing %d long videos (parallel, workers=8)...", len(long_remaining))
        
        def process_video(video):
            nonlocal skipped_triage
            segments = video.get("transcript_segments", [])
            should_proc, hit_ratio = triage_video(segments)
            if not should_proc:
                with cache_lock:
                    skipped_triage += 1
                return []
            
            issues = extract_issues_from_video(video, scaffold, hit_ratio=hit_ratio)
            if issues:
                with cache_lock:
                    all_raw.extend(issues)
                    save_cache()
            return issues

        with ThreadPoolExecutor(max_workers=8) as executor:
            futures = [executor.submit(process_video, v) for v in long_remaining]
            for future in as_completed(futures):
                try:
                    future.result()
                except Exception as e:
                    log.error("Worker failed: %s", e)

    # Process Shorts in batches (sequential batching, but each batch could be parallelized if needed)
    if short_remaining:
        log.info("Pass 1 — batching %d Shorts...", len(short_remaining))
        batches: list[list[dict]] = []
        current_batch: list[dict] = []
        batch_words = 0
        for video in short_remaining:
            text = video.get("transcript_text", "")
            wc = len(text.split()) if text else 0
            if current_batch and batch_words + wc > BATCH_WORD_LIMIT:
                batches.append(current_batch)
                current_batch = []
                batch_words = 0
            current_batch.append(video)
            batch_words += wc
        if current_batch:
            batches.append(current_batch)

        def process_batch(batch):
            issues = extract_issues_batched(batch, scaffold)
            if issues:
                with cache_lock:
                    all_raw.extend(issues)
                    save_cache()
            return issues

        with ThreadPoolExecutor(max_workers=4) as executor:
            futures = [executor.submit(process_batch, b) for b in batches]
            for future in as_completed(futures):
                future.result()

    metrics["pass1_end"] = time.perf_counter()
    if skipped_triage:
        log.info("Pass 1 triaged out %d low-relevance videos", skipped_triage)
    log.info("Pass 1 complete — %d raw issues from %d videos", len(all_raw), len(videos))

    consolidation_ok = False
    if args.skip_consolidation:
        log.info("Skipping consolidation (--skip-consolidation)")
        final = all_raw
    else:
        # ── Pass 2 ────────────────────────────────────────────────────────────
        metrics["pass2_start"] = time.perf_counter()
        final = consolidate_issues(all_raw, scaffold_context, n_videos=len(videos), slug=slug)
        metrics["pass2_end"] = time.perf_counter()
        consolidation_ok = final is not all_raw  # True if we got a new merged list

    final = refresh_issue_counters(final)

    # Save full results
    save_outputs(final, out_json, out_csv)

    # Save confirmed (corroborated) results if requested
    if not args.skip_consolidation and args.filter_confirmed:
        # Pipeline Rule: Allow single-source issues if they are high-confidence technical hits
        RESCUE_KEYWORDS = {"dpf", "egr", "edc", "adblue", "injector", "bearing", "timing chain", "timing belt", "turbo"}
        
        confirmed = []
        for i in final:
            count = i.get("corroboration_count", 0)
            conf = str(i.get("confidence", "")).lower()
            dq = str(i.get("data_quality", "")).lower()
            text = f"{i.get('label','')} {i.get('symptom','')}".lower()
            
            # Rule A: Standard corroboration (2+ independent sources)
            is_corroborated = count >= args.min_corroboration
            
            # Rule B: "Smart Trust" for high-quality technical deep dives
            is_technical_rescue = (
                count >= 1 and 
                conf == "high" and 
                (dq == "high" or any(kw in text for kw in RESCUE_KEYWORDS))
            )
            
            if is_corroborated or is_technical_rescue:
                confirmed.append(i)
        conf_out_json = out_json.with_stem(out_json.stem + "_confirmed")
        conf_out_csv = conf_out_json.with_suffix(".csv")
        save_outputs(confirmed, conf_out_json, conf_out_csv)
        log.info("Saved confirmed set: %d issues", len(confirmed))

    # Only clean up pass-1 cache if consolidation actually succeeded
    if pass1_cache.exists() and consolidation_ok:
        pass1_cache.unlink()
        log.info("Removed pass-1 cache")

    end_time = time.perf_counter()
    total_time = end_time - metrics["start_time"]
    p1_time = metrics["pass1_end"] - metrics["pass1_start"]
    p2_time = metrics["pass2_end"] - metrics["pass2_start"] if metrics["pass2_end"] > 0 else 0

    log.info("Done — %d final issues written", len(final))
    log.info("=== Performance Summary ===")
    log.info(f"Total time: {total_time:.1f}s (Pass1: {p1_time:.1f}s, Pass2: {p2_time:.1f}s)")
    log.info(f"LLM calls: {metrics['llm_calls']}")
    log.info(f"Total tokens: {metrics['total_input_tokens']} in, {metrics['total_output_tokens']} out")
    log.info("===========================")


if __name__ == "__main__":
    main()
