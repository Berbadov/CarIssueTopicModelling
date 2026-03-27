#!/usr/bin/env python3
"""
scraper_uk.py
──────────────
Scrapes thread messages from golfgtiforum.co.uk (SMF forum).
Reads thread URLs from data/raw/extracted_links_uk.json and writes
grouped thread data to data/raw/messages_uk.json.

Usage:
    python scrapers/scraper_uk.py [--max-pages N] [--workers N] [--no-resume]
"""

import argparse
import json
import os
import random
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests
from bs4 import BeautifulSoup

# ── Config ────────────────────────────────────────────────────────────────────

BASE_URL         = "https://www.golfgtiforum.co.uk"
LINKS_FILE       = Path(__file__).parent.parent / "data" / "raw" / "extracted_links_uk.json"
OUTPUT_FILE      = Path(__file__).parent.parent / "data" / "raw" / "messages_uk.json"
CHECKPOINT_FILE  = Path(__file__).parent.parent / "data" / "raw" / "scraper_uk_checkpoint.json"

DEFAULT_MAX_PAGES = 15
DEFAULT_WORKERS   = 8
SMF_PAGE_STEP     = 10   # confirmed: golfgtiforum.co.uk uses 10 posts per page

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36 Edg/123.0.0.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4.1 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.3.1 Safari/605.1.15",
]

REFERERS = [
    "https://www.google.co.uk/",
    "https://www.google.com/",
    "https://www.bing.com/",
    "https://duckduckgo.com/",
    f"{BASE_URL}/",
    f"{BASE_URL}/index.php?board=117.0",
]


def _headers(referer: str | None = None) -> dict:
    return {
        "User-Agent":      random.choice(USER_AGENTS),
        "Accept":          "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": random.choice(["en-GB,en;q=0.9", "en-US,en;q=0.9,en-GB;q=0.8"]),
        "Connection":      "keep-alive",
        # Accept-Encoding intentionally omitted — let requests handle decompression natively
        "Referer":         referer or random.choice(REFERERS),
        "DNT":             "1",
    }


# ── Thread-local session factory ─────────────────────────────────────────────

import threading
_local = threading.local()


def _session() -> requests.Session:
    if not hasattr(_local, "session"):
        s = requests.Session()
        # Warm cookie jar with a homepage hit
        try:
            s.get(BASE_URL, headers=_headers(), timeout=10)
        except Exception:
            pass
        _local.session = s
    return _local.session


# ── Fetch helpers ─────────────────────────────────────────────────────────────

def fetch(url: str, retries: int = 4) -> BeautifulSoup | None:
    s = _session()
    for attempt in range(1, retries + 1):
        try:
            r = s.get(url, headers=_headers(referer=BASE_URL + "/"), timeout=15, allow_redirects=True)
            if r.status_code == 200:
                return BeautifulSoup(r.text, "html.parser")
            if r.status_code in (429, 503):
                wait = 6 * attempt + random.uniform(0, 4)
                print(f"    [{r.status_code}] throttled — sleeping {wait:.1f}s")
                time.sleep(wait)
            else:
                return None
        except requests.RequestException as e:
            if attempt < retries:
                time.sleep(2 * attempt + random.uniform(0, 2))
    return None


# ── SMF post extraction ───────────────────────────────────────────────────────

def extract_posts(soup: BeautifulSoup) -> list[str]:
    """
    Extract visible post text from an SMF thread page.
    SMF 2.x stores post body in:  <div class="post"> > <div class="inner">
    Quoted content (blockquote) is stripped before text extraction.
    """
    posts = []

    # Primary: SMF 2.x
    for inner in soup.select("div.post div.inner"):
        # Remove quoted content in-place before extracting text
        for bq in inner.find_all("blockquote"):
            bq.decompose()
        for tag in inner.find_all(["script", "style"]):
            tag.decompose()
        text = inner.get_text(separator=" ", strip=True)
        if text:
            posts.append(text)

    if not posts:
        # SMF 1.x / custom theme fallback
        for td in soup.select("td.post"):
            for bq in td.find_all("blockquote"):
                bq.decompose()
            text = td.get_text(separator=" ", strip=True)
            if text:
                posts.append(text)

    if not posts:
        # Last resort
        for div in soup.find_all("div", id=re.compile(r"^msg_\d+")):
            for tag in div.find_all(["script", "style", "blockquote"]):
                tag.decompose()
            text = div.get_text(separator=" ", strip=True)
            if text:
                posts.append(text)

    cleaned = []
    for p in posts:
        # Strip any remaining [quote]...[/quote] BBCode that survived as text
        p = re.sub(r"\[quote[^\]]*\].*?\[/quote\]", " ", p, flags=re.DOTALL | re.IGNORECASE)
        # Strip "Quote from: X on DATE" header lines that leaked as plain text
        p = re.sub(r"Quote\s+from:[^\n]*\n?", " ", p, flags=re.IGNORECASE)
        p = re.sub(r"\s{2,}", " ", p).strip()
        if len(p) > 10:
            cleaned.append(p)

    return cleaned


def extract_thread_title(soup: BeautifulSoup) -> str:
    # SMF breadcrumb: last item in navigate_section is the thread title
    nav_items = soup.select(".navigate_section li")
    if nav_items:
        text = nav_items[-1].get_text(strip=True)
        if text and text.lower() not in ("golfgtiforum.co.uk", ""):
            return text
    # Fallback: h3.catbg contains "AuthorTopic: <title> (Read N times)"
    h3 = soup.select_one("h3.catbg")
    if h3:
        text = h3.get_text(strip=True)
        m = re.search(r"AuthorTopic:\s*(.+?)\s*(?:\(Read|\(", text)
        if m:
            return m.group(1).strip()
    return "Unknown Thread"


# ── SMF pagination ────────────────────────────────────────────────────────────

def next_page_url(current_url: str, soup: BeautifulSoup, step: int = SMF_PAGE_STEP) -> str | None:
    """
    Find the next-page URL for an SMF topic.
    Parses pagination offsets from nav links, skipping sort/action/prev_next junk.
    Falls back to offset+step if no nav links found.
    """
    m = re.search(r"topic=(\d+)\.(\d+)", current_url)
    if not m:
        return None
    topic_id   = m.group(1)
    cur_offset = int(m.group(2))

    # Collect all clean numeric offsets for this topic from the page nav
    nav_offsets = set()
    for a in soup.find_all("a", href=re.compile(rf"topic={topic_id}\.\d+")):
        href = a.get("href", "")
        if any(x in href for x in ("prev_next", "printpage", "action=", "sort=", "#")):
            continue
        om = re.search(rf"topic={topic_id}\.(\d+)", href)
        if om:
            nav_offsets.add(int(om.group(1)))

    if nav_offsets:
        greater = sorted(o for o in nav_offsets if o > cur_offset)
        if not greater:
            return None  # already on last page
        next_off = greater[0]
    else:
        # No nav links — single-page thread or can't detect; try +step once
        next_off = cur_offset + step

    return f"{BASE_URL}/index.php?topic={topic_id}.{next_off}"


# ── Thread scraper ────────────────────────────────────────────────────────────

def scrape_thread(url: str, max_pages: int = DEFAULT_MAX_PAGES) -> dict | None:
    """Scrape all pages of one thread, return {thread_name, thread_url, messages}."""
    messages = []
    seen_msgs: set[str] = set()
    current_url = url
    pages_done = 0
    thread_name = None

    while current_url and pages_done < max_pages:
        soup = fetch(current_url)
        if soup is None:
            break

        if thread_name is None:
            thread_name = extract_thread_title(soup)

        posts = extract_posts(soup)
        for p in posts:
            key = p[:120]  # dedup key
            if key not in seen_msgs:
                seen_msgs.add(key)
                messages.append(p)

        pages_done += 1
        _next = next_page_url(current_url, soup)

        if _next is None or _next == current_url:
            break

        current_url = _next
        time.sleep(random.uniform(0.3, 0.9))

    if not messages:
        return None

    # Store clean canonical URL (no PHPSESSID)
    m2 = re.search(r"topic=(\d+)\.", url)
    clean_url = f"{BASE_URL}/index.php?topic={m2.group(1)}.0" if m2 else url.split("#")[0]
    return {
        "thread_name": thread_name or "Unknown Thread",
        "thread_url":  clean_url,
        "messages":    messages,
    }


# ── Checkpoint helpers ────────────────────────────────────────────────────────

def load_checkpoint() -> set[str]:
    if CHECKPOINT_FILE.exists():
        with open(CHECKPOINT_FILE, encoding="utf-8") as f:
            return set(json.load(f))
    return set()


def save_checkpoint(done: set[str]):
    CHECKPOINT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(CHECKPOINT_FILE, "w", encoding="utf-8") as f:
        json.dump(sorted(done), f, ensure_ascii=False, indent=2)


def load_links() -> list[str]:
    if not LINKS_FILE.exists():
        raise FileNotFoundError(f"Links file not found: {LINKS_FILE}")
    links = []
    seen = set()
    with open(LINKS_FILE, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                link = json.loads(line)["link"]
                if link not in seen:
                    seen.add(link)
                    links.append(link)
            except (json.JSONDecodeError, KeyError):
                continue
    return links


def load_existing_threads(path: Path) -> dict[str, dict]:
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as f:
        threads = json.load(f)
    return {t["thread_url"]: t for t in threads}


def save_threads(threads: dict[str, dict], path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(list(threads.values()), f, ensure_ascii=False, indent=2)


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-pages", type=int, default=DEFAULT_MAX_PAGES)
    parser.add_argument("--workers",   type=int, default=DEFAULT_WORKERS)
    parser.add_argument("--no-resume", action="store_true")
    parser.add_argument("--output",    type=str, default=str(OUTPUT_FILE))
    args = parser.parse_args()

    out_path = Path(args.output)
    links = load_links()
    print(f"Total links loaded: {len(links)}")

    done = set() if args.no_resume else load_checkpoint()
    existing = {} if args.no_resume else load_existing_threads(out_path)
    pending = [l for l in links if l not in done]
    print(f"Already done: {len(done)}  |  Pending: {len(pending)}")

    if not pending:
        print("Nothing to scrape.")
        return

    results = dict(existing)
    lock = __import__("threading").Lock()
    completed_urls: set[str] = set(done)

    def worker(url: str) -> tuple[str, dict | None]:
        result = scrape_thread(url, max_pages=args.max_pages)
        time.sleep(random.uniform(0.2, 0.6))
        return url, result

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(worker, url): url for url in pending}
        for i, future in enumerate(as_completed(futures), 1):
            url, thread = future.result()
            with lock:
                completed_urls.add(url)
                if thread:
                    results[url] = thread
                if i % 25 == 0 or i == len(pending):
                    save_threads(results, out_path)
                    save_checkpoint(completed_urls)
                    msgs = sum(len(t["messages"]) for t in results.values())
                    print(f"  [{i}/{len(pending)}] {len(results)} threads | {msgs} messages")

    save_threads(results, out_path)
    save_checkpoint(completed_urls)
    total_msgs = sum(len(t["messages"]) for t in results.values())
    print(f"\nDone. {len(results)} threads | {total_msgs} messages -> {out_path}")


if __name__ == "__main__":
    main()
