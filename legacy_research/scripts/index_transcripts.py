"""Embed transcript chunks and index them in ChromaDB.

Reads data/processed/chunks/{slug}_chunks.jsonl and upserts into a persistent
Chroma collection at data/vector_store/chroma/, one collection per slug.

Uses intfloat/multilingual-e5-base. E5 requires "passage: " prefix at index
time (and "query: " at retrieval time).
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import chromadb
from sentence_transformers import SentenceTransformer

ROOT = Path(__file__).resolve().parents[1]
CHUNKS_DIR = ROOT / "data" / "processed" / "chunks"
STORE_DIR = ROOT / "data" / "vector_store" / "chroma"

MODEL_NAME = "intfloat/multilingual-e5-base"
BATCH_SIZE = 64


def load_chunks(slug: str) -> list[dict]:
    tagged = CHUNKS_DIR / f"{slug}_chunks_tagged.jsonl"
    plain = CHUNKS_DIR / f"{slug}_chunks.jsonl"
    path = tagged if tagged.exists() else plain
    if not path.exists():
        raise FileNotFoundError(f"Missing chunks: {path}")
    print(f"[{slug}] using chunk file: {path.name}")
    with path.open("r", encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def _join_tags(values: list) -> str:
    # Pipe-delimited with leading/trailing pipes so substring filters are unambiguous:
    # "|1.4_TSI|2.0_TDI|" — "|1.4_TSI|" match is exact.
    if not values:
        return ""
    return "|" + "|".join(str(v) for v in values) + "|"


def chunk_metadata(chunk: dict) -> dict:
    meta = {
        "video_id": chunk["video_id"],
        "start": float(chunk["start"]),
        "end": float(chunk["end"]),
        "language": chunk.get("language") or "unknown",
        "channel": chunk.get("channel") or "",
        "title": chunk.get("title") or "",
        "video_url_ts": chunk.get("video_url_ts") or "",
    }
    tags = chunk.get("tags") or {}
    meta["engines"] = _join_tags(tags.get("engines") or [])
    meta["engine_families"] = _join_tags(tags.get("engine_families") or [])
    meta["fuel_types"] = _join_tags(tags.get("fuel_types") or [])
    meta["drive_types"] = _join_tags(tags.get("drive_types") or [])
    meta["transmissions"] = _join_tags(tags.get("transmissions") or [])
    meta["trims"] = _join_tags(tags.get("trims") or [])
    meta["years"] = _join_tags(tags.get("years") or [])
    meta["mileages_km"] = _join_tags(tags.get("mileages_km") or [])
    meta["cross_generation_risk"] = bool(tags.get("cross_generation_risk"))
    meta["cross_generation_markers"] = _join_tags(tags.get("cross_generation_markers") or [])
    return meta


def index_slug(slug: str, rebuild: bool = False) -> None:
    chunks = load_chunks(slug)
    print(f"[{slug}] loaded {len(chunks)} chunks")

    print(f"[{slug}] loading model {MODEL_NAME} ...")
    model = SentenceTransformer(MODEL_NAME)

    STORE_DIR.mkdir(parents=True, exist_ok=True)
    client = chromadb.PersistentClient(path=str(STORE_DIR))

    if rebuild:
        try:
            client.delete_collection(slug)
            print(f"[{slug}] dropped existing collection")
        except Exception:
            pass

    collection = client.get_or_create_collection(
        name=slug,
        metadata={"hnsw:space": "cosine"},
    )

    texts = [f"passage: {c['text']}" for c in chunks]
    ids = [c["chunk_id"] for c in chunks]
    metas = [chunk_metadata(c) for c in chunks]
    docs = [c["text"] for c in chunks]

    print(f"[{slug}] embedding {len(texts)} chunks (batch={BATCH_SIZE}) ...")
    embeddings = model.encode(
        texts,
        batch_size=BATCH_SIZE,
        show_progress_bar=True,
        normalize_embeddings=True,
        convert_to_numpy=True,
    )

    # Upsert in batches to avoid single oversized payload.
    n = len(ids)
    for start in range(0, n, 256):
        end = min(start + 256, n)
        collection.upsert(
            ids=ids[start:end],
            embeddings=embeddings[start:end].tolist(),
            documents=docs[start:end],
            metadatas=metas[start:end],
        )

    print(f"[{slug}] collection count = {collection.count()} (expected {n})")
    print(f"[{slug}] persisted to {STORE_DIR}")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--slug", required=True)
    p.add_argument(
        "--rebuild",
        action="store_true",
        help="Drop the existing collection before indexing.",
    )
    args = p.parse_args()
    index_slug(args.slug, rebuild=args.rebuild)


if __name__ == "__main__":
    main()
