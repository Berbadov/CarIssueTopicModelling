"""Merge multiple {slug}_*_raw.json files into {slug}_raw.json.

Usage:
    python scripts/merge_corpus.py --slug renault_clio_mk4
    python scripts/merge_corpus.py --slug renault_clio_mk4 --inputs en tr entities_en entities_tr

Auto-discovers files matching data/raw/videos/{slug}_*_raw.json when
--inputs is omitted. Always deduplicates by video_id (first occurrence wins).
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT / "data" / "raw" / "videos"


def merge(slug: str, suffixes: list[str] | None = None) -> Path:
    if suffixes:
        paths = [RAW_DIR / f"{slug}_{s}_raw.json" for s in suffixes]
    else:
        paths = sorted(p for p in RAW_DIR.glob(f"{slug}_*_raw.json")
                       if "_raw.json" in p.name)

    if not paths:
        raise FileNotFoundError(f"No raw files found for slug '{slug}'")

    seen: set[str] = set()
    merged: list[dict] = []
    sources: list[str] = []

    for p in paths:
        if not p.exists():
            print(f"[!] missing: {p.name} — skipping")
            continue
        d = json.loads(p.read_text(encoding="utf-8"))
        videos = d.get("videos") or []
        before = len(merged)
        for v in videos:
            vid_id = v.get("video_id")
            if not vid_id or vid_id in seen:
                continue
            seen.add(vid_id)
            merged.append(v)
        added = len(merged) - before
        sources.append(p.name)
        print(f"  {p.name}: {len(videos)} videos → {added} new (deduped)")

    ok = sum(1 for v in merged if v.get("transcript_status") == "ok")
    out_path = RAW_DIR / f"{slug}_raw.json"

    output = {
        "meta": {
            "slug": slug,
            "merged_at": datetime.now(timezone.utc).isoformat(),
            "merged_from": sources,
            "total_videos": len(merged),
            "total_with_transcript": ok,
        },
        "videos": merged,
    }
    out_path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nMerged {len(merged)} unique videos ({ok} with transcripts) → {out_path.name}")
    return out_path


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--slug", required=True)
    p.add_argument(
        "--inputs", nargs="*",
        help="Suffixes to merge, e.g. 'en tr entities_en entities_tr'. "
             "Auto-discovers if omitted.",
    )
    args = p.parse_args()
    merge(args.slug, args.inputs)


if __name__ == "__main__":
    main()
