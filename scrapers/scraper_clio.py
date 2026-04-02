#!/usr/bin/env python3
"""
scraper_clio.py
---------------
Scrape Clio forum threads from two platforms:
  - otoclubturkiye.com (Invision Community)
  - renaultfanclub.com (XenForo)

Input:
  data/raw/extracted_links_clio.json (jsonlines from link_extractor_clio.py)

Output:
  data/raw/messages_clio.json (structured list)

Usage:
  python scrapers/scraper_clio.py
  python scrapers/scraper_clio.py --max-pages 15 --workers 8
"""

import argparse
import json
import random
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import urljoin, urlparse, urlunparse

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent.parent
LINKS_FILE = ROOT / "data" / "raw" / "extracted_links_clio.json"
OUTPUT_FILE = ROOT / "data" / "raw" / "messages_clio.json"
CHECKPOINT_FILE = ROOT / "data" / "raw" / "scraper_clio_checkpoint.json"

DEFAULT_MAX_PAGES = 15
DEFAULT_WORKERS = 6

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

_local = threading.local()


def _headers() -> dict:
    h = dict(BASE_HEADERS)
    h["User-Agent"] = random.choice(USER_AGENTS)
    return h


def _session() -> requests.Session:
    if not hasattr(_local, "session"):
        _local.session = requests.Session()
    return _local.session


def _normalize_page_url(url: str) -> str:
    p = urlparse(url)
    return urlunparse((p.scheme, p.netloc, p.path.rstrip("/"), "", "", ""))


def canonical_thread_url(url: str) -> str:
    p = urlparse(url)
    path = p.path

    if p.netloc == "www.otoclubturkiye.com":
        path = re.sub(r"/page/\d+/?$", "", path)
        path = path.rstrip("/") + "/"
    elif p.netloc == "www.renaultfanclub.com":
        path = re.sub(r"/page-\d+/?$", "", path)
        path = path.rstrip("/") + "/"

    return urlunparse((p.scheme, p.netloc, path, "", "", ""))


def fetch(url: str, retries: int = 4) -> BeautifulSoup | None:
    s = _session()
    for attempt in range(1, retries + 1):
        try:
            r = s.get(url, headers=_headers(), timeout=20, allow_redirects=True)
            if r.status_code == 200:
                return BeautifulSoup(r.text, "html.parser")
            if r.status_code in (429, 503):
                wait = 3 * attempt + random.uniform(0.2, 2.0)
                print(f"    [{r.status_code}] throttled, sleeping {wait:.1f}s")
                time.sleep(wait)
            else:
                return None
        except requests.RequestException:
            if attempt < retries:
                time.sleep(2 * attempt)
    return None


def _clean_text(text: str) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    text = re.sub(r"Click to expand\.?.*$", "", text, flags=re.IGNORECASE)
    return text.strip()


def extract_thread_title(soup: BeautifulSoup) -> str:
    selectors = [
        "h1.ipsType_pageTitle",
        "h1.p-title-value",
        "h1.ipsPageHeader_title",
        "h1",
    ]
    for sel in selectors:
        node = soup.select_one(sel)
        if node:
            t = _clean_text(node.get_text(" ", strip=True))
            if t:
                return t

    title_node = soup.find("title")
    if title_node:
        raw = _clean_text(title_node.get_text(" ", strip=True))
        if "|" in raw:
            return raw.split("|", 1)[0].strip()
        return raw

    return "Unknown Thread"


def extract_posts(soup: BeautifulSoup) -> list[str]:
    selectors = [
        # Invision Community
        "article.ipsComment div[data-role='commentContent']",
        "article.ipsComment div.ipsType_richText",
        "article.ipsComment_content",
        # XenForo
        "article.message div.message-body div.bbWrapper",
        "article.message div.message-content div.bbWrapper",
        "article.message div.bbWrapper",
    ]

    nodes = []
    for sel in selectors:
        found = soup.select(sel)
        if found:
            nodes.extend(found)
        if len(nodes) >= 2:
            break

    posts: list[str] = []
    for node in nodes:
        for junk in node.select(
            "blockquote, script, style, .ipsQuote, .ipsSignature, .message-signature, .bbCodeBlock"
        ):
            junk.decompose()

        txt = _clean_text(node.get_text(" ", strip=True))
        if len(txt) >= 15:
            posts.append(txt)

    # Last fallback: if structured selectors fail, attempt broad post bodies.
    if not posts:
        for node in soup.select("div[data-role='commentContent'], article.message"):
            txt = _clean_text(node.get_text(" ", strip=True))
            if len(txt) >= 20:
                posts.append(txt)

    dedup = []
    seen = set()
    for p in posts:
        key = p[:160].lower()
        if key in seen:
            continue
        seen.add(key)
        dedup.append(p)

    return dedup


def next_page_url(current_url: str, soup: BeautifulSoup) -> str | None:
    # Preferred: explicit rel=next links.
    next_node = soup.select_one(
        "link[rel='next'], a[rel='next'], a.ipsPagination_next, a.pageNav-jump--next"
    )
    if next_node:
        href_attr = next_node.get("href")
        if isinstance(href_attr, str) and href_attr:
            nxt = _normalize_page_url(urljoin(current_url, href_attr))
            if nxt != _normalize_page_url(current_url):
                return nxt

    p = urlparse(current_url)
    path = p.path

    # Invision fallback: /page/2/
    if p.netloc == "www.otoclubturkiye.com":
        base = re.sub(r"/page/\d+/?$", "", path).rstrip("/") + "/"
        m = re.search(r"/page/(\d+)/?$", path)
        cur = int(m.group(1)) if m else 1
        cand_path = f"{base}page/{cur + 1}/"
        return urlunparse((p.scheme, p.netloc, cand_path, "", "", ""))

    # XenForo fallback: /page-2
    if p.netloc == "www.renaultfanclub.com":
        base = re.sub(r"/page-\d+/?$", "", path).rstrip("/") + "/"
        m = re.search(r"/page-(\d+)/?$", path)
        cur = int(m.group(1)) if m else 1
        cand_path = f"{base}page-{cur + 1}"
        return urlunparse((p.scheme, p.netloc, cand_path, "", "", ""))

    return None


def scrape_thread(url: str, max_pages: int) -> dict | None:
    messages: list[str] = []
    seen_messages: set[str] = set()

    current_url = url
    seen_pages: set[str] = set()
    title = None
    pages = 0

    while current_url and pages < max_pages:
        norm = _normalize_page_url(current_url)
        if norm in seen_pages:
            break
        seen_pages.add(norm)

        soup = fetch(current_url)
        if soup is None:
            break

        if title is None:
            title = extract_thread_title(soup)

        page_posts = extract_posts(soup)
        for post in page_posts:
            key = post[:180].lower()
            if key in seen_messages:
                continue
            seen_messages.add(key)
            messages.append(post)

        pages += 1
        nxt = next_page_url(current_url, soup)
        if not nxt or _normalize_page_url(nxt) in seen_pages:
            break

        current_url = nxt
        time.sleep(random.uniform(0.05, 0.15))

    if not messages:
        return None

    return {
        "thread_name": title or "Unknown Thread",
        "thread_url": canonical_thread_url(url),
        "messages": messages,
    }


def load_links(path: Path) -> list[str]:
    if not path.exists():
        raise FileNotFoundError(f"Links file not found: {path}")

    links = []
    seen = set()
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                link = json.loads(line)["link"]
            except (json.JSONDecodeError, KeyError):
                continue
            c = canonical_thread_url(link)
            if c in seen:
                continue
            seen.add(c)
            links.append(c)
    return links


def load_checkpoint(path: Path) -> set[str]:
    if path.exists():
        return set(json.loads(path.read_text(encoding="utf-8")))
    return set()


def save_checkpoint(path: Path, done: set[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(sorted(done), ensure_ascii=False, indent=2), encoding="utf-8")


def load_existing_threads(path: Path) -> dict[str, dict]:
    if not path.exists():
        return {}
    records = json.loads(path.read_text(encoding="utf-8"))
    return {r["thread_url"]: r for r in records if "thread_url" in r}


def save_threads(path: Path, threads: dict[str, dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = sorted(threads.values(), key=lambda x: x.get("thread_url", ""))
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Scrape Renault Clio forum thread messages")
    parser.add_argument("--links", type=str, default=str(LINKS_FILE))
    parser.add_argument("--output", type=str, default=str(OUTPUT_FILE))
    parser.add_argument("--max-pages", type=int, default=DEFAULT_MAX_PAGES)
    parser.add_argument("--workers", type=int, default=DEFAULT_WORKERS)
    parser.add_argument("--no-resume", action="store_true")
    args = parser.parse_args()

    links_path = Path(args.links)
    out_path = Path(args.output)

    links = load_links(links_path)
    done = set() if args.no_resume else load_checkpoint(CHECKPOINT_FILE)
    existing = {} if args.no_resume else load_existing_threads(out_path)

    pending = [u for u in links if u not in done]

    print(f"Total links: {len(links)}")
    print(f"Already done: {len(done)}")
    print(f"Pending: {len(pending)}")

    if not pending:
        print("Nothing to scrape.")
        return

    results = dict(existing)
    completed = set(done)
    lock = threading.Lock()

    def worker(thread_url: str) -> tuple[str, dict | None]:
        scraped = scrape_thread(thread_url, max_pages=args.max_pages)
        time.sleep(random.uniform(0.02, 0.08))
        return thread_url, scraped

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(worker, url): url for url in pending}
        for i, future in enumerate(as_completed(futures), 1):
            src_url, thread = future.result()
            with lock:
                completed.add(src_url)
                if thread:
                    results[thread["thread_url"]] = thread

                if i % 20 == 0 or i == len(pending):
                    save_threads(out_path, results)
                    save_checkpoint(CHECKPOINT_FILE, completed)
                    total_msgs = sum(len(t.get("messages", [])) for t in results.values())
                    print(f"  [{i}/{len(pending)}] threads={len(results)} messages={total_msgs}")

    save_threads(out_path, results)
    save_checkpoint(CHECKPOINT_FILE, completed)
    final_msgs = sum(len(t.get("messages", [])) for t in results.values())
    print(f"\nDone. {len(results)} threads | {final_msgs} messages -> {out_path}")


if __name__ == "__main__":
    main()
