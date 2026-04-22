#!/usr/bin/env python3
"""
generate_issue_knowledge_nhtsa.py
──────────────────────────────────
Reads BERTopic NHTSA outputs, builds a context bundle per topic,
calls DeepSeek API (deepseek-chat), writes structured issue knowledge
to data/processed/issue_knowledge_nhtsa.json and issue_knowledge_nhtsa.csv.

Usage:
    DEEPSEEK_API_KEY=<key> python scripts/generate_issue_knowledge_nhtsa.py
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
DATA_DIR      = ROOT / "data" / "processed"
SCAFFOLD_PATH = ROOT / "data" / "scaffolds" / "vw_golf.yaml"
MODEL = "deepseek-chat"


def load_scaffold(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


SCAFFOLD = load_scaffold(SCAFFOLD_PATH)


api_key = os.environ.get("DEEPSEEK_API_KEY")
if not api_key:
    sys.exit("DEEPSEEK_API_KEY environment variable not set")

client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com/v1")


# ── Data loading ──────────────────────────────────────────────────────────────

def load_data() -> dict:
    log.info("Loading NHTSA BERTopic outputs ...")
    enriched  = pd.read_csv(DATA_DIR / "nhtsa_thread_enriched.csv")
    effects   = pd.read_csv(DATA_DIR / "nhtsa_covariate_effects.csv")
    llm_input = pd.read_csv(DATA_DIR / "nhtsa_llm_input.csv")
    top_terms = pd.read_csv(DATA_DIR / "nhtsa_top_terms.csv")
    prepared  = pd.read_csv(DATA_DIR / "nhtsa_prepared.csv", dtype=str, low_memory=False)
    log.info("Loaded. %d topics, %d enriched docs.", len(top_terms), len(enriched))
    return dict(
        enriched=enriched,
        effects=effects,
        llm_input=llm_input,
        top_terms=top_terms,
        prepared=prepared,
    )


# ── Context bundle builder ────────────────────────────────────────────────────

def build_bundle(topic_id: int, data: dict) -> dict:
    enriched  = data["enriched"]
    effects   = data["effects"]
    llm_input = data["llm_input"]
    top_terms = data["top_terms"]
    prepared  = data["prepared"]

    tt_row     = top_terms[top_terms["topic"] == topic_id].iloc[0]
    terms      = str(tt_row.get("terms_prob", ""))

    li_row          = llm_input[llm_input["topic"] == topic_id].iloc[0]
    prevalence_pct  = round(float(li_row["prevalence_pct"]), 1)
    chronic_signal  = round(float(li_row.get("chronic_signal", 0)), 3)
    thread_count    = int(li_row["thread_count"])
    top_comps       = str(li_row.get("top_components", ""))

    mid = li_row.get("mileage_median_miles")
    p20 = li_row.get("mileage_p20_miles")
    p80 = li_row.get("mileage_p80_miles")
    mileage_median = int(mid) if pd.notna(mid) else None
    mileage_p20    = int(p20) if pd.notna(p20) else None
    mileage_p80    = int(p80) if pd.notna(p80) else None

    topic_docs = enriched[enriched["dominant_topic"] == topic_id]

    # Engine spec breakdown
    if len(topic_docs) > 0:
        spec_counts = topic_docs["engine_spec"].value_counts().reset_index()
        spec_counts.columns = ["engine_spec", "n"]
        spec_counts["pct"]   = (spec_counts["n"] / len(topic_docs) * 100).round(1)
        engine_breakdown = spec_counts.to_dict("records")
    else:
        engine_breakdown = []

    # Production year breakdown
    if len(topic_docs) > 0:
        year_counts = topic_docs["prod_year"].dropna().value_counts().head(8).reset_index()
        year_counts.columns = ["year", "n"]
        year_breakdown = year_counts.to_dict("records")
    else:
        year_breakdown = []

    # Covariate effects
    topic_effects = effects[effects["topic"] == topic_id][
        ["feature", "coefficient"]
    ].to_dict("records")

    # Top 5 snippets (from prepared description text)
    topic_enriched = enriched[enriched["dominant_topic"] == topic_id].copy()

    # prepared may use doc_name or complaint_id — try doc_name first
    id_col = "doc_name" if "doc_name" in prepared.columns else None
    if id_col and "doc_name" in topic_enriched.columns:
        snippet_df = topic_enriched.merge(
            prepared[[id_col, "txt", "technical_score"]].drop_duplicates(id_col),
            on=id_col, how="inner",
        )
    else:
        snippet_df = pd.DataFrame()

    if len(snippet_df) > 0:
        snippet_df["technical_score"] = pd.to_numeric(
            snippet_df["technical_score"], errors="coerce").fillna(0)
        snippet_df["topic_gamma"] = pd.to_numeric(
            snippet_df["topic_gamma"], errors="coerce").fillna(0)
        snippet_df["rank_score"] = snippet_df["topic_gamma"] * (
            1 + snippet_df["technical_score"].clip(upper=8) / 8
        )
        top5 = snippet_df.nlargest(5, "rank_score")
        snippets = [str(s)[:400] for s in top5["txt"].tolist()]
    else:
        # Fallback: just take first 5 descriptions from enriched
        desc_col = next(
            (c for c in prepared.columns if c.lower() in ("description", "txt", "cdescr")),
            None
        )
        if desc_col and len(topic_enriched) > 0:
            snippets = [str(s)[:400] for s in topic_enriched.merge(
                prepared[[id_col or "doc_name", desc_col]].drop_duplicates(),
                on=id_col or "doc_name", how="inner"
            )[desc_col].head(5).tolist()]
        else:
            snippets = []

    return {
        "topic_id":            topic_id,
        "terms":               terms,
        "prevalence_pct":      prevalence_pct,
        "chronic_signal":      chronic_signal,
        "thread_count":        thread_count,
        "top_components":      top_comps,
        "mileage_median_miles": mileage_median,
        "mileage_p20_miles":   mileage_p20,
        "mileage_p80_miles":   mileage_p80,
        "engine_breakdown":    engine_breakdown,
        "year_breakdown":      year_breakdown,
        "covariate_effects":   topic_effects,
        "snippets":            snippets,
    }


# ── Scaffold context ──────────────────────────────────────────────────────────

def build_scaffold_context(scaffold: dict) -> str:
    lines = []
    meta = scaffold.get("meta", {})
    lines.append(f"Vehicle: {meta.get('make', '?')} {meta.get('model', '?')} "
                 f"(gen {meta.get('generations', '?')})")
    lines.append("\nEngine families:")
    for ef in scaffold.get("engine_families", []):
        disps = ", ".join(ef.get("displacements", []))
        yr    = ef.get("year_range", [])
        lines.append(f"  {ef['code']} | {ef['fuel_type']} | {disps} | {yr[0]}–{yr[1]}")
        for issue in ef.get("known_issues", []):
            if issue.get("issue") == "none_major":
                continue
            lines.append(f"    • {issue['issue']}: {issue.get('notes', '').strip()}")
    lines.append("\nTransmissions:")
    for tx in scaffold.get("transmissions", []):
        compat = ", ".join(tx.get("compatible_engines", []))
        yr     = tx.get("year_range", [])
        lines.append(
            f"  {tx['code']} ({tx.get('internal_code', '?')}) | {tx['type']} | "
            f"{compat} | {yr[0]}–{yr[1]}")
        for issue in tx.get("known_issues", []):
            lines.append(f"    • {issue['issue']}: {issue.get('notes', '').strip()}")
    return "\n".join(lines)


SCAFFOLD_CONTEXT = build_scaffold_context(SCAFFOLD)

# ── Prompts ───────────────────────────────────────────────────────────────────

SYSTEM_PROMPT = (
    "You are an automotive data analyst specializing in VW Golf reliability data. "
    "You will receive a structured data bundle for one BERTopic topic extracted from "
    "NHTSA (US National Highway Traffic Safety Administration) owner complaints about "
    "VW Golf vehicles. "
    "Complaints are real owner-reported defects filed with a US regulator — they are "
    "more diagnostic than forum posts (owners often state the part, fault code, or "
    "repair performed). "
    "Engine specs are given as displacement+fuel (e.g. 2.0_TSI, 1.8_TSI, 1.4_TSI, 2.0_TDI). "
    "GTI = 2.0 TSI, Golf TDI = 2.0 TDI (US market). "
    "Mileage values are in MILES (US). "
    "The corpus is US market (no 1.5 TSI, 1.6 TDI, or 1.2 TSI — those weren't sold in the US). "
    "Return ONLY valid JSON — no markdown, no explanation, no code fences."
)


def format_prompt(bundle: dict) -> str:
    mid = bundle["mileage_median_miles"]
    p20 = bundle["mileage_p20_miles"]
    p80 = bundle["mileage_p80_miles"]
    mileage_line = (
        f"Median: {mid} miles | P20–P80: {p20}–{p80} miles"
        if mid is not None else "Insufficient mileage data"
    )

    return f"""Analyze this BERTopic topic data bundle from NHTSA VW Golf complaints and return a structured JSON interpretation.

=== VEHICLE PARTS KNOWLEDGE (use to populate known_part_codes) ===
{SCAFFOLD_CONTEXT}

=== TOPIC DATA BUNDLE (Topic {bundle["topic_id"]}) ===

Topic terms (c-TF-IDF + KeyBERT): {bundle["terms"]}

Corpus prevalence: {bundle["prevalence_pct"]}%
Complaint count (dominant topic): {bundle["thread_count"]}
Chronic signal score: {bundle["chronic_signal"]} (higher = more recurring/unresolved complaints)

NHTSA component categories (top): {bundle["top_components"]}

Mileage distribution at time of complaint:
  {mileage_line}

Engine spec breakdown (% of dominant-topic complaints):
{json.dumps(bundle["engine_breakdown"], ensure_ascii=False, indent=2)}

Production year breakdown (top years):
{json.dumps(bundle["year_breakdown"], ensure_ascii=False, indent=2)}

Covariate effects (multinomial logistic regression — positive = more prevalent):
{json.dumps(bundle["covariate_effects"], ensure_ascii=False, indent=2)}

Representative complaint snippets (ranked by relevance):
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
  "affected_engines": ["e.g. 2.0_TSI", "1.8_TSI"],
  "affected_years": "e.g. 2010-2014 or null",
  "known_part_codes": [{{"code": "e.g. 0AM325065", "name": "e.g. DQ200 mechatronic unit", "notes": "optional"}}],
  "engine_notes": "1 sentence on engine-specific patterns, or null",
  "prevalence_pct": {bundle["prevalence_pct"]},
  "chronic_signal": {bundle["chronic_signal"]},
  "summary": "2 sentences describing the issue pattern as observed in the NHTSA complaint data",
  "warning_signs": ["sign 1", "sign 2"],
  "inspection_advice": "1-2 sentences on what to check when buying a used VW Golf",
  "data_quality": "low | medium | high",
  "thread_count": {bundle["thread_count"]},
  "notes": "any caveats (e.g. US-only engine variants, model year limitations), or null"
}}"""


# ── API call ──────────────────────────────────────────────────────────────────

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
            if raw.startswith("```"):
                raw = raw.split("```", 2)[1]
                if raw.startswith("json"):
                    raw = raw[4:]
                raw = raw.strip()
            return json.loads(raw)
        except json.JSONDecodeError as e:
            log.warning("T%d: JSON parse error attempt %d: %s", topic_id, attempt, e)
        except Exception as e:
            log.warning("T%d: API error attempt %d: %s", topic_id, attempt, e)
        if attempt < max_retries:
            time.sleep(5 * attempt)
    log.error("T%d: all %d attempts failed", topic_id, max_retries)
    return None


# ── Main ──────────────────────────────────────────────────────────────────────

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
    log.info("Found %d topics: %s", K, topic_ids)

    json_path = DATA_DIR / "issue_knowledge_nhtsa.json"
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

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    log.info("Saved: %s", json_path)

    csv_path = DATA_DIR / "issue_knowledge_nhtsa.csv"
    flat = []
    for r in results:
        row = {
            k: (json.dumps(v, ensure_ascii=False) if isinstance(v, (list, dict)) else v)
            for k, v in r.items()
        }
        flat.append(row)
    pd.DataFrame(flat).to_csv(csv_path, index=False)
    log.info("Saved: %s", csv_path)
    log.info("Done. %d topics processed.", K)


if __name__ == "__main__":
    main()
