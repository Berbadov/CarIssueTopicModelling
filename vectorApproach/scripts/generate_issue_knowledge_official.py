#!/usr/bin/env python3
"""
generate_issue_knowledge_official.py
──────────────────────────────────────
LLM interpretation of BERTopic topics from official sources
(NHTSA TSBs, recalls, CarComplaints, CarProblemZoo).

Usage:
    DEEPSEEK_API_KEY=<key> python scripts/generate_issue_knowledge_official.py
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

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger(__name__)

ROOT          = Path(__file__).resolve().parent.parent
DATA_DIR      = ROOT / "data" / "processed"
SCAFFOLD_PATH = ROOT / "data" / "scaffolds" / "vw_golf.yaml"
MODEL         = "deepseek-chat"


def load_scaffold(path):
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)

SCAFFOLD = load_scaffold(SCAFFOLD_PATH)

api_key = os.environ.get("DEEPSEEK_API_KEY")
if not api_key:
    sys.exit("DEEPSEEK_API_KEY not set")
client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com/v1")


def load_data() -> dict:
    log.info("Loading official BERTopic outputs ...")
    enriched  = pd.read_csv(DATA_DIR / "official_thread_enriched.csv")
    effects   = pd.read_csv(DATA_DIR / "official_covariate_effects.csv")
    llm_input = pd.read_csv(DATA_DIR / "official_llm_input.csv")
    top_terms = pd.read_csv(DATA_DIR / "official_top_terms.csv")
    prepared  = pd.read_csv(DATA_DIR / "official_prepared.csv", dtype=str, low_memory=False)
    log.info("Loaded. %d topics, %d enriched docs.", len(top_terms), len(enriched))
    return dict(enriched=enriched, effects=effects, llm_input=llm_input,
                top_terms=top_terms, prepared=prepared)


def build_bundle(topic_id: int, data: dict) -> dict:
    enriched  = data["enriched"]
    llm_input = data["llm_input"]
    top_terms = data["top_terms"]
    prepared  = data["prepared"]

    tt_row   = top_terms[top_terms["topic"] == topic_id].iloc[0]
    li_row   = llm_input[llm_input["topic"] == topic_id].iloc[0]

    topic_docs = enriched[enriched["dominant_topic"] == topic_id]
    n = len(topic_docs)

    # Engine spec breakdown
    spec_counts = topic_docs["engine_spec"].value_counts().reset_index()
    spec_counts.columns = ["engine_spec", "n"]
    spec_counts["pct"]  = (spec_counts["n"] / n * 100).round(1)

    # Year breakdown
    year_counts = topic_docs["prod_year"].dropna().value_counts().head(8).reset_index()
    year_counts.columns = ["year", "n"]

    # Source breakdown
    src_counts = topic_docs["source"].value_counts().reset_index()
    src_counts.columns = ["source", "n"]

    # Top snippets
    topic_enr = topic_docs.copy()
    topic_enr["topic_gamma"] = pd.to_numeric(topic_enr.get("topic_gamma", 0), errors="coerce").fillna(0)
    left = topic_enr.drop(columns=["technical_score"], errors="ignore")
    snippet_df = left.merge(
        prepared[["doc_name", "txt", "technical_score"]].drop_duplicates("doc_name"),
        on="doc_name", how="inner",
    )
    if len(snippet_df) > 0:
        snippet_df["technical_score"] = pd.to_numeric(snippet_df["technical_score"], errors="coerce").fillna(0)
        snippet_df["rank"] = snippet_df["topic_gamma"] * (1 + snippet_df["technical_score"].clip(upper=8) / 8)
        snippets = [str(s)[:400] for s in snippet_df.nlargest(5, "rank")["txt"].tolist()]
    else:
        snippets = []

    mid = li_row.get("mileage_median_miles")
    p20 = li_row.get("mileage_p20_miles")
    p80 = li_row.get("mileage_p80_miles")

    return {
        "topic_id":             topic_id,
        "terms":                str(tt_row["terms_prob"]),
        "prevalence_pct":       round(float(li_row["prevalence_pct"]), 1),
        "chronic_signal":       round(float(li_row.get("chronic_signal", 0)), 3),
        "thread_count":         int(li_row["thread_count"]),
        "source_breakdown":     str(li_row.get("source_breakdown", "")),
        "mileage_median_miles": int(mid) if pd.notna(mid) else None,
        "mileage_p20_miles":    int(p20) if pd.notna(p20) else None,
        "mileage_p80_miles":    int(p80) if pd.notna(p80) else None,
        "engine_breakdown":     spec_counts.to_dict("records"),
        "year_breakdown":       year_counts.to_dict("records"),
        "source_detail":        src_counts.to_dict("records"),
        "snippets":             snippets,
    }


def build_scaffold_context(scaffold: dict) -> str:
    lines = []
    meta = scaffold.get("meta", {})
    lines.append(f"Vehicle: {meta.get('make','?')} {meta.get('model','?')}")
    for ef in scaffold.get("engine_families", []):
        disps = ", ".join(ef.get("displacements", []))
        yr    = ef.get("year_range", [])
        lines.append(f"  {ef['code']} | {ef['fuel_type']} | {disps} | {yr[0]}–{yr[1]}")
        for issue in ef.get("known_issues", []):
            if issue.get("issue") != "none_major":
                lines.append(f"    • {issue['issue']}: {issue.get('notes','').strip()}")
    for tx in scaffold.get("transmissions", []):
        compat = ", ".join(tx.get("compatible_engines", []))
        yr     = tx.get("year_range", [])
        lines.append(f"  {tx['code']} | {tx['type']} | {compat} | {yr[0]}–{yr[1]}")
        for issue in tx.get("known_issues", []):
            lines.append(f"    • {issue['issue']}: {issue.get('notes','').strip()}")
    return "\n".join(lines)

SCAFFOLD_CONTEXT = build_scaffold_context(SCAFFOLD)

SYSTEM_PROMPT = (
    "You are an automotive reliability analyst. "
    "You will receive a BERTopic topic bundle aggregated from multiple official sources: "
    "NHTSA Technical Service Bulletins (manufacturer repair instructions), "
    "NHTSA safety recalls (defect/consequence/remedy), "
    "CarComplaints.com owner narratives, and CarProblemZoo owner reports — all for VW Golf. "
    "Sources span US and European market vehicles. "
    "Engine specs: 2.0_TSI (GTI/R), 2.0_TDI (diesel), 1.8_TSI, 1.4_TSI, 1.6_TDI, 1.5_TSI etc. "
    "Return ONLY valid JSON — no markdown, no code fences."
)


def format_prompt(bundle: dict) -> str:
    mid = bundle["mileage_median_miles"]
    p20 = bundle["mileage_p20_miles"]
    p80 = bundle["mileage_p80_miles"]
    mileage_line = f"Median: {mid} miles | P20–P80: {p20}–{p80}" if mid else "Insufficient mileage data"

    return f"""Analyze this multi-source BERTopic topic and return structured JSON.

=== VEHICLE KNOWLEDGE ===
{SCAFFOLD_CONTEXT}

=== TOPIC {bundle["topic_id"]} ===

Terms: {bundle["terms"]}
Prevalence: {bundle["prevalence_pct"]}% ({bundle["thread_count"]} documents)
Source breakdown: {bundle["source_breakdown"]}
Mileage: {mileage_line}

Engine spec breakdown:
{json.dumps(bundle["engine_breakdown"], indent=2)}

Production year breakdown:
{json.dumps(bundle["year_breakdown"], indent=2)}

Representative snippets:
{chr(10).join(f"[{i+1}] {s}" for i, s in enumerate(bundle["snippets"]))}

=== OUTPUT FORMAT (JSON only) ===

{{
  "topic_id": {bundle["topic_id"]},
  "label": "descriptive label",
  "label_short": "2-3 word short label",
  "system_component": "engine | gearbox | cooling | electrical | suspension | exhaust | brakes | battery | lighting | other",
  "issue_type": "chronic_failure | intermittent_fault | wear_item | sensor_fault | fluid_leak | noise | safety_recall | other",
  "severity": "low | medium | high",
  "confidence": "low | medium | high",
  "onset_mileage_typical_miles": null,
  "onset_mileage_range": "e.g. 40k-80k miles or null",
  "affected_engines": ["e.g. 1.4_TSI", "2.0_TSI"],
  "affected_years": "e.g. 2010-2014 or null",
  "known_part_codes": [{{"code": "part number", "name": "part name", "notes": "optional"}}],
  "engine_notes": "1 sentence on engine-specific patterns or null",
  "prevalence_pct": {bundle["prevalence_pct"]},
  "chronic_signal": {bundle["chronic_signal"]},
  "summary": "2 sentences describing the issue pattern based on the combined source data",
  "warning_signs": ["sign 1", "sign 2"],
  "inspection_advice": "1-2 sentences on what to check when buying a used VW Golf",
  "data_quality": "low | medium | high",
  "thread_count": {bundle["thread_count"]},
  "notes": "source caveats (e.g. US-only data, recall-dominated) or null"
}}"""


def call_deepseek(prompt: str, topic_id: int) -> dict | None:
    for attempt in range(1, 4):
        try:
            log.info("T%d attempt %d", topic_id, attempt)
            resp = client.chat.completions.create(
                model=MODEL,
                messages=[{"role": "system", "content": SYSTEM_PROMPT},
                          {"role": "user", "content": prompt}],
                temperature=0.2, max_tokens=2000,
            )
            raw = resp.choices[0].message.content.strip()
            if raw.startswith("```"):
                raw = raw.split("```", 2)[1]
                if raw.startswith("json"):
                    raw = raw[4:]
                raw = raw.strip()
            return json.loads(raw)
        except json.JSONDecodeError as e:
            log.warning("T%d JSON error: %s", topic_id, e)
        except Exception as e:
            log.warning("T%d API error: %s", topic_id, e)
        if attempt < 3:
            time.sleep(5 * attempt)
    return None


def process_topic(topic_id: int, data: dict) -> dict:
    bundle = build_bundle(topic_id, data)
    result = call_deepseek(format_prompt(bundle), topic_id)
    return result or {"topic_id": topic_id, "error": "failed_after_retries"}


def main():
    data = load_data()
    topic_ids = sorted(data["top_terms"]["topic"].tolist())
    log.info("Topics: %s", topic_ids)

    json_path = DATA_DIR / "issue_knowledge_official.json"
    results_map: dict[int, dict] = {}
    if json_path.exists():
        for r in json.loads(json_path.read_text(encoding="utf-8")):
            if "error" not in r:
                results_map[r["topic_id"]] = r

    todo = [t for t in topic_ids if t not in results_map]
    log.info("To process: %s", todo)

    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = {pool.submit(process_topic, t, data): t for t in todo}
        for future in as_completed(futures):
            t = futures[future]
            try:
                results_map[t] = future.result()
                log.info("T%d done", t)
            except Exception as e:
                results_map[t] = {"topic_id": t, "error": str(e)}

    results = [results_map[t] for t in topic_ids]
    json_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    log.info("Saved: %s", json_path)

    flat = [{k: (json.dumps(v) if isinstance(v, (list, dict)) else v) for k, v in r.items()} for r in results]
    pd.DataFrame(flat).to_csv(DATA_DIR / "issue_knowledge_official.csv", index=False)
    log.info("Done. %d topics.", len(topic_ids))


if __name__ == "__main__":
    main()
