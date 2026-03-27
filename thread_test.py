"""
diagnose_coverage.py
────────────────────
Run against your threads JSON to find out how many threads have
parseable year + HP + displacement before committing to the
engine-family lookup approach.

Usage:
    python diagnose_coverage.py --input threads.json
    python diagnose_coverage.py --input threads.json --verbose
    python diagnose_coverage.py --input threads.json --export coverage_report.xlsx
"""

import json
import re
import argparse
from collections import defaultdict, Counter
from pathlib import Path

# ── Engine family lookup ──────────────────────────────────────────────────────
# (displacement, hp, year_range) → family
# Add / extend rows as you discover more variants in your corpus.
ENGINE_FAMILY_LOOKUP = [
    # EA111 petrol
    ("1.2_TSI",  60, range(2009, 2016), "EA111_CBZB"),
    ("1.2_TSI",  70, range(2009, 2016), "EA111_CBZA"),
    ("1.2_TSI",  86, range(2009, 2016), "EA111_CBZC"),
    ("1.4_TSI",  85, range(2006, 2013), "EA111_CAXA"),
    ("1.4_TSI", 122, range(2006, 2012), "EA111_CAVD"),
    ("1.4_TSI", 140, range(2007, 2013), "EA111_CAVH"),
    ("1.4_TSI", 160, range(2007, 2012), "EA111_CTHD"),
    # EA211 petrol
    ("1.2_TSI",  86, range(2012, 2021), "EA211_CJZB"),
    ("1.2_TSI", 105, range(2012, 2021), "EA211_CJZA"),
    ("1.4_TSI", 122, range(2012, 2020), "EA211_CMBA"),
    ("1.4_TSI", 125, range(2012, 2020), "EA211_CZCA"),
    ("1.4_TSI", 150, range(2012, 2020), "EA211_CZDA"),
    ("1.5_TSI", 130, range(2017, 2025), "EA211_DADA"),
    ("1.5_TSI", 150, range(2017, 2025), "EA211_DPCA"),
    # EA188 / EA189 diesel
    ("1.6_TDI",  90, range(2008, 2016), "EA189_CAYB"),
    ("1.6_TDI", 105, range(2008, 2016), "EA189_CAYC"),
    ("2.0_TDI", 110, range(2008, 2016), "EA189_CLJA"),
    ("2.0_TDI", 140, range(2008, 2016), "EA189_CFHC"),
    ("2.0_TDI", 150, range(2008, 2016), "EA189_CRBC"),
    # EA288 diesel
    ("1.6_TDI",  90, range(2013, 2025), "EA288_CXXB"),
    ("1.6_TDI", 105, range(2013, 2025), "EA288_CRKB"),
    ("2.0_TDI", 110, range(2013, 2025), "EA288_CRKB"),
    ("2.0_TDI", 150, range(2013, 2025), "EA288_DFGA"),
    ("2.0_TDI", 184, range(2013, 2025), "EA288_DFHA"),
]

DISPLACEMENT_ALIASES = {
    "1.2tsi": "1.2_TSI", "1.2 tsi": "1.2_TSI",
    "1.4tsi": "1.4_TSI", "1.4 tsi": "1.4_TSI",
    "1.5tsi": "1.5_TSI", "1.5 tsi": "1.5_TSI",
    "1.6tdi": "1.6_TDI", "1.6 tdi": "1.6_TDI",
    "2.0tdi": "2.0_TDI", "2.0 tdi": "2.0_TDI",
    "2.0tsi": "2.0_TSI", "2.0 tsi": "2.0_TSI",
}

def resolve_engine_family(displacement, hp, year):
    """Return (family_code, confidence) given parsed fields."""
    if not displacement or not hp or not year:
        return None, "missing_fields"

    norm_disp = displacement.upper().replace(" ", "_")
    hp = int(hp)
    year = int(year)

    for (d, h, yr, family) in ENGINE_FAMILY_LOOKUP:
        if norm_disp == d and hp == h and year in yr:
            return family, "exact"

    # Fallback: year + displacement without HP match
    for (d, h, yr, family) in ENGINE_FAMILY_LOOKUP:
        if norm_disp == d and year in yr:
            return family.split("_")[0] + "_" + d.split("_")[0], "year_disp_only"

    return None, "no_match"


# ── Regex extractors ──────────────────────────────────────────────────────────

_YEAR_RE    = re.compile(r"\b(200[0-9]|201[0-9]|202[0-5])\b")
_HP_RE      = re.compile(
    r"(\d{2,3})\s*(?:hp|bg|beygir|bhp|ps|cv|kw)\b", re.IGNORECASE
)
_DISP_RE    = re.compile(
    r"\b(1\.2|1\.4|1\.5|1\.6|2\.0)\s*(tsi|tdi|gti|gtd|tfsi)\b", re.IGNORECASE
)
_KM_RE      = re.compile(
    r"(\d{2,3})[.\s]?(?:000|bin)\s*(?:km|kilometre)?|"
    r"(\d{3,6})\s*km\b",
    re.IGNORECASE
)


def extract_fields(text: str) -> dict:
    t = text.lower()

    year = _YEAR_RE.search(t)
    hp   = _HP_RE.search(t)
    disp = _DISP_RE.search(t)

    km_match = _KM_RE.search(t)
    if km_match:
        raw = km_match.group(1) or km_match.group(2)
        km_val = int(raw) * 1000 if km_match.group(1) else int(raw)
        km_val = km_val if 1_000 < km_val < 600_000 else None
    else:
        km_val = None

    disp_norm = None
    if disp:
        key = f"{disp.group(1)}{disp.group(2).lower()}"
        disp_norm = DISPLACEMENT_ALIASES.get(key) or \
                    DISPLACEMENT_ALIASES.get(f"{disp.group(1)} {disp.group(2).lower()}")

    return {
        "year":        int(year.group(1)) if year else None,
        "hp":          int(hp.group(1))   if hp   else None,
        "displacement": disp_norm,
        "mileage_km":  km_val,
    }


def extract_from_thread(thread: dict) -> dict:
    """
    Priority order for extracting structured metadata:
    1. Thread name
    2. First message (opener)
    3. First 3 messages combined (fallback)
    Fields are merged — whatever is found earliest wins.
    """
    sources = [
        ("thread_name",    thread.get("thread_name", "")),
        ("first_message",  thread["messages"][0] if thread.get("messages") else ""),
        ("first_3",        " ".join((thread.get("messages") or [])[:3])),
    ]

    merged = {}
    source_map = {}

    for src_label, text in sources:
        if not text:
            continue
        fields = extract_fields(text)
        for k, v in fields.items():
            if v is not None and k not in merged:
                merged[k] = v
                source_map[k] = src_label

    family, confidence = resolve_engine_family(
        merged.get("displacement"),
        merged.get("hp"),
        merged.get("year"),
    )

    return {**merged, "engine_family": family,
            "family_confidence": confidence, "source_map": source_map}


# ── Main diagnostic ───────────────────────────────────────────────────────────

def run_diagnostics(threads: list, verbose: bool = False) -> dict:
    N = len(threads)
    results = []

    field_found      = Counter()
    family_conf      = Counter()
    family_dist      = Counter()
    unresolved_combos = Counter()   # (disp, hp, year) combos we couldn't map

    for thread in threads:
        r = extract_from_thread(thread)
        results.append(r)

        for f in ("year", "hp", "displacement", "mileage_km"):
            if r.get(f) is not None:
                field_found[f] += 1

        family_conf[r["family_confidence"]] += 1

        if r.get("engine_family"):
            family_dist[r["engine_family"]] += 1

        if r["family_confidence"] == "no_match":
            combo = (r.get("displacement"), r.get("hp"), r.get("year"))
            unresolved_combos[combo] += 1

    # ── Summary ──────────────────────────────────────────────────────────────
    print("\n" + "═" * 60)
    print(f"  METADATA COVERAGE REPORT  ({N:,} threads)")
    print("═" * 60)

    print("\n── Field extraction rates ──────────────────────────────────")
    for f in ("year", "hp", "displacement", "mileage_km"):
        n = field_found[f]
        print(f"  {f:<18} {n:>5,} / {N:,}  ({100*n/N:.1f}%)")

    print("\n── Engine family resolution ────────────────────────────────")
    for conf, n in family_conf.most_common():
        print(f"  {conf:<22} {n:>5,}  ({100*n/N:.1f}%)")

    resolved = family_conf["exact"] + family_conf["year_disp_only"]
    print(f"\n  ✓ Resolvable (exact + approx): {resolved:,}  ({100*resolved/N:.1f}%)")

    print("\n── Engine family distribution (resolved only) ──────────────")
    for fam, n in family_dist.most_common():
        bar = "█" * int(n / N * 40)
        print(f"  {fam:<26} {n:>4,}  {bar}")

    print("\n── Top unresolved (disp, hp, year) combos ──────────────────")
    print("  (these need new rows in ENGINE_FAMILY_LOOKUP)")
    for combo, n in unresolved_combos.most_common(15):
        print(f"  disp={combo[0]:<10} hp={str(combo[1]):<6} year={combo[2]}  → {n}×")

    if verbose:
        print("\n── Sample extractions (first 10 threads) ───────────────────")
        for i, (thread, r) in enumerate(zip(threads[:10], results[:10])):
            print(f"\n  [{i+1}] {thread.get('thread_name','')[:70]}")
            for k in ("year","hp","displacement","mileage_km","engine_family","family_confidence"):
                v = r.get(k)
                src = r["source_map"].get(k, "—")
                if k not in ("engine_family","family_confidence"):
                    print(f"       {k:<18} {str(v):<12}  (from: {src})")
                else:
                    print(f"       {k:<18} {v}")

    print("\n" + "═" * 60 + "\n")
    return {"threads": threads, "results": results, "N": N,
            "field_found": field_found, "family_conf": family_conf,
            "family_dist": family_dist, "unresolved_combos": unresolved_combos}


def export_to_excel(threads, results, path):
    try:
        import openpyxl
        from openpyxl import Workbook
    except ImportError:
        print("openpyxl not installed — skipping Excel export (pip install openpyxl)")
        return

    wb = Workbook()
    ws = wb.active
    ws.title = "coverage"

    headers = ["thread_name", "year", "hp", "displacement",
               "mileage_km", "engine_family", "family_confidence",
               "year_src", "hp_src", "displacement_src", "mileage_src"]
    ws.append(headers)

    for thread, r in zip(threads, results):
        sm = r.get("source_map", {})
        ws.append([
            thread.get("thread_name", ""),
            r.get("year"), r.get("hp"), r.get("displacement"),
            r.get("mileage_km"), r.get("engine_family"),
            r.get("family_confidence"),
            sm.get("year"), sm.get("hp"),
            sm.get("displacement"), sm.get("mileage_km"),
        ])

    wb.save(path)
    print(f"Saved Excel report → {path}")


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Metadata coverage diagnostic")
    parser.add_argument("--input",   required=True, help="Path to threads JSON file")
    parser.add_argument("--verbose", action="store_true", help="Print sample extractions")
    parser.add_argument("--export",  default=None, help="Export results to Excel (.xlsx)")
    args = parser.parse_args()

    path = Path(args.input)
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")

    with open(path, encoding="utf-8") as f:
        data = json.load(f)

    # Accept both {"threads": [...]} and plain [...]
    threads = data["threads"] if isinstance(data, dict) and "threads" in data else data

    diag = run_diagnostics(threads, verbose=args.verbose)

    if args.export:
        export_to_excel(threads, diag["results"], args.export)