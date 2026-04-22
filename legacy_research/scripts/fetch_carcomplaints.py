#!/usr/bin/env python3
"""
fetch_carcomplaints.py
──────────────────────
Scrape CarComplaints.com VW Golf complaint narratives.
3-level crawl: year → category → individual complaint page.

Output: data/raw/carcomplaints_vw_golf.csv

Usage:
    python scripts/fetch_carcomplaints.py
    python scripts/fetch_carcomplaints.py --min-year 2010 --max-year 2022
"""

import argparse
import logging
import re
import time
from pathlib import Path

import pandas as pd
import requests
from bs4 import BeautifulSoup

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger(__name__)

ROOT     = Path(__file__).resolve().parent.parent
RAW_DIR  = ROOT / "data" / "raw"
OUT_PATH = RAW_DIR / "carcomplaints_vw_golf.csv"

BASE_URL = "https://www.carcomplaints.com"
GOLF_URL = f"{BASE_URL}/Volkswagen/Golf"
DELAY    = 0.6   # seconds between requests — polite crawling

HEADERS  = {
    "User-Agent": "Mozilla/5.0 (research bot; academic use)",
    "Accept-Language": "en-US,en;q=0.9",
}

# All known category slugs from the 2015 page
CATEGORIES = [
    "engine", "transmission", "fuel_system", "electrical", "cooling_system",
    "suspension", "brakes", "steering", "clutch", "drivetrain",
    "windows_windshield", "seat_belts_air_bags", "lights", "body_paint",
    "accessories-interior", "accessories-exterior", "exhaust_system",
    "wheels_hubs", "miscellaneous",
]


def get(url: str, session: requests.Session) -> BeautifulSoup | None:
    try:
        resp = session.get(url, timeout=20)
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        time.sleep(DELAY)
        return BeautifulSoup(resp.text, "html.parser")
    except Exception as e:
        log.warning("GET %s failed: %s", url, e)
        return None


def get_complaint_links(year: int, category: str, session: requests.Session) -> list[str]:
    """Return list of complaint page URLs for a given year+category."""
    url  = f"{GOLF_URL}/{year}/{category}/"
    soup = get(url, session)
    if not soup:
        return []
    links = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if f"/Volkswagen/Golf/{year}/{category}/" in href and href.endswith(".shtml"):
            full = href if href.startswith("http") else BASE_URL + href
            if full not in links:
                links.append(full)
    return links


def parse_complaint_page(url: str, year: int, category: str, session: requests.Session) -> list[dict]:
    """Extract individual complaints from a complaint detail page."""
    soup = get(url, session)
    if not soup:
        return []

    rows = []
    # Each complaint is in a div with class "problem" or similar
    # Try multiple selectors
    problem_divs = (
        soup.find_all("div", class_="problem") or
        soup.find_all("div", class_=re.compile(r"problem", re.I))
    )

    if not problem_divs:
        # Fallback: extract all paragraph text as one complaint
        body = soup.find("div", id=re.compile(r"content|main", re.I))
        if body:
            text = body.get_text(" ", strip=True)
            if len(text) > 50:
                rows.append({
                    "source":    "carcomplaints",
                    "model_year": year,
                    "category":  category,
                    "url":       url,
                    "mileage":   None,
                    "summary":   text[:2000],
                })
        return rows

    for div in problem_divs:
        text = div.get_text(" ", strip=True)

        # Extract mileage
        mileage = None
        m = re.search(r"(\d[\d,]+)\s*miles?", text, re.IGNORECASE)
        if m:
            try:
                mileage = int(m.group(1).replace(",", ""))
            except ValueError:
                pass

        if len(text) > 30:
            rows.append({
                "source":    "carcomplaints",
                "model_year": year,
                "category":  category,
                "url":       url,
                "mileage":   mileage,
                "summary":   text[:2000],
            })

    return rows


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--min-year", type=int, default=2000)
    parser.add_argument("--max-year", type=int, default=2022)
    args = parser.parse_args()

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    session.headers.update(HEADERS)

    all_rows = []
    years = range(args.min_year, args.max_year + 1)

    for year in years:
        log.info("=== Year %d ===", year)
        year_total = 0

        for category in CATEGORIES:
            complaint_links = get_complaint_links(year, category, session)
            if not complaint_links:
                continue
            log.info("  %s: %d complaint pages", category, len(complaint_links))

            for link in complaint_links:
                rows = parse_complaint_page(link, year, category, session)
                all_rows.extend(rows)
                year_total += len(rows)

        log.info("  Year %d total: %d complaints", year, year_total)

        # Checkpoint save every year
        if all_rows:
            pd.DataFrame(all_rows).to_csv(OUT_PATH, index=False)

    df = pd.DataFrame(all_rows)
    log.info("Total complaints scraped: %d", len(df))
    df.to_csv(OUT_PATH, index=False)
    log.info("Saved to %s", OUT_PATH)

    log.info("\n=== CATEGORY DISTRIBUTION ===")
    log.info("\n%s", df["category"].value_counts().to_string())

    log.info("\n=== YEAR DISTRIBUTION ===")
    log.info("\n%s", df["model_year"].value_counts().sort_index().to_string())


if __name__ == "__main__":
    main()
