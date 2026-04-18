#!/usr/bin/env python3
"""
visualize_issue_knowledge.py
----------------------------
Create an interactive HTML explorer for structured issue-knowledge JSON output.

The script is schema-aware but model-agnostic. It reads one or more JSON files
whose root is a list of issue objects, normalizes the shared structure, and
builds a browser dashboard with:

- Dataset switcher (for multiple files)
- KPI cards
- Distribution charts
- Search + filters
- Sort controls
- Expandable issue detail cards

Examples:
    python scripts/visualize_issue_knowledge.py \
        --input data/processed/issue_knowledge_youtube_renault_clio_mk4_final.json \
        --input data/processed/issue_knowledge_youtube_vw_golf_mk7_final.json

    python scripts/visualize_issue_knowledge.py \
        --output data/processed/issue_knowledge_dashboard.html \
        --title "Issue Knowledge Explorer" --open

If no --input values are provided, the script auto-discovers files by glob.
"""

from __future__ import annotations

import argparse
import json
import webbrowser
from collections import Counter
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent


def _clean_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    return str(value).strip()


def _clean_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        items: list[str] = []
        for item in value:
            text = _clean_text(item)
            if text:
                items.append(text)
        return items
    text = _clean_text(value)
    return [text] if text else []


def _to_int(value: Any) -> int:
    if value is None:
        return 0
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    text = _clean_text(value)
    if not text:
        return 0
    try:
        return int(float(text))
    except ValueError:
        return 0


def _clean_source_videos(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    out: list[dict[str, str]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        video_id = _clean_text(item.get("video_id"))
        title = _clean_text(item.get("title"))
        if video_id or title:
            out.append({"video_id": video_id, "title": title})
    return out


def _clean_engine_year_context(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    out: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        engine = _clean_text(item.get("engine"))
        years = _clean_text(item.get("years"))
        hits = _to_int(item.get("evidence_hits"))
        if engine or years or hits:
            out.append({"engine": engine, "years": years, "evidence_hits": hits})
    return out


def _clean_engine_scope_warnings(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    out: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        out.append(
            {
                "rule": _clean_text(item.get("rule")),
                "note": _clean_text(item.get("note")),
                "current_engines": _clean_list(item.get("current_engines")),
                "suggested_engines": _clean_list(item.get("suggested_engines")),
                "invalid_engines_flagged": _clean_list(
                    item.get("invalid_engines_flagged")
                ),
                "action": _clean_text(item.get("action")),
            }
        )
    return out


def _clean_years_evidence(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}

    cleaned: dict[str, Any] = {}
    for key, raw_value in value.items():
        if isinstance(raw_value, list):
            arr = [_clean_text(x) for x in raw_value]
            arr = [x for x in arr if x]
            if arr:
                cleaned[key] = arr
            continue

        if isinstance(raw_value, dict):
            inner: dict[str, str] = {}
            for inner_key, inner_value in raw_value.items():
                text = _clean_text(inner_value)
                if text:
                    inner[inner_key] = text
            if inner:
                cleaned[key] = inner
            continue

        text = _clean_text(raw_value)
        if text:
            cleaned[key] = text

    return cleaned


KNOWN_KEYS = {
    "issue_id",
    "label",
    "label_short",
    "system_component",
    "issue_type",
    "severity",
    "confidence",
    "affected_engines",
    "affected_engines_original",
    "affected_years",
    "affected_years_triangulated",
    "affected_years_evidence",
    "onset_km_range",
    "symptom",
    "cause",
    "fix",
    "warning_signs",
    "inspection_advice",
    "mention_count",
    "source_videos",
    "source",
    "data_quality",
    "notes",
    "merged_from_issue_ids",
    "model_scope",
    "engine_year_context",
    "engine_scope_warnings",
    "_scope_notes",
}


def normalize_issues(raw_issues: list[Any]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for idx, raw in enumerate(raw_issues, start=1):
        if not isinstance(raw, dict):
            continue

        issue_id = _clean_text(raw.get("issue_id")) or f"issue_{idx}"
        label = _clean_text(raw.get("label")) or issue_id.replace("_", " ").title()

        extras: dict[str, Any] = {}
        for key, value in raw.items():
            if key in KNOWN_KEYS:
                continue
            extras[key] = value

        issue = {
            "issue_id": issue_id,
            "label": label,
            "label_short": _clean_text(raw.get("label_short")),
            "system_component": _clean_text(raw.get("system_component")).lower()
            or "other",
            "issue_type": _clean_text(raw.get("issue_type")).lower() or "other",
            "severity": _clean_text(raw.get("severity")).lower() or "unknown",
            "confidence": _clean_text(raw.get("confidence")).lower() or "unknown",
            "affected_engines": _clean_list(raw.get("affected_engines")),
            "affected_engines_original": _clean_list(
                raw.get("affected_engines_original")
            ),
            "affected_years": _clean_text(raw.get("affected_years")),
            "affected_years_triangulated": _clean_text(
                raw.get("affected_years_triangulated")
            ),
            "affected_years_evidence": _clean_years_evidence(
                raw.get("affected_years_evidence")
            ),
            "onset_km_range": _clean_text(raw.get("onset_km_range")),
            "symptom": _clean_text(raw.get("symptom")),
            "cause": _clean_text(raw.get("cause")),
            "fix": _clean_text(raw.get("fix")),
            "warning_signs": _clean_list(raw.get("warning_signs")),
            "inspection_advice": _clean_text(raw.get("inspection_advice")),
            "mention_count": _to_int(raw.get("mention_count")),
            "source_videos": _clean_source_videos(raw.get("source_videos")),
            "source": _clean_text(raw.get("source")).lower() or "unknown",
            "data_quality": _clean_text(raw.get("data_quality")).lower() or "unknown",
            "notes": _clean_text(raw.get("notes")),
            "merged_from_issue_ids": _clean_list(raw.get("merged_from_issue_ids")),
            "model_scope": _clean_list(raw.get("model_scope")),
            "engine_year_context": _clean_engine_year_context(
                raw.get("engine_year_context")
            ),
            "engine_scope_warnings": _clean_engine_scope_warnings(
                raw.get("engine_scope_warnings")
            ),
            "scope_notes": _clean_list(raw.get("_scope_notes")),
            "extra_fields": extras,
        }
        normalized.append(issue)
    return normalized


def _preferred_engine_list(issue: dict[str, Any]) -> list[str]:
    primary = issue.get("affected_engines", [])
    if primary:
        return primary
    original = issue.get("affected_engines_original", [])
    if original:
        return original
    return []


def build_summary(issues: list[dict[str, Any]]) -> dict[str, Any]:
    issue_id_counts = Counter(issue["issue_id"] for issue in issues)
    duplicate_rows = sum(n - 1 for n in issue_id_counts.values() if n > 1)
    duplicate_groups = sum(1 for n in issue_id_counts.values() if n > 1)

    component_counts = Counter(issue["system_component"] for issue in issues)
    type_counts = Counter(issue["issue_type"] for issue in issues)
    severity_counts = Counter(issue["severity"] for issue in issues)
    confidence_counts = Counter(issue["confidence"] for issue in issues)
    quality_counts = Counter(issue["data_quality"] for issue in issues)
    source_counts = Counter(issue["source"] for issue in issues)

    engine_counts: Counter[str] = Counter()
    scope_counts: Counter[str] = Counter()
    year_window_source_counts: Counter[str] = Counter()
    warning_rule_counts: Counter[str] = Counter()

    mention_total = 0
    high_severity = 0
    with_fix = 0
    with_engine_scope_warning = 0
    with_year_signal = 0
    with_source_videos = 0

    for issue in issues:
        mention_total += issue["mention_count"]
        if issue["severity"] == "high":
            high_severity += 1
        if issue["fix"]:
            with_fix += 1
        if issue["source_videos"]:
            with_source_videos += 1

        if issue["affected_years"] or issue["affected_years_triangulated"]:
            with_year_signal += 1

        engines = _preferred_engine_list(issue)
        if engines:
            for engine in engines:
                engine_counts[engine] += 1
        else:
            engine_counts["unknown"] += 1

        scopes = issue["model_scope"]
        if scopes:
            for scope in scopes:
                scope_counts[scope] += 1
        else:
            scope_counts["unknown"] += 1

        evidence = issue.get("affected_years_evidence", {})
        if isinstance(evidence, dict):
            source_name = _clean_text(evidence.get("window_source"))
            if source_name:
                year_window_source_counts[source_name] += 1

        warnings = issue.get("engine_scope_warnings", [])
        if warnings:
            with_engine_scope_warning += 1
            for warning in warnings:
                rule = _clean_text(warning.get("rule")) or "unknown"
                warning_rule_counts[rule] += 1

    return {
        "total_issues": len(issues),
        "unique_issue_ids": len(issue_id_counts),
        "duplicate_rows": duplicate_rows,
        "duplicate_groups": duplicate_groups,
        "mention_total": mention_total,
        "high_severity_count": high_severity,
        "with_fix_count": with_fix,
        "with_engine_scope_warning_count": with_engine_scope_warning,
        "with_year_signal_count": with_year_signal,
        "with_source_videos_count": with_source_videos,
        "component_counts": dict(component_counts),
        "type_counts": dict(type_counts),
        "severity_counts": dict(severity_counts),
        "confidence_counts": dict(confidence_counts),
        "quality_counts": dict(quality_counts),
        "source_counts": dict(source_counts),
        "engine_counts": dict(engine_counts),
        "scope_counts": dict(scope_counts),
        "year_window_source_counts": dict(year_window_source_counts),
        "warning_rule_counts": dict(warning_rule_counts),
    }


def _json_for_script_tag(value: Any) -> str:
    text = json.dumps(value, ensure_ascii=False)
    return text.replace("</", "<\\/").replace("<", "\\u003c")


def _default_dataset_name(path: Path) -> str:
    stem = path.stem
    for prefix in ("issue_knowledge_", "issues_"):
        if stem.startswith(prefix):
            stem = stem[len(prefix) :]
            break
    stem = stem.replace("_final", "")
    return stem or path.stem


def _resolve_input_paths(input_args: list[str], auto_glob: str) -> list[Path]:
    raw_paths: list[Path] = []

    if input_args:
        for raw in input_args:
            candidate = Path(raw)
            if not candidate.is_absolute():
                candidate = (ROOT / candidate).resolve()
            raw_paths.append(candidate)
    else:
        raw_paths = sorted((ROOT / ".").glob(auto_glob))

    if not raw_paths:
        raise FileNotFoundError(
            "No input JSON files found. Provide --input or adjust --auto-glob."
        )

    deduped: list[Path] = []
    seen: set[Path] = set()
    for path in raw_paths:
        rp = path.resolve()
        if rp in seen:
            continue
        seen.add(rp)
        deduped.append(rp)

    missing = [p for p in deduped if not p.exists()]
    if missing:
        joined = "\n".join(f"- {p}" for p in missing)
        raise FileNotFoundError(f"Input JSON not found:\n{joined}")

    return deduped


def _load_dataset(path: Path) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as handle:
        raw = json.load(handle)

    if not isinstance(raw, list):
        raise ValueError(f"Input must be a list of issue objects: {path}")

    issues = normalize_issues(raw)
    summary = build_summary(issues)

    return {
        "dataset_id": path.stem,
        "dataset_name": _default_dataset_name(path),
        "input_path": path.as_posix(),
        "issues": issues,
        "summary": summary,
    }


def build_dashboard_html(title: str, datasets: list[dict[str, Any]]) -> str:
    datasets_json = _json_for_script_tag(datasets)
    safe_title = _clean_text(title) or "Issue Knowledge Explorer"

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{safe_title}</title>
  <style>
    :root {{
      --ink: #1e2934;
      --muted: #64748b;
      --surface: #ffffff;
      --surface-2: #f6f8fa;
      --line: #d7e0e7;
      --accent: #0f766e;
      --accent-2: #1d4ed8;
      --accent-3: #d97706;
      --high: #b42318;
      --medium: #b54708;
      --low: #027a48;
      --shadow: 0 8px 22px rgba(15, 23, 42, 0.08);
    }}

    * {{ box-sizing: border-box; }}

    body {{
      margin: 0;
      color: var(--ink);
      font-family: "IBM Plex Sans", "Trebuchet MS", "Verdana", sans-serif;
      background:
        radial-gradient(1200px 700px at -8% -12%, #dbf1eb 0%, transparent 58%),
        radial-gradient(900px 680px at 108% -12%, #fff4dc 0%, transparent 52%),
        linear-gradient(180deg, #f7faf9 0%, #edf2f6 100%);
      min-height: 100vh;
    }}

    .page {{
      max-width: 1320px;
      margin: 0 auto;
      padding: 18px 16px 30px;
    }}

    .hero {{
      border: 1px solid var(--line);
      border-radius: 16px;
      background: linear-gradient(120deg, #ffffff 0%, #f1f8f5 68%);
      box-shadow: var(--shadow);
      padding: 16px;
      position: relative;
      overflow: hidden;
    }}

    .hero::after {{
      content: "";
      position: absolute;
      right: -80px;
      top: -85px;
      width: 225px;
      height: 225px;
      border-radius: 50%;
      background: radial-gradient(circle, rgba(15, 118, 110, 0.18) 0%, rgba(15, 118, 110, 0) 66%);
      pointer-events: none;
    }}

    h1 {{
      margin: 0;
      font-family: "Bitter", "Palatino Linotype", serif;
      font-size: clamp(1.25rem, 2.2vw, 1.95rem);
      letter-spacing: 0.2px;
    }}

    .meta {{
      margin-top: 5px;
      color: var(--muted);
      font-size: 0.92rem;
    }}

    .dataset-picker {{
      margin-top: 12px;
      display: grid;
      grid-template-columns: 1fr;
      gap: 7px;
      max-width: 560px;
    }}

    .dataset-picker label,
    .controls label {{
      color: var(--muted);
      text-transform: uppercase;
      letter-spacing: 0.08em;
      font-size: 0.74rem;
    }}

    select,
    input {{
      width: 100%;
      border: 1px solid #cad6df;
      border-radius: 9px;
      background: #ffffff;
      color: var(--ink);
      padding: 8px 10px;
      font-size: 0.92rem;
    }}

    .kpis {{
      margin-top: 13px;
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(145px, 1fr));
      gap: 8px;
    }}

    .tile {{
      border: 1px solid var(--line);
      border-radius: 11px;
      background: var(--surface);
      padding: 9px 10px;
      box-shadow: 0 4px 12px rgba(15, 23, 42, 0.05);
    }}

    .tile .label {{
      color: var(--muted);
      text-transform: uppercase;
      letter-spacing: 0.07em;
      font-size: 0.73rem;
    }}

    .tile .value {{
      margin-top: 3px;
      font-size: 1.2rem;
      font-weight: 700;
    }}

    .grid {{
      margin-top: 12px;
      display: grid;
      grid-template-columns: 1fr;
      gap: 10px;
    }}

    @media (min-width: 1060px) {{
      .grid {{
        grid-template-columns: repeat(2, minmax(0, 1fr));
      }}
    }}

    .panel {{
      border: 1px solid var(--line);
      border-radius: 12px;
      background: var(--surface);
      box-shadow: var(--shadow);
      padding: 10px;
    }}

    .panel h2 {{
      margin: 0 0 7px;
      font-size: 0.96rem;
      letter-spacing: 0.02em;
    }}

    .bars {{
      display: grid;
      gap: 6px;
    }}

    .bar-row {{
      display: grid;
      grid-template-columns: 148px 1fr 42px;
      gap: 8px;
      align-items: center;
      font-size: 0.84rem;
    }}

    .bar-label {{
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }}

    .bar-track {{
      height: 11px;
      border-radius: 999px;
      border: 1px solid #dce5ec;
      background: #eef3f7;
      overflow: hidden;
    }}

    .bar-fill {{
      height: 100%;
      border-radius: 999px;
      background: linear-gradient(90deg, var(--accent), var(--accent-2));
    }}

    .bar-value {{
      text-align: right;
      color: var(--muted);
      font-variant-numeric: tabular-nums;
    }}

    .controls {{
      margin-top: 10px;
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(170px, 1fr));
      gap: 8px;
    }}

    .field {{
      display: grid;
      gap: 4px;
    }}

    .results-meta {{
      margin-top: 10px;
      color: var(--muted);
      font-size: 0.9rem;
    }}

    .cards {{
      margin-top: 9px;
      display: grid;
      grid-template-columns: 1fr;
      gap: 9px;
    }}

    @media (min-width: 940px) {{
      .cards {{
        grid-template-columns: repeat(2, minmax(0, 1fr));
      }}
    }}

    .card {{
      border: 1px solid var(--line);
      border-radius: 11px;
      background: #ffffff;
      padding: 10px;
      box-shadow: 0 4px 10px rgba(15, 23, 42, 0.05);
      animation: rise 220ms ease;
    }}

    @keyframes rise {{
      from {{ opacity: 0; transform: translateY(4px); }}
      to {{ opacity: 1; transform: translateY(0); }}
    }}

    .card h3 {{
      margin: 0;
      font-size: 1rem;
      line-height: 1.28;
    }}

    .card-id {{
      margin-top: 2px;
      color: var(--muted);
      font-family: "IBM Plex Mono", "Consolas", monospace;
      font-size: 0.76rem;
    }}

    .badges {{
      margin-top: 7px;
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
    }}

    .badge {{
      border-radius: 999px;
      border: 1px solid #d5e0e8;
      background: #f7fbfe;
      color: #1e4a62;
      padding: 2px 8px;
      font-size: 0.73rem;
      white-space: nowrap;
    }}

    .badge.severity-high {{
      color: #7f1d1d;
      border-color: #efc7c7;
      background: #fff1f1;
    }}

    .badge.severity-medium {{
      color: #8a4b06;
      border-color: #f4dfbf;
      background: #fff8ee;
    }}

    .badge.severity-low {{
      color: #0a6b42;
      border-color: #cce9da;
      background: #f2fbf5;
    }}

    .badge.warning {{
      color: #7c2d12;
      border-color: #ffd0bf;
      background: #fff4f0;
    }}

    .facts {{
      margin-top: 8px;
      display: grid;
      gap: 3px;
      font-size: 0.88rem;
      line-height: 1.33;
    }}

    .facts .k {{
      color: var(--muted);
      font-weight: 600;
      margin-right: 4px;
    }}

    .card p {{
      margin: 6px 0;
      font-size: 0.9rem;
      line-height: 1.35;
    }}

    details {{
      margin-top: 6px;
      border-top: 1px dashed #d7e2ea;
      padding-top: 6px;
    }}

    summary {{
      cursor: pointer;
      color: #1d4f6b;
      user-select: none;
      font-size: 0.85rem;
    }}

    pre {{
      margin: 6px 0 0;
      border: 1px solid #d7e1ea;
      border-radius: 8px;
      background: #f8fbff;
      padding: 8px;
      font-size: 0.78rem;
      overflow-x: auto;
      white-space: pre-wrap;
      word-break: break-word;
    }}

    .empty {{
      border: 1px dashed #cbd7e0;
      border-radius: 10px;
      background: #fafcff;
      color: var(--muted);
      text-align: center;
      padding: 12px;
      font-size: 0.9rem;
    }}

    .hint {{
      margin-top: 8px;
      color: var(--muted);
      font-size: 0.82rem;
    }}
  </style>
</head>
<body>
  <div class="page">
    <section class="hero">
      <h1>{safe_title}</h1>
      <div class="meta" id="dataset-meta"></div>

      <div class="dataset-picker">
        <label for="dataset-select">Dataset</label>
        <select id="dataset-select"></select>
      </div>

      <div class="kpis" id="kpis"></div>
    </section>

    <section class="grid">
      <article class="panel">
        <h2>System Components</h2>
        <div class="bars" id="component-chart"></div>
      </article>
      <article class="panel">
        <h2>Issue Types</h2>
        <div class="bars" id="type-chart"></div>
      </article>
      <article class="panel">
        <h2>Severity</h2>
        <div class="bars" id="severity-chart"></div>
      </article>
      <article class="panel">
        <h2>Confidence</h2>
        <div class="bars" id="confidence-chart"></div>
      </article>
      <article class="panel">
        <h2>Data Quality</h2>
        <div class="bars" id="quality-chart"></div>
      </article>
      <article class="panel">
        <h2>Sources</h2>
        <div class="bars" id="source-chart"></div>
      </article>
      <article class="panel" style="grid-column: 1 / -1;">
        <h2>Affected Engines (Preferred Mapping)</h2>
        <div class="bars" id="engine-chart"></div>
      </article>
      <article class="panel" style="grid-column: 1 / -1;">
        <h2>Model Scope</h2>
        <div class="bars" id="scope-chart"></div>
      </article>
    </section>

    <section class="panel" style="margin-top: 11px;">
      <h2>Issue Explorer</h2>

      <div class="controls">
        <div class="field">
          <label for="search">Search</label>
          <input id="search" type="text" placeholder="label, issue_id, symptom, cause, fix, notes">
        </div>
        <div class="field">
          <label for="component">Component</label>
          <select id="component"></select>
        </div>
        <div class="field">
          <label for="type">Issue Type</label>
          <select id="type"></select>
        </div>
        <div class="field">
          <label for="severity">Severity</label>
          <select id="severity"></select>
        </div>
        <div class="field">
          <label for="confidence">Confidence</label>
          <select id="confidence"></select>
        </div>
        <div class="field">
          <label for="data-quality">Data Quality</label>
          <select id="data-quality"></select>
        </div>
        <div class="field">
          <label for="engine">Engine</label>
          <select id="engine"></select>
        </div>
        <div class="field">
          <label for="source">Source</label>
          <select id="source"></select>
        </div>
        <div class="field">
          <label for="warnings">Engine Scope Warnings</label>
          <select id="warnings">
            <option value="all">All</option>
            <option value="yes">Has warning</option>
            <option value="no">No warning</option>
          </select>
        </div>
        <div class="field">
          <label for="min-mentions">Min Mentions</label>
          <input id="min-mentions" type="number" min="0" step="1" value="0">
        </div>
        <div class="field">
          <label for="sort">Sort</label>
          <select id="sort">
            <option value="mentions_desc">Mentions (High to Low)</option>
            <option value="severity_desc">Severity (High to Low)</option>
            <option value="confidence_desc">Confidence (High to Low)</option>
            <option value="label_asc">Label (A to Z)</option>
            <option value="issue_id_asc">Issue ID (A to Z)</option>
          </select>
        </div>
      </div>

      <div class="results-meta" id="results-meta"></div>
      <div class="cards" id="cards"></div>
      <div class="hint">Tip: combine component + severity + min mentions first, then inspect year evidence and source videos.</div>
    </section>
  </div>

  <script id="datasets-data" type="application/json">{datasets_json}</script>

  <script>
    const datasets = JSON.parse(document.getElementById('datasets-data').textContent);

    const severityRank = {{ high: 3, medium: 2, low: 1, unknown: 0 }};
    const confidenceRank = {{ high: 3, medium: 2, low: 1, unknown: 0 }};

    const state = {{ datasetIndex: 0 }};

    function esc(text) {{
      return String(text || '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
    }}

    function tc(text) {{
      return String(text || '')
        .replace(/_/g, ' ')
        .trim()
        .replace(/\\w\\S*/g, (w) => w.charAt(0).toUpperCase() + w.slice(1));
    }}

    function listText(values, fallback = 'n/a') {{
      if (!Array.isArray(values) || !values.length) return fallback;
      return values.join(', ');
    }}

    function preferredEngines(issue) {
      if (Array.isArray(issue.affected_engines) && issue.affected_engines.length) {
        return issue.affected_engines;
      }
      if (Array.isArray(issue.affected_engines_original) && issue.affected_engines_original.length) {
        return issue.affected_engines_original;
      }
      return [];
    }

    function getDataset() {{
      return datasets[state.datasetIndex] || datasets[0];
    }}

    function uniqueSorted(values) {{
      return [...new Set(values.filter(Boolean))].sort((a, b) => a.localeCompare(b));
    }}

    function populateSelect(id, values) {{
      const el = document.getElementById(id);
      const options = ['all', ...uniqueSorted(values)];
      el.innerHTML = options
        .map((v) => `<option value="${{esc(v)}}">${{v === 'all' ? 'All' : esc(tc(v))}}</option>`)
        .join('');
    }}

    function renderBars(containerId, countsObj, maxItems = 18) {{
      const container = document.getElementById(containerId);
      const rows = Object.entries(countsObj || {{}})
        .sort((a, b) => b[1] - a[1])
        .slice(0, maxItems);

      if (!rows.length) {{
        container.innerHTML = '<div class="empty">No data</div>';
        return;
      }}

      const max = rows[0][1] || 1;
      container.innerHTML = rows
        .map(([name, value]) => {{
          const width = Math.max(4, Math.round((value / max) * 100));
          return `
            <div class="bar-row">
              <div class="bar-label" title="${{esc(name)}}">${{esc(tc(name))}}</div>
              <div class="bar-track"><div class="bar-fill" style="width:${{width}}%"></div></div>
              <div class="bar-value">${{Number(value).toLocaleString()}}</div>
            </div>
          `;
        }})
        .join('');
    }}

    function buildKpis(summary) {{
      const rows = [
        {{ label: 'Rows', value: summary.total_issues }},
        {{ label: 'Unique Issue IDs', value: summary.unique_issue_ids }},
        {{ label: 'Total Mentions', value: summary.mention_total }},
        {{ label: 'High Severity', value: summary.high_severity_count }},
        {{ label: 'Rows With Fix', value: summary.with_fix_count }},
        {{ label: 'Rows With Year Signal', value: summary.with_year_signal_count }},
        {{ label: 'Rows With Source Videos', value: summary.with_source_videos_count }},
        {{ label: 'Engine Scope Warnings', value: summary.with_engine_scope_warning_count }},
        {{ label: 'Duplicate Rows', value: summary.duplicate_rows }},
      ];

      const root = document.getElementById('kpis');
      root.innerHTML = rows
        .map((row) => `
          <div class="tile">
            <div class="label">${{esc(row.label)}}</div>
            <div class="value">${{Number(row.value || 0).toLocaleString()}}</div>
          </div>
        `)
        .join('');
    }}

    function datasetMetaText(dataset) {{
      return `${{dataset.dataset_name}}  |  ${{dataset.input_path}}`;
    }}

    function createBadges(issue) {{
      const badges = [
        `<span class="badge severity-${{esc(issue.severity)}}">severity: ${{esc(issue.severity)}}</span>`,
        `<span class="badge">component: ${{esc(issue.system_component)}}</span>`,
        `<span class="badge">type: ${{esc(issue.issue_type)}}</span>`,
        `<span class="badge">confidence: ${{esc(issue.confidence)}}</span>`,
        `<span class="badge">quality: ${{esc(issue.data_quality)}}</span>`,
        `<span class="badge">mentions: ${{Number(issue.mention_count || 0).toLocaleString()}}</span>`,
      ];
      if (Array.isArray(issue.engine_scope_warnings) && issue.engine_scope_warnings.length) {{
        badges.push('<span class="badge warning">engine scope warning</span>');
      }}
      return badges.join('');
    }}

    function sourceVideoHtml(videos) {{
      if (!Array.isArray(videos) || !videos.length) return '<p class="meta">No source videos listed.</p>';
      const items = videos.slice(0, 10).map((v) => {{
        const vid = esc(v.video_id || '');
        const title = esc(v.title || v.video_id || 'video');
        if (vid) {{
          return `<li><a href="https://www.youtube.com/watch?v=${{vid}}" target="_blank" rel="noreferrer">${{title}}</a></li>`;
        }}
        return `<li>${{title}}</li>`;
      }}).join('');
      return `<ul>${{items}}</ul>`;
    }}

    function warningHtml(warnings) {{
      if (!Array.isArray(warnings) || !warnings.length) return '<p class="meta">None</p>';
      const parts = warnings.map((w, idx) => {{
        const payload = {{
          rule: w.rule || '',
          action: w.action || '',
          current_engines: w.current_engines || [],
          suggested_engines: w.suggested_engines || [],
          invalid_engines_flagged: w.invalid_engines_flagged || [],
          note: w.note || '',
        }};
        return `<details><summary>Warning ${{idx + 1}}: ${{esc(w.rule || 'rule')}}</summary><pre>${{esc(JSON.stringify(payload, null, 2))}}</pre></details>`;
      }});
      return parts.join('');
    }}

    function renderCards(items, totalCount) {{
      const root = document.getElementById('cards');
      const meta = document.getElementById('results-meta');
      meta.textContent = `${{items.length.toLocaleString()}} matching issues out of ${{totalCount.toLocaleString()}}`;

      if (!items.length) {{
        root.innerHTML = '<div class="empty">No issues match current filters.</div>';
        return;
      }}

      root.innerHTML = items.map((issue) => {{
        const engines = preferredEngines(issue);
        const years = issue.affected_years || issue.affected_years_triangulated || 'n/a';
        const yearEvidence = issue.affected_years_evidence && Object.keys(issue.affected_years_evidence).length
          ? JSON.stringify(issue.affected_years_evidence, null, 2)
          : '';
        const engineYearContext = Array.isArray(issue.engine_year_context) && issue.engine_year_context.length
          ? issue.engine_year_context.map((row) => `${{row.engine || 'unknown'}}: ${{row.years || 'n/a'}} (hits: ${{row.evidence_hits || 0}})`).join('; ')
          : 'n/a';
        const extras = issue.extra_fields && Object.keys(issue.extra_fields).length
          ? JSON.stringify(issue.extra_fields, null, 2)
          : '';

        return `
          <article class="card">
            <h3>${{esc(issue.label)}}</h3>
            <div class="card-id">${{esc(issue.issue_id)}}</div>
            <div class="badges">${{createBadges(issue)}}</div>

            <div class="facts">
              <div><span class="k">Engines:</span>${{esc(listText(engines, 'unknown'))}}</div>
              <div><span class="k">Model Scope:</span>${{esc(listText(issue.model_scope, 'unknown'))}}</div>
              <div><span class="k">Years:</span>${{esc(years)}}</div>
              <div><span class="k">Onset:</span>${{esc(issue.onset_km_range || 'n/a')}}</div>
              <div><span class="k">Merged IDs:</span>${{esc(listText(issue.merged_from_issue_ids, 'n/a'))}}</div>
            </div>

            <p><strong>Symptom:</strong> ${{esc(issue.symptom || 'n/a')}}</p>
            <p><strong>Cause:</strong> ${{esc(issue.cause || 'n/a')}}</p>
            <p><strong>Fix:</strong> ${{esc(issue.fix || 'n/a')}}</p>
            <p><strong>Inspection Advice:</strong> ${{esc(issue.inspection_advice || 'n/a')}}</p>
            <p><strong>Warning Signs:</strong> ${{esc(listText(issue.warning_signs, 'n/a'))}}</p>
            <p><strong>Notes:</strong> ${{esc(issue.notes || 'n/a')}}</p>
            <p><strong>Engine-Year Context:</strong> ${{esc(engineYearContext)}}</p>

            <details>
              <summary>Source Videos (${{(issue.source_videos || []).length}})</summary>
              ${{sourceVideoHtml(issue.source_videos || [])}}
            </details>

            <details>
              <summary>Engine Scope Warnings (${{(issue.engine_scope_warnings || []).length}})</summary>
              ${{warningHtml(issue.engine_scope_warnings || [])}}
            </details>

            <details>
              <summary>Scope Notes (${{(issue.scope_notes || []).length}})</summary>
              <pre>${{esc(JSON.stringify(issue.scope_notes || [], null, 2))}}</pre>
            </details>

            <details>
              <summary>Year Evidence</summary>
              ${{yearEvidence ? `<pre>${{esc(yearEvidence)}}</pre>` : '<p class="meta">None</p>'}}
            </details>

            <details>
              <summary>Additional Fields</summary>
              ${{extras ? `<pre>${{esc(extras)}}</pre>` : '<p class="meta">None</p>'}}
            </details>
          </article>
        `;
      }}).join('');
    }}

    function applyFilters() {{
      const dataset = getDataset();
      const issues = dataset.issues || [];

      const q = (document.getElementById('search').value || '').trim().toLowerCase();
      const component = document.getElementById('component').value;
      const type = document.getElementById('type').value;
      const severity = document.getElementById('severity').value;
      const confidence = document.getElementById('confidence').value;
      const quality = document.getElementById('data-quality').value;
      const engine = document.getElementById('engine').value;
      const source = document.getElementById('source').value;
      const warnings = document.getElementById('warnings').value;
      const minMentions = Number(document.getElementById('min-mentions').value || 0);
      const sort = document.getElementById('sort').value;

      let filtered = issues.filter((issue) => {{
        const engines = preferredEngines(issue);
        const textHaystack = [
          issue.issue_id,
          issue.label,
          issue.label_short,
          issue.system_component,
          issue.issue_type,
          issue.severity,
          issue.confidence,
          issue.data_quality,
          issue.symptom,
          issue.cause,
          issue.fix,
          issue.notes,
          issue.inspection_advice,
          issue.onset_km_range,
          issue.affected_years,
          issue.affected_years_triangulated,
          (issue.warning_signs || []).join(' '),
          (issue.model_scope || []).join(' '),
          engines.join(' '),
          JSON.stringify(issue.affected_years_evidence || {{}}),
          JSON.stringify(issue.engine_scope_warnings || []),
          JSON.stringify(issue.extra_fields || {{}}),
        ].join(' ').toLowerCase();

        if (q && !textHaystack.includes(q)) return false;
        if (component !== 'all' && issue.system_component !== component) return false;
        if (type !== 'all' && issue.issue_type !== type) return false;
        if (severity !== 'all' && issue.severity !== severity) return false;
        if (confidence !== 'all' && issue.confidence !== confidence) return false;
        if (quality !== 'all' && issue.data_quality !== quality) return false;
        if (source !== 'all' && issue.source !== source) return false;
        if (engine !== 'all' && !(engines.includes(engine) || engines.includes('all'))) return false;

        const hasWarnings = Array.isArray(issue.engine_scope_warnings) && issue.engine_scope_warnings.length > 0;
        if (warnings === 'yes' && !hasWarnings) return false;
        if (warnings === 'no' && hasWarnings) return false;

        if ((issue.mention_count || 0) < minMentions) return false;
        return true;
      }});

      filtered.sort((a, b) => {{
        if (sort === 'mentions_desc') {{
          return (b.mention_count || 0) - (a.mention_count || 0);
        }}
        if (sort === 'severity_desc') {{
          return (severityRank[b.severity] || 0) - (severityRank[a.severity] || 0)
            || (b.mention_count || 0) - (a.mention_count || 0);
        }}
        if (sort === 'confidence_desc') {{
          return (confidenceRank[b.confidence] || 0) - (confidenceRank[a.confidence] || 0)
            || (b.mention_count || 0) - (a.mention_count || 0);
        }}
        if (sort === 'issue_id_asc') {{
          return String(a.issue_id || '').localeCompare(String(b.issue_id || ''));
        }}
        return String(a.label || '').localeCompare(String(b.label || ''));
      }});

      renderCards(filtered, issues.length);
    }}

    function rebuildDatasetView() {{
      const dataset = getDataset();
      if (!dataset) return;

      document.getElementById('dataset-meta').textContent = datasetMetaText(dataset);
      buildKpis(dataset.summary || {{}});

      renderBars('component-chart', dataset.summary.component_counts || {{}});
      renderBars('type-chart', dataset.summary.type_counts || {{}});
      renderBars('severity-chart', dataset.summary.severity_counts || {{}});
      renderBars('confidence-chart', dataset.summary.confidence_counts || {{}});
      renderBars('quality-chart', dataset.summary.quality_counts || {{}});
      renderBars('source-chart', dataset.summary.source_counts || {{}});
      renderBars('engine-chart', dataset.summary.engine_counts || {{}}, 30);
      renderBars('scope-chart', dataset.summary.scope_counts || {{}});

      const issues = dataset.issues || [];
      populateSelect('component', issues.map((x) => x.system_component));
      populateSelect('type', issues.map((x) => x.issue_type));
      populateSelect('severity', issues.map((x) => x.severity));
      populateSelect('confidence', issues.map((x) => x.confidence));
      populateSelect('data-quality', issues.map((x) => x.data_quality));
      populateSelect('source', issues.map((x) => x.source));
      populateSelect('engine', issues.flatMap((x) => preferredEngines(x)));

      document.getElementById('search').value = '';
      document.getElementById('warnings').value = 'all';
      document.getElementById('min-mentions').value = '0';
      document.getElementById('sort').value = 'mentions_desc';

      applyFilters();
    }}

    function initDatasetSelect() {{
      const select = document.getElementById('dataset-select');
      select.innerHTML = datasets
        .map((ds, i) => `<option value="${{i}}">${{esc(ds.dataset_name)}} (${{(ds.summary && ds.summary.total_issues || 0).toLocaleString()}} rows)</option>`)
        .join('');
      select.addEventListener('change', (event) => {{
        state.datasetIndex = Number(event.target.value || 0);
        rebuildDatasetView();
      }});
    }}

    function initEvents() {{
      [
        'search',
        'component',
        'type',
        'severity',
        'confidence',
        'data-quality',
        'engine',
        'source',
        'warnings',
        'min-mentions',
        'sort',
      ].forEach((id) => {{
        document.getElementById(id).addEventListener('input', applyFilters);
      }});
    }}

    function init() {{
      if (!Array.isArray(datasets) || !datasets.length) {{
        document.body.innerHTML = '<div class="page"><div class="empty">No dataset data found in generated HTML.</div></div>';
        return;
      }}
      initDatasetSelect();
      initEvents();
      rebuildDatasetView();
    }}

    init();
  </script>
</body>
</html>
"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build an HTML visualizer for structured issue-knowledge JSON outputs."
    )
    parser.add_argument(
        "--input",
        dest="inputs",
        action="append",
        default=[],
        help="Path to an input JSON file. Can be repeated.",
    )
    parser.add_argument(
        "--auto-glob",
        default="data/processed/issue_knowledge_youtube_*_final.json",
        help="Glob used when no --input values are passed.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "data" / "processed" / "issue_knowledge_dashboard.html",
        help="Output HTML path.",
    )
    parser.add_argument(
        "--title",
        type=str,
        default="Issue Knowledge Explorer",
        help="Dashboard title.",
    )
    parser.add_argument(
        "--open",
        action="store_true",
        help="Open generated dashboard in your default browser.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    input_paths = _resolve_input_paths(input_args=args.inputs, auto_glob=args.auto_glob)
    datasets = [_load_dataset(path) for path in input_paths]

    output_path = args.output
    if not output_path.is_absolute():
        output_path = (ROOT / output_path).resolve()

    html = build_dashboard_html(title=args.title, datasets=datasets)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html, encoding="utf-8")

    print(f"Dashboard generated: {output_path}")
    print(f"Datasets loaded: {len(datasets)}")
    for ds in datasets:
        summary = ds["summary"]
        print(
            "- "
            f"{ds['dataset_name']}: "
            f"{summary['total_issues']} rows, "
            f"{summary['unique_issue_ids']} unique issue_id, "
            f"{summary['mention_total']} total mentions"
        )

    if args.open:
        webbrowser.open(f"file:///{output_path.as_posix()}")


if __name__ == "__main__":
    main()
