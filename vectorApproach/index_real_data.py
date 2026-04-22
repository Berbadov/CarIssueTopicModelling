import json
import chromadb
from chromadb.utils import embedding_functions
from pathlib import Path

import argparse

def index_chunks(slug):
    client = chromadb.PersistentClient(path="./chroma_db")
    
    # Use the official project embedding model
    embedding_func = embedding_functions.SentenceTransformerEmbeddingFunction(
        model_name="intfloat/multilingual-e5-base"
    )
    
    collection_name = f"{slug}_real"
    
    # DELETE existing collection to force metadata update
    try:
        client.delete_collection(name=collection_name)
        print(f"Deleted existing collection: {collection_name}")
    except Exception:
        pass
    
    collection = client.create_collection(
        name=collection_name,
        embedding_function=embedding_func
    )
    
    chunks_path = Path(f"data_processed/chunks/{slug}_chunks_tagged.jsonl")
    if not chunks_path.exists():
        print(f"Error: {chunks_path} not found.")
        return

    ids = []
    documents = []
    metadatas = []
    
    count = 0
    with open(chunks_path, 'r', encoding='utf-8') as f:
        for line in f:
            chunk = json.loads(line)
            
            # MANDATORY: Add "passage: " prefix for E5 model indexing
            text_with_prefix = f"passage: {chunk['text']}"
            
            # Flatten tags for ChromaDB metadata (it doesn't support lists)
            tags = chunk.get('tags', {})
            meta = {
                "model": slug, # Store model name
                "engine_family": tags.get('engine_families')[0] if tags.get('engine_families') else "unknown",
                "fuel_type": tags.get('fuel_types')[0] if tags.get('fuel_types') else "unknown",
                "timing_drive": tags.get('drive_types')[0] if tags.get('drive_types') else "unknown",
                "is_flagged": tags.get('cross_generation_risk', False),
                "has_sunroof": tags.get('has_sunroof', False),
                # Convert lists to comma-separated strings for filtering
                "transmission": ",".join(tags.get('transmissions', [])),
                "engine_common_names": ",".join(tags.get('engines', [])),
                "years": ",".join(map(str, tags.get('years', []))),
                "power_hp": ",".join(map(str, tags.get('power_hp', []))),
                "video_id": chunk['video_id'],
                "start": chunk['start']
            }
            
            ids.append(chunk['chunk_id'])
            documents.append(text_with_prefix)
            metadatas.append(meta)
            count += 1
            
            # Batch insert every 100 chunks
            if len(ids) >= 100:
                collection.add(ids=ids, documents=documents, metadatas=metadatas)
                ids, documents, metadatas = [], [], []
                print(f"Indexed {count} chunks...")

    # Final batch
    if ids:
        collection.add(ids=ids, documents=documents, metadatas=metadatas)
        print(f"Final batch indexed. Total: {count}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--slug", default="renault_clio_mk4")
    args = parser.parse_args()
    index_chunks(args.slug)
