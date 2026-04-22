import json
import chromadb
from chromadb.utils import embedding_functions
from pathlib import Path

import argparse

def normalize_filters(filters):
    # Backward-compatible: older files may contain only one filter dict.
    if isinstance(filters, dict) and "broad" in filters and "strict" in filters:
        return filters["broad"], filters["strict"]
    return filters, filters

def run_retrieval(listing_text, filters, collection_name="vw_golf_mk7_real", resolved_spec=None):
    # Initialize Persistent ChromaDB Client
    client = chromadb.PersistentClient(path="./chroma_db")
    
    # Use the official project embedding model
    embedding_func = embedding_functions.SentenceTransformerEmbeddingFunction(
        model_name="intfloat/multilingual-e5-base"
    )
    
    try:
        collection = client.get_collection(
            name=collection_name, 
            embedding_function=embedding_func
        )
    except Exception as e:
        print(f"Error: Collection '{collection_name}' not found. {e}")
        return []

    # PASS 1: Neutral technical probes in EN+TR for multilingual recall.
    model_name = resolved_spec.get('model_name', 'Vehicle') if resolved_spec else "Vehicle"
    engine_name = resolved_spec.get('engine_common_name', '') if resolved_spec else ""
    engine_name_query = engine_name.replace("_", " ")
    year = resolved_spec.get('listing_year') if resolved_spec else ""
    km = resolved_spec.get('listing_km') if resolved_spec else None
    transmissions = resolved_spec.get('transmissions', []) if resolved_spec else []
    fuel_type = resolved_spec.get('fuel_type', '') if resolved_spec else ""

    probes_en = [
        f"{model_name} {year} common issues and problems",
        f"{model_name} {fuel_type} engine reliability and common faults",
    ]
    probes_tr = [
        f"{model_name} {year} kronik sorunlar ve arizalar",
        f"{model_name} motor guvenilirlik ve yaygin sorunlar",
    ]

    if engine_name_query:
        probes_en.append(f"{model_name} {engine_name_query} common reliability issues")
        probes_tr.append(f"{model_name} {engine_name_query} motor sorunlari")

    if transmissions:
        for trans in transmissions:
            probes_en.append(f"{model_name} {trans} transmission gearbox problems")
            probes_tr.append(f"{model_name} {trans} sanziman sorunlari")
    else:
        probes_en.append(f"{model_name} transmission gearbox problems")
        probes_tr.append(f"{model_name} sanziman sorunlari")

    probes_en.extend([
        f"{model_name} electrical sensor issues faults",
        f"{model_name} suspension steering noise problems",
        f"{model_name} chronic faults defect failure",
        f"{model_name} long term ownership reliability issues",
        f"{model_name} high mileage common issues",
        f"{model_name} owner complaints and reliability",
        f"{model_name} ownership experience common problems",
        f"{model_name} things that break over time",
        f"{model_name} mechanic workshop common findings"
    ])
    probes_tr.extend([
        f"{model_name} elektrik sensor ariza sorun",
        f"{model_name} suspansiyon direksiyon ses sorunlari",
        f"{model_name} kronik ariza ve sikayetler",
        f"{model_name} uzun donem kullanim guvenilirlik sorunlari",
        f"{model_name} yuksek km yaygin sorunlar",
        f"{model_name} kullanici sikayetleri ve guvenilirlik",
        f"{model_name} sahiplik deneyimi yaygin sorunlar",
        f"{model_name} zamanla bozulan parcalar",
        f"{model_name} usta servis deneyimi yaygin sorunlar"
    ])

    # Mileage Probes
    if km:
        rounded_km = round(km / 10000) * 10000
        probes_en.append(f"{model_name} problems at {rounded_km} km")
        probes_tr.append(f"{model_name} {rounded_km} km sorunlar")
        if km > 150000:
            probes_en.append(f"{model_name} high mileage long term reliability issues")
            probes_tr.append(f"{model_name} yuksek km uzun donem sorunlar")
    probes_en.append(f"{model_name} high mileage reliability after 150000 km")
    probes_tr.append(f"{model_name} 150000 km sonrasi yaygin sorunlar")

    # Keep order stable while deduplicating.
    probes = list(dict.fromkeys(probes_en + probes_tr))

    formatted_chunks = []
    seen_ids = set()

    def add_results(res):
        if res['ids']:
            for i in range(len(res['ids'][0])):
                cid = res['ids'][0][i]
                if cid not in seen_ids:
                    chunk = {
                        "id": cid,
                        "text": res['documents'][0][i],
                        "metadata": res['metadatas'][0][i],
                        "distance": res['distances'][0][i]
                    }
                    formatted_chunks.append(chunk)
                    seen_ids.add(cid)

    broad_filter, strict_filter = normalize_filters(filters)

    print(f"DEBUG: Running {len(probes)} Neutral Technical Probes (strict + broad)...")
    for probe in probes:
        query_with_prefix = f"query: {probe}"
        strict_results = collection.query(
            query_texts=[query_with_prefix],
            n_results=14,
            where=strict_filter
        )
        add_results(strict_results)

        broad_results = collection.query(
            query_texts=[query_with_prefix],
            n_results=8,
            where=broad_filter
        )
        add_results(broad_results)

    # Feature-Specific Probes
    if resolved_spec and resolved_spec.get('has_sunroof'):
        feature_queries = [
            f"query: {model_name} sunroof leak problems",
            f"query: {model_name} sunroof rattles and water ingress",
            f"query: {model_name} sunroof su sizintisi ve tikirti"
        ]
        for fq in feature_queries:
            print(f"DEBUG: Running feature query: {fq}")
            sf_strict = collection.query(
                query_texts=[fq],
                n_results=14,
                where=strict_filter
            )
            add_results(sf_strict)

            sf_broad = collection.query(
                query_texts=[fq],
                n_results=8,
                where=broad_filter
            )
            add_results(sf_broad)
            
    return formatted_chunks

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--slug", default="renault_clio_mk4")
    parser.add_argument("--listing", default="data_raw/listing_clio_1.5_dci_icon_2016.txt")
    args = parser.parse_args()
    
    # Load Listing Text
    with open(args.listing, 'r', encoding='utf-8') as f:
        listing = f.read()
        
    # Load Pre-built Filters
    # Note: These should ideally be re-built per car, but for now we assume outputs/query_filters.json is updated by resolve_listing.py
    with open('outputs/query_filters.json', 'r') as f:
        filters = json.load(f)
        
    # Load Resolved Spec
    with open('outputs/resolved_spec.json', 'r') as f:
        spec = json.load(f)
        
    c_name = f"{args.slug}_real"
    print(f"Running query for '{c_name}' using listing '{args.listing}'...")
    chunks = run_retrieval(listing, filters, collection_name=c_name, resolved_spec=spec)
    
    print(f"Retrieved {len(chunks)} chunks.")
    
    with open('outputs/retrieved_chunks.json', 'w', encoding='utf-8') as f:
        json.dump(chunks, f, indent=2, ensure_ascii=False)
