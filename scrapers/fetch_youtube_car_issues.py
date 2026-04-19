import argparse
import json
import logging
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from typing import cast

import requests
import yt_dlp
from tqdm import tqdm

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scrapers.fetch_youtube_transcripts import search_youtube_videos
from scripts.extract_youtube_issues import load_scaffold
from scripts.trim_balance import downsample_performance_videos

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)

# Broad, model-level query templates. These surface general ownership and
# mechanic content without presupposing any specific issue.
_QUERY_TEMPLATES_EN = [
    "{car} chronic issues",
    "{car} chronic problems",
    "{car} known faults",
]

_QUERY_TEMPLATES_TR = [
    "{car} kronik sorunları",
    "{car} kronik arızaları",
]

_MECHANIC_SIGNALS_EN = (
    "mechanic",
    "workshop",
    "garage",
    "specialist",
    "independent",
    "inspection",
    "diagnostic",
    "diagnosis",
    "teardown",
    "technician",
    "master tech",
    "ownership",
    "owner review",
    "daily driver",
    "long term",
    "long term ownership",
    "family car",
    "known faults",
    "common faults",
    "buyers guide",
    "buyer's guide",
    "what to look for",
    "what goes wrong",
)

_MECHANIC_SIGNALS_TR = (
    "usta",
    "tamir",
    "servis",
    "bakım",
    "garaj",
    "mekanik",
    "atölye",
    "kronik",
    "sorun",
    "ariza",
    "arıza",
    "kullanıcı",
    "inceleme",
    "alınır mı",
    "alinir mi",
    "neden alınmaz",
    "neden alinmaz",
)

_LIST_FORMAT_SIGNALS_EN = (
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

_LIST_FORMAT_SIGNALS_TR = (
    "alınır mı",
    "alinir mi",
    "kronik sorunlar",
    "dikkat edilmesi gerekenler",
    "neden alınmaz",
    "neden alinmaz",
    "problemleri",
    "şikayetleri",
)

# Global variables that will be swapped based on language
_QUERY_TEMPLATES = _QUERY_TEMPLATES_EN
_MECHANIC_SIGNALS = _MECHANIC_SIGNALS_EN
_LIST_FORMAT_SIGNALS = _LIST_FORMAT_SIGNALS_EN

# Entertainment / hype markers — videos that rarely contain owner-grade
# fault evidence. Only reject when the title shows NO fault/ownership signal.
_HYPE_SIGNALS_EN = (
    "drag race",
    " vs ",
    " vs. ",
    "0-60",
    "0 to 60",
    "top speed",
    "stage 1",
    "stage 2",
    "stage 3",
    "tuned",
    "modified",
    "dyno",
    "acceleration",
    "launch control",
    "remap",
)

_HYPE_SIGNALS_TR = (
    "yarış",
    "hız testi",
    "0-100",
    "modifiye",
    "yazılım",
    "drag",
    "kapışma",
    "hızlanma",
)

# If any of these appear we keep the video even if hype markers also match.
_FAULT_OR_OWNERSHIP_SIGNALS_EN = (
    "problem",
    "issue",
    "fault",
    "break",
    "broken",
    "failure",
    "failed",
    "fix",
    "repair",
    "leak",
    "noise",
    "rattle",
    "diagnos",
    "ownership",
    "owner review",
    "daily driver",
    "long term",
    "long-term",
    "miles review",
    "miles ownership",
    "years later",
    "after \u2026 miles",
    "buyer's guide",
    "buyers guide",
    "should you buy",
    "reliability",
    "everything you need to know",
    "known problems",
    "common problems",
)

_FAULT_OR_OWNERSHIP_SIGNALS_TR = (
    "sorun",
    "arıza",
    "ariza",
    "problem",
    "tamir",
    "bakım",
    "kronik",
    "şikayet",
    "sikayet",
    "kullanıcı yorumu",
    "uzun kullanım",
    "neden alınmaz",
    "neden alinmaz",
    "alınır mı",
    "alinir mi",
    "neleri bozulur",
    "masraf",
    "eksikleri",
)

# Global variables that will be swapped based on language
_QUERY_TEMPLATES = _QUERY_TEMPLATES_EN
_MECHANIC_SIGNALS = _MECHANIC_SIGNALS_EN
_LIST_FORMAT_SIGNALS = _LIST_FORMAT_SIGNALS_EN
_HYPE_SIGNALS = _HYPE_SIGNALS_EN
_FAULT_OR_OWNERSHIP_SIGNALS = _FAULT_OR_OWNERSHIP_SIGNALS_EN


def _title_blob(video: dict) -> str:
    return f"{video.get('title', '')} {video.get('channel', '')}".lower()


def _has_signal(blob: str, signals: tuple[str, ...]) -> bool:
    return any(sig in blob for sig in signals)


# ── Cross-brand title filter ────────────────────────────────────────────────
# YouTube's search results sometimes surface videos from a different OEM that
# happen to rank for the query (e.g. a Ford 1.0 EcoBoost teardown matching a
# "Renault Clio chronic issues" search). These contaminate the transcript
# corpus with wrong-brand engine wording that the LLM then absorbs. We drop
# any video whose title mentions a foreign OEM or a foreign engine-family
# token *and* doesn't mention the target make/model from the scaffold.
_BRAND_GROUPS: list[set[str]] = [
    {"vw", "volkswagen", "audi", "seat", "skoda", "cupra", "porsche", "bentley"},
    {"renault", "dacia", "nissan", "infiniti", "mitsubishi"},
    {"ford", "lincoln"},
    {"toyota", "lexus", "subaru"},
    {"honda", "acura"},
    {"hyundai", "kia", "genesis"},
    {"peugeot", "citroen", "citroën", "opel", "vauxhall", "fiat",
     "alfa", "lancia", "chrysler", "dodge", "jeep", "ram", "maserati", "ds"},
    {"bmw", "mini"},
    {"mercedes", "mercedes-benz", "smart"},
    {"volvo", "polestar"},
    {"mazda"},
    {"tesla"},
    {"jaguar", "land rover", "range rover"},
]
_FOREIGN_ENGINE_TOKENS: dict[str, set[str]] = {
    "ford":     {"ecoboost", "duratec", "duratorq"},
    "bmw":      {"n20", "n47", "n54", "n55", "b48", "b58"},
    "toyota":   {"2ar-fe", "1zz", "2zz"},
    "honda":    {"k20", "k24"},
    "peugeot":  {"puretech", "hdi", "bluehdi"},
    "mazda":    {"skyactiv"},
    "mercedes": {"cdi", "bluetec"},
    "vw":       {"tsi", "tdi", "tfsi"},
}


def _scaffold_allowed_brand_group(scaffold: dict) -> set[str]:
    make = ((scaffold or {}).get("meta") or {}).get("make", "").lower().strip()
    if not make:
        return set()
    for group in _BRAND_GROUPS:
        if make in group:
            return group
    return {make}


def _scaffold_target_tokens(scaffold: dict) -> list[str]:
    """Tokens the target video title must contain (any one) to be considered
    on-topic. Derived from scaffold make + model (split on whitespace) plus
    every engine family code and displacement code declared in the scaffold.

    Engine-code hits let mechanic-niche videos through even when the title
    doesn't name the make/model (e.g. "EA888 2.0 TSI teardown" for a Golf Mk7).
    Displacement codes like "1.4_TSI" are expanded to variants the title might
    use (e.g. "1.4 tsi", "1.4tsi").
    """
    meta = (scaffold or {}).get("meta") or {}
    make = str(meta.get("make", "")).lower().strip()
    model = str(meta.get("model", "")).lower().strip()
    toks: list[str] = []
    if make:
        toks.append(make)
    for part in re.split(r"\s+", model):
        part = part.strip()
        if part and len(part) >= 2:
            toks.append(part)

    for ef in scaffold.get("engine_families") or []:
        fam = str(ef.get("code", "")).strip().lower()
        if fam and len(fam) >= 3:
            toks.append(fam)
        for d in ef.get("displacements") or []:
            code = d.get("code") if isinstance(d, dict) else d
            code = str(code or "").strip().lower()
            if not code:
                continue
            # "1.4_tsi" → also accept "1.4 tsi", "1.4tsi"
            toks.append(code.replace("_", " "))
            toks.append(code.replace("_", ""))
    # dedup while preserving order
    seen: set[str] = set()
    out: list[str] = []
    for t in toks:
        if t not in seen:
            seen.add(t)
            out.append(t)
    return out


def cross_brand_title_filter(
    videos: list[dict], scaffold: dict
) -> tuple[list[dict], list[dict]]:
    """On-topic title gate. A video is accepted only when its title mentions
    the scaffold target (make, model, engine-family code, or displacement
    code). Otherwise rejected — tagged as `foreign_brand:*` / `foreign_engine:*`
    when a competing OEM is named, else `off_topic_title`.

    This is cheaper than transcript-level validation: no transcript fetch,
    no LLM call. No-op when scaffold has no meta.
    """
    allowed = _scaffold_allowed_brand_group(scaffold)
    targets = _scaffold_target_tokens(scaffold)
    if not allowed or not targets:
        return videos, []

    accepted: list[dict] = []
    rejected: list[dict] = []
    for v in videos:
        title = str(v.get("title", "")).lower()
        if not title:
            accepted.append(v)
            continue

        if any(re.search(r"\b" + re.escape(t) + r"\b", title) for t in targets):
            accepted.append(v)
            continue

        # No target mention → reject. Classify the reason for audit.
        reason: str = "off_topic_title"
        for group in _BRAND_GROUPS:
            if group == allowed:
                continue
            for brand in group:
                if re.search(r"\b" + re.escape(brand) + r"\b", title):
                    reason = f"foreign_brand:{brand}"
                    break
            if reason != "off_topic_title":
                break
        if reason == "off_topic_title":
            for brand, tokens in _FOREIGN_ENGINE_TOKENS.items():
                if brand in allowed:
                    continue
                for tok in tokens:
                    if re.search(r"\b" + re.escape(tok) + r"\b", title):
                        reason = f"foreign_engine:{tok}"
                        break
                if reason != "off_topic_title":
                    break

        v["prefilter_reason"] = reason
        rejected.append(v)
    return accepted, rejected


def relevancy_prefilter(
    videos: list[dict],
    viral_list_view_threshold: int = 1_500_000,
) -> tuple[list[dict], list[dict]]:
    """
    Split candidates into (accepted, rejected) based on content signals.

    Model-agnostic rules only — trim/variant filters belong in scaffolds.

    Rules:
      1. Always accept if the video reads as niche mechanic content.
      2. Reject viral list-format videos (buyer's guide / common problems)
         whose view count is above `viral_list_view_threshold`. These are the
         curated-enumeration videos that inflate mention_count.
      3. Reject hype/entertainment videos with no fault or ownership signal.
      4. Otherwise accept.
    """
    accepted: list[dict] = []
    rejected: list[dict] = []

    for video in videos:
        blob = _title_blob(video)
        view_count = video.get("view_count_raw")

        is_list_format = _has_signal(blob, _LIST_FORMAT_SIGNALS)
        if (
            is_list_format
            and isinstance(view_count, int)
            and view_count > viral_list_view_threshold
        ):
            video["prefilter_reason"] = "viral_list_format"
            rejected.append(video)
            continue

        if _is_mechanic_niche(video):
            accepted.append(video)
            continue

        if _has_signal(blob, _HYPE_SIGNALS) and not _has_signal(
            blob, _FAULT_OR_OWNERSHIP_SIGNALS
        ):
            video["prefilter_reason"] = "hype_no_fault_signal"
            rejected.append(video)
            continue

        accepted.append(video)

    return accepted, rejected


def _get_video_type_category(video: dict) -> str:
    title = str(video.get("title", "")).lower()
    if any(sig in title for sig in _LIST_FORMAT_SIGNALS):
        return "list_format"
    return "organic"

_YDL_BASE_OPTS = {
    "quiet": True,
    "no_warnings": True,
    "skip_download": True,
    "extractor_args": {"youtube": {"player_client": ["web", "android"]}},
}
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}


def _parse_json3(url: str, video_id: str) -> dict[str, Any]:
    """Fetch and parse a YouTube JSON3 subtitle URL into segments."""
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=20)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        logging.warning(f"Failed to fetch/parse subtitle URL for {video_id}: {e}")
        return {"status": "error", "segments": [], "text": ""}

    segments = []
    for event in data.get("events", []):
        segs = event.get("segs")
        if not segs:
            continue
        text = "".join(s.get("utf8", "") for s in segs).strip()
        if not text or text == "\n":
            continue
        start = event.get("tStartMs", 0) / 1000.0
        dur = event.get("dDurationMs", 0) / 1000.0
        segments.append({"text": text, "start": start, "duration": dur})

    if not segments:
        return {"status": "error", "segments": [], "text": ""}
    return {
        "status": "ok",
        "segments": segments,
        "text": "\n".join(s["text"] for s in segments),
    }


def fetch_transcript_structured(
    video_id: str,
    cookies_file: str | None = None,
    target_lang: str = "en",
) -> dict[str, Any]:
    """
    Fetch transcript via yt-dlp (web client, android fallback for bot detection).

    Returns:
        {
            "status": "ok" | "no_english" | "disabled" | "error",
            "video_language": str | None,
            "segments": [...],
            "text": str
        }
    """
    opts = dict(_YDL_BASE_OPTS)
    if cookies_file:
        opts["cookiefile"] = cookies_file

    url = f"https://www.youtube.com/watch?v={video_id}"
    try:
        with yt_dlp.YoutubeDL(cast(Any, opts)) as ydl:
            info = ydl.extract_info(url, download=False)
        if not info:
            return {
                "status": "error",
                "video_language": None,
                "segments": [],
                "text": "",
            }

        video_lang = info.get("language") or ""

        if video_lang and not video_lang.lower().startswith(target_lang):
            logging.info(
                f"Skipping {video_id}: video language is '{video_lang}' (want '{target_lang}')"
            )
            return {
                "status": "no_english",
                "video_language": video_lang,
                "segments": [],
                "text": "",
            }

        target_langs = [target_lang, f"{target_lang}-US", f"{target_lang}-GB"]
        for source in [info.get("subtitles", {}), info.get("automatic_captions", {})]:
            for lang in target_langs:
                formats = source.get(lang, [])
                if not formats:
                    continue
                sub_url = next(
                    (f["url"] for f in formats if f.get("ext") == "json3"), None
                )
                if not sub_url:
                    sub_url = formats[0].get("url")
                if sub_url:
                    result = _parse_json3(sub_url, video_id)
                    result["video_language"] = video_lang or target_lang
                    return result

        all_sub_langs = set(info.get("subtitles", {}).keys()) | set(
            info.get("automatic_captions", {}).keys()
        )
        if all_sub_langs and not any(l.startswith(target_lang) for l in all_sub_langs):
            return {
                "status": "no_english",
                "video_language": video_lang or "unknown",
                "segments": [],
                "text": "",
            }

        return {
            "status": "disabled",
            "video_language": video_lang or None,
            "segments": [],
            "text": "",
        }

    except Exception as e:
        logging.warning(f"Could not fetch transcript for {video_id}: {e}")
        return {"status": "error", "video_language": None, "segments": [], "text": ""}


def build_queries(car_label: str) -> list[str]:
    """Generate broad, model-level search queries from templates."""
    return [t.format(car=car_label) for t in _QUERY_TEMPLATES]


def collect_videos(
    car_label: str,
    candidates_per_query: int = 15,
) -> dict[str, dict]:
    """
    Search YouTube with broad model-level queries and deduplicate results.

    Returns dict[video_id -> video_dict]. Each video tracks which queries
    surfaced it (for provenance, not for topic assignment).
    """
    queries = build_queries(car_label)
    candidates: dict[str, dict] = {}

    for query in queries:
        results = search_youtube_videos(query, max_results=candidates_per_query)
        for video in results:
            vid_id = video["video_id"]
            if not vid_id:
                continue
            if vid_id in candidates:
                candidates[vid_id]["matched_queries"].append(query)
            else:
                candidates[vid_id] = {**video, "matched_queries": [query]}

    logging.info(
        f"Collected {len(candidates)} unique candidates from {len(queries)} queries"
    )
    return candidates


def _coerce_view_count(value: Any) -> int | None:
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        digits = re.sub(r"\D", "", value)
        if digits:
            return int(digits)
    return None


def _is_mechanic_niche(video: dict) -> bool:
    title = str(video.get("title", ""))
    channel = str(video.get("channel", ""))
    blob = f"{title} {channel}".lower()
    return any(signal in blob for signal in _MECHANIC_SIGNALS)


def _view_count_score(view_count: int | None) -> int:
    """Higher views = more credible signal (engagement, reach, corroboration)."""
    if view_count is None:
        return 0
    if view_count >= 3_000_000:
        return 4
    if view_count >= 1_000_000:
        return 3
    if view_count >= 500_000:
        return 2
    if view_count >= 200_000:
        return 1
    return 0


def filter_and_rank_candidates(
    candidates: dict[str, dict],
    min_seconds: int = 480,
    min_views: int | None = 80_000,
    enable_prefilter: bool = True,
) -> tuple[list[dict], list[dict]]:
    """
    Keep candidates above min_seconds and min_views, rank by credibility.

    Ranking prefers:
      1) mechanic/workshop-style content
      2) videos surfaced by multiple broad model-level queries
      3) higher view counts (views = engagement / corroboration signal)
      4) longer duration as a weak tie-breaker

    If min_views is set, videos below that threshold are dropped. If that
    would drop every candidate, the floor is relaxed and we fall back to
    ranking-only.
    """
    filtered: list[dict] = []
    for video in candidates.values():
        secs = video.get("duration_seconds")
        if secs is None or secs < min_seconds:
            continue
        view_count_raw = _coerce_view_count(
            video.get("view_count_raw", video.get("view_count"))
        )
        video["view_count_raw"] = view_count_raw
        filtered.append(video)

    if min_views is not None:
        gated = [
            v
            for v in filtered
            if v.get("view_count_raw") is None or v["view_count_raw"] >= min_views
        ]
        if gated:
            dropped = len(filtered) - len(gated)
            if dropped:
                logging.info(
                    f"Applied min view floor ({min_views:,}): dropped {dropped} low-view videos"
                )
            filtered = gated
        else:
            logging.warning(
                f"No videos above min view floor ({min_views:,}); falling back to ranking-only"
            )

    rejected: list[dict] = []
    if enable_prefilter:
        filtered, rejected = relevancy_prefilter(filtered)
        if rejected:
            reasons: dict[str, int] = {}
            for r in rejected:
                reasons[r.get("prefilter_reason", "unknown")] = (
                    reasons.get(r.get("prefilter_reason", "unknown"), 0) + 1
                )
            reason_str = ", ".join(f"{k}={v}" for k, v in sorted(reasons.items()))
            logging.info(
                f"Pre-filter rejected {len(rejected)}/{len(filtered) + len(rejected)} "
                f"candidates ({reason_str})"
            )

    for video in filtered:
        query_hits = len(video.get("matched_queries", []))
        mechanic_bonus = 4 if _is_mechanic_niche(video) else 0
        views_bonus = _view_count_score(video.get("view_count_raw"))
        video["selection_score"] = (query_hits * 2) + mechanic_bonus + views_bonus
        video["is_niche_mechanic_candidate"] = mechanic_bonus > 0

    filtered.sort(
        key=lambda v: (
            int(v.get("selection_score", 0)),
            len(v.get("matched_queries", [])),
            int(v["view_count_raw"]) if v.get("view_count_raw") is not None else 0,
            int(v.get("duration_seconds") or 0),
        ),
        reverse=True,
    )
    return filtered, rejected


def scrape_car_issues(
    car_label: str,
    slug: str | None = None,
    max_videos: int = 30,
    min_duration_seconds: int = 120,
    candidates_per_query: int = 15,
    min_view_count: int | None = 80_000,
    enable_prefilter: bool = True,
    out_dir: Path | None = None,
    cookies_file: str | None = None,
    request_delay: float = 2.0,
    target_lang: str = "en",
) -> Path:
    """
    Full pipeline for one car model:
      1. collect_videos → broad model-level search, deduplicated
      2. filter_and_rank_candidates → prioritize niche mechanic videos,
         de-prioritize mainstream high-view videos
      3. fetch_transcript_structured for selected videos
      4. Write structured JSON output
    """
    global _QUERY_TEMPLATES, _MECHANIC_SIGNALS, _LIST_FORMAT_SIGNALS
    global _HYPE_SIGNALS, _FAULT_OR_OWNERSHIP_SIGNALS

    if target_lang == "tr":
        _QUERY_TEMPLATES = _QUERY_TEMPLATES_TR
        _MECHANIC_SIGNALS = _MECHANIC_SIGNALS_TR
        _LIST_FORMAT_SIGNALS = _LIST_FORMAT_SIGNALS_TR
        _HYPE_SIGNALS = _HYPE_SIGNALS_TR
        _FAULT_OR_OWNERSHIP_SIGNALS = _FAULT_OR_OWNERSHIP_SIGNALS_TR
    else:
        _QUERY_TEMPLATES = _QUERY_TEMPLATES_EN
        _MECHANIC_SIGNALS = _MECHANIC_SIGNALS_EN
        _LIST_FORMAT_SIGNALS = _LIST_FORMAT_SIGNALS_EN
        _HYPE_SIGNALS = _HYPE_SIGNALS_EN
        _FAULT_OR_OWNERSHIP_SIGNALS = _FAULT_OR_OWNERSHIP_SIGNALS_EN

    slug = slug or car_label.lower().replace(" ", "_")

    out_dir = out_dir or (ROOT / "data" / "raw" / "videos")
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{slug}_raw.json"

    logging.info(f"Collecting candidates for '{car_label}'...")
    candidates = collect_videos(car_label, candidates_per_query)

    qualifying, rejected = filter_and_rank_candidates(
        candidates,
        min_duration_seconds,
        min_views=min_view_count,
        enable_prefilter=enable_prefilter,
    )

    # Scaffold-driven performance-trim balancing. No-op when the scaffold does
    # not declare a ``performance_trims`` block, so this generalises to any
    # model without model-specific scraper logic.
    try:
        scaffold = load_scaffold(slug)
    except Exception as e:
        logging.info(f"No scaffold loaded for '{slug}' ({e}); skipping trim balancing")
        scaffold = {}

    # Cross-brand title filter — drops foreign-OEM videos that leaked through
    # YouTube's search ranking for the target query.
    qualifying, cross_brand_rejected = cross_brand_title_filter(qualifying, scaffold)
    if cross_brand_rejected:
        reasons: dict[str, int] = {}
        for r in cross_brand_rejected:
            reasons[r.get("prefilter_reason", "unknown")] = (
                reasons.get(r.get("prefilter_reason", "unknown"), 0) + 1
            )
        logging.info(
            f"Cross-brand title filter rejected {len(cross_brand_rejected)} videos "
            f"({', '.join(f'{k}={v}' for k, v in sorted(reasons.items()))})"
        )
        rejected.extend(cross_brand_rejected)

    qualifying = downsample_performance_videos(qualifying, scaffold)

    selected = qualifying[:max_videos]

    if rejected:
        rejected_path = out_dir / f"{slug}_rejected.json"
        with open(rejected_path, "w", encoding="utf-8") as f:
            json.dump(
                [
                    {
                        "video_id": r.get("video_id"),
                        "title": r.get("title", ""),
                        "channel": r.get("channel", ""),
                        "view_count_raw": r.get("view_count_raw"),
                        "duration_seconds": r.get("duration_seconds"),
                        "prefilter_reason": r.get("prefilter_reason"),
                        "matched_queries": r.get("matched_queries", []),
                    }
                    for r in rejected
                ],
                f,
                ensure_ascii=False,
                indent=2,
            )
        logging.info(f"Wrote {len(rejected)} rejected candidates → {rejected_path}")
    logging.info(
        f"Selected {len(selected)} videos (from {len(qualifying)} qualifying, "
        f"{len(candidates)} total candidates)"
    )

    logging.info(f"Fetching transcripts for {len(selected)} videos...")
    videos_out = []
    for i, video in enumerate(tqdm(selected, desc="Fetching transcripts")):
        vid_id = video["video_id"]
        if i > 0 and request_delay > 0:
            time.sleep(request_delay)
        transcript = fetch_transcript_structured(
            vid_id, cookies_file=cookies_file, target_lang=target_lang
        )
        videos_out.append(
            {
                "video_id": vid_id,
                "url": f"https://www.youtube.com/watch?v={vid_id}",
                "title": video.get("title", ""),
                "channel": video.get("channel", ""),
                "matched_queries": video.get("matched_queries", []),
                "duration_raw": video.get("duration", ""),
                "duration_seconds": video["duration_seconds"],
                "view_count": video.get("view_count", ""),
                "view_count_raw": video.get("view_count_raw"),
                "selection_score": video.get("selection_score"),
                "is_niche_mechanic_candidate": video.get(
                    "is_niche_mechanic_candidate", False
                ),
                "video_type_category": _get_video_type_category(video),
                "video_language": transcript.get("video_language"),
                "transcript_status": transcript["status"],
                "transcript_text": transcript["text"],
                "transcript_segments": transcript["segments"],
            }
        )

    total_ok = sum(1 for v in videos_out if v["transcript_status"] == "ok")
    skipped_lang = [v for v in videos_out if v["transcript_status"] == "no_english"]
    if skipped_lang:
        logging.info(
            f"Skipped {len(skipped_lang)} non-English videos: "
            + ", ".join(
                f"{v['title'][:40]} ({v['video_language']})" for v in skipped_lang
            )
        )

    output = {
        "meta": {
            "car_model": car_label,
            "slug": slug,
            "scraped_at": datetime.now(timezone.utc).isoformat(),
            "queries": build_queries(car_label),
            "total_videos": len(videos_out),
            "total_with_transcript": total_ok,
            "duration_filter_seconds": min_duration_seconds,
            "min_view_count": min_view_count,
            "prefilter_enabled": enable_prefilter,
            "rejected_candidates": len(rejected),
            "selection_strategy": "mechanic_niche_plus_low_view_count_plus_relevancy_prefilter",
        },
        "videos": videos_out,
    }

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    logging.info(
        f"Saved {len(videos_out)} videos ({total_ok} with transcripts) → {out_path}"
    )
    return out_path


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Scrape YouTube transcripts for car issue discovery (broad model-level search)"
    )
    parser.add_argument(
        "--car",
        required=True,
        help='Car model label, e.g. "VW Golf MK7", "Renault Clio MK4"',
    )
    parser.add_argument(
        "--slug",
        default=None,
        help="Output slug (default: derived from --car). E.g. vw_golf_mk7",
    )
    parser.add_argument(
        "--max-videos",
        type=int,
        default=30,
        help="Max videos to fetch transcripts for (default: 30)",
    )
    parser.add_argument(
        "--min-duration",
        type=int,
        default=120,
        help="Min duration in seconds (default: 120)",
    )
    parser.add_argument("--candidates-per-query", type=int, default=15)
    parser.add_argument(
        "--min-views",
        type=int,
        default=80_000,
        help=(
            "Minimum view count to qualify (default: 80000). Views are treated "
            "as a credibility / engagement signal. If no candidates pass the "
            "floor, fallback uses soft ranking."
        ),
    )
    parser.add_argument(
        "--disable-prefilter",
        action="store_true",
        help="Disable the relevancy pre-filter (viral list-format / hype rejection).",
    )
    parser.add_argument(
        "--cookies-file",
        default=None,
        help="Path to Netscape cookies.txt — use if YouTube blocks transcript requests.",
    )
    parser.add_argument("--request-delay", type=float, default=2.0)
    parser.add_argument(
        "--lang",
        default="en",
        help="ISO 639-1 language prefix to require (default: en).",
    )
    args = parser.parse_args()

    scrape_car_issues(
        car_label=args.car,
        slug=args.slug,
        max_videos=args.max_videos,
        min_duration_seconds=args.min_duration,
        candidates_per_query=args.candidates_per_query,
        min_view_count=args.min_views,
        enable_prefilter=not args.disable_prefilter,
        cookies_file=args.cookies_file,
        request_delay=args.request_delay,
        target_lang=args.lang,
    )


if __name__ == "__main__":
    main()
