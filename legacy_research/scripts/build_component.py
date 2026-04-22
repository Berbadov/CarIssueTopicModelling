"""End-to-end pipeline for component-specific corpora.

Scrapes component-focused videos (no model prefix required), chunks, tags using
an associated scaffold, and indexes into a dedicated Chroma collection.

Usage:
    python scripts/build_component.py --code K9K \\
        --scaffold renault_clio_mk4 --lang en --max-per-term 30
    python scripts/build_component.py --code EA211 \\
        --scaffold vw_golf_mk7 --lang en
    python scripts/build_component.py --code DQ200 \\
        --scaffold vw_golf_mk7 --lang en
    python scripts/build_component.py --all-from-scaffold \\
        --scaffold renault_clio_mk4 --lang en --max-per-term 30 --workers 3 --resume
"""
from __future__ import annotations

import argparse
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scrapers"))
sys.path.insert(0, str(ROOT / "scripts"))

from fetch_youtube_car_issues import scrape_entity_videos  # noqa: E402
from build_transcript_chunks import build_for_slug  # noqa: E402
from tag_chunks import tag_slug, load_scaffold  # noqa: E402
from index_transcripts import index_slug  # noqa: E402

RAW_DIR = ROOT / "data" / "raw" / "videos"
CHUNK_DIR = ROOT / "data" / "processed" / "chunks"
VECTOR_DIR = ROOT / "data" / "vector_store" / "chroma"


def _dedupe_keep_order(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for raw in items:
        item = str(raw or "").strip()
        if not item:
            continue
        key = item.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def _pretty_engine_code(code: str | None) -> str:
    return str(code or "").replace("_", " ").strip()


def _component_search_terms(scaffold: dict[str, Any], code: str) -> list[str]:
    """Terms to search for this component only (code + scaffold aliases)."""
    code = code.strip()
    if not code:
        return []
    norm = code.lower()

    terms: list[str] = [code]
    matched = False

    for fam in scaffold.get("engine_families") or []:
        fam_code = str((fam or {}).get("code", "")).strip()
        disps = (fam or {}).get("displacements") or []
        fam_match = fam_code.lower() == norm
        disp_match = False
        for d in disps:
            d_code = str((d.get("code") if isinstance(d, dict) else d) or "").strip()
            if d_code.lower() == norm:
                disp_match = True
                break
        if not (fam_match or disp_match):
            continue

        matched = True
        if fam_code:
            terms.append(fam_code)
        for d in disps:
            aliases = (d.get("search_alias") or []) if isinstance(d, dict) else []
            alias_terms: list[str] = []
            if aliases:
                for alias in aliases:
                    alias_text = str(alias)
                    terms.append(alias_text)
                    alias_terms.append(alias_text)
            else:
                d_code = d.get("code") if isinstance(d, dict) else d
                alias_text = _pretty_engine_code(d_code)
                terms.append(alias_text)
                alias_terms.append(alias_text)

            # Disambiguation for engine-family generations (e.g. EA111 vs EA211):
            # include "family + displacement alias" forms so searches bias toward
            # the intended generation-specific engine variant.
            if fam_match and fam_code:
                for alias_text in alias_terms:
                    terms.append(f"{fam_code} {alias_text}")

    for trans in scaffold.get("transmissions") or []:
        trans_code = str((trans or {}).get("code", "")).strip()
        if not trans_code or trans_code.lower() != norm:
            continue
        matched = True
        terms.append(trans_code)
        trans_type = str((trans or {}).get("type", "")).replace("_", " ").strip()
        if trans_type:
            terms.append(trans_type)

    if not matched:
        terms.append(_pretty_engine_code(code))
    return _dedupe_keep_order(terms)


def _all_component_codes(scaffold: dict[str, Any]) -> list[str]:
    codes: list[str] = []
    for fam in scaffold.get("engine_families") or []:
        codes.append(str((fam or {}).get("code", "")))
    for trans in scaffold.get("transmissions") or []:
        codes.append(str((trans or {}).get("code", "")))
    return _dedupe_keep_order(codes)


def _collection_count(slug: str) -> int:
    import chromadb

    client = chromadb.PersistentClient(path=str(VECTOR_DIR))
    names = [getattr(c, "name", str(c)) for c in client.list_collections()]
    if slug not in names:
        return 0
    return int(client.get_collection(slug).count())


def _print_batch_summary(results: list[dict[str, Any]]) -> None:
    print("\n=== Component batch summary ===")
    print(f"{'component':<14} {'status':<8} {'seconds':>8}  error")
    for r in results:
        err = str(r.get("error") or "")
        if len(err) > 80:
            err = err[:77] + "..."
        print(f"{r['code']:<14} {r['status']:<8} {r['seconds']:>8.1f}  {err}")


def build_component(
    code: str,
    scaffold_slug: str,
    lang: str = "en",
    max_per_term: int = 30,
    candidates_per_query: int = 30,
    min_view_count: int = 5_000,
    request_delay: float = 2.0,
    search_workers: int = 1,
    transcript_workers: int = 1,
    chunk_workers: int = 1,
    resume: bool = False,
    rebuild: bool = False,
) -> dict[str, Any]:
    started = time.perf_counter()
    slug = f"component_{code}"
    suffix = "tr" if lang == "tr" else "en"
    entity_out = RAW_DIR / f"{slug}_entities_{suffix}_raw.json"
    raw_path = RAW_DIR / f"{slug}_raw.json"
    chunk_path = CHUNK_DIR / f"{slug}_chunks.jsonl"
    tagged_path = CHUNK_DIR / f"{slug}_chunks_tagged.jsonl"
    scaffold = load_scaffold(scaffold_slug)
    entity_terms = _component_search_terms(scaffold, code)
    stages: dict[str, dict[str, Any]] = {}
    ran_stage = False

    print(f"\n=== Component: {code} | lang={lang} | scaffold={scaffold_slug} ===")
    print(f"Search terms ({len(entity_terms)}): {', '.join(entity_terms)}")

    stage_started = time.perf_counter()
    if resume and raw_path.exists():
        print(f"[{slug}] scrape stage skipped (--resume, raw exists)")
        stages["scrape"] = {"status": "skipped", "seconds": round(time.perf_counter() - stage_started, 1)}
    else:
        scrape_entity_videos(
            slug=slug,
            max_per_entity=max_per_term,
            candidates_per_query=candidates_per_query,
            min_view_count=min_view_count,
            target_lang=lang,
            scaffold_slug=scaffold_slug,
            entity_terms=entity_terms,
            request_delay=request_delay,
            search_workers=search_workers,
            transcript_workers=transcript_workers,
            out_dir=RAW_DIR,
        )
        if entity_out.exists():
            if raw_path.exists():
                raw_path.unlink()
            entity_out.rename(raw_path)
            print(f"Raw -> {raw_path.name}")
        if not raw_path.exists():
            raise FileNotFoundError(f"No raw file produced for {code}/{lang}: {raw_path}")
        stages["scrape"] = {"status": "done", "seconds": round(time.perf_counter() - stage_started, 1)}
        ran_stage = True

    stage_started = time.perf_counter()
    if resume and chunk_path.exists():
        print(f"[{slug}] chunk stage skipped (--resume, chunks exist)")
        stages["chunk"] = {"status": "skipped", "seconds": round(time.perf_counter() - stage_started, 1)}
    else:
        build_for_slug(slug, workers=chunk_workers)
        stages["chunk"] = {"status": "done", "seconds": round(time.perf_counter() - stage_started, 1)}
        ran_stage = True

    stage_started = time.perf_counter()
    if resume and tagged_path.exists():
        print(f"[{slug}] tag stage skipped (--resume, tagged chunks exist)")
        stages["tag"] = {"status": "skipped", "seconds": round(time.perf_counter() - stage_started, 1)}
    else:
        tag_slug(slug, scaffold_slug=scaffold_slug)
        stages["tag"] = {"status": "done", "seconds": round(time.perf_counter() - stage_started, 1)}
        ran_stage = True

    stage_started = time.perf_counter()
    if resume and not rebuild and _collection_count(slug) > 0:
        print(f"[{slug}] index stage skipped (--resume, collection has vectors)")
        stages["index"] = {"status": "skipped", "seconds": round(time.perf_counter() - stage_started, 1)}
    else:
        index_slug(slug, rebuild=rebuild)
        stages["index"] = {"status": "done", "seconds": round(time.perf_counter() - stage_started, 1)}
        ran_stage = True

    status = "skipped" if not ran_stage else "success"
    print(f"=== {code}/{lang} complete ===\n")
    return {
        "code": code,
        "slug": slug,
        "status": status,
        "seconds": round(time.perf_counter() - started, 1),
        "error": "",
        "stages": stages,
    }


def _run_component_safe(**kwargs: Any) -> dict[str, Any]:
    code = str(kwargs.get("code", "unknown"))
    slug = f"component_{code}"
    try:
        return build_component(**kwargs)
    except Exception as exc:
        return {
            "code": code,
            "slug": slug,
            "status": "failed",
            "seconds": 0.0,
            "error": str(exc),
            "stages": {},
        }


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--code", help="Component code, e.g. K9K, EA211, DQ200")
    p.add_argument("--scaffold", required=True, help="Scaffold slug for tagging, e.g. renault_clio_mk4")
    p.add_argument(
        "--all-from-scaffold",
        action="store_true",
        help="Build every engine-family/transmission component defined in --scaffold.",
    )
    p.add_argument("--lang", default="en", choices=["en", "tr"])
    p.add_argument("--max-per-term", type=int, default=30)
    p.add_argument("--candidates-per-query", type=int, default=30)
    p.add_argument("--min-views", type=int, default=5_000)
    p.add_argument("--request-delay", type=float, default=2.0)
    p.add_argument("--search-workers", type=int, default=1)
    p.add_argument("--transcript-workers", type=int, default=1)
    p.add_argument("--chunk-workers", type=int, default=1)
    p.add_argument("--workers", type=int, default=1, help="Component-level workers for --all-from-scaffold.")
    p.add_argument("--resume", action="store_true", help="Skip stages with existing outputs.")
    p.add_argument("--continue-on-error", action="store_true", help="Continue batch even if a component fails.")
    p.add_argument(
        "--rebuild",
        action="store_true",
        help="Delete and rebuild the Chroma collection from scratch",
    )
    args = p.parse_args()
    if args.all_from_scaffold and args.code:
        p.error("--code and --all-from-scaffold are mutually exclusive")
    if not args.all_from_scaffold and not args.code:
        p.error("Provide --code or --all-from-scaffold")

    if args.all_from_scaffold:
        scaffold = load_scaffold(args.scaffold)
        codes = _all_component_codes(scaffold)
        if not codes:
            print(f"[!] No component codes found in scaffold: {args.scaffold}")
            return
        print(
            f"Building {len(codes)} components from {args.scaffold}: {', '.join(codes)} "
            f"(workers={max(1, int(args.workers))})"
        )

        common_kwargs = {
            "scaffold_slug": args.scaffold,
            "lang": args.lang,
            "max_per_term": args.max_per_term,
            "candidates_per_query": args.candidates_per_query,
            "min_view_count": args.min_views,
            "request_delay": args.request_delay,
            "search_workers": args.search_workers,
            "transcript_workers": args.transcript_workers,
            "chunk_workers": args.chunk_workers,
            "resume": args.resume,
            "rebuild": args.rebuild,
        }

        results: list[dict[str, Any]] = []
        max_workers = max(1, int(args.workers))
        if max_workers == 1:
            for code in codes:
                result = _run_component_safe(code=code, **common_kwargs)
                results.append(result)
                if result["status"] == "failed" and not args.continue_on_error:
                    break
        else:
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                futures = {
                    executor.submit(_run_component_safe, code=code, **common_kwargs): code
                    for code in codes
                }
                for future in as_completed(futures):
                    results.append(future.result())
            order = {code: idx for idx, code in enumerate(codes)}
            results.sort(key=lambda r: order.get(str(r.get("code", "")), 10**9))

        _print_batch_summary(results)
        failed = [r for r in results if r["status"] == "failed"]
        if failed and not args.continue_on_error:
            raise SystemExit(1)
        return

    result = _run_component_safe(
        code=str(args.code),
        scaffold_slug=args.scaffold,
        lang=args.lang,
        max_per_term=args.max_per_term,
        candidates_per_query=args.candidates_per_query,
        min_view_count=args.min_views,
        request_delay=args.request_delay,
        search_workers=args.search_workers,
        transcript_workers=args.transcript_workers,
        chunk_workers=args.chunk_workers,
        resume=args.resume,
        rebuild=args.rebuild,
    )
    _print_batch_summary([result])
    if result["status"] == "failed":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
