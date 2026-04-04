import logging
from pathlib import Path
from typing import Any

import pandas as pd
from youtube_transcript_api import YouTubeTranscriptApi
from youtubesearchpython import VideosSearch

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
ROOT = Path(__file__).resolve().parent.parent
OUT_PATH = ROOT / "data" / "raw" / "videos" / "youtube_transcripts_raw.csv"

def search_youtube_videos(query: str, max_results: int = 10) -> list[dict[str, str]]:
    """Search YouTube for videos matching the query."""
    logging.info(f"Searching YouTube for: '{query}'")
    try:
        videos_search = VideosSearch(query, limit=max_results)
        payload = videos_search.result()
        raw_results = payload.get("result", []) if isinstance(payload, dict) else []

        videos: list[dict[str, str]] = []
        for video in raw_results:
            if not isinstance(video, dict):
                continue

            channel_obj = video.get("channel")
            channel_name = "Unknown"
            if isinstance(channel_obj, dict):
                channel_name = str(channel_obj.get("name", "Unknown"))

            view_count_obj = video.get("viewCount")
            view_count = "Unknown"
            if isinstance(view_count_obj, dict):
                view_count = str(view_count_obj.get("text", "Unknown"))

            videos.append({
                "video_id": str(video.get("id", "")),
                "title": str(video.get("title", "")),
                "channel": channel_name,
                "duration": str(video.get("duration", "Unknown")),
                "view_count": view_count,
            })

        return videos
    except Exception as e:
        logging.error(f"Error searching YouTube for {query}: {e}")
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
        "Renault Clio 1.2 TCE problems"
    ]
    
    all_data: list[dict[str, str]] = []
    
    # Iterate through our targeted searches
    for query in queries:
        videos = search_youtube_videos(query, max_results=5) # 5 videos per specific query to start
        
        for video in videos:
            logging.info(f"Fetching transcript for: {video['title']} ({video['video_id']})")
            
            transcript_text = fetch_transcript(video['video_id'])
            
            if transcript_text:
                all_data.append({
                    'query': query,
                    'video_id': video['video_id'],
                    'title': video['title'],
                    'channel': video['channel'],
                    'transcript': transcript_text
                })
    
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
