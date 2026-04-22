#!/usr/bin/env python3
"""
Scrape technical details and description text from a Sahibinden listing page.

This scraper is built for pages that may require an authenticated browser session.
If you hit a login/security wall, run with --manual-login and a real Chrome profile.
"""

from __future__ import annotations

import argparse
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.common.exceptions import WebDriverException
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service

try:
    import chromedriver_autoinstaller
except ImportError:
    chromedriver_autoinstaller = None


BLOCK_MARKERS = (
    "just a moment",
    "performing security verification",
    "olağan dışı erişim",
    "olağandışı bir durum tespit ettik",
    "security check",
    "cloudflare",
    "destek kodu: f-",
)


def _clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _extract_listing_id(url: str) -> str:
    slug_match = re.search(r"-(\d{7,})/detail", url)
    if slug_match:
        return slug_match.group(1)
    path_match = re.search(r"/listing/(\d{7,})/detail", url)
    if path_match:
        return path_match.group(1)
    return "unknown"


def _extract_listing_slug(url: str) -> str | None:
    m = re.search(r"/listing/([^/]+)/detail", url)
    if not m:
        return None
    slug = m.group(1)
    slug = re.sub(r"-\d{7,}$", "", slug)
    slug = slug.strip("-")
    return slug or None


def _build_slug_fallback_data(url: str) -> dict[str, Any]:
    slug = _extract_listing_slug(url) or ""
    tokens = [t for t in slug.split("-") if t]
    text = " ".join(tokens)

    technical: dict[str, str] = {}

    year_match = re.search(r"(19\d{2}|20\d{2})(?:\b|(?=[a-zA-Z]))", text)
    if year_match:
        technical["Year"] = year_match.group(1)

    km_match = re.search(r"\b(\d{1,3}(?:[.,]\d{3})+|\d+)\s*km\b", text, flags=re.IGNORECASE)
    if km_match:
        technical["Kilometer"] = km_match.group(1).replace(",", ".") + " km"

    engine_match = re.search(
        r"\b(\d\.\d)\s*(tsi|tdi|dci|mpi|tce|hdi|ecoboost|multijet)\b",
        text,
        flags=re.IGNORECASE,
    )
    if engine_match:
        technical["Engine"] = f"{engine_match.group(1)} {engine_match.group(2).upper()}"

    trim_words = {
        "highline": "Highline",
        "comfortline": "Comfortline",
        "trendline": "Trendline",
        "midline": "Midline",
        "gti": "GTI",
        "r": "R",
    }
    for token in tokens:
        value = trim_words.get(token.lower())
        if value:
            technical["Trim"] = value
            break

    if "volkswagen" in [t.lower() for t in tokens]:
        technical["Brand"] = "Volkswagen"
    if "golf" in [t.lower() for t in tokens]:
        technical["Model"] = "Golf"

    headline = _clean_text(
        " ".join(
            t.upper() if re.fullmatch(r"\d\.\d(?:tsi|tdi|dci|mpi|tce|hdi)", t, flags=re.IGNORECASE) else t
            for t in tokens
        )
    )
    description = headline or None

    return {
        "source_url": url,
        "final_url": url,
        "listing_id": _extract_listing_id(url),
        "scraped_at_utc": datetime.now(timezone.utc).isoformat(),
        "headline": headline or None,
        "price": None,
        "location": None,
        "technical_details": technical,
        "description": description,
        "blocked": True,
        "extraction_method": "url_slug_fallback",
    }


def _is_blocked_page(title: str, html: str, current_url: str) -> bool:
    lowered = f"{title}\n{html[:50000]}\n{current_url}".lower()
    if "secure.sahibinden.com/login" in current_url.lower():
        return True
    return any(marker in lowered for marker in BLOCK_MARKERS)


def _extract_from_li(li: Any) -> tuple[str | None, str | None]:
    strong = li.find("strong")
    if strong:
        key = _clean_text(strong.get_text(" ", strip=True).rstrip(":"))
        strong.extract()
        value = _clean_text(li.get_text(" ", strip=True))
        return (key or None, value or None)

    text = _clean_text(li.get_text(" ", strip=True))
    if ":" in text:
        key, value = text.split(":", 1)
        key = _clean_text(key)
        value = _clean_text(value)
        return (key or None, value or None)
    return (None, None)


def _extract_technical_details(soup: BeautifulSoup) -> dict[str, str]:
    details: dict[str, str] = {}

    for li in soup.select("ul.classifiedInfoList li"):
        key, value = _extract_from_li(li)
        if key and value:
            details[key] = value

    for row in soup.select("table tr"):
        th = row.find("th")
        td = row.find("td")
        if th and td:
            key = _clean_text(th.get_text(" ", strip=True).rstrip(":"))
            value = _clean_text(td.get_text(" ", strip=True))
            if key and value and key not in details:
                details[key] = value

    return details


def _iter_json_ld_objects(soup: BeautifulSoup) -> list[dict[str, Any]]:
    objects: list[dict[str, Any]] = []
    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        raw = script.string if script.string is not None else script.get_text()
        text = raw.strip()
        if not text:
            continue
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            continue

        if isinstance(data, dict):
            objects.append(data)
        elif isinstance(data, list):
            for item in data:
                if isinstance(item, dict):
                    objects.append(item)
    return objects


def _extract_json_ld_additional_data(
    soup: BeautifulSoup,
) -> tuple[dict[str, str], str | None, str | None]:
    technical: dict[str, str] = {}
    description: str | None = None
    headline: str | None = None

    for obj in _iter_json_ld_objects(soup):
        if headline is None and isinstance(obj.get("name"), str):
            headline = _clean_text(obj["name"])

        if description is None and isinstance(obj.get("description"), str):
            description = _clean_text(obj["description"])

        additional = obj.get("additionalProperty")
        if not isinstance(additional, list):
            continue

        for entry in additional:
            if not isinstance(entry, dict):
                continue
            key = entry.get("name")
            value = entry.get("value")
            if isinstance(key, str) and isinstance(value, str):
                cleaned_key = _clean_text(key)
                cleaned_val = _clean_text(value)
                if cleaned_key and cleaned_val and cleaned_key not in technical:
                    technical[cleaned_key] = cleaned_val

    return technical, description, headline


def _extract_first_text(soup: BeautifulSoup, selectors: list[str]) -> str | None:
    for selector in selectors:
        node = soup.select_one(selector)
        if node:
            text = _clean_text(node.get_text(" ", strip=True))
            if text:
                return text
    return None


def _extract_meta_content(soup: BeautifulSoup, attr_name: str, attr_value: str) -> str | None:
    node = soup.find("meta", attrs={attr_name: attr_value})
    if not node:
        return None
    content = node.get("content")
    if isinstance(content, str):
        cleaned = _clean_text(content)
        return cleaned or None
    return None


def extract_listing_data(url: str, final_url: str, page_title: str, html: str) -> dict[str, Any]:
    soup = BeautifulSoup(html, "html.parser")
    json_ld_tech, json_ld_desc, json_ld_headline = _extract_json_ld_additional_data(soup)
    technical_details = _extract_technical_details(soup)

    for key, value in json_ld_tech.items():
        technical_details.setdefault(key, value)

    headline = (
        _extract_first_text(soup, ["h1", "h1.classifiedTitle"])
        or _extract_meta_content(soup, "property", "og:title")
        or json_ld_headline
        or page_title
    )
    price = _extract_first_text(
        soup,
        [
            "h3.classified-price-wrapper",
            ".classifiedInfo h3",
            ".classified-price",
            "span[class*='price']",
        ],
    )
    location = _extract_first_text(
        soup,
        [
            ".classifiedInfo h2",
            ".classifiedInfo .classifiedInfoLocation",
            "span[class*='location']",
            ".breadcrumb li:last-child",
        ],
    )
    description = (
        _extract_first_text(
            soup,
            [
                "#classifiedDescription .classifiedDescriptionContent",
                "#classifiedDescription",
                ".classifiedDescription",
                "[itemprop='description']",
            ],
        )
        or _extract_meta_content(soup, "name", "description")
        or json_ld_desc
    )

    return {
        "source_url": url,
        "final_url": final_url,
        "listing_id": _extract_listing_id(url),
        "scraped_at_utc": datetime.now(timezone.utc).isoformat(),
        "headline": headline,
        "price": price,
        "location": location,
        "technical_details": technical_details,
        "description": description,
        "blocked": False,
        "extraction_method": "page_html",
    }


def _build_driver(args: argparse.Namespace) -> webdriver.Chrome:
    options = Options()
    options.add_argument("--lang=tr-TR")
    options.add_argument("--disable-blink-features=AutomationControlled")
    if args.browser_binary:
        options.binary_location = args.browser_binary

    if args.debugger_address:
        options.debugger_address = args.debugger_address
    else:
        if args.user_data_dir:
            options.add_argument(f"--user-data-dir={args.user_data_dir}")
        if args.profile_directory:
            options.add_argument(f"--profile-directory={args.profile_directory}")
        if args.headless:
            options.add_argument("--headless=new")

    service: Service | None = None
    if args.driver_path:
        service = Service(executable_path=args.driver_path)
    elif chromedriver_autoinstaller is not None:
        try:
            detected_driver_path = chromedriver_autoinstaller.install()
            service = Service(executable_path=detected_driver_path)
        except ValueError:
            service = None

    if service is not None:
        return webdriver.Chrome(service=service, options=options)
    return webdriver.Chrome(options=options)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Scrape technical details + description from a Sahibinden listing."
    )
    parser.add_argument("url", help="Sahibinden listing detail URL")
    parser.add_argument(
        "--output",
        help="Output JSON path. Default: data\\raw\\sahibinden\\sahibinden_<listing_id>.json",
    )
    parser.add_argument(
        "--user-data-dir",
        help="Chrome user data dir for authenticated session reuse "
        "(e.g. C:\\Users\\<user>\\AppData\\Local\\Google\\Chrome\\User Data)",
    )
    parser.add_argument(
        "--profile-directory",
        default="Default",
        help='Chrome profile directory inside user-data-dir (default: "Default")',
    )
    parser.add_argument(
        "--debugger-address",
        help="Attach to existing Chrome DevTools endpoint (example: 127.0.0.1:9222)",
    )
    parser.add_argument(
        "--driver-path",
        help="Explicit chromedriver path (optional).",
    )
    parser.add_argument(
        "--browser-binary",
        help="Explicit Chrome/Chromium binary path (optional).",
    )
    parser.add_argument(
        "--manual-login",
        action="store_true",
        help="If blocked, wait for manual login/captcha completion in opened browser.",
    )
    parser.add_argument(
        "--use-current-tab",
        action="store_true",
        help="Do not navigate; scrape whichever page is already open in attached browser.",
    )
    parser.add_argument(
        "--keep-browser-open",
        action="store_true",
        help="Do not close browser on exit (recommended with --debugger-address).",
    )
    parser.add_argument(
        "--no-url-fallback",
        action="store_true",
        help="Disable fallback extraction from URL slug when blocked.",
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Run headless (ignored when --debugger-address is used).",
    )
    parser.add_argument(
        "--wait-seconds",
        type=int,
        default=10,
        help="Wait time after each page load (default: 10)",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    listing_id = _extract_listing_id(args.url)
    output_path = (
        Path(args.output)
        if args.output
        else Path("data") / "raw" / "sahibinden" / f"sahibinden_{listing_id}.json"
    )

    try:
        driver = _build_driver(args)
    except WebDriverException as exc:
        raise SystemExit(f"Could not start Chrome WebDriver: {exc}") from exc

    try:
        if not args.use_current_tab:
            driver.get(args.url)
            time.sleep(args.wait_seconds)

        title = driver.title or ""
        current_url = driver.current_url
        html = driver.page_source

        if _is_blocked_page(title, html, current_url):
            if args.manual_login:
                print(
                    "Blocked by Sahibinden security/login wall.\n"
                    "Complete login/captcha in the opened browser, then press ENTER here."
                )
                input()
                if not args.use_current_tab:
                    driver.get(args.url)
                    time.sleep(args.wait_seconds)
                title = driver.title or ""
                current_url = driver.current_url
                html = driver.page_source

            if _is_blocked_page(title, html, current_url):
                if args.no_url_fallback:
                    raise SystemExit(
                        "Still blocked. Use an authenticated Chrome profile or attach with "
                        "--debugger-address to a logged-in Chrome session."
                    )
                data = _build_slug_fallback_data(args.url)
            else:
                data = extract_listing_data(
                    url=args.url,
                    final_url=current_url,
                    page_title=title,
                    html=html,
                )
        else:
            data = extract_listing_data(
                url=args.url,
                final_url=current_url,
                page_title=title,
                html=html,
            )
    finally:
        if not args.keep_browser_open and not args.debugger_address:
            driver.quit()

    if not data["technical_details"] and not data["description"]:
        raise SystemExit(
            "Page loaded but no technical details/description were found. "
            "Check selectors or verify listing visibility."
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"Saved: {output_path}")
    print(f"Headline: {data['headline']}")
    print(f"Technical detail count: {len(data['technical_details'])}")
    print(f"Description length: {len(data['description'] or '')}")


if __name__ == "__main__":
    main()

