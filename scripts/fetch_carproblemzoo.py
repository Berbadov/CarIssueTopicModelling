#!/usr/bin/env python3
"""
fetch_carproblemzoo.py
──────────────────────
Scrape CarProblemZoo VW Golf complaint descriptions.
2-level crawl: year page → category problem pages.

Output: data/raw/carproblemzoo_vw_golf.csv

Usage:
    python scripts/fetch_carproblemzoo.py
    python scripts/fetch_carproblemzoo.py --min-year 2000 --max-year 2023
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
OUT_PATH = RAW_DIR / "carproblemzoo_vw_golf.csv"

BASE_URL  = "https://www.carproblemzoo.com"
DELAY     = 0.6

HEADERS = {
    "User-Agent": "Mozilla/5.0 (research bot; academic use)",
    "Accept-Language": "en-US,en;q=0.9",
}


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


def get_category_links(year: int, session: requests.Session) -> list[tuple[str, str]]:
    """Return list of (category_name, url) for a given year."""
    url  = f"{BASE_URL}/volkswagen/golf/{year}/"
    soup = get(url, session)
    if not soup:
        return []

    links = []
    prefix = f"{year}-volkswagen-golf"
    for a in soup.find_all("a", href=True):
        href = a["href"]
        # Category pages use relative hrefs like: 2015-volkswagen-golf-engine-problems.php
        if prefix in href and "problems" in href:
            name = a.get_text(strip=True)
            if href.startswith("http"):
                full = href
            else:
                # Relative href — construct full URL under the year directory
                full = f"{BASE_URL}/volkswagen/golf/{year}/{href.lstrip('/')}"
            if full not in [l[1] for l in links] and name:
                links.append((name, full))
    return links


def parse_category_page(url: str, year: int, category: str, session: requests.Session) -> list[dict]:
    """Extract individual complaint descriptions from a category problem page."""
    soup = get(url, session)
    if not soup:
        return []

    rows = []
    # Complaints are in div.problem-item or h2 + p structure
    problem_items = soup.find_all("div", class_="problem-item")

    if problem_items:
        for div in problem_items:
            text = div.get_text(" ", strip=True)
            # Extract failure date
            date_match = re.search(r"Failure Date[:\s]+([0-9/]+)", text)
            failure_date = date_match.group(1) if date_match else None
            # Extract mileage from text
            mileage = None
            m = re.search(r"(\d[\d,]+)\s*miles?", text, re.IGNORECASE)
            if m:
                try:
                    mileage = int(m.group(1).replace(",", ""))
                except ValueError:
                    pass
            if len(text) > 30:
                rows.append({
                    "source":      "carproblemzoo",
                    "model_year":  year,
                    "category":    category,
                    "url":         url,
                    "failure_date": failure_date,
                    "mileage":     mileage,
                    "summary":     text[:2000],
                })
    else:
        # Fallback: find h2 + following p tags pattern
        for h2 in soup.find_all("h2"):
            text_parts = [h2.get_text(strip=True)]
            for sib in h2.find_next_siblings():
                if sib.name == "h2":
                    break
                if sib.name in ("p", "div"):
                    text_parts.append(sib.get_text(strip=True))
            text = " ".join(text_parts)
            failure_date = None
            m_date = re.search(r"Failure Date[:\s]+([0-9/]+)", text)
            if m_date:
                failure_date = m_date.group(1)
            mileage = None
            m = re.search(r"(\d[\d,]+)\s*miles?", text, re.IGNORECASE)
            if m:
                try:
                    mileage = int(m.group(1).replace(",", ""))
                except ValueError:
                    pass
            if len(text) > 30:
                rows.append({
                    "source":      "carproblemzoo",
                    "model_year":  year,
                    "category":    category,
                    "url":         url,
                    "failure_date": failure_date,
                    "mileage":     mileage,
                    "summary":     text[:2000],
                })

    return rows


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--min-year", type=int, default=2000)
    parser.add_argument("--max-year", type=int, default=2023)
    args = parser.parse_args()

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    session.headers.update(HEADERS)

    all_rows = []

    for year in range(args.min_year, args.max_year + 1):
        log.info("=== Year %d ===", year)
        cat_links = get_category_links(year, session)
        if not cat_links:
            log.info("  No categories found")
            continue
        log.info("  %d categories", len(cat_links))

        year_total = 0
        for cat_name, cat_url in cat_links:
            rows = parse_category_page(cat_url, year, cat_name, session)
            all_rows.extend(rows)
            year_total += len(rows)
            if rows:
                log.info("    %s: %d complaints", cat_name, len(rows))

        log.info("  Year %d total: %d", year, year_total)

        # Checkpoint save
        if all_rows:
            pd.DataFrame(all_rows).to_csv(OUT_PATH, index=False)

    df = pd.DataFrame(all_rows)
    log.info("Total complaints: %d", len(df))
    if df.empty:
        log.warning("No complaints collected — check scraper logic")
        return
    df.to_csv(OUT_PATH, index=False)
    log.info("Saved to %s", OUT_PATH)

    log.info("\n=== CATEGORY DISTRIBUTION (top 15) ===")
    log.info("\n%s", df["category"].value_counts().head(15).to_string())

    log.info("\n=== YEAR DISTRIBUTION ===")
    log.info("\n%s", df["model_year"].value_counts().sort_index().to_string())


if __name__ == "__main__":
    main()
