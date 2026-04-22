#!/usr/bin/env python3
"""
fetch_nhtsa_tsb.py
──────────────────
Fetch NHTSA Technical Service Bulletins for VW Golf via data.transportation.gov Socrata API.
TSBs are manufacturer-issued repair instructions for known problems — high diagnostic value.

Output: data/raw/nhtsa_vw_golf_tsb.csv

Usage:
    python scripts/fetch_nhtsa_tsb.py
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
OUT_PATH = RAW_DIR / "nhtsa_vw_golf_tsb.csv"

# Socrata API endpoint for NHTSA TSBs
API_URL  = "https://data.transportation.gov/resource/hczg-qbhf.json"
PAGE_SIZE = 50000


def fetch_all(session: requests.Session) -> list[dict]:
    rows = []
    offset = 0
    while True:
        params = {
            "$where": "UPPER(MAKE) LIKE '%VOLKSWAGEN%' AND UPPER(MODEL) LIKE '%GOLF%'",
            "$limit": PAGE_SIZE,
            "$offset": offset,
            "$order": ":id",
        }
        log.info("Fetching offset=%d ...", offset)
        try:
            resp = session.get(API_URL, params=params, timeout=60)
            resp.raise_for_status()
            batch = resp.json()
        except Exception as e:
            log.warning("Request failed at offset %d: %s", offset, e)
            # Don't retry on auth errors — exit immediately
            if "403" in str(e) or "401" in str(e):
                log.error("Auth/access error — aborting. TSB API requires an app token.")
                break
            time.sleep(5)
            continue

        if not batch:
            break
        rows.extend(batch)
        log.info("  Got %d records (total so far: %d)", len(batch), len(rows))
        if len(batch) < PAGE_SIZE:
            break
        offset += PAGE_SIZE
        time.sleep(0.3)
    return rows


def flatten(rec: dict) -> dict:
    summary_parts = [
        rec.get("summary", ""),
        rec.get("mfr_subsystem", ""),
    ]
    combined = " ".join(p for p in summary_parts if p and str(p).strip())
    return {
        "nhtsa_id":       rec.get("nhtsa_id", ""),
        "tsb_id":         rec.get("tsb_id", ""),
        "date_added":     rec.get("date_added", ""),
        "mfr_date":       rec.get("mfr_date", ""),
        "make":           rec.get("make", ""),
        "model":          rec.get("model", ""),
        "model_yr":       rec.get("model_yr", ""),
        "components":     rec.get("nhtsacomponents", rec.get("components", "")),
        "mfr_component":  rec.get("mfr_component", ""),
        "mfr_subsystem":  rec.get("mfr_subsystem", ""),
        "summary":        str(rec.get("summary", ""))[:4000],
        "source":         "nhtsa_tsb",
    }


def main():
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    session.headers["User-Agent"] = "research/1.0"
    session.headers["Accept"] = "application/json"

    records = fetch_all(session)
    log.info("Total records fetched: %d", len(records))

    if not records:
        log.error("No records returned — check API endpoint or filters")
        return

    rows = [flatten(r) for r in records]
    df = pd.DataFrame(rows)

    # Drop rows with no summary
    df = df[df["summary"].notna() & (df["summary"].str.strip() != "")]
    log.info("After dropping empty summary: %d", len(df))

    df.to_csv(OUT_PATH, index=False)
    log.info("Saved to %s", OUT_PATH)

    log.info("\n=== COMPONENT DISTRIBUTION (top 15) ===")
    log.info("\n%s", df["components"].value_counts().head(15).to_string())

    log.info("\n=== MODEL YEAR DISTRIBUTION ===")
    log.info("\n%s", df["model_yr"].value_counts().sort_index().to_string())

    log.info("\n=== SAMPLE SUMMARIES ===")
    for _, row in df.head(3).iterrows():
        log.info("  [%s %s] %s", row["model_yr"], row["components"], str(row["summary"])[:200])


if __name__ == "__main__":
    main()
