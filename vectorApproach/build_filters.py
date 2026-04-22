import json

def build_chroma_filters(resolved_spec):
    # Broad pass keeps recall high.
    broad_filter = {
        "is_flagged": {"$eq": False}
    }

    # Strict pass improves precision when metadata is available.
    strict_terms = [{"is_flagged": {"$eq": False}}]
    if resolved_spec.get("fuel_type"):
        strict_terms.append({"fuel_type": {"$eq": resolved_spec["fuel_type"]}})
    if resolved_spec.get("timing_drive"):
        strict_terms.append({"timing_drive": {"$eq": resolved_spec["timing_drive"]}})
    if resolved_spec.get("engine_family"):
        strict_terms.append({"engine_family": {"$eq": resolved_spec["engine_family"]}})

    strict_filter = {"$and": strict_terms} if len(strict_terms) > 1 else broad_filter

    return {
        "broad": broad_filter,
        "strict": strict_filter
    }

if __name__ == "__main__":
    with open('outputs/resolved_spec.json', 'r') as f:
        resolved = json.load(f)
    
    chroma_where = build_chroma_filters(resolved)
    
    print("Generated ChromaDB Filters:")
    print(json.dumps(chroma_where, indent=2))
    
    with open('outputs/query_filters.json', 'w') as f:
        json.dump(chroma_where, f, indent=2)
