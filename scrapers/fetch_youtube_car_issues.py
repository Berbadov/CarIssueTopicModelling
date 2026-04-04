import argparse
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tqdm import tqdm
from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api._errors import TranscriptsDisabled

from scrapers.fetch_youtube_transcripts import (
    _coerce_transcript_rows,
    search_youtube_videos,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
ROOT = Path(__file__).resolve().parent.parent

CAR_CONFIGS: dict[str, dict] = {
    "vw_golf_mk7": {
        "label": "VW Golf MK7",
        "slug": "vw_golf_mk7",
        "queries": [
            "VW Golf MK7 common problems",
            "Golf 7 reliability issues",
            "VW Golf MK7 known issues",
            "Golf MK7 chronic problems",
            "Volkswagen Golf 7 engine problems",
            "VW Golf MK7 what goes wrong",
        ],
    },
}


def parse_duration_to_seconds(duration_str: str) -> int | None:
    """Parse 'MM:SS' or 'H:MM:SS' duration string to total seconds."""
    try:
        parts = duration_str.strip().split(":")
        if len(parts) == 2:
            return int(parts[0]) * 60 + int(parts[1])
        if len(parts) == 3:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
    except (ValueError, AttributeError):
        pass
    return None


def fetch_transcript_structured(video_id: str) -> dict[str, Any]:
    """
    Fetch transcript with timestamps preserved.

    Returns:
        {
            "status": "ok" | "disabled" | "error",
            "segments": [{"text": str, "start": float, "duration": float}, ...],
            "text": str
        }
    """
    try:
        api = YouTubeTranscriptApi()
        if hasattr(api, "fetch"):
            raw = api.fetch(video_id, languages=["en"])
        else:
            raw = YouTubeTranscriptApi.get_transcript(video_id, languages=["en"])  # type: ignore[attr-defined]

        rows = _coerce_transcript_rows(raw)
        if not rows:
            return {"status": "error", "segments": [], "text": ""}

        segments = [
            {
                "text": str(r.get("text", "")).strip(),
                "start": float(r.get("start", 0.0)),
                "duration": float(r.get("duration", 0.0)),
            }
            for r in rows
            if isinstance(r.get("text"), str) and str(r.get("text", "")).strip()
        ]
        joined = "\n".join(s["text"] for s in segments)
        return {"status": "ok", "segments": segments, "text": joined}

    except TranscriptsDisabled:
        logging.warning(f"Transcripts disabled for {video_id}")
        return {"status": "disabled", "segments": [], "text": ""}
    except Exception as e:
        logging.warning(f"Could not fetch transcript for {video_id}: {e}")
        return {"status": "error", "segments": [], "text": ""}


def collect_candidate_videos(
    queries: list[str], candidates_per_query: int = 15
) -> dict[str, dict]:
    """
    Search each query and collect candidates, keyed by video_id.
    Duplicate video_ids accumulate matched_queries rather than being overwritten.
    """
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
    logging.info(f"Collected {len(candidates)} unique candidate videos across {len(queries)} queries")
    return candidates


def filter_by_duration(
    candidates: dict[str, dict], min_seconds: int = 600
) -> list[dict]:
    """
    Parse duration strings, drop candidates below min_seconds or unparseable.
    Returns list sorted by duration_seconds descending.
    """
    filtered = []
    dropped = 0
    for video in candidates.values():
        secs = parse_duration_to_seconds(video.get("duration", ""))
        if secs is None or secs < min_seconds:
            dropped += 1
            continue
        filtered.append({**video, "duration_seconds": secs})
    filtered.sort(key=lambda v: v["duration_seconds"], reverse=True)
    logging.info(
        f"Duration filter (>={min_seconds}s): {len(filtered)} passed, {dropped} dropped"
    )
    return filtered


def scrape_car_issues(
    car_model: str,
    top_n: int = 10,
    min_duration_seconds: int = 600,
    candidates_per_query: int = 15,
    out_dir: Path | None = None,
) -> Path:
    """
    Full pipeline for one car model:
      1. collect_candidate_videos
      2. filter_by_duration
      3. take top_n
      4. fetch_transcript_structured for each
      5. Write structured JSON
    """
    if car_model not in CAR_CONFIGS:
        raise ValueError(f"Unknown car model '{car_model}'. Available: {list(CAR_CONFIGS)}")

    config = CAR_CONFIGS[car_model]
    queries = config["queries"]
    slug = config["slug"]
    label = config["label"]

    out_dir = out_dir or (ROOT / "data" / "raw" / "videos")
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{slug}_raw.json"

    candidates = collect_candidate_videos(queries, candidates_per_query)
    qualifying = filter_by_duration(candidates, min_duration_seconds)

    if len(qualifying) < top_n:
        logging.warning(
            f"Only {len(qualifying)} videos passed duration filter — "
            f"returning all (requested {top_n})"
        )
    selected = qualifying[:top_n]
    logging.info(f"Fetching transcripts for {len(selected)} videos...")

    videos_out = []
    for video in tqdm(selected, desc="Fetching transcripts"):
        vid_id = video["video_id"]
        transcript = fetch_transcript_structured(vid_id)
        videos_out.append(
            {
                "video_id": vid_id,
                "url": f"https://www.youtube.com/watch?v={vid_id}",
                "title": video.get("title", ""),
                "channel": video.get("channel", ""),
                "duration_raw": video.get("duration", ""),
                "duration_seconds": video["duration_seconds"],
                "view_count": video.get("view_count", ""),
                "matched_queries": video.get("matched_queries", []),
                "transcript_status": transcript["status"],
                "transcript_text": transcript["text"],
                "transcript_segments": transcript["segments"],
            }
        )

    total_ok = sum(1 for v in videos_out if v["transcript_status"] == "ok")
    output = {
        "meta": {
            "car_model": label,
            "slug": slug,
            "scraped_at": datetime.now(timezone.utc).isoformat(),
            "queries_used": queries,
            "total_videos": len(videos_out),
            "total_with_transcript": total_ok,
            "duration_filter_seconds": min_duration_seconds,
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
    parser = argparse.ArgumentParser(description="Scrape YouTube transcripts for car issues")
    parser.add_argument("--car-model", default="vw_golf_mk7", choices=list(CAR_CONFIGS))
    parser.add_argument("--top-n", type=int, default=10)
    parser.add_argument("--min-duration", type=int, default=600, help="Min duration in seconds")
    parser.add_argument("--candidates-per-query", type=int, default=15)
    args = parser.parse_args()

    scrape_car_issues(
        car_model=args.car_model,
        top_n=args.top_n,
        min_duration_seconds=args.min_duration,
        candidates_per_query=args.candidates_per_query,
    )


if __name__ == "__main__":
    main()
