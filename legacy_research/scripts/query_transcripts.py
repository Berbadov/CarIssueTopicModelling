"""CLI for inspecting transcript retrieval from a Chroma collection.

Example:
    python scripts/query_transcripts.py --slug vw_golf_mk7 \
        --q "timing chain tensioner rattle" --k 10
    python scripts/query_transcripts.py --slug vw_golf_mk7 \
        --q "soguk calistirma sesi" --k 5 --lang tr
"""
from __future__ import annotations

import argparse
from pathlib import Path

import chromadb
from sentence_transformers import SentenceTransformer

ROOT = Path(__file__).resolve().parents[1]
STORE_DIR = ROOT / "data" / "vector_store" / "chroma"
MODEL_NAME = "intfloat/multilingual-e5-base"

_MODEL: SentenceTransformer | None = None


def embed_query(text: str) -> list[float]:
    global _MODEL
    if _MODEL is None:
        _MODEL = SentenceTransformer(MODEL_NAME)
    vec = _MODEL.encode(
        [f"query: {text}"],
        normalize_embeddings=True,
        convert_to_numpy=True,
    )
    return vec[0].tolist()


def query(
    slug: str,
    q: str,
    k: int = 10,
    lang: str | None = None,
    snippet_chars: int = 220,
) -> None:
    client = chromadb.PersistentClient(path=str(STORE_DIR))
    coll = client.get_collection(slug)

    where = {"language": lang} if lang else None
    emb = embed_query(q)

    res = coll.query(
        query_embeddings=[emb],
        n_results=k,
        where=where,
    )

    docs = res["documents"][0]
    metas = res["metadatas"][0]
    dists = res["distances"][0]

    print(f"\n=== [{slug}] q={q!r}  k={k}  lang={lang or 'any'}  hits={len(docs)}")
    for rank, (doc, meta, dist) in enumerate(zip(docs, metas, dists), 1):
        sim = 1.0 - dist  # cosine distance -> similarity
        start = meta.get("start", 0.0)
        end = meta.get("end", 0.0)
        channel = meta.get("channel", "")
        title = meta.get("title", "")
        url = meta.get("video_url_ts", "")
        print(
            f"\n#{rank} sim={sim:.3f}  "
            f"[{start:.1f}-{end:.1f}s]  {meta.get('language','?')}  "
            f"{channel} — {title[:70]}"
        )
        print(f"    {url}")
        snippet = doc.strip().replace("\n", " ")
        if len(snippet) > snippet_chars:
            snippet = snippet[:snippet_chars] + "..."
        print(f"    {snippet}")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--slug", required=True)
    p.add_argument("--q", required=True, help="natural-language query")
    p.add_argument("--k", type=int, default=10)
    p.add_argument("--lang", default=None, help="filter by language code (e.g. en, tr)")
    p.add_argument("--chars", type=int, default=220, help="snippet length")
    args = p.parse_args()
    query(args.slug, args.q, k=args.k, lang=args.lang, snippet_chars=args.chars)


if __name__ == "__main__":
    main()
