"""
VectorApproach One-Click Pipeline
---------------------------------
Automates the flow from Ad Listing to Prioritized Issue Report.

Steps:
1. Resolve Listing (Ad text -> Technical Spec)
2. Build Filters (Spec -> ChromaDB query)
3. Retrieve Chunks (Vector Search)
4. Rank & Filter (Technical Relevance + Issue Signal)

Usage:
    python main_pipeline.py --slug renault_clio_mk4 --listing data_raw/listing_clio_1.5_dci_icon_2016.txt
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path

def run_step(name, cmd):
    print(f"\n>>> Step: {name}")
    print(f"Executing: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8')
    if result.returncode != 0:
        print(f"ERROR in {name}:")
        print(result.stderr)
        sys.exit(1)
    if result.stdout:
        print(result.stdout.strip())
    return result.stdout

def main():
    parser = argparse.ArgumentParser(description="One-click Vector RAG Pipeline")
    parser.add_argument("--slug", required=True, help="Car model slug (e.g. vw_golf_mk7)")
    parser.add_argument("--listing", required=True, help="Path to listing text file")
    parser.add_argument("--scaffold", help="Optional override for scaffold YAML path")
    args = parser.parse_args()

    listing_path = Path(args.listing)
    if not listing_path.exists():
        print(f"Error: Listing file not found: {listing_path}")
        sys.exit(1)

    scaffold_path = args.scaffold or f"scaffolds/{args.slug}.yaml"
    if not Path(scaffold_path).exists():
        print(f"Error: Scaffold file not found: {scaffold_path}")
        sys.exit(1)

    # 1. RESOLVE LISTING
    run_step("Resolving Listing", [
        sys.executable, "resolve_listing.py",
        "--listing", str(listing_path),
        "--scaffold", scaffold_path
    ])

    # 2. BUILD FILTERS
    run_step("Building ChromaDB Filters", [
        sys.executable, "build_filters.py"
    ])

    # 3. RETRIEVAL
    run_step("Retrieving Chunks from Vector DB", [
        sys.executable, "query_engine.py",
        "--slug", args.slug,
        "--listing", str(listing_path)
    ])

    # 4. RANK & FILTER
    run_step("Ranking and Filtering Results", [
        sys.executable, "rank_and_filter.py"
    ])

    print("\n" + "="*50)
    print("PIPELINE COMPLETE")
    print("="*50)
    
    # Show top 5 issues
    try:
        with open('outputs/final_output.json', 'r', encoding='utf-8') as f:
            final = json.load(f)
            print(f"\nTop {min(5, len(final))} Prioritized Issue Chunks:")
            for i, chunk in enumerate(final[:5]):
                tier = chunk.get('tier', '?')
                text = chunk.get('text', '')[:150].replace('\n', ' ')
                print(f"{i+1}. [Tier {tier}] {text}...")
    except Exception as e:
        print(f"Could not read outputs/final_output.json: {e}")

    print(f"\nFull report saved to: outputs/final_output.json")

if __name__ == "__main__":
    main()
