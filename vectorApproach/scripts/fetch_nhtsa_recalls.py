#!/usr/bin/env python3
"""
fetch_nhtsa_recalls.py
──────────────────────
Fetch NHTSA recall data for VW Golf via public API.
Combines defectSummary + Consequence + Remedy as full text.

Output: data/raw/nhtsa_vw_golf_recalls.csv

Usage:
    python scripts/fetch_nhtsa_recalls.py
"""

import logging
import time
from pathlib import Path

import pandas as pd
import requests

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger(__name__)

ROOT     = Path(__file__).resolve().parent.parent
RAW_DIR  = ROOT / "data" / "raw"
OUT_PATH = RAW_DIR / "nhtsa_vw_golf_recalls.csv"

API_BASE = "https://api.nhtsa.gov/recalls/recallsByVehicle"


def fetch_year(year: int, session: requests.Session) -> list[dict]:
    for attempt in range(1, 4):
        try:
            resp = session.get(API_BASE, params={"make": "VOLKSWAGEN", "model": "GOLF", "modelYear": year}, timeout=30)
            resp.raise_for_status()
            results = resp.json().get("results", [])
            log.info("  %d: %d recalls", year, len(results))
            return results
        except Exception as e:
            log.warning("  %d attempt %d failed: %s", year, attempt, e)
            time.sleep(3 * attempt)
    return []


def flatten(rec: dict, year: int) -> dict:
    # Combine all text fields into one summary for BERTopic
    parts = [
        rec.get("Summary", ""),
        rec.get("Consequence", ""),
        rec.get("Remedy", ""),
    ]
    combined = " ".join(p for p in parts if p and p.strip())
    return {
        "recall_id":    rec.get("NHTSACampaignNumber", ""),
        "model_year":   year,
        "make":         rec.get("Make", ""),
        "model":        rec.get("Model", ""),
        "component":    rec.get("Component", ""),
        "summary":      combined,
        "defect":       rec.get("Summary", ""),
        "consequence":  rec.get("Consequence", ""),
        "remedy":       rec.get("Remedy", ""),
        "date":         rec.get("ReportReceivedDate", ""),
        "source":       "nhtsa_recall",
    }


def main():
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    session.headers["User-Agent"] = "research/1.0"

    rows = []
    for year in range(2000, 2025):
        for rec in fetch_year(year, session):
            rows.append(flatten(rec, year))
        time.sleep(0.3)

    df = pd.DataFrame(rows)
    df = df[df["summary"].notna() & (df["summary"].str.strip() != "")]
    log.info("Total recalls: %d", len(df))

    df.to_csv(OUT_PATH, index=False)
    log.info("Saved to %s", OUT_PATH)

    log.info("\n=== COMPONENT DISTRIBUTION (top 15) ===")
    log.info("\n%s", df["component"].value_counts().head(15).to_string())

    log.info("\n=== MODEL YEAR DISTRIBUTION ===")
    log.info("\n%s", df["model_year"].value_counts().sort_index().to_string())


if __name__ == "__main__":
    main()
