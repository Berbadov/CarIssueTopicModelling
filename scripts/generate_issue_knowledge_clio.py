#!/usr/bin/env python3
"""
generate_issue_knowledge_clio.py
--------------------------------
Builds structured issue knowledge from Clio STM outputs via DeepSeek API.

Usage:
  DEEPSEEK_API_KEY=<key> python scripts/generate_issue_knowledge_clio.py
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

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data" / "processed"
SCAFFOLD_FILE = ROOT / "data" / "scaffolds" / "renault_clio.yaml"
MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")
MAX_WORKERS = int(os.environ.get("DEEPSEEK_WORKERS", "3"))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)


def load_scaffold(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


SCAFFOLD = load_scaffold(SCAFFOLD_FILE)

api_key = os.environ.get("DEEPSEEK_API_KEY")
if not api_key:
    sys.exit("DEEPSEEK_API_KEY environment variable not set")

client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com/v1")


def load_data() -> dict:
    enriched = pd.read_csv(DATA_DIR / "stm_thread_enriched_clio.csv")
    effects = pd.read_csv(DATA_DIR / "stm_topic_engine_effects_clio.csv")
    llm_input = pd.read_csv(DATA_DIR / "llm_issue_input_clio.csv")

    top_terms = pd.read_excel(DATA_DIR / "stm_results_clio.xlsx", sheet_name="top_terms")
    gamma_full = pd.read_excel(DATA_DIR / "stm_results_clio.xlsx", sheet_name="gamma_full")
    thread_data = pd.read_excel(DATA_DIR / "stm_results_clio.xlsx", sheet_name="thread_topics")

    if "doc_name" in gamma_full.columns and "document" in gamma_full.columns:
        gamma_full = gamma_full.drop(columns=["document"])
    elif "doc_name" not in gamma_full.columns and "document" in gamma_full.columns:
        gamma_full = gamma_full.rename(columns={"document": "doc_name"})

    if "doc_name" not in gamma_full.columns:
        raise ValueError("gamma_full sheet must contain 'doc_name' or 'document' column")

    return {
        "enriched": enriched,
        "effects": effects,
        "llm_input": llm_input,
        "top_terms": top_terms,
        "gamma_full": gamma_full,
        "thread_data": thread_data,
    }


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
        yr = ef.get("year_range", ["?", "?"])
        lines.append(f"  {ef['code']} | {ef['fuel_type']} | {disps} | {yr[0]}-{yr[1]}")

    lines.append("\nTransmissions:")
    for tx in scaffold.get("transmissions", []):
        compat = ", ".join(tx.get("compatible_engines", []))
        yr = tx.get("year_range", ["?", "?"])
        lines.append(
            f"  {tx['code']} ({tx.get('internal_code', '?')}) | {tx['type']} | "
            f"{compat} | {yr[0]}-{yr[1]}"
        )

    return "\n".join(lines)


SCAFFOLD_CONTEXT = build_scaffold_context(SCAFFOLD)

SYSTEM_PROMPT = (
    "You are an automotive data analyst specializing in Turkish Renault Clio forum data. "
    "You will receive a structured data bundle for one STM topic. "
    "Return ONLY valid JSON - no markdown, no explanation, no code fences.\n\n"
    "Rules:\n"
    "- Infer issues strictly from the topic bundle evidence (terms, snippets, prevalence, covariates).\n"
    "- Treat scaffold as structural metadata only (engine/transmission/year mapping), not issue evidence.\n"
    "- Populate affected_engines conservatively. If evidence is broad, use ['all'].\n"
    "- Only mark chronic_failure when chronic_signal and snippets support repeated unresolved complaints.\n"
    "- engine_family_codes must be evidence-based from provided bundle and scaffold only.\n"
    "- Use FREX terms as the primary signal for classification.\n"
    "- Keep notes explicit about uncertainty where needed."
)


def build_bundle(topic_id: int, data: dict) -> dict:
    enriched = data["enriched"]
    effects = data["effects"]
    llm_input = data["llm_input"]
    top_terms = data["top_terms"]
    gamma_full = data["gamma_full"]
    thread_data = data["thread_data"]

    tt_row = top_terms[top_terms["topic"] == topic_id].iloc[0]
    li_row = llm_input[llm_input["topic"] == topic_id].iloc[0]

    topic_threads = enriched[enriched["dominant_topic"] == topic_id]
    thread_count = len(topic_threads)

    high_gamma = gamma_full[
        (gamma_full["topic"] == topic_id) & (gamma_full["gamma"] > 0.3)
    ][["doc_name", "gamma"]]

    mileage_df = high_gamma.merge(
        enriched[["doc_name", "mileage_km"]].dropna(subset=["mileage_km"]),
        on="doc_name",
        how="inner",
    )

    mileage_n = len(mileage_df)
    if mileage_n >= 5:
        mileage_median = int(mileage_df["mileage_km"].median())
        mileage_p20 = int(mileage_df["mileage_km"].quantile(0.2))
        mileage_p80 = int(mileage_df["mileage_km"].quantile(0.8))
    else:
        mileage_median = mileage_p20 = mileage_p80 = None

    if thread_count > 0:
        eng_counts = topic_threads.groupby("engine_group").size().reset_index(name="n")
        eng_counts["pct"] = (eng_counts["n"] / thread_count * 100).round(1)
        engine_breakdown = eng_counts.sort_values("n", ascending=False).to_dict("records")
    else:
        engine_breakdown = []

    topic_effects = (
        effects[effects["topic"] == topic_id][
            ["engine_group", "estimate", "ci_lower", "ci_upper", "significant"]
        ]
        .sort_values("estimate", ascending=False)
        .to_dict("records")
    )
    for row in topic_effects:
        row["significant"] = bool(row.get("significant", False))

    cohorts = SCAFFOLD.get("year_cohorts", {})
    year_cohort_breakdown = {}
    if "year" in enriched.columns and thread_count > 0:
        for cohort_key, cohort in cohorts.items():
            mask = (topic_threads["year"] >= cohort["year_min"]) & (
                topic_threads["year"] < cohort["year_max"]
            )
            cohort_threads = topic_threads[mask]
            if len(cohort_threads) == 0:
                continue
            eng_by_cohort = (
                cohort_threads.groupby("engine_group")
                .size()
                .reset_index(name="n")
                .sort_values("n", ascending=False)
            )
            eng_by_cohort["pct_of_cohort"] = (
                eng_by_cohort["n"] / len(cohort_threads) * 100
            ).round(1)
            year_cohort_breakdown[cohort_key] = {
                "label": cohort["label"],
                "total_threads": len(cohort_threads),
                "engine_breakdown": eng_by_cohort.to_dict("records"),
            }

    gf_topic = gamma_full[gamma_full["topic"] == topic_id][["doc_name", "gamma"]]
    if "technical_score" in thread_data.columns and "txt" in thread_data.columns:
        snippet_df = gf_topic.merge(
            thread_data[["doc_name", "txt", "technical_score"]].copy(),
            on="doc_name",
            how="inner",
        )
        snippet_df["technical_score"] = snippet_df["technical_score"].fillna(0)
        snippet_df["rank_score"] = snippet_df["gamma"] * (
            1 + snippet_df["technical_score"].clip(upper=8) / 8
        )
        top5 = snippet_df.nlargest(5, "rank_score")
        snippets = [str(s)[:250] for s in top5["txt"].tolist()]
    elif "txt" in thread_data.columns:
        snippet_df = gf_topic.merge(
            thread_data[["doc_name", "txt"]].copy(),
            on="doc_name",
            how="inner",
        )
        top5 = snippet_df.nlargest(5, "gamma")
        snippets = [str(s)[:250] for s in top5["txt"].tolist()]
    else:
        snippets = []

    return {
        "topic_id": topic_id,
        "terms_frex": str(tt_row.get("terms_frex", "")),
        "terms_prob": str(tt_row.get("terms_prob", "")),
        "prevalence_pct": round(float(li_row.get("prevalence_pct", 0)), 1),
        "chronic_signal": round(float(li_row.get("chronic_signal", 0)), 3),
        "thread_count": thread_count,
        "mileage_median_km": mileage_median,
        "mileage_p20_km": mileage_p20,
        "mileage_p80_km": mileage_p80,
        "mileage_thread_count": mileage_n,
        "engine_breakdown": engine_breakdown,
        "covariate_effects": topic_effects,
        "year_cohort_breakdown": year_cohort_breakdown,
        "snippets": snippets,
    }


def format_prompt(bundle: dict) -> str:
    if bundle["mileage_median_km"] is not None:
        mileage_line = (
            f"Median: {bundle['mileage_median_km']} km | "
            f"P20-P80: {bundle['mileage_p20_km']}-{bundle['mileage_p80_km']} km"
        )
    else:
        mileage_line = "Insufficient mileage data"

    cohort_section = (
        json.dumps(bundle["year_cohort_breakdown"], ensure_ascii=False, indent=2)
        if bundle["year_cohort_breakdown"]
        else "  No year data available"
    )

    snippet_lines = "\n".join(
        f"[{i + 1}] {s}" for i, s in enumerate(bundle["snippets"])
    )

    return f"""Analyze this STM topic bundle and return structured JSON.

=== VEHICLE STRUCTURE CONTEXT (NO ISSUE PRIORS) ===
{SCAFFOLD_CONTEXT}

=== TOPIC DATA BUNDLE (Topic {bundle['topic_id']}) ===

FREX terms: {bundle['terms_frex']}
PROB terms: {bundle['terms_prob']}

Corpus prevalence: {bundle['prevalence_pct']}%
Thread count (dominant): {bundle['thread_count']}
Chronic signal: {bundle['chronic_signal']}

Mileage distribution (gamma > 0.3, n={bundle['mileage_thread_count']}):
  {mileage_line}

Engine breakdown (% of dominant-topic threads):
{json.dumps(bundle['engine_breakdown'], ensure_ascii=False, indent=2)}

Year-cohort x engine breakdown:
{cohort_section}

Covariate effects:
{json.dumps(bundle['covariate_effects'], ensure_ascii=False, indent=2)}

Representative snippets:
{snippet_lines}

=== OUTPUT JSON SCHEMA ===
{{
  "topic_id": {bundle['topic_id']},
  "label": "descriptive label in English",
  "label_short": "2-3 word short label",
  "system_component": "engine | gearbox | cooling | electrical | suspension | exhaust | brakes | battery | lighting | other",
  "issue_type": "chronic_failure | intermittent_fault | wear_item | sensor_fault | fluid_leak | noise | other",
  "severity": "low | medium | high",
  "confidence": "low | medium | high",
  "onset_mileage_typical_km": null,
  "onset_mileage_range": "e.g. 80k-130k km or null",
  "affected_engines": ["use specific engines only when evidence is clear, otherwise 'all'"],
  "affected_years": "e.g. pre-2013, 2013-2019, all, or null",
  "engine_family_codes": [],
  "known_part_codes": [{{"code": "optional", "name": "optional", "notes": "optional"}}],
  "engine_notes": "1 sentence or null",
  "prevalence_pct": {bundle['prevalence_pct']},
  "chronic_signal": {bundle['chronic_signal']},
  "summary": "2 concise sentences",
  "warning_signs": ["sign 1", "sign 2"],
  "inspection_advice": "1-2 sentences",
  "data_quality": "low | medium | high",
  "thread_count": {bundle['thread_count']},
  "notes": "caveats / uncertainty / mixed-topic concerns"
}}"""


def call_deepseek(prompt: str, topic_id: int, max_retries: int = 3) -> dict | None:
    for attempt in range(1, max_retries + 1):
        try:
            log.info("T%s: API call attempt %d/%d", topic_id, attempt, max_retries)
            response = client.chat.completions.create(
                model=MODEL,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.2,
                max_tokens=2000,
            )
            raw = (response.choices[0].message.content or "").strip()
            if raw.startswith("```"):
                raw = raw.split("```", 2)[1]
                if raw.startswith("json"):
                    raw = raw[4:]
                raw = raw.strip()
            return json.loads(raw)
        except json.JSONDecodeError as e:
            log.warning("T%s: JSON parse error on attempt %d: %s", topic_id, attempt, e)
        except Exception as e:
            log.warning("T%s: API error on attempt %d: %s", topic_id, attempt, e)

        if attempt < max_retries:
            time.sleep(5 * attempt)

    log.error("T%s: all retries failed", topic_id)
    return None


def process_topic(topic_id: int, data: dict) -> dict:
    bundle = build_bundle(topic_id, data)
    prompt = format_prompt(bundle)
    result = call_deepseek(prompt, topic_id)
    if result is None:
        result = {"topic_id": topic_id, "error": "failed_after_retries"}
    return result


def main() -> None:
    data = load_data()

    topic_ids = sorted(int(x) for x in data["top_terms"]["topic"].dropna().unique())
    if not topic_ids:
        sys.exit("No topics found in stm_results_clio.xlsx / top_terms sheet")

    json_path = DATA_DIR / "issue_knowledge_clio.json"
    results_map: dict[int, dict] = {}

    if json_path.exists():
        with open(json_path, encoding="utf-8") as f:
            existing = json.load(f)
        for row in existing:
            tid = row.get("topic_id")
            if tid in topic_ids and "error" not in row:
                results_map[int(tid)] = row
                log.info("T%s: loaded from existing results, skipping", tid)

    todo = [tid for tid in topic_ids if tid not in results_map]
    log.info("Topics to process: %s", todo)

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = {pool.submit(process_topic, tid, data): tid for tid in todo}
        for future in as_completed(futures):
            tid = futures[future]
            try:
                results_map[tid] = future.result()
                log.info("T%s: done", tid)
            except Exception as e:
                log.error("T%s: unhandled error: %s", tid, e)
                results_map[tid] = {"topic_id": tid, "error": str(e)}

    results = [results_map[tid] for tid in topic_ids]

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    log.info("Saved: %s", json_path)

    csv_path = DATA_DIR / "issue_knowledge_clio.csv"
    flat_rows = []
    for row in results:
        flat_rows.append(
            {
                k: (json.dumps(v, ensure_ascii=False) if isinstance(v, (list, dict)) else v)
                for k, v in row.items()
            }
        )
    pd.DataFrame(flat_rows).to_csv(csv_path, index=False)
    log.info("Saved: %s", csv_path)


if __name__ == "__main__":
    main()
