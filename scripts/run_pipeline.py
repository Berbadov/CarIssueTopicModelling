"""
Unified pipeline driver: scrape -> extract -> postprocess -> benchmark.

Shells out to the existing stage scripts with canonical flags so that
runs across agents (Claude / Gemini / Copilot) are reproducible.

Usage:
    python scripts/run_pipeline.py --car "VW Golf MK7"
    python scripts/run_pipeline.py --car "VW Golf MK7" --skip scrape
    python scripts/run_pipeline.py --car "VW Golf MK7" --resume-from postprocess
    python scripts/run_pipeline.py --car "VW Golf MK7" --force
"""

from __future__ import annotations

import argparse
import json
import logging
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "data" / "raw" / "videos"
PROC_DIR = ROOT / "data" / "processed"

STAGES = ("scrape", "extract", "postprocess", "benchmark")


def slug_from_car(car_label: str) -> str:
    return car_label.lower().replace(" ", "_")


def stage_outputs(slug: str) -> dict[str, Path]:
    return {
        "scrape": RAW_DIR / f"{slug}_raw.json",
        "extract": PROC_DIR / f"issue_knowledge_youtube_{slug}.json",
        "postprocess": PROC_DIR / f"issue_knowledge_youtube_{slug}_final.json",
        "benchmark": ROOT / "data" / "benchmarks" / "benchmark_history.json",
    }


def stage_inputs(slug: str) -> dict[str, Path | None]:
    return {
        "scrape": None,
        "extract": RAW_DIR / f"{slug}_raw.json",
        "postprocess": PROC_DIR / f"issue_knowledge_youtube_{slug}.json",
        "benchmark": PROC_DIR / f"issue_knowledge_youtube_{slug}_final.json",
    }


def is_up_to_date(stage: str, slug: str) -> bool:
    out = stage_outputs(slug)[stage]
    src = stage_inputs(slug)[stage]
    if not out.exists():
        return False
    if src is None:
        return True
    if not src.exists():
        return False
    return out.stat().st_mtime >= src.stat().st_mtime


def build_scrape_cmd(car: str, slug: str, args: argparse.Namespace) -> list[str]:
    cmd = [
        sys.executable,
        str(ROOT / "scrapers" / "fetch_youtube_car_issues.py"),
        "--car", car,
        "--slug", slug,
        "--max-videos", str(args.max_videos),
        "--max-views", str(args.max_views),
    ]
    if args.disable_prefilter:
        cmd.append("--disable-prefilter")
    return cmd


def build_extract_cmd(slug: str, args: argparse.Namespace) -> list[str]:
    return [
        sys.executable,
        str(ROOT / "scripts" / "extract_youtube_issues.py"),
        "--slug", slug,
    ]


def build_postprocess_cmd(slug: str, args: argparse.Namespace) -> list[str]:
    return [
        sys.executable,
        str(ROOT / "scripts" / "postprocess_youtube_issues.py"),
        "--slug", slug,
    ]


def build_benchmark_cmd(slug: str, args: argparse.Namespace) -> list[str]:
    return [sys.executable, str(ROOT / "benchmark_knowledge.py")]


BUILDERS = {
    "scrape": build_scrape_cmd,
    "extract": build_extract_cmd,
    "postprocess": build_postprocess_cmd,
    "benchmark": build_benchmark_cmd,
}


def run_stage(
    stage: str,
    car: str,
    slug: str,
    args: argparse.Namespace,
    log_file: Path,
) -> dict:
    if stage == "scrape":
        cmd = BUILDERS[stage](car, slug, args)
    else:
        cmd = BUILDERS[stage](slug, args)

    start = time.time()
    start_iso = datetime.now(timezone.utc).isoformat()
    logging.info(f"[{stage}] starting: {' '.join(cmd)}")

    with open(log_file, "a", encoding="utf-8") as lf:
        lf.write(f"\n===== {stage} @ {start_iso} =====\n")
        lf.write(" ".join(cmd) + "\n")
        lf.flush()
        proc = subprocess.run(cmd, stdout=lf, stderr=subprocess.STDOUT)

    duration = time.time() - start
    record = {
        "stage": stage,
        "cmd": cmd,
        "exit_code": proc.returncode,
        "started_at": start_iso,
        "duration_seconds": round(duration, 2),
    }
    out_path = stage_outputs(slug)[stage]
    if out_path.exists():
        record["output"] = str(out_path.relative_to(ROOT))
        record["output_mtime"] = datetime.fromtimestamp(
            out_path.stat().st_mtime, tz=timezone.utc
        ).isoformat()
    logging.info(
        f"[{stage}] done in {duration:.1f}s exit={proc.returncode}"
    )
    return record


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--car", required=True, help='Car label, e.g. "VW Golf MK7"')
    parser.add_argument("--slug", default=None, help="Override derived slug")
    parser.add_argument(
        "--skip",
        default="",
        help="Comma-separated stages to skip: " + ",".join(STAGES),
    )
    parser.add_argument(
        "--resume-from",
        choices=STAGES,
        default=None,
        help="Skip everything before this stage.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-run stages even if outputs are up to date.",
    )
    # Passthrough flags for scrape
    parser.add_argument("--max-videos", type=int, default=30)
    parser.add_argument("--max-views", type=int, default=150_000)
    parser.add_argument("--disable-prefilter", action="store_true")

    args = parser.parse_args()

    slug = args.slug or slug_from_car(args.car)
    skip = {s.strip() for s in args.skip.split(",") if s.strip()}
    resume_idx = STAGES.index(args.resume_from) if args.resume_from else 0

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    PROC_DIR.mkdir(parents=True, exist_ok=True)
    log_file = PROC_DIR / f"_pipeline_{slug}.log"
    manifest_file = PROC_DIR / f"_pipeline_{slug}_manifest.json"

    logging.info(f"Pipeline start: car='{args.car}' slug='{slug}'")
    logging.info(f"Log: {log_file}")

    manifest: dict = {
        "car": args.car,
        "slug": slug,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "flags": {
            "max_videos": args.max_videos,
            "max_views": args.max_views,
            "disable_prefilter": args.disable_prefilter,
            "force": args.force,
            "skip": sorted(skip),
            "resume_from": args.resume_from,
        },
        "stages": [],
    }

    overall_ok = True
    for idx, stage in enumerate(STAGES):
        if idx < resume_idx:
            manifest["stages"].append({"stage": stage, "status": "skipped_by_resume"})
            continue
        if stage in skip:
            manifest["stages"].append({"stage": stage, "status": "skipped_by_user"})
            continue
        if not args.force and is_up_to_date(stage, slug):
            logging.info(f"[{stage}] up to date, skipping (use --force to rerun)")
            manifest["stages"].append({"stage": stage, "status": "up_to_date"})
            continue

        record = run_stage(stage, args.car, slug, args, log_file)
        record["status"] = "ok" if record["exit_code"] == 0 else "failed"
        manifest["stages"].append(record)

        if record["exit_code"] != 0:
            overall_ok = False
            logging.error(f"[{stage}] failed — aborting pipeline.")
            break

    manifest["finished_at"] = datetime.now(timezone.utc).isoformat()
    manifest["ok"] = overall_ok
    with open(manifest_file, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
    logging.info(f"Manifest: {manifest_file}")

    return 0 if overall_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
