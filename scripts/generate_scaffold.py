#!/usr/bin/env python3
"""
generate_scaffold.py
────────────────────
Scrapes one or more spec pages (e.g. VW Newsroom engine profiles) and uses
an LLM to produce a vehicle knowledge scaffold YAML in the project schema.

The script is intentionally model/make agnostic: pass --make and --model and
the output file follows the same schema as data/scaffolds/vw_golf.yaml so
the rest of the pipeline picks it up without any code changes.

Usage:
    DEEPSEEK_API_KEY=<key> python scripts/generate_scaffold.py \\
        --make VW --model Golf \\
        --url https://www.volkswagen-newsroom.com/en/engine-versions-golf-7-profile-20040 \\
        --output data/scaffolds/vw_golf_generated.yaml

    # Multiple URLs are concatenated before sending to the LLM
    DEEPSEEK_API_KEY=<key> python scripts/generate_scaffold.py \\
        --make BMW --model "3 Series" \\
        --url https://... --url https://... \\
        --output data/scaffolds/bmw_3series.yaml
"""

import argparse
import logging
import os
import re
import sys
import time
from pathlib import Path

import requests
import yaml
from openai import OpenAI

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

SCAFFOLD_DIR = Path(__file__).parent.parent / "data" / "scaffolds"
SCHEMA_EXAMPLE = SCAFFOLD_DIR / "vw_golf.yaml"

MODEL = "deepseek-chat"

# ── DeepSeek client ───────────────────────────────────────────────────────────

api_key = os.environ.get("DEEPSEEK_API_KEY")
if not api_key:
    sys.exit("DEEPSEEK_API_KEY environment variable not set")

client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com/v1")

# ── Page fetching ─────────────────────────────────────────────────────────────

_TAG_RE = re.compile(r"<[^>]+>")
_SPACE_RE = re.compile(r"\n{3,}")


def fetch_text(url: str, timeout: int = 15) -> str:
    """Fetch a URL and return its content as plain text (HTML tags stripped)."""
    log.info(f"Fetching: {url}")
    headers = {"User-Agent": "Mozilla/5.0 (compatible; scaffold-builder/1.0)"}
    try:
        resp = requests.get(url, headers=headers, timeout=timeout)
        resp.raise_for_status()
    except requests.RequestException as e:
        log.error(f"Failed to fetch {url}: {e}")
        return ""

    # Try BeautifulSoup for cleaner extraction; fall back to regex strip
    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(resp.text, "html.parser")
        # Remove script/style noise
        for tag in soup(["script", "style", "nav", "footer", "header"]):
            tag.decompose()
        text = soup.get_text(separator="\n")
    except ImportError:
        text = _TAG_RE.sub(" ", resp.text)

    text = _SPACE_RE.sub("\n\n", text).strip()
    log.info(f"Fetched {len(text):,} chars from {url}")
    return text


# ── Prompt ────────────────────────────────────────────────────────────────────

SYSTEM_PROMPT = (
    "You are an automotive data engineer. You will be given raw text scraped from "
    "one or more vehicle specification pages, plus a YAML schema example. "
    "Your job is to produce a new scaffold YAML for the requested make/model "
    "that follows the exact same schema. "
    "Use the scraped data as the primary source for engine specs and year ranges. "
    "Use your own knowledge to fill in engine family codes (e.g. EA111, EA211, B47), "
    "transmission codes (e.g. DQ200, ZF8HP), part codes, and known failure modes "
    "that are not on the page. "
    "Return ONLY valid YAML — no markdown fences, no explanation."
)


def build_prompt(make: str, model: str, scraped_pages: list[str], schema_yaml: str) -> str:
    pages_block = "\n\n---\n\n".join(
        f"[SOURCE {i + 1}]\n{text}" for i, text in enumerate(scraped_pages)
    )
    return f"""Generate a vehicle knowledge scaffold YAML for: {make} {model}

=== SCHEMA EXAMPLE (follow this structure exactly) ===

{schema_yaml}

=== SCRAPED SPEC PAGES ===

{pages_block}

=== INSTRUCTIONS ===

1. Keep the same top-level keys: meta, year_cohorts, engine_families, transmissions
2. Fill meta.make, meta.model, meta.generations from the scraped data
3. Derive year_cohorts from major engine-family transitions visible in the data
4. For each engine family: code, fuel_type, displacements, year_range, known_issues
   - known_issues must reference stm_topic: null (this is a new corpus, no topic IDs yet)
   - Include severity and notes for each known issue
5. For each transmission: code, internal_code, type, compatible_engines, year_range,
   known_names_tr (if Turkish forum is the target — leave empty list otherwise),
   known_issues
6. Output valid YAML only."""


# ── LLM call ─────────────────────────────────────────────────────────────────


def call_llm(prompt: str, max_retries: int = 3) -> str | None:
    for attempt in range(1, max_retries + 1):
        try:
            log.info(f"LLM call attempt {attempt}/{max_retries}")
            response = client.chat.completions.create(
                model=MODEL,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.1,
                max_tokens=3000,
            )
            raw = response.choices[0].message.content.strip()
            # Strip accidental markdown fences
            if raw.startswith("```"):
                raw = raw.split("```", 2)[1]
                if raw.startswith("yaml"):
                    raw = raw[4:]
                raw = raw.strip()
            return raw
        except Exception as e:
            log.warning(f"LLM error on attempt {attempt}: {e}")
            if attempt < max_retries:
                time.sleep(5 * attempt)

    log.error("All LLM attempts failed")
    return None


# ── Main ─────────────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(description="Generate a vehicle scaffold YAML via LLM")
    parser.add_argument("--make",   required=True, help="Vehicle make (e.g. VW)")
    parser.add_argument("--model",  required=True, help="Vehicle model (e.g. Golf)")
    parser.add_argument("--url",    required=True, action="append", dest="urls",
                        help="Spec page URL(s) to scrape (repeat for multiple)")
    parser.add_argument("--output", default=None,
                        help="Output path (default: data/scaffolds/<make>_<model>.yaml)")
    parser.add_argument("--schema", default=str(SCHEMA_EXAMPLE),
                        help="Path to schema example YAML (default: vw_golf.yaml)")
    args = parser.parse_args()

    # Output path
    if args.output:
        out_path = Path(args.output)
    else:
        slug = f"{args.make.lower()}_{args.model.lower().replace(' ', '_')}"
        out_path = SCAFFOLD_DIR / f"{slug}_generated.yaml"

    # Load schema example
    schema_path = Path(args.schema)
    if not schema_path.exists():
        sys.exit(f"Schema example not found: {schema_path}")
    schema_yaml = schema_path.read_text(encoding="utf-8")
    log.info(f"Schema loaded from {schema_path}")

    # Fetch pages
    scraped = [fetch_text(url) for url in args.urls]
    scraped = [t for t in scraped if t]
    if not scraped:
        sys.exit("No page content could be fetched — aborting")

    # Build prompt and call LLM
    prompt = build_prompt(args.make, args.model, scraped, schema_yaml)
    log.info(f"Prompt length: {len(prompt):,} chars")

    raw_yaml = call_llm(prompt)
    if raw_yaml is None:
        sys.exit("LLM failed to produce output")

    # Validate YAML before saving
    try:
        parsed = yaml.safe_load(raw_yaml)
        required_keys = {"meta", "year_cohorts", "engine_families", "transmissions"}
        missing = required_keys - set(parsed.keys())
        if missing:
            log.warning(f"Output YAML is missing top-level keys: {missing}")
    except yaml.YAMLError as e:
        log.error(f"LLM output is not valid YAML: {e}")
        log.error(f"Raw output:\n{raw_yaml}")
        sys.exit(1)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(raw_yaml, encoding="utf-8")
    log.info(f"Saved: {out_path}")


if __name__ == "__main__":
    main()
