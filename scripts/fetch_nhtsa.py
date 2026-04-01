#!/usr/bin/env python3
"""
fetch_nhtsa.py
──────────────
Fetch NHTSA VW Golf complaints via the public JSON API (per model year).
No ZIP download needed — returns clean named JSON fields.

Output:  data/raw/nhtsa_vw_golf.csv

Usage:
    python scripts/fetch_nhtsa.py
    python scripts/fetch_nhtsa.py --min-year 2005 --max-year 2024
"""

import argparse
import logging
import time
from pathlib import Path

import pandas as pd
import requests

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

ROOT     = Path(__file__).resolve().parent.parent
RAW_DIR  = ROOT / "data" / "raw"
OUT_PATH = RAW_DIR / "nhtsa_vw_golf.csv"

API_BASE = "https://api.nhtsa.gov/complaints/complaintsByVehicle"


def fetch_year(make: str, model: str, year: int, session: requests.Session) -> list[dict]:
    url    = API_BASE
    params = {"make": make, "model": model, "modelYear": year}
    for attempt in range(1, 4):
        try:
            resp = session.get(url, params=params, timeout=30)
            resp.raise_for_status()
            data = resp.json()
            results = data.get("results", [])
            log.info("  %d: %d complaints", year, len(results))
            return results
        except Exception as e:
            log.warning("  %d: attempt %d failed — %s", year, attempt, e)
            time.sleep(3 * attempt)
    return []


def flatten_complaint(rec: dict, year: int) -> dict:
    """Flatten NHTSA JSON record to a single dict row."""
    # components may be a list of dicts, a plain string, or absent
    components = rec.get("components", rec.get("component", ""))
    if isinstance(components, list):
        comp_names = "; ".join(
            (c.get("name", "") if isinstance(c, dict) else str(c))
            for c in components
        )
    else:
        comp_names = str(components) if components else ""

    return {
        "complaint_id":  rec.get("odiNumber"),
        "model_year":    year,
        "make":          rec.get("manufacturer", ""),
        "model":         "GOLF",
        "component":     comp_names,
        "description":   rec.get("summary", ""),
        "date_filed":    rec.get("dateComplaintFiled", ""),
        "date_incident": rec.get("dateOfIncident", ""),
        "miles":         rec.get("mileage"),
        "crash":         rec.get("crash", False),
        "fire":          rec.get("fire", False),
        "injured":       rec.get("numberOfInjuries", 0),
        "deaths":        rec.get("numberOfDeaths", 0),
        "vin":           rec.get("vin", ""),
    }


def main():
    parser = argparse.ArgumentParser(description="Fetch NHTSA VW Golf complaints via API")
    parser.add_argument("--min-year", type=int, default=2000)
    parser.add_argument("--max-year", type=int, default=2024)
    args = parser.parse_args()

    RAW_DIR.mkdir(parents=True, exist_ok=True)

    years   = range(args.min_year, args.max_year + 1)
    session = requests.Session()
    session.headers.update({"User-Agent": "research/1.0"})

    all_rows = []
    for year in years:
        records = fetch_year("VOLKSWAGEN", "GOLF", year, session)
        for rec in records:
            all_rows.append(flatten_complaint(rec, year))
        time.sleep(0.3)   # be polite to the API

    df = pd.DataFrame(all_rows)
    log.info("Total complaints fetched: %d", len(df))

    # Drop rows with empty description
    df = df[df["description"].notna() & (df["description"].str.strip() != "")]
    log.info("After dropping empty descriptions: %d", len(df))

    df.to_csv(OUT_PATH, index=False)
    log.info("Saved to %s", OUT_PATH)

    log.info("\n=== COMPONENT DISTRIBUTION (top 20) ===")
    # Components field may contain multiple values — expand
    all_comps = df["component"].str.split(";").explode().str.strip()
    log.info("\n%s", all_comps.value_counts().head(20).to_string())

    log.info("\n=== MODEL YEAR DISTRIBUTION ===")
    log.info("\n%s", df["model_year"].value_counts().sort_index().to_string())


if __name__ == "__main__":
    main()
