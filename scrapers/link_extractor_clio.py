#!/usr/bin/env python3
"""
link_extractor_clio.py
----------------------
Extract thread URLs for Renault Clio discussions from:
  - otoclubturkiye.com (Invision Community)
  - renaultfanclub.com (XenForo)

Output:
  data/raw/extracted_links_clio.json  (jsonlines, {"link": "..."})

Usage:
  python scrapers/link_extractor_clio.py
  python scrapers/link_extractor_clio.py --max-list-pages 300 --output data/raw/extracted_links_clio.json
"""

import argparse
import json
import random
import re
import time
from collections import deque
from pathlib import Path
from urllib.parse import urljoin, urlparse, urlunparse

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent.parent
OUTPUT_FILE = ROOT / "data" / "raw" / "extracted_links_clio.json"

SEED_FORUMS = [
    "https://www.otoclubturkiye.com/forum/forum/400-clio/",
    "https://www.renaultfanclub.com/forums/renault-clio-kulubu.8/",
]

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64; rv:125.0) Gecko/20100101 Firefox/125.0",
]

BASE_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "tr-TR,tr;q=0.9,en;q=0.8",
    "Connection": "keep-alive",
}

THREAD_PATTERNS = {
    "www.otoclubturkiye.com": re.compile(r"^/forum/topic/\d+-"),
    "www.renaultfanclub.com": re.compile(r"^/threads/[^/]+\.\d+/?(?:page-\d+/?)*$"),
}

FORUM_PATTERNS = {
    "www.otoclubturkiye.com": re.compile(r"^/forum/forum/\d+-[^/]+(?:/page/\d+)?/?$"),
    "www.renaultfanclub.com": re.compile(r"^/forums/[^/]+\.\d+/?(?:page-\d+/?)*$"),
}

_SKIP_PATH_HINTS = (
    "/login",
    "/register",
    "/members/",
    "/search",
    "/help",
    "/contact",
    "/privacy",
    "/misc/",
)


def _headers() -> dict:
    h = dict(BASE_HEADERS)
    h["User-Agent"] = random.choice(USER_AGENTS)
    return h


def _sleep_jitter() -> None:
    time.sleep(random.uniform(0.25, 0.9))


def _normalize_url(url: str) -> str:
    p = urlparse(url)
    return urlunparse((p.scheme, p.netloc, p.path.rstrip("/"), "", "", ""))


def _canonical_thread_url(url: str) -> str:
    p = urlparse(url)
    path = p.path

    if p.netloc == "www.otoclubturkiye.com":
        path = re.sub(r"/page/\d+/?$", "", path)
        path = path.rstrip("/") + "/"
    elif p.netloc == "www.renaultfanclub.com":
        path = re.sub(r"/page-\d+/?$", "", path)
        path = path.rstrip("/") + "/"

    return urlunparse((p.scheme, p.netloc, path, "", "", ""))


def _is_skip_path(path: str) -> bool:
    pl = path.lower()
    return any(h in pl for h in _SKIP_PATH_HINTS)


def _is_clio_forum_url(url: str) -> bool:
    p = urlparse(url)
    path_l = p.path.lower()
    if p.netloc == "www.otoclubturkiye.com":
        return path_l.startswith("/forum/forum/") and "clio" in path_l
    if p.netloc == "www.renaultfanclub.com":
        return path_l.startswith("/forums/") and "clio" in path_l
    return False


def fetch(session: requests.Session, url: str, retries: int = 4) -> BeautifulSoup | None:
    for attempt in range(1, retries + 1):
        try:
            r = session.get(url, headers=_headers(), timeout=20, allow_redirects=True)
            if r.status_code == 200:
                return BeautifulSoup(r.text, "html.parser")
            if r.status_code in (429, 503):
                wait = 3 * attempt + random.uniform(0.0, 2.0)
                print(f"  [{r.status_code}] throttled, sleeping {wait:.1f}s")
                time.sleep(wait)
            else:
                print(f"  HTTP {r.status_code}: {url}")
                return None
        except requests.RequestException as e:
            if attempt == retries:
                print(f"  Request failed: {url} -> {e}")
                return None
            time.sleep(2 * attempt)
    return None


def extract_links(soup: BeautifulSoup, page_url: str) -> tuple[set[str], set[str]]:
    p_page = urlparse(page_url)
    domain = p_page.netloc

    thread_links: set[str] = set()
    forum_links: set[str] = set()

    thread_re = THREAD_PATTERNS.get(domain)
    forum_re = FORUM_PATTERNS.get(domain)

    for a in soup.find_all("a", href=True):
        href_attr = a.get("href")
        if not isinstance(href_attr, str):
            continue
        href = href_attr.strip()
        if not href:
            continue

        full = urljoin(page_url, href)
        p = urlparse(full)

        if p.scheme not in ("http", "https"):
            continue
        if p.netloc != domain:
            continue
        if _is_skip_path(p.path):
            continue

        path = p.path
        if thread_re and thread_re.match(path):
            thread_links.add(_canonical_thread_url(full))
            continue

        if forum_re and forum_re.match(path):
            if _is_clio_forum_url(full):
                forum_links.add(_normalize_url(full))
            continue

        # Invision/XenForo list pagination links are sometimes exposed as plain anchors.
        if _is_clio_forum_url(full):
            forum_links.add(_normalize_url(full))

    return thread_links, forum_links


def crawl_forum_links(max_list_pages: int) -> list[str]:
    session = requests.Session()
    queue = deque(_normalize_url(u) for u in SEED_FORUMS)
    seen_pages: set[str] = set()
    all_threads: set[str] = set()

    processed = 0
    while queue and processed < max_list_pages:
        url = queue.popleft()
        if url in seen_pages:
            continue

        seen_pages.add(url)
        processed += 1
        print(f"[{processed}] Forum page: {url}")

        soup = fetch(session, url)
        if soup is None:
            continue

        threads, forums = extract_links(soup, url)
        before = len(all_threads)
        all_threads.update(threads)
        added = len(all_threads) - before

        for f in sorted(forums):
            if f not in seen_pages:
                queue.append(f)

        print(
            f"  threads found: {len(threads)} ({added} new) | "
            f"forum pages queued: {len(queue)} | total threads: {len(all_threads)}"
        )
        _sleep_jitter()

    return sorted(all_threads)


def main() -> None:
    parser = argparse.ArgumentParser(description="Extract Renault Clio thread links")
    parser.add_argument("--max-list-pages", type=int, default=240)
    parser.add_argument("--output", type=str, default=str(OUTPUT_FILE))
    args = parser.parse_args()

    links = crawl_forum_links(max_list_pages=args.max_list_pages)

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        for link in links:
            f.write(json.dumps({"link": link}, ensure_ascii=False) + "\n")

    print(f"\nSaved {len(links)} thread URLs to {out}")


if __name__ == "__main__":
    main()
