#!/usr/bin/env python3
"""
visualize_issue_knowledge.py
----------------------------
Build an interactive HTML dashboard from an issue-knowledge JSON file.

The dashboard includes:
- KPI tiles (issue count, mention totals, high-severity share, duplicate IDs)
- Distribution charts (component, issue type, severity, confidence)
- Engine coverage chart
- Search and filter controls
- Sort controls and issue detail cards

Usage:
    python scripts/visualize_issue_knowledge.py \
        --input data/processed/issue_knowledge_youtube_vw_golf_mk7.json

Optional:
    --output data/processed/issue_knowledge_youtube_vw_golf_mk7_dashboard.html
    --title "VW Golf MK7 Issue Dashboard"
    --open
"""

from __future__ import annotations

import argparse
import json
import os
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
        cleaned = []
        for item in value:
            text = _clean_text(item)
            if text:
                cleaned.append(text)
        return cleaned
    text = _clean_text(value)
    return [text] if text else []


def _clean_source_videos(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    out: list[dict[str, str]] = []
    for item in value:
        if isinstance(item, dict):
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
        if engine or years:
            out.append({"engine": engine, "years": years, "evidence_hits": hits})
    return out


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


def normalize_issues(raw_issues: list[Any]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for index, raw in enumerate(raw_issues, start=1):
        if not isinstance(raw, dict):
            continue

        issue_id = _clean_text(raw.get("issue_id")) or f"issue_{index}"
        label = _clean_text(raw.get("label")) or issue_id.replace("_", " ").title()

        issue = {
            "issue_id": issue_id,
            "label": label,
            "label_short": _clean_text(raw.get("label_short")),
            "system_component": _clean_text(raw.get("system_component")).lower() or "other",
            "issue_type": _clean_text(raw.get("issue_type")).lower() or "other",
            "severity": _clean_text(raw.get("severity")).lower() or "unknown",
            "confidence": _clean_text(raw.get("confidence")).lower() or "unknown",
            "affected_engines": _clean_list(raw.get("affected_engines")),
            "affected_engine_variants": _clean_list(raw.get("affected_engine_variants")),
            "affected_years": _clean_text(raw.get("affected_years")),
            "engine_year_context": _clean_engine_year_context(raw.get("engine_year_context")),
            "onset_km_range": _clean_text(raw.get("onset_km_range")),
            "symptom": _clean_text(raw.get("symptom")),
            "cause": _clean_text(raw.get("cause")),
            "fix": _clean_text(raw.get("fix")),
            "warning_signs": _clean_list(raw.get("warning_signs")),
            "inspection_advice": _clean_text(raw.get("inspection_advice")),
            "mention_count": _to_int(raw.get("mention_count")),
            "source_videos": _clean_source_videos(raw.get("source_videos")),
            "source": _clean_text(raw.get("source")) or "unknown",
            "data_quality": _clean_text(raw.get("data_quality")).lower() or "unknown",
            "notes": _clean_text(raw.get("notes")),
        }
        normalized.append(issue)

    return normalized


def build_summary(issues: list[dict[str, Any]]) -> dict[str, Any]:
    id_counts = Counter(issue["issue_id"] for issue in issues)
    duplicate_id_rows = sum(count - 1 for count in id_counts.values() if count > 1)
    duplicate_id_groups = sum(1 for count in id_counts.values() if count > 1)

    mention_total = sum(issue["mention_count"] for issue in issues)
    high_severity_count = sum(1 for issue in issues if issue["severity"] == "high")
    chronic_count = sum(1 for issue in issues if issue["issue_type"] == "chronic_failure")

    component_counts = Counter(issue["system_component"] for issue in issues)
    type_counts = Counter(issue["issue_type"] for issue in issues)
    severity_counts = Counter(issue["severity"] for issue in issues)
    confidence_counts = Counter(issue["confidence"] for issue in issues)
    quality_counts = Counter(issue["data_quality"] for issue in issues)

    engine_counts: Counter[str] = Counter()
    for issue in issues:
        engines = issue["affected_engines"]
        if not engines:
            engine_counts["unknown"] += 1
            continue
        for engine in engines:
            engine_counts[engine] += 1

    return {
        "total_issues": len(issues),
        "unique_issue_ids": len(id_counts),
        "duplicate_id_rows": duplicate_id_rows,
        "duplicate_id_groups": duplicate_id_groups,
        "mention_total": mention_total,
        "high_severity_count": high_severity_count,
        "chronic_count": chronic_count,
        "component_counts": dict(component_counts),
        "type_counts": dict(type_counts),
        "severity_counts": dict(severity_counts),
        "confidence_counts": dict(confidence_counts),
        "quality_counts": dict(quality_counts),
        "engine_counts": dict(engine_counts),
    }


def _json_for_script_tag(value: Any) -> str:
    # Avoid closing script tag injection while keeping readable unicode.
    text = json.dumps(value, ensure_ascii=False)
    return text.replace("</", "<\\/").replace("<", "\\u003c")


def build_dashboard_html(
    title: str,
    input_path: Path,
    issues: list[dict[str, Any]],
    summary: dict[str, Any],
) -> str:
    issues_json = _json_for_script_tag(issues)
    summary_json = _json_for_script_tag(summary)
    safe_title = _clean_text(title) or "Issue Knowledge Dashboard"

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{safe_title}</title>
  <style>
    :root {{
      --ink: #1d2933;
      --muted: #667785;
      --surface: #ffffff;
      --surface-2: #f5f7f2;
      --line: #d7e0dc;
      --accent: #0f766e;
      --accent-2: #d97706;
      --accent-3: #2563eb;
      --high: #b42318;
      --medium: #b54708;
      --low: #027a48;
      --unknown: #6b7280;
      --shadow: 0 10px 24px rgba(16, 38, 49, 0.08);
    }}

    * {{ box-sizing: border-box; }}

    body {{
      margin: 0;
      color: var(--ink);
      font-family: "IBM Plex Sans", "Trebuchet MS", "Verdana", sans-serif;
      background:
        radial-gradient(1200px 700px at 20% -10%, #e0f2f1 0%, transparent 60%),
        radial-gradient(1000px 700px at 100% 0%, #fff4dd 0%, transparent 55%),
        linear-gradient(180deg, #f8fbf9 0%, #eef3f1 100%);
      min-height: 100vh;
    }}

    .page {{
      max-width: 1240px;
      margin: 0 auto;
      padding: 20px 18px 36px;
    }}

    .hero {{
      border: 1px solid var(--line);
      background: linear-gradient(120deg, #ffffff 0%, #f3f8f5 70%);
      box-shadow: var(--shadow);
      border-radius: 18px;
      padding: 18px 20px;
      margin-bottom: 14px;
      position: relative;
      overflow: hidden;
    }}

    .hero::after {{
      content: "";
      position: absolute;
      right: -90px;
      top: -90px;
      width: 240px;
      height: 240px;
      border-radius: 50%;
      background: radial-gradient(circle, rgba(15,118,110,0.17) 0%, rgba(15,118,110,0) 65%);
    }}

    h1 {{
      margin: 0 0 6px;
      font-family: "Bitter", "Palatino Linotype", serif;
      font-size: clamp(1.4rem, 2vw, 2rem);
      letter-spacing: 0.2px;
    }}

    .subtle {{
      color: var(--muted);
      font-size: 0.95rem;
      margin: 0;
    }}

    .kpis {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
      gap: 10px;
      margin: 12px 0 14px;
    }}

    .tile {{
      border: 1px solid var(--line);
      border-radius: 12px;
      background: var(--surface);
      padding: 10px 12px;
      box-shadow: 0 4px 12px rgba(16, 38, 49, 0.05);
    }}

    .tile .label {{
      color: var(--muted);
      font-size: 0.8rem;
      text-transform: uppercase;
      letter-spacing: 0.08em;
    }}

    .tile .value {{
      margin-top: 4px;
      font-size: 1.4rem;
      font-weight: 700;
    }}

    .grid {{
      display: grid;
      grid-template-columns: 1fr;
      gap: 12px;
    }}

    @media (min-width: 1024px) {{
      .grid {{
        grid-template-columns: repeat(2, 1fr);
      }}
    }}

    .panel {{
      background: var(--surface);
      border: 1px solid var(--line);
      border-radius: 14px;
      box-shadow: var(--shadow);
      padding: 12px;
    }}

    .panel h2 {{
      margin: 0 0 8px;
      font-size: 1rem;
      letter-spacing: 0.02em;
    }}

    .bars {{
      display: grid;
      gap: 7px;
    }}

    .bar-row {{
      display: grid;
      grid-template-columns: 145px 1fr 40px;
      gap: 8px;
      align-items: center;
      font-size: 0.86rem;
    }}

    .bar-label {{
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }}

    .bar-track {{
      width: 100%;
      background: #edf2ef;
      border-radius: 999px;
      overflow: hidden;
      border: 1px solid #dfebe6;
      height: 12px;
    }}

    .bar-fill {{
      height: 100%;
      border-radius: 999px;
      background: linear-gradient(90deg, var(--accent), var(--accent-3));
      transition: width 300ms ease;
    }}

    .bar-value {{
      text-align: right;
      color: var(--muted);
      font-variant-numeric: tabular-nums;
    }}

    .controls {{
      margin-top: 12px;
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(170px, 1fr));
      gap: 8px;
    }}

    .controls .field {{
      display: grid;
      gap: 4px;
    }}

    label {{
      font-size: 0.77rem;
      color: var(--muted);
      text-transform: uppercase;
      letter-spacing: 0.07em;
    }}

    input, select {{
      width: 100%;
      padding: 8px 10px;
      border-radius: 9px;
      border: 1px solid #ccd8d2;
      background: #ffffff;
      color: var(--ink);
      font-size: 0.92rem;
    }}

    .results-header {{
      margin-top: 12px;
      display: flex;
      justify-content: space-between;
      gap: 8px;
      align-items: center;
      flex-wrap: wrap;
    }}

    .results-meta {{
      color: var(--muted);
      font-size: 0.9rem;
    }}

    .cards {{
      margin-top: 10px;
      display: grid;
      grid-template-columns: 1fr;
      gap: 10px;
    }}

    @media (min-width: 900px) {{
      .cards {{
        grid-template-columns: repeat(2, minmax(0, 1fr));
      }}
    }}

    .card {{
      border: 1px solid var(--line);
      border-radius: 12px;
      background: #ffffff;
      padding: 12px;
      box-shadow: 0 5px 12px rgba(16, 38, 49, 0.05);
      animation: rise 220ms ease;
    }}

    @keyframes rise {{
      from {{ opacity: 0; transform: translateY(4px); }}
      to {{ opacity: 1; transform: translateY(0); }}
    }}

    .card-title {{
      margin: 0;
      font-size: 1rem;
      line-height: 1.3;
    }}

    .card-id {{
      margin-top: 2px;
      color: var(--muted);
      font-family: "IBM Plex Mono", "Consolas", monospace;
      font-size: 0.78rem;
    }}

    .badges {{
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
      margin: 8px 0;
    }}

    .badge {{
      display: inline-flex;
      align-items: center;
      border-radius: 999px;
      border: 1px solid #d5e0db;
      padding: 2px 8px;
      font-size: 0.75rem;
      background: #f8fcfa;
      color: #27503d;
    }}

    .badge.severity-high {{
      color: #8c1d18;
      border-color: #f2cbc9;
      background: #fff1f1;
    }}

    .badge.severity-medium {{
      color: #8e4e00;
      border-color: #f6dfc0;
      background: #fff8ef;
    }}

    .badge.severity-low {{
      color: #0a6b42;
      border-color: #cce8da;
      background: #f1fbf5;
    }}

    .card p {{
      margin: 6px 0;
      font-size: 0.9rem;
      line-height: 1.35;
    }}

    .hint {{
      margin-top: 8px;
      color: var(--muted);
      font-size: 0.82rem;
    }}

    details {{
      margin-top: 6px;
      border-top: 1px dashed #d7e1dc;
      padding-top: 6px;
    }}

    summary {{
      cursor: pointer;
      color: #1b4c62;
      font-size: 0.86rem;
      user-select: none;
    }}

    .empty {{
      border: 1px dashed #c9d7d1;
      border-radius: 11px;
      padding: 14px;
      color: var(--muted);
      background: #fbfdfc;
      text-align: center;
    }}
  </style>
</head>
<body>
  <div class="page">
    <section class="hero">
      <h1>{safe_title}</h1>
      <p class="subtle">Source: {input_path.as_posix()}</p>
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
      <article class="panel" style="grid-column: 1 / -1;">
        <h2>Affected Engines</h2>
        <div class="bars" id="engine-chart"></div>
      </article>
    </section>

    <section class="panel" style="margin-top: 12px;">
      <h2>Issue Explorer</h2>

      <div class="controls">
        <div class="field">
          <label for="search">Search</label>
          <input id="search" type="text" placeholder="label, symptom, issue_id">
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
          <label for="engine">Engine</label>
          <select id="engine"></select>
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
          </select>
        </div>
      </div>

      <div class="results-header">
        <div class="results-meta" id="results-meta"></div>
      </div>

      <div class="cards" id="cards"></div>
      <div class="hint">Tip: start with component + severity filters, then inspect source videos per issue.</div>
    </section>
  </div>

  <script id="issue-data" type="application/json">{issues_json}</script>
  <script id="summary-data" type="application/json">{summary_json}</script>

  <script>
    const issues = JSON.parse(document.getElementById('issue-data').textContent);
    const summary = JSON.parse(document.getElementById('summary-data').textContent);

    const severityRank = {{ high: 3, medium: 2, low: 1, unknown: 0 }};
    const confidenceRank = {{ high: 3, medium: 2, low: 1, unknown: 0 }};

    function titleCase(text) {{
      return String(text || '')
        .replace(/_/g, ' ')
        .trim()
        .replace(/\\w\\S*/g, (w) => w.charAt(0).toUpperCase() + w.slice(1));
    }}

    function escapeHtml(text) {{
      return String(text || '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
    }}

    function buildKpis() {{
      const kpis = [
        {{ label: 'Rows', value: summary.total_issues }},
        {{ label: 'Unique Issue IDs', value: summary.unique_issue_ids }},
        {{ label: 'Total Mentions', value: summary.mention_total }},
        {{ label: 'High Severity', value: summary.high_severity_count }},
        {{ label: 'Chronic Failures', value: summary.chronic_count }},
        {{ label: 'Duplicate ID Rows', value: summary.duplicate_id_rows }},
      ];

      const root = document.getElementById('kpis');
      root.innerHTML = kpis
        .map((k) => `
          <div class="tile">
            <div class="label">${{escapeHtml(k.label)}}</div>
            <div class="value">${{Number(k.value).toLocaleString()}}</div>
          </div>
        `)
        .join('');
    }}

    function renderBars(containerId, countsObj, maxItems = 20) {{
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
              <div class="bar-label" title="${{escapeHtml(name)}}">${{escapeHtml(titleCase(name))}}</div>
              <div class="bar-track"><div class="bar-fill" style="width:${{width}}%"></div></div>
              <div class="bar-value">${{Number(value).toLocaleString()}}</div>
            </div>
          `;
        }})
        .join('');
    }}

    function uniqueSorted(values) {{
      return [...new Set(values.filter(Boolean))].sort((a, b) => a.localeCompare(b));
    }}

    function populateSelect(id, values) {{
      const el = document.getElementById(id);
      const options = ['all', ...uniqueSorted(values)];
      el.innerHTML = options
        .map((v) => `<option value="${{escapeHtml(v)}}">${{v === 'all' ? 'All' : escapeHtml(titleCase(v))}}</option>`)
        .join('');
    }}

    function createBadges(issue) {{
      const badges = [
        `<span class="badge severity-${{escapeHtml(issue.severity)}}">severity: ${{escapeHtml(issue.severity)}}</span>`,
        `<span class="badge">component: ${{escapeHtml(issue.system_component)}}</span>`,
        `<span class="badge">type: ${{escapeHtml(issue.issue_type)}}</span>`,
        `<span class="badge">confidence: ${{escapeHtml(issue.confidence)}}</span>`,
        `<span class="badge">mentions: ${{Number(issue.mention_count).toLocaleString()}}</span>`,
      ];
      return badges.join('');
    }}

    function sourceVideoHtml(videos) {{
      if (!Array.isArray(videos) || !videos.length) return '<p class="subtle">No source videos listed.</p>';
      const list = videos.slice(0, 8).map((v) => {{
        const vid = escapeHtml(v.video_id || '');
        const title = escapeHtml(v.title || v.video_id || 'video');
        if (vid) {{
          return `<li><a href="https://www.youtube.com/watch?v=${{vid}}" target="_blank" rel="noreferrer">${{title}}</a></li>`;
        }}
        return `<li>${{title}}</li>`;
      }}).join('');
      return `<ul>${{list}}</ul>`;
    }}

    function renderCards(items) {{
      const root = document.getElementById('cards');
      if (!items.length) {{
        root.innerHTML = '<div class="empty">No issues match the current filters.</div>';
        return;
      }}

      root.innerHTML = items.map((issue) => {{
        const engines = issue.affected_engines && issue.affected_engines.length
          ? issue.affected_engines.join(', ')
          : 'unknown';
        const variants = issue.affected_engine_variants && issue.affected_engine_variants.length
          ? issue.affected_engine_variants.join(', ')
          : 'n/a';
        const yearContext = issue.engine_year_context && issue.engine_year_context.length
          ? issue.engine_year_context
              .map((row) => `${{row.engine}}: ${{row.years || 'n/a'}} (hits: ${{row.evidence_hits || 0}})`)
              .join('; ')
          : 'n/a';
        const warningSigns = issue.warning_signs && issue.warning_signs.length
          ? issue.warning_signs.join('; ')
          : 'n/a';

        return `
          <article class="card">
            <h3 class="card-title">${{escapeHtml(issue.label)}}</h3>
            <div class="card-id">${{escapeHtml(issue.issue_id)}}</div>
            <div class="badges">${{createBadges(issue)}}</div>
            <p><strong>Symptom:</strong> ${{escapeHtml(issue.symptom || 'n/a')}}</p>
            <p><strong>Cause:</strong> ${{escapeHtml(issue.cause || 'n/a')}}</p>
            <p><strong>Fix:</strong> ${{escapeHtml(issue.fix || 'n/a')}}</p>
            <p><strong>Engines:</strong> ${{escapeHtml(engines)}}</p>
            <p><strong>Affected Years:</strong> ${{escapeHtml(issue.affected_years || 'n/a')}}</p>
            <p><strong>Engine Variants:</strong> ${{escapeHtml(variants)}}</p>
            <p><strong>Year Evidence:</strong> ${{escapeHtml(yearContext)}}</p>
            <p><strong>Onset:</strong> ${{escapeHtml(issue.onset_km_range || 'n/a')}}</p>
            <p><strong>Warning Signs:</strong> ${{escapeHtml(warningSigns)}}</p>
            <details>
              <summary>Source Videos (${{issue.source_videos ? issue.source_videos.length : 0}})</summary>
              ${{sourceVideoHtml(issue.source_videos || [])}}
            </details>
          </article>
        `;
      }}).join('');
    }}

    function applyFilters() {{
      const query = (document.getElementById('search').value || '').trim().toLowerCase();
      const component = document.getElementById('component').value;
      const type = document.getElementById('type').value;
      const severity = document.getElementById('severity').value;
      const confidence = document.getElementById('confidence').value;
      const engine = document.getElementById('engine').value;
      const minMentions = Number(document.getElementById('min-mentions').value || 0);
      const sort = document.getElementById('sort').value;

      let filtered = issues.filter((issue) => {{
        const hay = [
          issue.issue_id,
          issue.label,
          issue.label_short,
          issue.symptom,
          issue.cause,
          issue.fix,
          issue.inspection_advice,
          issue.affected_years,
          (issue.warning_signs || []).join(' '),
          (issue.affected_engines || []).join(' '),
          (issue.affected_engine_variants || []).join(' '),
          (issue.engine_year_context || []).map((x) => `${{x.engine}} ${{x.years}}`).join(' '),
        ].join(' ').toLowerCase();

        if (query && !hay.includes(query)) return false;
        if (component !== 'all' && issue.system_component !== component) return false;
        if (type !== 'all' && issue.issue_type !== type) return false;
        if (severity !== 'all' && issue.severity !== severity) return false;
        if (confidence !== 'all' && issue.confidence !== confidence) return false;
        if (engine !== 'all') {{
          const engines = issue.affected_engines || [];
          if (!(engines.includes(engine) || engines.includes('all'))) return false;
        }}
        if ((issue.mention_count || 0) < minMentions) return false;

        return true;
      }});

      filtered.sort((a, b) => {{
        if (sort === 'mentions_desc') {{
          return (b.mention_count || 0) - (a.mention_count || 0);
        }}
        if (sort === 'severity_desc') {{
          return (severityRank[b.severity] || 0) - (severityRank[a.severity] || 0) ||
                 (b.mention_count || 0) - (a.mention_count || 0);
        }}
        if (sort === 'confidence_desc') {{
          return (confidenceRank[b.confidence] || 0) - (confidenceRank[a.confidence] || 0) ||
                 (b.mention_count || 0) - (a.mention_count || 0);
        }}
        return String(a.label || '').localeCompare(String(b.label || ''));
      }});

      renderCards(filtered);

      const meta = document.getElementById('results-meta');
      meta.textContent = `${{filtered.length.toLocaleString()}} matching issues out of ${{issues.length.toLocaleString()}}`;
    }}

    function init() {{
      buildKpis();
      renderBars('component-chart', summary.component_counts, 20);
      renderBars('type-chart', summary.type_counts, 20);
      renderBars('severity-chart', summary.severity_counts, 10);
      renderBars('confidence-chart', summary.confidence_counts, 10);
      renderBars('engine-chart', summary.engine_counts, 30);

      populateSelect('component', issues.map((x) => x.system_component));
      populateSelect('type', issues.map((x) => x.issue_type));
      populateSelect('severity', issues.map((x) => x.severity));
      populateSelect('confidence', issues.map((x) => x.confidence));
      populateSelect('engine', issues.flatMap((x) => x.affected_engines || []));

      ['search', 'component', 'type', 'severity', 'confidence', 'engine', 'min-mentions', 'sort']
        .forEach((id) => document.getElementById(id).addEventListener('input', applyFilters));

      applyFilters();
    }}

    init();
  </script>
</body>
</html>
"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build an HTML visualizer for issue knowledge JSON output.")
    parser.add_argument(
        "--input",
        type=Path,
        default=ROOT / "data" / "processed" / "issue_knowledge_youtube_vw_golf_mk7.json",
        help="Path to issue knowledge JSON input.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Output HTML path. Default: <input_stem>_dashboard.html",
    )
    parser.add_argument(
        "--title",
        type=str,
        default=None,
        help="Dashboard title.",
    )
    parser.add_argument(
        "--open",
        action="store_true",
        help="Open generated dashboard in default browser.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    input_path = args.input
    if not input_path.is_absolute():
        input_path = (ROOT / input_path).resolve()

    if not input_path.exists():
        raise FileNotFoundError(f"Input JSON not found: {input_path}")

    with open(input_path, "r", encoding="utf-8") as handle:
        raw = json.load(handle)

    if not isinstance(raw, list):
        raise ValueError("Input JSON must be a list of issue objects.")

    issues = normalize_issues(raw)
    summary = build_summary(issues)

    output_path = args.output
    if output_path is None:
        output_path = input_path.with_name(f"{input_path.stem}_dashboard.html")
    if not output_path.is_absolute():
        output_path = (ROOT / output_path).resolve()

    title = args.title
    if not title:
        title = f"Issue Knowledge Dashboard - {input_path.stem}"

    html = build_dashboard_html(title=title, input_path=input_path, issues=issues, summary=summary)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html, encoding="utf-8")

    print(f"Dashboard generated: {output_path}")
    print(f"Rows: {summary['total_issues']} | Unique issue_id: {summary['unique_issue_ids']}")
    if summary["duplicate_id_rows"]:
        print(
            "Duplicate issue_id rows: "
            f"{summary['duplicate_id_rows']} across {summary['duplicate_id_groups']} issue_id groups"
        )

    if args.open:
        webbrowser.open(f"file:///{output_path.as_posix()}")


if __name__ == "__main__":
    main()
