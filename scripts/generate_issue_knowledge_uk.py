#!/usr/bin/env python3
"""
generate_issue_knowledge_uk.py
──────────────────────────────
Reads BERTopic UK outputs, builds a context bundle per topic,
calls DeepSeek API (deepseek-chat), and writes structured issue knowledge
to data/processed/issue_knowledge_uk.json and issue_knowledge_uk.csv.

Usage:
    DEEPSEEK_API_KEY=<key> python scripts/generate_issue_knowledge_uk.py
"""

import json
import logging
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pandas as pd
import yaml
from openai import OpenAI

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data" / "processed"
SCAFFOLD_PATH = ROOT / "data" / "scaffolds" / "vw_golf.yaml"
MODEL = "deepseek-chat"

# ── Scaffold ─────────────────────────────────────────────────────────────────


def load_scaffold(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


SCAFFOLD = load_scaffold(SCAFFOLD_PATH)


# ── DeepSeek client ──────────────────────────────────────────────────────────

api_key = os.environ.get("DEEPSEEK_API_KEY")
if not api_key:
    sys.exit("DEEPSEEK_API_KEY environment variable not set")

client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com/v1")


# ── Data loading ─────────────────────────────────────────────────────────────


def load_data() -> dict:
    log.info("Loading BERTopic UK outputs ...")

    enriched = pd.read_csv(DATA_DIR / "bertopic_thread_enriched_uk.csv")
    effects = pd.read_csv(DATA_DIR / "bertopic_covariate_effects_uk.csv")
    llm_input = pd.read_csv(DATA_DIR / "llm_issue_input_uk.csv")
    top_terms = pd.read_csv(DATA_DIR / "bertopic_top_terms_uk.csv")
    prepared = pd.read_csv(DATA_DIR / "uk_threads_prepared.csv")

    log.info("All data loaded. %d topics, %d enriched threads.",
             len(top_terms), len(enriched))
    return dict(
        enriched=enriched,
        effects=effects,
        llm_input=llm_input,
        top_terms=top_terms,
        prepared=prepared,
    )


# ── Context bundle builder ───────────────────────────────────────────────────


def build_bundle(topic_id: int, data: dict) -> dict:
    enriched = data["enriched"]
    effects = data["effects"]
    llm_input = data["llm_input"]
    top_terms = data["top_terms"]
    prepared = data["prepared"]

    # Terms
    tt_row = top_terms[top_terms["topic"] == topic_id].iloc[0]
    terms = str(tt_row.get("terms_prob", ""))

    # Prevalence + chronic signal
    li_row = llm_input[llm_input["topic"] == topic_id].iloc[0]
    prevalence_pct = round(float(li_row["prevalence_pct"]), 1)
    chronic_signal = round(float(li_row.get("chronic_signal", 0)), 3)
    thread_count = int(li_row["thread_count"])

    # Mileage (miles)
    mid = li_row.get("mileage_median_miles")
    p20 = li_row.get("mileage_p20_miles")
    p80 = li_row.get("mileage_p80_miles")
    mileage_median = int(mid) if pd.notna(mid) else None
    mileage_p20 = int(p20) if pd.notna(p20) else None
    mileage_p80 = int(p80) if pd.notna(p80) else None

    # Engine group breakdown
    topic_threads = enriched[enriched["dominant_topic"] == topic_id]
    if len(topic_threads) > 0:
        eng_counts = topic_threads["engine_group"].value_counts().reset_index()
        eng_counts.columns = ["engine_group", "n"]
        eng_counts["pct"] = (eng_counts["n"] / len(topic_threads) * 100).round(1)
        engine_breakdown = eng_counts.to_dict("records")
    else:
        engine_breakdown = []

    # Covariate effects
    topic_effects = effects[effects["topic"] == topic_id][
        ["feature", "coefficient"]
    ].to_dict("records")

    # Top 5 snippets: merge enriched with prepared to get text
    topic_enriched = enriched[enriched["dominant_topic"] == topic_id].copy()
    snippet_df = topic_enriched.merge(
        prepared[["doc_name", "txt", "technical_score"]].drop_duplicates("doc_name"),
        on="doc_name", how="inner",
    )
    if len(snippet_df) > 0:
        snippet_df["technical_score"] = snippet_df["technical_score"].fillna(0)
        snippet_df["rank_score"] = snippet_df["topic_gamma"] * (
            1 + snippet_df["technical_score"].clip(upper=8) / 8
        )
        top5 = snippet_df.nlargest(5, "rank_score")
        snippets = [str(s)[:300] for s in top5["txt"].tolist()]
    else:
        snippets = []

    return {
        "topic_id": topic_id,
        "terms": terms,
        "prevalence_pct": prevalence_pct,
        "chronic_signal": chronic_signal,
        "thread_count": thread_count,
        "mileage_median_miles": mileage_median,
        "mileage_p20_miles": mileage_p20,
        "mileage_p80_miles": mileage_p80,
        "engine_breakdown": engine_breakdown,
        "covariate_effects": topic_effects,
        "snippets": snippets,
    }


# ── Scaffold context ─────────────────────────────────────────────────────────


def build_scaffold_context(scaffold: dict) -> str:
    lines = []
    meta = scaffold.get("meta", {})
    lines.append(
        f"Vehicle: {meta.get('make', '?')} {meta.get('model', '?')} "
        f"(gen {meta.get('generations', '?')})"
    )

    lines.append("\nEngine families:")
    for ef in scaffold.get("engine_families", []):
        disps = ", ".join(ef.get("displacements", []))
        yr = ef.get("year_range", [])
        lines.append(f"  {ef['code']} | {ef['fuel_type']} | {disps} | {yr[0]}–{yr[1]}")
        for issue in ef.get("known_issues", []):
            if issue.get("issue") == "none_major":
                continue
            lines.append(f"    • {issue['issue']}: {issue.get('notes', '').strip()}")

    lines.append("\nTransmissions:")
    for tx in scaffold.get("transmissions", []):
        compat = ", ".join(tx.get("compatible_engines", []))
        yr = tx.get("year_range", [])
        lines.append(
            f"  {tx['code']} ({tx.get('internal_code', '?')}) | {tx['type']} | "
            f"{compat} | {yr[0]}–{yr[1]}"
        )
        for issue in tx.get("known_issues", []):
            lines.append(f"    • {issue['issue']}: {issue.get('notes', '').strip()}")

    return "\n".join(lines)


SCAFFOLD_CONTEXT = build_scaffold_context(SCAFFOLD)


# ── Prompt ───────────────────────────────────────────────────────────────────

SYSTEM_PROMPT = (
    "You are an automotive data analyst specializing in UK VW Golf forum data. "
    "You will receive a structured data bundle for one BERTopic topic extracted from "
    "~2,700 UK English forum threads about VW Golf cars (primarily MK5–MK8, majority MK7/MK7.5). "
    "The forum is golfgtiforum.co.uk — users are enthusiast owners of Golf GTI/GTD/R models. "
    "Mileage values are in MILES (UK). "
    "Return ONLY valid JSON — no markdown, no explanation, no code fences."
)


def format_prompt(bundle: dict) -> str:
    mid = bundle["mileage_median_miles"]
    p20 = bundle["mileage_p20_miles"]
    p80 = bundle["mileage_p80_miles"]
    mileage_line = (
        f"Median: {mid} miles | P20–P80: {p20}–{p80} miles"
        if mid is not None
        else "Insufficient mileage data"
    )

    return f"""Analyze this BERTopic topic data bundle and return a structured JSON interpretation.

=== VEHICLE PARTS KNOWLEDGE (use to populate known_part_codes) ===
{SCAFFOLD_CONTEXT}

=== TOPIC DATA BUNDLE (Topic {bundle["topic_id"]}) ===

Topic terms (c-TF-IDF + KeyBERT): {bundle["terms"]}

Corpus prevalence: {bundle["prevalence_pct"]}%
Thread count (dominant topic): {bundle["thread_count"]}
Chronic signal score: {bundle["chronic_signal"]} (higher = more recurring/unresolved complaints)

Mileage distribution (dominant-topic threads):
  {mileage_line}

Engine group / generation breakdown (% of dominant-topic threads):
{json.dumps(bundle["engine_breakdown"], ensure_ascii=False, indent=2)}

Covariate effects (multinomial logistic regression coefficients — positive = more prevalent for that group):
{json.dumps(bundle["covariate_effects"], ensure_ascii=False, indent=2)}

Representative thread snippets (English, ranked by relevance):
{chr(10).join(f"[{i + 1}] {s}" for i, s in enumerate(bundle["snippets"]))}

=== REQUIRED OUTPUT FORMAT (JSON only, no markdown) ===

{{
  "topic_id": {bundle["topic_id"]},
  "label": "descriptive label in English",
  "label_short": "2-3 word short label",
  "system_component": "engine | gearbox | cooling | electrical | suspension | exhaust | brakes | battery | lighting | other",
  "issue_type": "chronic_failure | intermittent_fault | wear_item | sensor_fault | fluid_leak | noise | other",
  "severity": "low | medium | high",
  "confidence": "low | medium | high",
  "onset_mileage_typical_miles": null,
  "onset_mileage_range": "e.g. 20k-50k miles or null",
  "affected_generations": ["e.g. MK7", "MK7.5"],
  "known_part_codes": [{{"code": "e.g. 0AM325065", "name": "e.g. DQ200 mechatronic unit", "notes": "optional"}}],
  "generation_notes": "1 sentence on generation-specific patterns or null",
  "prevalence_pct": {bundle["prevalence_pct"]},
  "chronic_signal": {bundle["chronic_signal"]},
  "summary": "2 sentences describing the issue pattern as observed in the data",
  "warning_signs": ["sign 1", "sign 2"],
  "inspection_advice": "1-2 sentences on what to check when buying",
  "data_quality": "low | medium | high",
  "thread_count": {bundle["thread_count"]},
  "notes": "any caveats or limitations for this topic, or null"
}}"""


# ── API call with retry ──────────────────────────────────────────────────────


def call_deepseek(prompt: str, topic_id: int, max_retries: int = 3) -> dict | None:
    for attempt in range(1, max_retries + 1):
        try:
            log.info("T%d: API call attempt %d/%d", topic_id, attempt, max_retries)
            response = client.chat.completions.create(
                model=MODEL,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.2,
                max_tokens=2000,
            )
            raw = response.choices[0].message.content.strip()
            log.info("T%d: raw response:\n%s", topic_id, raw[:200])
            # Strip markdown code fences if present
            if raw.startswith("```"):
                raw = raw.split("```", 2)[1]
                if raw.startswith("json"):
                    raw = raw[4:]
                raw = raw.strip()
            return json.loads(raw)
        except json.JSONDecodeError as e:
            log.warning("T%d: JSON parse error on attempt %d: %s", topic_id, attempt, e)
        except Exception as e:
            log.warning("T%d: API error on attempt %d: %s", topic_id, attempt, e)
        if attempt < max_retries:
            time.sleep(5 * attempt)

    log.error("T%d: all %d attempts failed — writing null record", topic_id, max_retries)
    return None


# ── Main ─────────────────────────────────────────────────────────────────────


def process_topic(topic_id: int, data: dict) -> dict:
    bundle = build_bundle(topic_id, data)
    prompt = format_prompt(bundle)
    result = call_deepseek(prompt, topic_id)
    if result is None:
        result = {"topic_id": topic_id, "error": "failed_after_retries"}
    return result


MAX_WORKERS = 3


def main():
    data = load_data()
    topic_ids = sorted(data["top_terms"]["topic"].tolist())
    K = len(topic_ids)
    log.info("Found %d topics to process: %s", K, topic_ids)

    # Load existing results to skip already-successful topics
    json_path = DATA_DIR / "issue_knowledge_uk.json"
    results_map: dict[int, dict] = {}
    if json_path.exists():
        with open(json_path, encoding="utf-8") as f:
            existing = json.load(f)
        for r in existing:
            tid = r.get("topic_id")
            if tid and "error" not in r:
                results_map[tid] = r
                log.info("T%d: loaded from existing — skipping", tid)

    todo = [tid for tid in topic_ids if tid not in results_map]
    log.info("Topics to process: %s", todo)

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = {pool.submit(process_topic, tid, data): tid for tid in todo}
        for future in as_completed(futures):
            tid = futures[future]
            try:
                results_map[tid] = future.result()
                log.info("T%d: done", tid)
            except Exception as e:
                log.error("T%d: unhandled error — %s", tid, e)
                results_map[tid] = {"topic_id": tid, "error": str(e)}

    results = [results_map[tid] for tid in topic_ids]

    # JSON output
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    log.info("Saved: %s", json_path)

    # CSV output
    csv_path = DATA_DIR / "issue_knowledge_uk.csv"
    flat = []
    for r in results:
        row = {
            k: (json.dumps(v, ensure_ascii=False) if isinstance(v, (list, dict)) else v)
            for k, v in r.items()
        }
        flat.append(row)
    pd.DataFrame(flat).to_csv(csv_path, index=False)
    log.info("Saved: %s", csv_path)

    log.info("Done. All %d topics processed.", K)


if __name__ == "__main__":
    main()
