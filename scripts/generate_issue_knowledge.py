#!/usr/bin/env python3
"""
generate_issue_knowledge.py
───────────────────────────
Reads STM outputs, builds a rich context bundle per topic (T1–T10),
calls DeepSeek API (deepseek-chat), and writes structured issue knowledge
to data/processed/issue_knowledge.json and issue_knowledge.csv.

Usage:
    DEEPSEEK_API_KEY=<key> python scripts/generate_issue_knowledge.py
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

__PATH__ = Path(__file__).parent

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

DATA_DIR = Path(r"D:\wstm\data\processed")
SCAFFOLD_DIR = Path(r"D:\wstm\data\scaffolds")
K = 25
MODEL = "deepseek-chat"

# ── Load parts scaffold ───────────────────────────────────────────────────────


def load_scaffold(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


SCAFFOLD = load_scaffold(SCAFFOLD_DIR / "vw_golf.yaml")

# ── DeepSeek client ───────────────────────────────────────────────────────────

api_key = os.environ.get("DEEPSEEK_API_KEY")
if not api_key:
    sys.exit("DEEPSEEK_API_KEY environment variable not set")

client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com/v1")


# ── Data loading ──────────────────────────────────────────────────────────────


def load_data() -> dict:
    log.info("Loading stm_thread_enriched.csv ...")
    enriched = pd.read_csv(DATA_DIR / "stm_thread_enriched.csv")

    log.info("Loading stm_topic_engine_effects.csv ...")
    effects = pd.read_csv(DATA_DIR / "stm_topic_engine_effects.csv")

    log.info("Loading llm_issue_input.csv ...")
    llm_input = pd.read_csv(DATA_DIR / "llm_issue_input.csv")

    log.info("Loading stm_results.xlsx (top_terms, gamma_full, thread_topics) ...")
    top_terms = pd.read_excel(DATA_DIR / "stm_results.xlsx", sheet_name="top_terms")
    gamma_full = pd.read_excel(DATA_DIR / "stm_results.xlsx", sheet_name="gamma_full")
    thread_data = pd.read_excel(
        DATA_DIR / "stm_results.xlsx", sheet_name="thread_topics"
    )

    # Normalise gamma_full key to doc_name
    gamma_full = gamma_full.rename(columns={"document": "doc_name"})

    log.info("All data loaded.")
    return dict(
        enriched=enriched,
        effects=effects,
        llm_input=llm_input,
        top_terms=top_terms,
        gamma_full=gamma_full,
        thread_data=thread_data,
    )


# ── Context bundle builder ────────────────────────────────────────────────────


def build_bundle(topic_id: int, data: dict) -> dict:
    enriched = data["enriched"]
    effects = data["effects"]
    llm_input = data["llm_input"]
    top_terms = data["top_terms"]
    gamma_full = data["gamma_full"]
    thread_data = data["thread_data"]

    # ── Terms ─────────────────────────────────────────────────────────────────
    tt_row = top_terms[top_terms["topic"] == topic_id].iloc[0]
    terms_frex = str(tt_row.get("terms_frex", ""))
    terms_prob = str(tt_row.get("terms_prob", ""))

    # ── Prevalence + chronic signal (pre-computed in llm_issue_input) ─────────
    li_row = llm_input[llm_input["topic"] == topic_id].iloc[0]
    prevalence_pct = round(float(li_row["prevalence_pct"]), 1)
    chronic_signal = round(float(li_row.get("chronic_signal", 0)), 3)

    # ── Thread count (dominant topic) ─────────────────────────────────────────
    topic_threads = enriched[enriched["dominant_topic"] == topic_id]
    thread_count = len(topic_threads)

    # ── Mileage distribution: threads where gamma > 0.3 ──────────────────────
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

    # ── Engine group breakdown (% of dominant-topic threads) ──────────────────
    if thread_count > 0:
        eng_counts = topic_threads.groupby("engine_group").size().reset_index(name="n")
        eng_counts["pct"] = (eng_counts["n"] / thread_count * 100).round(1)
        engine_breakdown = eng_counts.sort_values("n", ascending=False).to_dict(
            "records"
        )
    else:
        engine_breakdown = []

    # ── Covariate effects for this topic ──────────────────────────────────────
    topic_effects = (
        effects[effects["topic"] == topic_id][
            ["engine_group", "estimate", "ci_lower", "ci_upper", "significant"]
        ]
        .sort_values("estimate", ascending=False)
        .to_dict("records")
    )
    # Convert numpy bools to plain Python bools for JSON serialisation
    for row in topic_effects:
        row["significant"] = bool(row["significant"])

    # ── Year-cohort × engine breakdown ────────────────────────────────────────
    # Uses cohorts from the scaffold so the same code works for any scaffold file.
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

    # ── Top 5 snippets: ranked by gamma × (1 + technical_score / 8) ──────────
    gf_topic = gamma_full[gamma_full["topic"] == topic_id][["doc_name", "gamma"]]
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

    return {
        "topic_id": topic_id,
        "terms_frex": terms_frex,
        "terms_prob": terms_prob,
        "prevalence_pct": prevalence_pct,
        "chronic_signal": chronic_signal,
        "thread_count": thread_count,
        "mileage_median_km": mileage_median,
        "mileage_p20_km": mileage_p20,
        "mileage_p80_km": mileage_p80,
        "year_cohort_breakdown": year_cohort_breakdown,
        "mileage_thread_count": mileage_n,
        "engine_breakdown": engine_breakdown,
        "covariate_effects": topic_effects,
        "snippets": snippets,
    }


# ── Scaffold context builder ──────────────────────────────────────────────────


def build_scaffold_context(scaffold: dict) -> str:
    """
    Render the parts scaffold as a compact text block for the prompt.
    Structured this way so swapping the YAML file is enough to support a
    different make/model — no prompt changes needed.
    """
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
            tid = f" [STM T{issue['stm_topic']}]" if issue.get("stm_topic") else ""
            lines.append(
                f"    • {issue['issue']}{tid}: {issue.get('notes', '').strip()}"
            )

    lines.append("\nTransmissions:")
    for tx in scaffold.get("transmissions", []):
        compat = ", ".join(tx.get("compatible_engines", []))
        yr = tx.get("year_range", [])
        lines.append(
            f"  {tx['code']} ({tx.get('internal_code', '?')}) | {tx['type']} | "
            f"{compat} | {yr[0]}–{yr[1]}"
        )
        for issue in tx.get("known_issues", []):
            tid = f" [STM T{issue['stm_topic']}]" if issue.get("stm_topic") else ""
            part = f" part={issue['part_code']}" if issue.get("part_code") else ""
            lines.append(
                f"    • {issue['issue']}{tid}{part}: {issue.get('notes', '').strip()}"
            )

    return "\n".join(lines)


SCAFFOLD_CONTEXT = build_scaffold_context(SCAFFOLD)


# ── Prompt ────────────────────────────────────────────────────────────────────

SYSTEM_PROMPT = (
    "You are an automotive data analyst specializing in Turkish VW Golf forum data. "
    "You will receive a structured data bundle for one STM topic extracted from ~1,978 "
    "Turkish forum threads about VW Golf cars (Golf 5/6/7, majority Golf 7). "
    "Return ONLY valid JSON — no markdown, no explanation, no code fences.\n\n"
    "CRITICAL RULES for engine attribution:\n"
    "- Only populate 'affected_engines' if the covariate effect for a specific engine is "
    "clearly elevated (positive estimate with CI not crossing zero) AND the topic terms "
    "or snippets explicitly reference that engine. A general issue (oil consumption, leaks, "
    "electrical faults) that affects all engines must use [\"all\"] or omit specific engines.\n"
    "- Only set issue_type to 'chronic_failure' if the chronic_signal score is meaningfully "
    "above 0.3 AND the snippets show repeated unresolved complaints. Low chronic_signal with "
    "common symptoms (oil, coolant, noise) is a 'wear_item' or 'intermittent_fault', not chronic.\n"
    "- Be conservative: when in doubt, broaden affected_engines rather than narrowing to one."
)


def format_prompt(bundle: dict) -> str:
    mid = bundle["mileage_median_km"]
    p20 = bundle["mileage_p20_km"]
    p80 = bundle["mileage_p80_km"]
    mileage_line = (
        f"Median: {mid} km | P20–P80: {p20}–{p80} km"
        if mid is not None
        else "Insufficient mileage data"
    )

    year_cohort_section = (
        json.dumps(bundle["year_cohort_breakdown"], ensure_ascii=False, indent=2)
        if bundle["year_cohort_breakdown"]
        else "  No year data available"
    )

    return f"""Analyze this STM topic data bundle and return a structured JSON interpretation.

=== VEHICLE PARTS KNOWLEDGE (use to populate known_part_codes) ===
{SCAFFOLD_CONTEXT}

=== TOPIC DATA BUNDLE (Topic {bundle["topic_id"]}) ===

FREX terms (most distinctive): {bundle["terms_frex"]}
PROB terms (most probable):    {bundle["terms_prob"]}

Corpus prevalence: {bundle["prevalence_pct"]}%
Thread count (dominant topic): {bundle["thread_count"]}
Chronic signal score: {bundle["chronic_signal"]} (higher = more recurring/unresolved complaints)

Mileage distribution (threads with gamma > 0.3, n={bundle["mileage_thread_count"]}):
  {mileage_line}

Engine group breakdown (% of dominant-topic threads):
{json.dumps(bundle["engine_breakdown"], ensure_ascii=False, indent=2)}

Year-cohort × engine breakdown (dominant-topic threads, split by production year):
{year_cohort_section}

Covariate effect estimates (topic prevalence by engine group, from STM estimateEffect):
{json.dumps(bundle["covariate_effects"], ensure_ascii=False, indent=2)}

Representative thread snippets (Turkish, ranked by relevance score):
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
  "onset_mileage_typical_km": null,
  "onset_mileage_range": "e.g. 80k-130k km or null",
  "affected_engines": ["use specific engine only if covariate data clearly supports it, otherwise \"all\""],
  "affected_years": "e.g. pre-2014 or all or null",
  "engine_family_codes": ["e.g. EA111"],
  "known_part_codes": [{{"code": "e.g. 0AM325065", "name": "e.g. DQ200 mechatronic unit", "notes": "optional"}}],
  "engine_notes": "1 sentence on engine-specific patterns, referencing year cohorts if relevant, or null",
  "prevalence_pct": {bundle["prevalence_pct"]},
  "chronic_signal": {bundle["chronic_signal"]},
  "summary": "2 sentences describing the issue pattern as observed in the data",
  "warning_signs": ["sign 1", "sign 2"],
  "inspection_advice": "1-2 sentences on what to check when buying",
  "data_quality": "low | medium | high",
  "thread_count": {bundle["thread_count"]},
  "notes": "any caveats or limitations for this topic, or null"
}}"""


# ── API call with retry ───────────────────────────────────────────────────────


def call_deepseek(prompt: str, topic_id: int, max_retries: int = 3) -> dict | None:
    for attempt in range(1, max_retries + 1):
        try:
            log.info(f"T{topic_id}: API call attempt {attempt}/{max_retries}")
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
            log.info(f"T{topic_id}: raw response:\n{raw}")
            # Strip markdown code fences if model ignores the "no fences" instruction
            if raw.startswith("```"):
                raw = raw.split("```", 2)[1]
                if raw.startswith("json"):
                    raw = raw[4:]
                raw = raw.strip()
            return json.loads(raw)
        except json.JSONDecodeError as e:
            log.warning(f"T{topic_id}: JSON parse error on attempt {attempt}: {e}")
        except Exception as e:
            log.warning(f"T{topic_id}: API error on attempt {attempt}: {e}")
        if attempt < max_retries:
            time.sleep(5 * attempt)  # 5s, 10s back-off

    log.error(f"T{topic_id}: all {max_retries} attempts failed — writing null record")
    return None


# ── Main ──────────────────────────────────────────────────────────────────────


def process_topic(topic_id: int, data: dict) -> dict:
    bundle = build_bundle(topic_id, data)
    prompt = format_prompt(bundle)
    result = call_deepseek(prompt, topic_id)
    if result is None:
        result = {"topic_id": topic_id, "error": "failed_after_retries"}
    return result


MAX_WORKERS = 3  # DeepSeek rate-limits at high concurrency


def main():
    data = load_data()

    # ── Load existing results so successful topics aren't re-called ───────────
    json_path = DATA_DIR / "issue_knowledge.json"
    results_map: dict[int, dict] = {}
    if json_path.exists():
        with open(json_path, encoding="utf-8") as f:
            existing = json.load(f)
        for r in existing:
            tid = r.get("topic_id")
            if tid and "error" not in r:
                results_map[tid] = r
                log.info(f"T{tid}: loaded from existing results — skipping API call")

    todo = [tid for tid in range(1, K + 1) if tid not in results_map]
    log.info(f"Topics to process: {todo}")

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = {pool.submit(process_topic, tid, data): tid for tid in todo}
        for future in as_completed(futures):
            tid = futures[future]
            try:
                results_map[tid] = future.result()
                log.info(f"T{tid}: done")
            except Exception as e:
                log.error(f"T{tid}: unhandled error — {e}")
                results_map[tid] = {"topic_id": tid, "error": str(e)}

    # Restore topic order
    results = [results_map[tid] for tid in range(1, K + 1)]

    # ── JSON output ───────────────────────────────────────────────────────────
    json_path = DATA_DIR / "issue_knowledge.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    log.info(f"Saved: {json_path}")

    # ── CSV output (flat — nested fields serialised as JSON strings) ──────────
    csv_path = DATA_DIR / "issue_knowledge.csv"
    flat = []
    for r in results:
        row = {
            k: (json.dumps(v, ensure_ascii=False) if isinstance(v, (list, dict)) else v)
            for k, v in r.items()
        }
        flat.append(row)
    pd.DataFrame(flat).to_csv(csv_path, index=False)
    log.info(f"Saved: {csv_path}")

    log.info(f"Done. All {K} topics processed.")


if __name__ == "__main__":
    main()
