"""Build time-windowed transcript chunks for RAG indexing.

Reads data/raw/videos/{slug}_raw.json and emits one JSONL chunk record per
time-window to data/processed/chunks/{slug}_chunks.jsonl.

Windows target ~35s with 10s overlap (effective step ~25s), preserving
transcript_segments timing so chunks deep-link to youtube.com/watch?v=X&t=Ns.
"""
from __future__ import annotations

import argparse
import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT / "data" / "raw" / "videos"
OUT_DIR = ROOT / "data" / "processed" / "chunks"

TARGET_DURATION = 35.0
MAX_DURATION = 45.0
OVERLAP = 10.0
MIN_CHARS = 40

MARKER_ONLY = re.compile(r"^\s*(\[[^\]]+\]\s*)+$")
WHITESPACE = re.compile(r"\s+")


def clean_text(text: str) -> str:
    return WHITESPACE.sub(" ", text.replace("\xa0", " ")).strip()


def is_marker_only(text: str) -> bool:
    return bool(MARKER_ONLY.match(text))


def build_chunks_for_video(video: dict) -> list[dict]:
    segs = video.get("transcript_segments") or []
    if not segs:
        return []

    video_id = video["video_id"]
    title = video.get("title", "")
    channel = video.get("channel", "")
    language = video.get("video_language", "unknown")
    duration_seconds = video.get("duration_seconds")

    chunks: list[dict] = []
    i = 0
    n = len(segs)

    while i < n:
        window: list[dict] = []
        start_time = segs[i]["start"]
        j = i
        while j < n:
            seg = segs[j]
            seg_end = seg["start"] + seg.get("duration", 0.0)
            current_duration = seg_end - start_time
            if window and current_duration > MAX_DURATION:
                break
            window.append(seg)
            if current_duration >= TARGET_DURATION:
                j += 1
                break
            j += 1

        if not window:
            break

        end_time = window[-1]["start"] + window[-1].get("duration", 0.0)
        text = clean_text(" ".join(s["text"] for s in window))

        if len(text) >= MIN_CHARS and not is_marker_only(text):
            chunk_id = f"{video_id}_{int(round(start_time * 10)):07d}"
            chunks.append(
                {
                    "chunk_id": chunk_id,
                    "video_id": video_id,
                    "start": round(start_time, 2),
                    "end": round(end_time, 2),
                    "text": text,
                    "language": language,
                    "title": title,
                    "channel": channel,
                    "duration_seconds": duration_seconds,
                    "video_url_ts": f"https://youtube.com/watch?v={video_id}&t={int(start_time)}s",
                }
            )

        if j >= n:
            break

        # Step forward, leaving ~OVERLAP seconds of tail as head of next window.
        next_start_target = end_time - OVERLAP
        k = j
        while k > i and segs[k - 1]["start"] >= next_start_target:
            k -= 1
        i = max(k, i + 1)

    return chunks


def build_for_slug(slug: str, workers: int = 1) -> Path:
    raw_path = RAW_DIR / f"{slug}_raw.json"
    if not raw_path.exists():
        raise FileNotFoundError(f"Missing raw file: {raw_path}")

    data = json.loads(raw_path.read_text(encoding="utf-8"))
    videos = data.get("videos", [])

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUT_DIR / f"{slug}_chunks.jsonl"

    total_chunks = 0
    skipped = 0
    valid_videos: list[dict] = []
    for v in videos:
        if v.get("transcript_status") != "ok":
            skipped += 1
            continue
        valid_videos.append(v)

    per_video_chunks: dict[int, list[dict]] = {}
    if workers <= 1:
        for idx, video in enumerate(valid_videos):
            per_video_chunks[idx] = build_chunks_for_video(video)
    else:
        max_workers = max(1, int(workers))
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(build_chunks_for_video, video): idx
                for idx, video in enumerate(valid_videos)
            }
            for future in as_completed(futures):
                idx = futures[future]
                per_video_chunks[idx] = future.result()

    with out_path.open("w", encoding="utf-8") as f:
        for idx in range(len(valid_videos)):
            for chunk in per_video_chunks.get(idx, []):
                f.write(json.dumps(chunk, ensure_ascii=False) + "\n")
                total_chunks += 1

    print(
        f"[{slug}] videos_used={len(valid_videos)} skipped={skipped} "
        f"chunks={total_chunks} -> {out_path.relative_to(ROOT)}"
    )
    return out_path


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--slug", required=True, help="e.g. vw_golf_mk7")
    p.add_argument("--workers", type=int, default=1, help="Chunking worker threads (default: 1).")
    args = p.parse_args()
    build_for_slug(args.slug, workers=args.workers)


if __name__ == "__main__":
    main()
