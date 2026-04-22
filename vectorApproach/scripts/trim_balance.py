"""
trim_balance.py — shared, scaffold-driven trim balancing helpers.

Purpose
───────
Video corpora from broad YouTube search are structurally biased toward
performance / enthusiast variants (Golf GTI/R, Clio RS, BMW M-series, …)
because those titles carry more search traffic. This module provides a
generic, scaffold-driven utility to:

  1. Detect the performance-variant signature in a video title using
     tokens declared in the scaffold (``scaffold.performance_trims.tokens``).
  2. Downsample the performance-variant subset to a configurable share of
     the corpus, keeping all non-performance videos.

Scaffold YAML contract (optional block, per model):

    performance_trims:
      max_share: 0.3
      tokens:
        - gti
        - "golf r"
        - "mk7.5 r"

Callers pass ``scaffold`` plus an optional share override. If the block is
missing the helpers are no-ops, so models without a declared performance
variant behave as before.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Iterable

log = logging.getLogger(__name__)

# Title/channel tokens that mark a video as ownership / fault / mechanic
# content regardless of trim. Perf-trim videos that *also* carry these
# signals are exempt from the downsample cap — they're genuine fault
# evidence, not performance hype.
_FAULT_OR_OWNERSHIP_SIGNALS = (
    "problem", "issue", "fault", "break", "broken", "failure", "failed",
    "fix", "repair", "leak", "noise", "rattle", "diagnos", "ownership",
    "owner review", "daily driver", "long term", "long-term",
    "miles review", "miles ownership", "years later", "buyer's guide",
    "buyers guide", "reliability", "known problems", "common problems",
    "what goes wrong", "what to look for", "things that break",
    "mechanic", "workshop", "garage",
)


def _has_fault_ownership_signal(video: dict) -> bool:
    blob = f"{video.get('title', '')} {video.get('channel', '')}".lower()
    return any(sig in blob for sig in _FAULT_OR_OWNERSHIP_SIGNALS)


def _compile_token_patterns(tokens: Iterable[str]) -> list[re.Pattern[str]]:
    pats: list[re.Pattern[str]] = []
    for tok in tokens:
        t = str(tok).strip().lower()
        if not t:
            continue
        # Word-boundary match; multi-word tokens get flexible whitespace.
        parts = [re.escape(p) for p in t.split()]
        pats.append(re.compile(r"\b" + r"\s+".join(parts) + r"\b", re.IGNORECASE))
    return pats


def get_perf_config(scaffold: dict[str, Any]) -> tuple[list[re.Pattern[str]], float]:
    """Return (patterns, max_share) from scaffold.performance_trims.

    Returns ([], 1.0) when no config is declared, which makes downstream
    helpers no-ops.
    """
    block = (scaffold or {}).get("performance_trims") or {}
    tokens = block.get("tokens") or []
    max_share = float(block.get("max_share", 1.0))
    return _compile_token_patterns(tokens), max_share


def title_is_performance(title: str, patterns: list[re.Pattern[str]]) -> bool:
    if not patterns:
        return False
    low = (title or "").lower()
    return any(p.search(low) for p in patterns)


def downsample_performance_videos(
    videos: list[dict],
    scaffold: dict[str, Any],
    share_override: float | None = None,
) -> list[dict]:
    """Cap the performance-variant share of a video list.

    Deterministic: drops surplus performance videos by sorted ``video_id``.
    No-op if the scaffold declares no performance_trims or the share is ≥1.
    """
    patterns, max_share = get_perf_config(scaffold)
    if share_override is not None:
        max_share = float(share_override)
    if not patterns or max_share >= 1.0:
        return videos

    # Split into (a) non-perf, (b) perf with fault/ownership signal — always
    # kept, (c) perf hype/performance content — subject to the cap. This is
    # score-aware: a GTI ownership review is treated as fault evidence, while
    # a GTI drag-race clip is treated as bias noise.
    other, perf_signal, perf_hype = [], [], []
    for v in videos:
        if title_is_performance(v.get("title", ""), patterns):
            if _has_fault_ownership_signal(v):
                perf_signal.append(v)
            else:
                perf_hype.append(v)
        else:
            other.append(v)

    if not perf_hype and not perf_signal:
        return videos

    # Cap applies to total perf share, but we preserve perf_signal first.
    base = other + perf_signal
    if max_share <= 0:
        total_perf_allowed = 0
    else:
        # k / (len(other) + k) <= max_share  →  k <= share*other / (1-share)
        total_perf_allowed = int(max_share * len(other) / (1.0 - max_share))

    perf_signal_kept = min(len(perf_signal), total_perf_allowed)
    remaining = max(0, total_perf_allowed - perf_signal_kept)
    hype_kept = min(len(perf_hype), remaining)

    perf_signal_sorted = sorted(perf_signal, key=lambda v: str(v.get("video_id", "")))
    perf_hype_sorted = sorted(perf_hype, key=lambda v: str(v.get("video_id", "")))

    result = other + perf_signal_sorted[:perf_signal_kept] + perf_hype_sorted[:hype_kept]
    dropped_signal = len(perf_signal) - perf_signal_kept
    dropped_hype = len(perf_hype) - hype_kept

    log.info(
        "Performance-trim downsample: non-perf=%d, perf-signal=%d (kept %d), "
        "perf-hype=%d (kept %d), dropped_signal=%d, dropped_hype=%d "
        "(max_share=%.2f)",
        len(other), len(perf_signal), perf_signal_kept,
        len(perf_hype), hype_kept, dropped_signal, dropped_hype, max_share,
    )
    return result
