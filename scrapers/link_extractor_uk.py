#!/usr/bin/env python3
"""
link_extractor_uk.py
─────────────────────
Extracts all thread URLs from golfgtiforum.co.uk SMF board 117
(Golf GTI / General Discussion → Problems & Fixes or equivalent).

Output: data/raw/forums/extracted_links_uk.json  (jsonlines, {"link": "..."})

Usage:
    python scrapers/link_extractor_uk.py [--pages N] [--board URL]
"""

import argparse
import json
import os
import random
import re
import time
from pathlib import Path

import requests
from bs4 import BeautifulSoup

# ── Config ────────────────────────────────────────────────────────────────────

BOARD_URL   = "https://www.golfgtiforum.co.uk/index.php?board=117.{offset}"
OUTPUT_FILE = Path(__file__).parent.parent / "data" / "raw" / "forums" / "extracted_links_uk.json"

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36 Edg/123.0.0.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4_1) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4.1 Safari/605.1.15",
]

BASE_HEADERS = {
    "Accept":          "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-GB,en;q=0.9",
    "Connection":      "keep-alive",
    "DNT":             "1",
    "Upgrade-Insecure-Requests": "1",
    # Accept-Encoding intentionally omitted — let requests handle decompression natively
}


def _headers():
    h = dict(BASE_HEADERS)
    h["User-Agent"] = random.choice(USER_AGENTS)
    return h


def _jitter():
    time.sleep(random.uniform(0.4, 1.1))


def fetch(session: requests.Session, url: str, retries: int = 4) -> BeautifulSoup | None:
    for attempt in range(1, retries + 1):
        try:
            r = session.get(url, headers=_headers(), timeout=15, allow_redirects=True)
            if r.status_code == 200:
                return BeautifulSoup(r.text, "html.parser")
            if r.status_code in (429, 503):
                wait = 5 * attempt + random.uniform(0, 3)
                print(f"  [{r.status_code}] rate-limited — sleeping {wait:.1f}s")
                time.sleep(wait)
            else:
                print(f"  HTTP {r.status_code} on {url}")
                return None
        except requests.RequestException as e:
            print(f"  Request error (attempt {attempt}): {e}")
            time.sleep(3 * attempt)
    return None


def _clean_url(href: str, base: str = "https://www.golfgtiforum.co.uk") -> str:
    """Strip PHPSESSID, anchors, and extra params; return a clean canonical URL."""
    if not href.startswith("http"):
        href = base + "/" + href.lstrip("/")
    href = href.split("#")[0]
    # Extract only the topic=ID part, drop PHPSESSID and everything else
    m = re.search(r"topic=(\d+)\.\d+", href)
    if m:
        return f"{base}/index.php?topic={m.group(1)}.0"
    return href


def extract_thread_links(soup: BeautifulSoup, base: str = "https://www.golfgtiforum.co.uk") -> list[str]:
    """Pull topic links from a board index page."""
    links = set()
    for a in soup.find_all("a", href=re.compile(r"topic=\d+\.\d+")):
        href = a.get("href", "")
        # Skip sort/action links that happen to include topic
        if "prev_next" in href or "printpage" in href or "action=" in href:
            continue
        clean = _clean_url(href, base)
        if re.search(r"topic=\d+\.0$", clean):
            links.add(clean)
    return list(links)


def detect_page_step(soup: BeautifulSoup) -> int:
    """
    Detect board page step from pagination links.
    e.g. board=117.35, board=117.70 → step = 35. Falls back to 35.
    """
    offsets = []
    for a in soup.find_all("a", href=re.compile(r"board=\d+\.\d+")):
        href = a.get("href", "")
        # Skip sort links
        if "sort=" in href:
            continue
        m = re.search(r"board=\d+\.(\d+)", href)
        if m:
            offsets.append(int(m.group(1)))
    offsets = sorted(set(o for o in offsets if o > 0))
    if offsets:
        return offsets[0]  # smallest non-zero offset = step
    return 35


def scrape_board(max_pages: int = 9999) -> list[str]:
    session = requests.Session()
    session.headers.update({"Referer": "https://www.golfgtiforum.co.uk/"})

    all_links: set[str] = set()
    offset = 0
    step = None
    page = 0

    while page < max_pages:
        url = BOARD_URL.format(offset=offset)
        print(f"Board page {page + 1} — offset={offset} — {url}")
        soup = fetch(session, url)
        if soup is None:
            print("  Failed to fetch board page — stopping.")
            break

        if step is None:
            step = detect_page_step(soup)
            print(f"  Detected page step: {step}")

        new_links = extract_thread_links(soup)
        before = len(all_links)
        all_links.update(new_links)
        added = len(all_links) - before
        print(f"  Found {len(new_links)} links on page ({added} new) — total so far: {len(all_links)}")

        if added == 0:
            print("  No new links — reached end of board.")
            break

        offset += step
        page += 1
        _jitter()

    return sorted(all_links)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--pages",  type=int, default=9999, help="Max board pages to crawl")
    parser.add_argument("--board",  type=str, default=None,  help="Override board URL template (use {offset})")
    parser.add_argument("--output", type=str, default=str(OUTPUT_FILE))
    args = parser.parse_args()

    if args.board:
        global BOARD_URL
        BOARD_URL = args.board

    links = scrape_board(max_pages=args.pages)
    print(f"\nTotal unique thread links: {len(links)}")

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        for link in links:
            f.write(json.dumps({"link": link}) + "\n")
    print(f"Saved: {out}")


if __name__ == "__main__":
    main()
