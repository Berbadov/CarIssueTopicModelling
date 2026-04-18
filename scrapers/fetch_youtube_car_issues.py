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

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)

# Broad, model-level query templates. These surface general ownership and
# mechanic content without presupposing any specific issue.
_QUERY_TEMPLATES = [
    "{car} problems",
    "{car} common issues",
    "{car} review",
    "{car} ownership experience",
    "{car} daily driver review",
    "{car} long term ownership",
    "{car} family car review",
    "{car} buyer's guide",
    "{car} things that break",
    "{car} reliability",
    "{car} mechanic workshop",
    "{car} long term review",
    "{car} what to look for",
    "{car} what goes wrong",
    "{car} known faults",
    "{car} mechanic review",
    "{car} workshop inspection",
    "{car} independent garage review",
]

_MECHANIC_SIGNALS = (
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

# Entertainment / hype markers — videos that rarely contain owner-grade
# fault evidence. Only reject when the title shows NO fault/ownership signal.
_HYPE_SIGNALS = (
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

# If any of these appear we keep the video even if hype markers also match.
_FAULT_OR_OWNERSHIP_SIGNALS = (
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
)


def _title_blob(video: dict) -> str:
    return f"{video.get('title', '')} {video.get('channel', '')}".lower()


def _has_signal(blob: str, signals: tuple[str, ...]) -> bool:
    return any(sig in blob for sig in signals)


def relevancy_prefilter(
    videos: list[dict],
    viral_list_view_threshold: int = 100_000,
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
    """Higher score means more niche / less mainstream."""
    if view_count is None:
        return 0
    if view_count <= 50_000:
        return 4
    if view_count <= 150_000:
        return 3
    if view_count <= 300_000:
        return 2
    if view_count <= 600_000:
        return 1
    if view_count <= 1_000_000:
        return 0
    if view_count <= 3_000_000:
        return -2
    return -4


def filter_and_rank_candidates(
    candidates: dict[str, dict],
    min_seconds: int = 480,
    max_views: int | None = 150_000,
    enable_prefilter: bool = True,
) -> tuple[list[dict], list[dict]]:
    """
    Keep candidates above min_seconds and rank toward niche mechanic videos.

    Ranking prefers:
      1) mechanic/workshop-style content
      2) videos surfaced by multiple broad model-level queries
      3) lower view counts (to drift away from mainstream/popular videos)
      4) longer duration as a weak tie-breaker

    If max_views is set, videos above that threshold are excluded when possible.
    If this would drop every candidate, cap is treated as a soft preference and
    we fall back to ranking without hard exclusion.
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

    if max_views is not None:
        capped = [
            v
            for v in filtered
            if v.get("view_count_raw") is None or v["view_count_raw"] <= max_views
        ]
        if capped:
            dropped = len(filtered) - len(capped)
            if dropped:
                logging.info(
                    f"Applied max view cap ({max_views:,}): dropped {dropped} high-view videos"
                )
            filtered = capped
        else:
            logging.warning(
                f"No videos under max view cap ({max_views:,}); using soft niche ranking fallback"
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
            -(
                int(v["view_count_raw"])
                if v.get("view_count_raw") is not None
                else 10**12
            ),
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
    max_view_count: int | None = 150_000,
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
    slug = slug or car_label.lower().replace(" ", "_")

    out_dir = out_dir or (ROOT / "data" / "raw" / "videos")
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{slug}_raw.json"

    logging.info(f"Collecting candidates for '{car_label}'...")
    candidates = collect_videos(car_label, candidates_per_query)

    qualifying, rejected = filter_and_rank_candidates(
        candidates,
        min_duration_seconds,
        max_views=max_view_count,
        enable_prefilter=enable_prefilter,
    )
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
            "max_view_count": max_view_count,
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
        "--max-views",
        type=int,
        default=150_000,
        help=(
            "Hard cap for view count to bias toward niche videos (default: 150000). "
            "If no candidates pass the cap, fallback uses soft ranking."
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
        max_view_count=args.max_views,
        enable_prefilter=not args.disable_prefilter,
        cookies_file=args.cookies_file,
        request_delay=args.request_delay,
        target_lang=args.lang,
    )


if __name__ == "__main__":
    main()
