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
from pathlib import Path
from typing import Any

import pandas as pd
import yaml
from openai import OpenAI

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
CONSOLIDATE_TOKENS = 4000   # output cap per consolidation call

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
    """Try to load a scaffold matching the slug (e.g. vw_golf_mk7 → vw_golf.yaml)."""
    candidates = [
        ROOT / "data" / "scaffolds" / f"{slug}.yaml",
        ROOT / "data" / "scaffolds" / "vw_golf.yaml",   # Golf fallback
        ROOT / "data" / "scaffolds" / "renault_clio.yaml",
    ]
    for p in candidates:
        if p.exists():
            with open(p, encoding="utf-8") as f:
                return yaml.safe_load(f)
    log.warning("No scaffold found for '%s' — proceeding without", slug)
    return {}


def build_scaffold_context(scaffold: dict) -> str:
    if not scaffold:
        return "(no scaffold available)"
    lines = []
    meta = scaffold.get("meta", {})
    lines.append(
        f"Vehicle: {meta.get('make','?')} {meta.get('model','?')} "
        f"gen {meta.get('generations','?')}, corpus years {meta.get('corpus_years','?')}"
    )
    lines.append("\nEngine families:")
    for ef in scaffold.get("engine_families", []):
        disps = ", ".join(ef.get("displacements", []))
        yr = ef.get("year_range", ["?", "?"])
        lines.append(f"  {ef['code']} | {ef['fuel_type']} | {disps} | {yr[0]}–{yr[1]}")
    lines.append("\nTransmissions:")
    for tx in scaffold.get("transmissions", []):
        compat = ", ".join(tx.get("compatible_engines", []))
        yr = tx.get("year_range", ["?", "?"])
        lines.append(
            f"  {tx['code']} ({tx.get('internal_code','?')}) | {tx['type']} | "
            f"{compat} | {yr[0]}–{yr[1]}"
        )
    return "\n".join(lines)


# ── Deterministic year-context enrichment ───────────────────────────────────

_YEAR_RE = re.compile(r"\b(19\d{2}|20[0-2]\d)\b")
_YEAR_RANGE_RE = re.compile(r"\b(19\d{2}|20[0-2]\d)\s*(?:-|–|to)\s*(19\d{2}|20[0-2]\d)\b", re.IGNORECASE)
_PRE_YEAR_RE = re.compile(r"\b(?:pre|before|up\s*to|until)\s*(?:-|–)?\s*(19\d{2}|20[0-2]\d)\b", re.IGNORECASE)
_POST_YEAR_RE = re.compile(r"\b(?:post|after|from|since)\s*(?:-|–)?\s*(19\d{2}|20[0-2]\d)\b", re.IGNORECASE)


def _build_engine_patterns(scaffold: dict) -> dict[str, re.Pattern]:
    """Compile regex patterns from scaffold displacement codes (e.g. 1.4_TSI)."""
    displacements: set[str] = set()
    for family in scaffold.get("engine_families", []):
        if not isinstance(family, dict):
            continue
        for disp in family.get("displacements", []):
            code = str(disp).strip().upper()
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
            evidence_hits = 0
            for vid in source_ids:
                ctx = video_engine_context.get(vid, {}).get(eng_code)
                if not ctx:
                    continue

                years.update(int(y) for y in ctx.get("years", []) if isinstance(y, int))
                for pre_year in ctx.get("pre_years", []):
                    if isinstance(pre_year, int):
                        years.add(pre_year)
                for post_year in ctx.get("post_years", []):
                    if isinstance(post_year, int):
                        years.add(post_year)

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

            per_engine_context.append(
                {
                    "engine": eng_code,
                    "years": _format_year_span(years_sorted),
                    "evidence_hits": evidence_hits,
                }
            )

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
}
# Combined set for quick membership checks
_ALL_KEYWORDS = _MECH_KEYWORDS_HIGH | _MECH_KEYWORDS_LOW

# System-level keywords used by the triage heuristic
_SYSTEM_KEYWORDS = {
    "engine", "gearbox", "transmiss", "turbo", "coolant", "dsg", "mechatronic",
    "suspension", "electrical", "injector", "egr", "dpf", "timing", "clutch",
    "brake", "exhaust", "fuel pump", "water pump", "alternator", "sensor",
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


def triage_video(segments: list[dict]) -> bool:
    """
    Quick local heuristic: decide if a video is worth sending to the LLM.
    Returns True if the video should be processed, False to skip.
    """
    if not segments:
        return False

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
        return False

    return True


# ── Pass 1: per-video extraction ─────────────────────────────────────────────

EXTRACT_SYSTEM = (
    "You are an automotive knowledge extraction engine. "
    "Extract only genuine design/manufacturing defects and known chronic failure patterns. "
    "SKIP: general maintenance advice, oil change reminders, tyre wear, improper-use damage, "
    "or issues caused by missed servicing. "
    "Return ONLY a valid JSON array. No markdown, no explanation, no code fences."
)

# Compact schema — 8 core fields. Saves ~60% output tokens vs the 15-field version.
EXTRACT_USER_TMPL = """\
=== VEHICLE REFERENCE ===
{scaffold_context}

=== VIDEO: {title} ({duration}) ===
{transcript}

=== TASK ===
Extract genuine design/manufacturing defects from the transcript.
One JSON object per distinct issue:

{{
  "issue_id": "snake_case (e.g. pcv_diaphragm_tear)",
  "label": "max 7 words",
  "system_component": "engine|gearbox|cooling|electrical|suspension|exhaust|brakes|fuel|body|other",
  "affected_engines": ["scaffold codes e.g. 1.6_TDI, 1.4_TSI — never 'all' unless truly universal"],
  "onset_km_range": "e.g. 80k-150k km or null",
  "symptom": "one sentence — what driver notices",
  "cause": "root cause if stated, else null",
  "fix": "repair/workaround if stated, else null"
}}

Rules:
- affected_engines: use specific codes from the vehicle reference above; only use "all" if the video explicitly says every variant is affected
- Skip issues framed as driver error or neglected maintenance
- Return [] if no genuine defects are mentioned
"""


def extract_issues_from_video(video: dict, scaffold_context: str) -> list[dict]:
    is_short = video.get("video_type") == "short" or (video.get("duration_seconds") or 9999) < 120
    segments = video.get("transcript_segments", [])

    if is_short:
        # Shorts are tiny — use full transcript, no filtering needed
        transcript = video.get("transcript_text", "") or "\n".join(s.get("text", "") for s in segments)
    elif segments:
        transcript = score_and_select_sentences(segments, max_words=MAX_TRANSCRIPT_WORDS)
    else:
        transcript = video.get("transcript_text", "")

    # Hard word cap as final safety net
    words = transcript.split()
    if len(words) > MAX_TRANSCRIPT_WORDS:
        transcript = " ".join(words[:MAX_TRANSCRIPT_WORDS]) + "\n[truncated]"
        log.info("  Hard-capped transcript to %d words", MAX_TRANSCRIPT_WORDS)

    prompt = EXTRACT_USER_TMPL.format(
        scaffold_context=scaffold_context,
        title=video["title"],
        channel=video["channel"],
        duration=video["duration_raw"],
        transcript=transcript,
    )

    vid_id = video["video_id"]
    for attempt in range(1, 4):
        try:
            log.info("  [%s] extraction attempt %d/3", vid_id, attempt)
            tok_limit = MAX_EXTRACT_TOKENS_SHORT if is_short else MAX_EXTRACT_TOKENS
            resp = _require_client().chat.completions.create(
                model=MODEL,
                messages=[
                    {"role": "system", "content": EXTRACT_SYSTEM},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.1,
                max_tokens=tok_limit,
            )
            raw = (resp.choices[0].message.content or "").strip()
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
            # Tag each issue with its source
            for issue in issues:
                issue["source_video_id"] = vid_id
                issue["source_title"] = video["title"]
                issue["source_channel"] = video.get("channel", "")
            log.info("  [%s] extracted %d issues", vid_id, len(issues))
            return issues
        except json.JSONDecodeError as e:
            log.warning("  [%s] JSON parse error attempt %d: %s", vid_id, attempt, e)
        except Exception as e:
            log.warning("  [%s] API error attempt %d: %s", vid_id, attempt, e)
        if attempt < 3:
            time.sleep(5 * attempt)

    log.error("  [%s] all attempts failed", vid_id)
    return []


# ── Batched extraction for short transcripts ─────────────────────────────────

BATCH_WORD_LIMIT = 2500  # max combined words for a batched API call

EXTRACT_BATCH_USER_TMPL = """\
=== VEHICLE REFERENCE ===
{scaffold_context}

=== TASK ===
Extract genuine design/manufacturing defects from each video transcript below.
One JSON object per distinct issue. Return a single JSON array covering ALL videos.

Schema per issue:
{{
  "issue_id": "snake_case (e.g. pcv_diaphragm_tear)",
  "label": "max 7 words",
  "system_component": "engine|gearbox|cooling|electrical|suspension|exhaust|brakes|fuel|body|other",
  "affected_engines": ["scaffold codes e.g. 1.6_TDI, 1.4_TSI — never 'all' unless truly universal"],
  "onset_km_range": "e.g. 80k-150k km or null",
  "symptom": "one sentence — what driver notices",
  "cause": "root cause if stated, else null",
  "fix": "repair/workaround if stated, else null",
  "source_video_id": "the video_id from the header above"
}}

Rules:
- affected_engines: use specific codes from the vehicle reference above
- Skip issues framed as driver error or neglected maintenance
- Return [] if no genuine defects are mentioned in any video

{video_sections}
"""


def extract_issues_batched(videos: list[dict], scaffold_context: str) -> list[dict]:
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

    prompt = EXTRACT_BATCH_USER_TMPL.format(
        scaffold_context=scaffold_context,
        video_sections="\n\n".join(sections),
    )

    vid_ids = [v["video_id"] for v in videos]
    log.info("  Batched extraction: %d videos (%s)", len(videos), ", ".join(vid_ids))

    for attempt in range(1, 4):
        try:
            log.info("  [batch] extraction attempt %d/3", attempt)
            resp = _require_client().chat.completions.create(
                model=MODEL,
                messages=[
                    {"role": "system", "content": EXTRACT_SYSTEM},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.1,
                max_tokens=MAX_EXTRACT_TOKENS,
            )
            raw = (resp.choices[0].message.content or "").strip()
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
                    issue["source_title"] = video_lookup[vid]["title"]
                    issue["source_channel"] = video_lookup[vid].get("channel", "")
                elif not issue.get("source_video_id"):
                    # If LLM didn't tag it, assign to first video in batch
                    issue["source_video_id"] = videos[0]["video_id"]
                    issue["source_title"] = videos[0]["title"]
                    issue["source_channel"] = videos[0].get("channel", "")
            log.info("  [batch] extracted %d issues from %d videos", len(issues), len(videos))
            return issues
        except json.JSONDecodeError as e:
            log.warning("  [batch] JSON parse error attempt %d: %s", attempt, e)
        except Exception as e:
            log.warning("  [batch] API error attempt %d: %s", attempt, e)
        if attempt < 3:
            time.sleep(5 * attempt)

    log.error("  [batch] all attempts failed")
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
- Let the model decide affected_years from explicit evidence in raw issues.
- Do not force pre/post cohort labels or infer missing year ranges.

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
  "source_videos": [
    {{"video_id": "...", "title": "..."}}
  ],
  "source": "youtube",
  "data_quality": "low|medium|high",
  "notes": "any caveats or null"
}}

Return the full array, sorted by mention_count descending.
"""


def _consolidate_batch(batch: list[dict], scaffold_context: str, n_videos: int, label: str) -> list[dict]:
    """Consolidate a single batch of raw issues. Returns merged list or original batch on failure."""
    raw_json = json.dumps(batch, ensure_ascii=False, indent=1)
    prompt = CONSOLIDATE_USER_TMPL.format(
        scaffold_context=scaffold_context,
        n_videos=n_videos,
        n_issues=len(batch),
        raw_issues_json=raw_json,
    )
    for attempt in range(1, 4):
        try:
            log.info("  [%s] consolidation attempt %d/3 (%d issues)...", label, attempt, len(batch))
            resp = _require_client().chat.completions.create(
                model=MODEL,
                messages=[
                    {"role": "system", "content": CONSOLIDATE_SYSTEM},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.1,
                max_tokens=CONSOLIDATE_TOKENS,
            )
            raw = (resp.choices[0].message.content or "").strip()
            if not raw:
                raise ValueError("Empty model response")
            if raw.startswith("```"):
                raw = raw.split("```", 2)[1]
                if raw.startswith("json"):
                    raw = raw[4:]
                raw = raw.strip()
            result = json.loads(raw)
            if not isinstance(result, list):
                result = [result]
            log.info("  [%s] → %d merged issues", label, len(result))
            return result
        except json.JSONDecodeError as e:
            log.warning("  [%s] JSON parse error attempt %d: %s", label, attempt, e)
        except Exception as e:
            log.warning("  [%s] API error attempt %d: %s", label, attempt, e)
        if attempt < 3:
            time.sleep(8 * attempt)
    log.error("  [%s] consolidation failed — keeping raw", label)
    return batch


def consolidate_issues(all_raw: list[dict], scaffold_context: str, n_videos: int) -> list[dict]:
    """
    Batch consolidation to stay within DeepSeek's output token limit:
      1. Consolidate in batches of CONSOLIDATE_BATCH
      2. Final merge on the reduced set
    """
    # Pass 2a: consolidate in batches
    batch_results: list[dict] = []
    for i in range(0, len(all_raw), CONSOLIDATE_BATCH):
        chunk = all_raw[i: i + CONSOLIDATE_BATCH]
        label = f"batch[{i}:{i+len(chunk)}]"
        merged = _consolidate_batch(chunk, scaffold_context, n_videos, label)
        batch_results.extend(merged)

    log.info("After batch consolidation: %d issues (was %d)", len(batch_results), len(all_raw))

    # Pass 2b: final merge (now a smaller set)
    if len(batch_results) <= CONSOLIDATE_BATCH:
        final = _consolidate_batch(batch_results, scaffold_context, n_videos, "final")
    else:
        final = []
        for i in range(0, len(batch_results), CONSOLIDATE_BATCH):
            chunk = batch_results[i: i + CONSOLIDATE_BATCH]
            merged = _consolidate_batch(chunk, scaffold_context, n_videos, f"final[{i}]")
            final.extend(merged)

    final.sort(key=lambda x: x.get("mention_count", 0), reverse=True)
    log.info("Consolidation complete — %d final issues", len(final))
    return final


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Extract issue knowledge from YouTube transcripts")
    parser.add_argument("--slug", default="vw_golf_mk7", help="Car model slug matching the raw JSON filename")
    parser.add_argument("--skip-consolidation", action="store_true", help="Skip pass 2 (useful for debugging pass 1)")
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
    # Resume from cache if available
    if pass1_cache.exists():
        with open(pass1_cache, encoding="utf-8") as f:
            all_raw = json.load(f)
        done_ids = {r["source_video_id"] for r in all_raw}
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
    # Process long videos one at a time
    for i, video in enumerate(long_remaining, 1):
        log.info("Pass 1 [%d/%d] %s — %s", i, len(long_remaining), video["video_id"], video["title"][:60])
        segments = video.get("transcript_segments", [])
        if not triage_video(segments):
            skipped_triage += 1
            continue
        issues = extract_issues_from_video(video, scaffold_context)
        all_raw.extend(issues)
        # Save cache after each video
        with open(pass1_cache, "w", encoding="utf-8") as f:
            json.dump(all_raw, f, ensure_ascii=False, indent=2)

    # Process Shorts in batches
    if short_remaining:
        log.info("Pass 1 — batching %d Shorts...", len(short_remaining))
        batch: list[dict] = []
        batch_words = 0
        for video in short_remaining:
            text = video.get("transcript_text", "")
            wc = len(text.split()) if text else 0
            if batch and batch_words + wc > BATCH_WORD_LIMIT:
                issues = extract_issues_batched(batch, scaffold_context)
                all_raw.extend(issues)
                with open(pass1_cache, "w", encoding="utf-8") as f:
                    json.dump(all_raw, f, ensure_ascii=False, indent=2)
                batch = []
                batch_words = 0
            batch.append(video)
            batch_words += wc
        if batch:
            issues = extract_issues_batched(batch, scaffold_context)
            all_raw.extend(issues)
            with open(pass1_cache, "w", encoding="utf-8") as f:
                json.dump(all_raw, f, ensure_ascii=False, indent=2)

    if skipped_triage:
        log.info("Pass 1 triaged out %d low-relevance videos", skipped_triage)
    log.info("Pass 1 complete — %d raw issues from %d videos", len(all_raw), len(videos))

    consolidation_ok = False
    if args.skip_consolidation:
        log.info("Skipping consolidation (--skip-consolidation)")
        final = all_raw
    else:
        # ── Pass 2 ────────────────────────────────────────────────────────────
        final = consolidate_issues(all_raw, scaffold_context, n_videos=len(videos))
        consolidation_ok = final is not all_raw  # True if we got a new merged list

    save_outputs(final, out_json, out_csv)

    # Only clean up pass-1 cache if consolidation actually succeeded
    if pass1_cache.exists() and consolidation_ok:
        pass1_cache.unlink()
        log.info("Removed pass-1 cache")

    log.info("Done — %d final issues written", len(final))


if __name__ == "__main__":
    main()
