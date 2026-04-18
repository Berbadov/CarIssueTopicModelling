import logging
from pathlib import Path
from typing import Any, cast

import yt_dlp
import pandas as pd
from youtube_transcript_api import YouTubeTranscriptApi

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
ROOT = Path(__file__).resolve().parent.parent
OUT_PATH = ROOT / "data" / "raw" / "videos" / "youtube_transcripts_raw.csv"


def search_youtube_videos(query: str, max_results: int = 10) -> list[dict]:
    """Search YouTube for videos matching the query using yt-dlp."""
    logging.info(f"Searching YouTube for: '{query}'")
    ydl_opts: dict[str, Any] = {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": True,
    }
    try:
        with yt_dlp.YoutubeDL(cast(Any, ydl_opts)) as ydl:
            info = ydl.extract_info(f"ytsearch{max_results}:{query}", download=False)
        entries = info.get("result", info.get("entries", [])) if info else []

        videos: list[dict] = []
        for entry in entries:
            if not isinstance(entry, dict):
                continue

            duration_secs = entry.get("duration")
            if duration_secs is not None:
                duration_secs = int(duration_secs)
                m, s = divmod(duration_secs, 60)
                h, m = divmod(m, 60)
                duration_str = f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"
            else:
                duration_str = "Unknown"

            raw_views = entry.get("view_count")
            try:
                view_count_raw = int(raw_views) if raw_views is not None else None
            except (TypeError, ValueError):
                view_count_raw = None
            view_count_str = (
                f"{view_count_raw:,} views" if view_count_raw is not None else "Unknown"
            )

            videos.append(
                {
                    "video_id": str(entry.get("id", "")),
                    "title": str(entry.get("title", "")),
                    "channel": str(
                        entry.get("channel") or entry.get("uploader", "Unknown")
                    ),
                    "duration": duration_str,
                    "duration_seconds": duration_secs,
                    "view_count": view_count_str,
                    "view_count_raw": view_count_raw,
                }
            )

        return videos
    except Exception as e:
        logging.error(f"Error searching YouTube for '{query}': {e}")
        return []


def _coerce_transcript_rows(obj: Any) -> list[dict[str, Any]]:
    if isinstance(obj, list):
        return [row for row in obj if isinstance(row, dict)]
    if hasattr(obj, "to_raw_data"):
        maybe_rows = obj.to_raw_data()
        if isinstance(maybe_rows, list):
            return [row for row in maybe_rows if isinstance(row, dict)]
    return []


def fetch_transcript(video_id: str) -> str | None:
    """Fetch the transcript for a given video ID."""
    try:
        api = YouTubeTranscriptApi()
        if hasattr(api, "fetch"):
            transcript_obj = api.fetch(video_id, languages=["en"])
            transcript_rows = _coerce_transcript_rows(transcript_obj)
        else:
            transcript_rows = _coerce_transcript_rows(
                YouTubeTranscriptApi.get_transcript(video_id, languages=["en"])  # type: ignore[attr-defined]
            )

        if not transcript_rows:
            return None

        text_transcript = "\n".join(
            str(row.get("text", "")).strip()
            for row in transcript_rows
            if isinstance(row.get("text"), str) and str(row.get("text", "")).strip()
        )
        return text_transcript
    except Exception as e:
        # Many videos have transcripts disabled
        logging.warning(f"Could not fetch transcript for {video_id}: {e}")
        return None


def main() -> None:
    # Define our targeted search queries based on the "Symptom vs Root Cause" problem
    queries = [
        "Volkswagen Golf Mk6 common problems",
        "Volkswagen Golf Mk7 common problems",
        "VW EA888 engine failure",
        "VW 1.4 TSI engine teardown",
        "VW DSG DQ200 mechatronic failure",
        "Renault Clio Mk4 common problems",
        "Renault Clio engine stalling",
        "Renault Clio 1.2 TCE problems",
    ]

    all_data: list[dict[str, str]] = []

    # Iterate through our targeted searches
    for query in queries:
        videos = search_youtube_videos(
            query, max_results=5
        )  # 5 videos per specific query to start

        for video in videos:
            logging.info(
                f"Fetching transcript for: {video['title']} ({video['video_id']})"
            )

            transcript_text = fetch_transcript(video["video_id"])

            if transcript_text:
                all_data.append(
                    {
                        "query": query,
                        "video_id": video["video_id"],
                        "title": video["title"],
                        "channel": video["channel"],
                        "transcript": transcript_text,
                    }
                )

    # Save the aggregated transcripts
    if all_data:
        df = pd.DataFrame(all_data)
        OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(OUT_PATH, index=False)
        logging.info(f"Successfully saved {len(df)} transcripts to {OUT_PATH}")
    else:
        logging.warning("No transcripts were successfully fetched.")


if __name__ == "__main__":
    main()
