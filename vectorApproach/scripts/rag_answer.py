"""Spec-scoped RAG answerer: listing -> grounded issue list.

Flow:
    1. Parse the listing text into a spec (scripts/parse_listing.py).
    2. Run a fixed bank of MODEL-LEVEL probes against the Chroma index
       (no failure-level probes, per agents.md §2).
    3. Post-filter retrieved chunks by spec with graceful relaxation:
         tier 1: chunk.engines intersects spec.engines             (strict)
         tier 2: chunk.engine_families intersects spec.fams        (family)
         tier 3: chunk.fuel_types intersects spec.fuel_types       (fuel)
         tier 4: no filter                                         (fallback)
    4. Dedup across probes (video_id + time overlap).
    5. Send surviving chunks to DeepSeek with strict JSON schema,
       grounded-only instructions, and emit a per-issue evidence list.

Example:
    DEEPSEEK_API_KEY=xxx python scripts/rag_answer.py \
        --slug vw_golf_mk7 \
        --text "2017 golf 1.4tsi automatic 120000 km"
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import chromadb
from openai import OpenAI
from sentence_transformers import SentenceTransformer
from tenacity import retry, stop_after_attempt, wait_exponential

from parse_listing import parse_listing, ListingSpec
from tag_chunks import load_scaffold

ROOT = Path(__file__).resolve().parents[1]
STORE_DIR = ROOT / "data" / "vector_store" / "chroma"
OUT_DIR = ROOT / "data" / "processed" / "rag"

EMBED_MODEL = "intfloat/multilingual-e5-base"
LLM_MODEL = "deepseek-chat"
LLM_BASE_URL = "https://api.deepseek.com/v1"
LLM_TIMEOUT = 120
LLM_MAX_TOKENS = 3000

# Model-level probes only — no failure names (agents.md §2/§3).
# Base probes always run; spec-aware expansions are added by build_probes().
BASE_PROBES = [
    "common issues and problems",
    "things that break over time",
    "ownership experience long term reliability",
    "engine problems",
    "transmission problems",
    "electrical problems",
    "suspension and steering problems",
    "interior and trim problems",
    "brake problems",
]

# Component-level probes (neutral taxonomy — components present on the vehicle,
# not failure terms). Enabled conditionally by spec.fuel_types.
DIESEL_COMPONENT_PROBES = [
    "diesel engine problems",
    "EGR valve problems",
    "DPF diesel particulate filter problems",
    "turbocharger problems",
    "injector problems",
    "glow plug problems",
]
PETROL_COMPONENT_PROBES = [
    "petrol engine problems",
    "turbocharger problems",
    "ignition coil problems",
    "spark plug problems",
]


def build_probes(spec: ListingSpec) -> list[str]:
    """Expand BASE_PROBES with spec-aware component and code probes.

    All additions are either (a) component names present on the vehicle,
    or (b) codes that appear in the scaffold (engine displacements, engine
    families, transmission codes) — never failure vocabulary.
    """
    probes: list[str] = list(BASE_PROBES)

    if "diesel" in spec.fuel_types:
        probes.extend(DIESEL_COMPONENT_PROBES)
    if "petrol" in spec.fuel_types:
        probes.extend(PETROL_COMPONENT_PROBES)

    for fam in spec.engine_families:
        probes.append(f"{fam} engine problems")
    for eng in spec.engines:
        pretty = eng.replace("_", " ")
        probes.append(f"{pretty} engine problems")

    for t in spec.transmissions:
        if t in {"automatic", "manual"}:
            continue
        probes.append(f"{t} transmission problems")

    seen: set[str] = set()
    out: list[str] = []
    for p in probes:
        key = p.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(p)
    return out


TOP_K_PER_PROBE = 20
TARGET_EVIDENCE_COUNT = 30
TIME_OVERLAP_TOLERANCE = 5.0  # seconds

# ──────────────────────────── retrieval ────────────────────────────────

_EMBEDDER: SentenceTransformer | None = None


def embed_query(text: str) -> list[float]:
    global _EMBEDDER
    if _EMBEDDER is None:
        _EMBEDDER = SentenceTransformer(EMBED_MODEL)
    v = _EMBEDDER.encode(
        [f"query: {text}"], normalize_embeddings=True, convert_to_numpy=True
    )
    return v[0].tolist()


def _split_tagstr(s: str) -> set[str]:
    if not s or s == "":
        return set()
    return {x for x in s.strip("|").split("|") if x}


def _tier_for_chunk(meta: dict, spec: ListingSpec) -> int:
    """Lower is stricter. 1 = engine match, 2 = family, 3 = fuel, 4 = fallback.

    Cross-generation risk bumps the chunk down by one tier (capped at 4).
    A chunk that mentions EA111 / Mk6 / pre-2013 alongside an engine match
    is probably describing an older-gen variant of "the same" displacement,
    so it becomes supporting context instead of primary evidence.
    """
    chunk_engines = _split_tagstr(meta.get("engines", ""))
    chunk_fams = _split_tagstr(meta.get("engine_families", ""))
    chunk_fuels = _split_tagstr(meta.get("fuel_types", ""))

    if spec.engines and chunk_engines & set(spec.engines):
        tier = 1
    elif spec.engine_families and chunk_fams & set(spec.engine_families):
        tier = 2
    elif spec.fuel_types and chunk_fuels & set(spec.fuel_types):
        tier = 3
    else:
        tier = 4

    if meta.get("cross_generation_risk"):
        tier = min(tier + 1, 4)
    return tier


def _query_collection(
    coll,
    probe: str,
    spec: ListingSpec,
    seen_ids: set[str],
    source_tag: str | None = None,
) -> list[dict]:
    emb = embed_query(probe)
    res = coll.query(query_embeddings=[emb], n_results=TOP_K_PER_PROBE)
    hits: list[dict] = []
    for cid, doc, meta, dist in zip(
        res["ids"][0], res["documents"][0],
        res["metadatas"][0], res["distances"][0]
    ):
        if cid in seen_ids:
            continue
        seen_ids.add(cid)
        tier = _tier_for_chunk(meta, spec)
        hit = {
            "chunk_id": cid,
            "probe": probe,
            "similarity": 1.0 - dist,
            "tier": tier,
            "text": doc,
            **meta,
        }
        if source_tag:
            hit["source"] = source_tag
        hits.append(hit)
    return hits


def _dedup_and_rank(all_hits: list[dict]) -> list[dict]:
    """Time-overlap dedup per video, then tier-walk to TARGET_EVIDENCE_COUNT."""
    all_hits.sort(key=lambda h: (h["tier"], -h["similarity"]))
    kept: list[dict] = []
    per_video: dict[str, list[tuple[float, float]]] = {}
    for h in all_hits:
        vid = h["video_id"]
        s, e = h["start"], h["end"]
        overlaps = any(
            not (e + TIME_OVERLAP_TOLERANCE < ks or s - TIME_OVERLAP_TOLERANCE > ke)
            for ks, ke in per_video.get(vid, [])
        )
        if overlaps:
            continue
        per_video.setdefault(vid, []).append((s, e))
        kept.append(h)

    out: list[dict] = []
    for tier in (1, 2, 3, 4):
        out.extend(h for h in kept if h["tier"] == tier)
        if len(out) >= TARGET_EVIDENCE_COUNT:
            break
    return out[: TARGET_EVIDENCE_COUNT * 2]


def retrieve_component_chunks(spec: ListingSpec, probes: list[str]) -> list[dict]:
    """Query per-component Chroma collections (cross-car engine/transmission evidence).

    Skips any component collection that doesn't exist yet — degrades gracefully
    while components are being built incrementally.
    """
    client = chromadb.PersistentClient(path=str(STORE_DIR))
    component_codes = list(spec.engine_families) + [
        t for t in spec.transmissions
        if t not in {"automatic", "manual"}
    ]

    seen_ids: set[str] = set()
    all_hits: list[dict] = []

    for code in component_codes:
        coll_name = f"component_{code}"
        try:
            coll = client.get_collection(coll_name)
        except Exception:
            continue  # collection not built yet

        for probe in probes:
            hits = _query_collection(coll, probe, spec, seen_ids, source_tag=f"component_{code}")
            # Component evidence is cross-car: cap tier at 2 so it never outranks
            # car-specific tier-1 hits but stays above generic tier-3/4 evidence.
            for h in hits:
                h["tier"] = min(h["tier"], 2)
            all_hits.extend(hits)

    return all_hits


def retrieve(spec: ListingSpec, probes: list[str] | None = None) -> list[dict]:
    probes = probes if probes is not None else build_probes(spec)

    # Component-level hits first (cross-car engine/transmission evidence).
    all_hits = retrieve_component_chunks(spec, probes)
    seen_ids: set[str] = {h["chunk_id"] for h in all_hits}

    # Car-level hits.
    client = chromadb.PersistentClient(path=str(STORE_DIR))
    coll = client.get_collection(spec.slug)
    for probe in probes:
        all_hits.extend(_query_collection(coll, probe, spec, seen_ids))

    return _dedup_and_rank(all_hits)


# ──────────────────────────── LLM ──────────────────────────────────────

def _client() -> OpenAI:
    key = os.environ.get("DEEPSEEK_API_KEY")
    if not key:
        sys.exit("DEEPSEEK_API_KEY not set")
    return OpenAI(api_key=key, base_url=LLM_BASE_URL)


SYSTEM_PROMPT = """You are extracting car-issue knowledge from YouTube transcript evidence.

Hard rules:
1. Ground every claim in the provided evidence. If evidence does not support a claim, do not include it.
2. Do NOT invent failure modes not mentioned in the evidence.
3. Every issue you output MUST include 1+ evidence entries with chunk_id and a short verbatim quote (<= 200 chars) copied from that chunk.
4. If the evidence discusses an engine or transmission that conflicts with the listing spec, flag it in applies_to_spec.match = "partial" or "mismatch"; use "match" only if the evidence directly concerns the listing's engine/family/fuel.
5. Chunks marked CROSS_GEN_RISK mention a different generation or older engine family (e.g. Mk6, EA111, pre-2013) alongside an engine term. Treat these as supporting context only; if you use them, set applies_to_spec.match = "mismatch" or "partial" and name the risk in the notes.
5b. Check the listing year against features mentioned in evidence. If the evidence describes a system or technology that was not available for the listing's specific year (e.g. AdBlue/SCR on a pre-2018 Euro 5 diesel, a facelift feature on a pre-facelift year), set match = "mismatch" and explain in notes.
6. severity is an observed judgement from the evidence: "safety" | "expensive" | "nuisance" | "unknown". Do not guess — pick "unknown" if the speaker doesn't indicate.
7. Output JSON only. No markdown. No commentary.

Output schema:
{
  "issues": [
    {
      "label": "short neutral phrase, no speculation",
      "component": "engine|transmission|electrical|suspension|brakes|interior|body|cooling|fuel|exhaust|other",
      "summary": "1-2 sentences of what the evidence actually says",
      "applies_to_spec": {
        "match": "match|partial|mismatch|unknown",
        "notes": "one sentence tying the evidence to the listing's engine/mileage/year"
      },
      "observed_mileage_km": null,
      "severity": "safety|expensive|nuisance|unknown",
      "evidence": [
        {"chunk_id": "...", "quote": "..."}
      ]
    }
  ]
}"""


def build_scaffold_summary(slug: str) -> str:
    """Compact, neutral taxonomy pulled straight from the scaffold — no
    failure information, just the engine/transmission facts already on disk."""
    try:
        sc = load_scaffold(slug)
    except FileNotFoundError:
        return ""
    meta = sc.get("meta", {})
    y_lo, y_hi = (sc.get("meta", {}).get("corpus_years") or [None, None])
    lines = [
        f"Model: {meta.get('make','?')} {meta.get('model','?')} "
        f"({meta.get('generation','?')}, {y_lo}-{y_hi})"
    ]
    for fl in sc.get("facelifts") or []:
        lines.append(f"Facelift {fl['year']}: {fl.get('label','?')} (pre: {fl.get('pre_label','?')})")
    for fam in sc.get("engine_families", []):
        disps = ", ".join(d["code"] for d in fam.get("displacements", []))
        lines.append(
            f"- {fam['code']} ({fam.get('fuel_type','?')}, "
            f"{fam.get('timing_drive','?')}-drive): {disps}"
        )
    transes = sc.get("transmissions", [])
    if transes:
        lines.append("Transmissions: " + ", ".join(
            f"{t['code']} ({t.get('type','?')})" for t in transes
        ))
    return "\n".join(lines)


def build_user_prompt(spec: ListingSpec, evidence: list[dict]) -> str:
    scaffold_summary = build_scaffold_summary(spec.slug)
    lines: list[str] = []
    if scaffold_summary:
        lines += ["SCAFFOLD (neutral model taxonomy — use to judge whether evidence applies to the listing):", scaffold_summary, ""]
    lines += ["LISTING SPEC:", json.dumps(spec.to_dict(), ensure_ascii=False, indent=2), ""]
    lines.append(f"EVIDENCE ({len(evidence)} chunks):")
    for h in evidence:
        tier_name = {1: "engine-match", 2: "family-match", 3: "fuel-match", 4: "general"}[h["tier"]]
        tags_bits = []
        if h.get("engines"):
            tags_bits.append(f"engines={h['engines'].strip('|')}")
        if h.get("transmissions"):
            tags_bits.append(f"trans={h['transmissions'].strip('|')}")
        if h.get("drive_types"):
            tags_bits.append(f"drive={h['drive_types'].strip('|')}")
        tag_s = " ".join(tags_bits) or "no_tags"
        if h.get("cross_generation_risk"):
            markers = (h.get("cross_generation_markers") or "").strip("|").replace("|", ",")
            tag_s += f" CROSS_GEN_RISK(markers={markers or '?'})"
        lines.append(
            f"\n[{h['chunk_id']}] tier={tier_name} {tag_s} "
            f"t={h['start']:.0f}-{h['end']:.0f}s channel={h.get('channel','')}"
        )
        lines.append(f"  {h['text']}")
    lines.append("\nReturn JSON only.")
    return "\n".join(lines)


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=4, max=20),
    reraise=True,
)
def call_llm(system_prompt: str, user_prompt: str) -> tuple[str, dict]:
    client = _client()
    resp = client.chat.completions.create(
        model=LLM_MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.1,
        max_tokens=LLM_MAX_TOKENS,
        timeout=LLM_TIMEOUT,
        response_format={"type": "json_object"},
    )
    usage = {
        "prompt_tokens": resp.usage.prompt_tokens,
        "completion_tokens": resp.usage.completion_tokens,
    }
    return (resp.choices[0].message.content or "").strip(), usage


# ──────────────────────────── enrich output ───────────────────────────

def enrich_issues(llm_json: dict, evidence: list[dict]) -> dict:
    """Attach full chunk metadata (url, channel, timestamps) to each evidence ref."""
    by_id = {h["chunk_id"]: h for h in evidence}
    issues = llm_json.get("issues", []) or []
    for iss in issues:
        full_ev = []
        distinct_videos: set[str] = set()
        distinct_channels: set[str] = set()
        for ev in iss.get("evidence", []) or []:
            cid = ev.get("chunk_id")
            if not cid or cid not in by_id:
                continue
            h = by_id[cid]
            full_ev.append(
                {
                    "chunk_id": cid,
                    "video_id": h["video_id"],
                    "start": h["start"],
                    "end": h["end"],
                    "url": h.get("video_url_ts"),
                    "channel": h.get("channel"),
                    "title": h.get("title"),
                    "tier": {1: "engine-match", 2: "family-match", 3: "fuel-match", 4: "general"}[h["tier"]],
                    "quote": (ev.get("quote") or "")[:400],
                }
            )
            distinct_videos.add(h["video_id"])
            if h.get("channel"):
                distinct_channels.add(h["channel"])
        iss["evidence"] = full_ev
        iss["corroboration"] = {
            "distinct_videos": len(distinct_videos),
            "distinct_channels": len(distinct_channels),
            "evidence_count": len(full_ev),
        }
    return llm_json


# ──────────────────────────── coverage note ────────────────────────────

def build_coverage_note(spec: ListingSpec, tier_counts: dict, component_count: int = 0) -> dict:
    """Honest signal about how well the corpus covers this specific listing.

    Confidence tiers:
      high    — 10+ engine-match chunks  (engine tagged in corpus)
      medium  — 3–9 engine-match chunks, or 15+ combined with component evidence
      low     — 0 engine-match but family/fuel/component match present
      minimal — nothing spec-specific; only generic Mk/model content
    """
    t1 = tier_counts.get(1, 0)
    t2 = tier_counts.get(2, 0)
    t3 = tier_counts.get(3, 0)
    total_specific = t1 + t2 + component_count

    if t1 >= 10 or total_specific >= 15:
        confidence = "high"
    elif t1 >= 3 or total_specific >= 5:
        confidence = "medium"
    elif total_specific > 0 or (t2 + t3) >= 5:
        confidence = "low"
    else:
        confidence = "minimal"

    engines_str = ", ".join(spec.engines) if spec.engines else "unknown engine"
    fams_str = ", ".join(spec.engine_families) if spec.engine_families else ""

    notes = {
        "high": (
            f"Good corpus coverage for {engines_str}. "
            "Issues shown are grounded in engine-specific evidence."
        ),
        "medium": (
            f"Moderate corpus coverage for {engines_str}. "
            "Some engine-specific issues may be missing if no relevant video covered them."
        ),
        "low": (
            f"No videos in the corpus specifically discuss {engines_str}. "
            + (
                f"Evidence comes from the broader {fams_str} engine family — "
                if t2 > 0 and fams_str else
                f"Evidence comes from general {', '.join(spec.fuel_types) or 'petrol/diesel'} content — "
            )
            + "engine-specific details (e.g. timing belt interval, injector seals) may not appear."
        ),
        "minimal": (
            f"Very limited corpus coverage for {engines_str}. "
            "Issues shown are based on general model content only — "
            "treat them as starting points, not a complete picture."
        ),
    }

    return {
        "confidence": confidence,
        "engine_specific_chunks": t1,
        "family_chunks": t2,
        "fuel_chunks": t3,
        "component_chunks": component_count,
        "note": notes[confidence],
    }


# ──────────────────────────── driver ───────────────────────────────────

def run(spec: ListingSpec, out_dir: Path, dry_run: bool = False) -> Path:
    t0 = time.time()
    probes = build_probes(spec)
    print(f"[{spec.slug}] probes ({len(probes)}): {probes}")
    evidence = retrieve(spec, probes=probes)
    tier_counts = {1: 0, 2: 0, 3: 0, 4: 0}
    for h in evidence:
        tier_counts[h["tier"]] += 1
    print(
        f"[{spec.slug}] retrieved {len(evidence)} chunks "
        f"(engine={tier_counts[1]} family={tier_counts[2]} "
        f"fuel={tier_counts[3]} general={tier_counts[4]})"
    )
    if not evidence:
        print("[!] no evidence retrieved — aborting before LLM call")
        return Path()

    if dry_run:
        out_dir.mkdir(parents=True, exist_ok=True)
        hsh = hashlib.sha1(spec.raw_text.encode("utf-8")).hexdigest()[:8]
        safe = re.sub(r"[^a-zA-Z0-9_-]+", "_", spec.raw_text.strip())[:40].strip("_")
        out_path = out_dir / f"{spec.slug}__{safe}__{hsh}__retrieval.json"
        component_count = sum(1 for h in evidence if h.get("source", "").startswith("component_"))
        payload = {
            "listing_spec": spec.to_dict(),
            "retrieval": {
                "probes": probes,
                "top_k_per_probe": TOP_K_PER_PROBE,
                "evidence_count": len(evidence),
                "tier_counts": tier_counts,
                "component_chunks": component_count,
            },
            "evidence": evidence,
        }
        out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[{spec.slug}] dry-run evidence -> {out_path.relative_to(ROOT)}")
        return out_path

    user_prompt = build_user_prompt(spec, evidence)
    print(f"[{spec.slug}] calling {LLM_MODEL} ...")
    raw, usage = call_llm(SYSTEM_PROMPT, user_prompt)

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"[!] LLM returned invalid JSON: {e}")
        parsed = {"issues": [], "_raw": raw}

    output = enrich_issues(parsed, evidence)
    component_count = sum(1 for h in evidence if h.get("source", "").startswith("component_"))
    output["coverage"] = build_coverage_note(spec, tier_counts, component_count=component_count)
    output["listing_spec"] = spec.to_dict()
    output["generated_at"] = datetime.now(timezone.utc).isoformat()
    output["llm_model"] = LLM_MODEL
    output["embed_model"] = EMBED_MODEL
    output["retrieval"] = {
        "probes": probes,
        "top_k_per_probe": TOP_K_PER_PROBE,
        "evidence_count": len(evidence),
        "tier_counts": tier_counts,
        "component_chunks": component_count,
    }
    output["usage"] = usage
    output["duration_seconds"] = round(time.time() - t0, 1)

    out_dir.mkdir(parents=True, exist_ok=True)
    hsh = hashlib.sha1(spec.raw_text.encode("utf-8")).hexdigest()[:8]
    safe = re.sub(r"[^a-zA-Z0-9_-]+", "_", spec.raw_text.strip())[:40].strip("_")
    out_path = out_dir / f"{spec.slug}__{safe}__{hsh}.json"
    out_path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    cov = output["coverage"]
    print(
        f"[{spec.slug}] {len(output.get('issues', []))} issues, "
        f"coverage={cov['confidence']} (t1={cov['engine_specific_chunks']} t2={cov['family_chunks']}), "
        f"{usage['prompt_tokens']}+{usage['completion_tokens']} tok, "
        f"{output['duration_seconds']}s -> {out_path.relative_to(ROOT)}"
    )
    return out_path


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--slug", required=True)
    p.add_argument("--text", default="", help="listing description (or use --listing-file)")
    p.add_argument("--out", default=str(OUT_DIR), help="output directory")
    p.add_argument("--dry-run", action="store_true", help="skip LLM; dump retrieved evidence only")
    p.add_argument("--listing-file", help="read listing text from a file")
    args = p.parse_args()
    text = args.text
    if args.listing_file:
        text = Path(args.listing_file).read_text(encoding="utf-8")
    spec = parse_listing(text, args.slug)
    run(spec, Path(args.out), dry_run=args.dry_run)


if __name__ == "__main__":
    main()
