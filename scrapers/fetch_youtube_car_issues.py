import argparse
import json
import logging
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from typing import cast

import requests
import yt_dlp
from tqdm import tqdm

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scrapers.fetch_youtube_transcripts import search_youtube_videos
from scripts.extract_youtube_issues import load_scaffold
from scripts.trim_balance import downsample_performance_videos

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)

# Broad, model-level query templates. These surface general ownership and
# mechanic content without presupposing any specific issue.
_QUERY_TEMPLATES_EN = [
    "{car} chronic issues",
    "{car} chronic problems",
    "{car} known faults",
    "{car} reliability problems",
    "{car} common faults",
    "{car} long term review",
    "{car} owner review problems",
    "{car} buying used problems",
    "{car} things to check before buying",
]

_QUERY_TEMPLATES_TR = [
    "{car} kronik sorunları",
    "{car} kronik arızaları",
    "{car} bilinen arızaları",
    "{car} ikinci el alırken nelere dikkat",
    "{car} uzun dönem kullanım",
    "{car} sahibinden şikayetleri",
]

# Per-engine expansions balance corpus coverage across the scaffold's engine
# bank (petrol vs diesel, high- vs low-displacement). Still model-level — we
# only add the displacement taxonomy, no failure vocabulary.
_PER_ENGINE_TEMPLATES_EN = [
    "{car} {engine} common problems",
    "{car} {engine} known faults",
]

_PER_ENGINE_TEMPLATES_TR = [
    "{car} {engine} kronik sorunları",
    "{car} {engine} arızaları",
]

_MECHANIC_SIGNALS_EN = (
    "mechanic",
    "workshop",
    "garage",
    "specialist",
    "independent",
    "inspection",
    "diagnostic",
    "diagnosis",
    "teardown",
    "technician",
    "master tech",
    "ownership",
    "owner review",
    "daily driver",
    "long term",
    "long term ownership",
    "family car",
    "known faults",
    "common faults",
    "buyers guide",
    "buyer's guide",
    "what to look for",
    "what goes wrong",
)

_MECHANIC_SIGNALS_TR = (
    "usta",
    "tamir",
    "servis",
    "bakım",
    "garaj",
    "mekanik",
    "atölye",
    "kronik",
    "sorun",
    "ariza",
    "arıza",
    "kullanıcı",
    "inceleme",
    "alınır mı",
    "alinir mi",
    "neden alınmaz",
    "neden alinmaz",
)

_LIST_FORMAT_SIGNALS_EN = (
    "buyer's guide",
    "buyers guide",
    "common problems",
    "common issues",
    "common faults",
    "avoid buying",
    "what to look for",
    "things that break",
    "known faults",
    "reliability review",
    "problems with",
)

_LIST_FORMAT_SIGNALS_TR = (
    "alınır mı",
    "alinir mi",
    "kronik sorunlar",
    "dikkat edilmesi gerekenler",
    "neden alınmaz",
    "neden alinmaz",
    "problemleri",
    "şikayetleri",
)

# Global variables that will be swapped based on language
_QUERY_TEMPLATES = _QUERY_TEMPLATES_EN
_MECHANIC_SIGNALS = _MECHANIC_SIGNALS_EN
_LIST_FORMAT_SIGNALS = _LIST_FORMAT_SIGNALS_EN

# Entertainment / hype markers — videos that rarely contain owner-grade
# fault evidence. Only reject when the title shows NO fault/ownership signal.
_HYPE_SIGNALS_EN = (
    "drag race",
    " vs ",
    " vs. ",
    "0-60",
    "0 to 60",
    "top speed",
    "stage 1",
    "stage 2",
    "stage 3",
    "tuned",
    "modified",
    "dyno",
    "acceleration",
    "launch control",
    "remap",
)

_HYPE_SIGNALS_TR = (
    "yarış",
    "hız testi",
    "0-100",
    "modifiye",
    "yazılım",
    "drag",
    "kapışma",
    "hızlanma",
)

# If any of these appear we keep the video even if hype markers also match.
_FAULT_OR_OWNERSHIP_SIGNALS_EN = (
    "problem",
    "issue",
    "fault",
    "break",
    "broken",
    "failure",
    "failed",
    "fix",
    "repair",
    "leak",
    "noise",
    "rattle",
    "diagnos",
    "ownership",
    "owner review",
    "daily driver",
    "long term",
    "long-term",
    "miles review",
    "miles ownership",
    "years later",
    "after \u2026 miles",
    "buyer's guide",
    "buyers guide",
    "should you buy",
    "reliability",
    "everything you need to know",
    "known problems",
    "common problems",
)

_FAULT_OR_OWNERSHIP_SIGNALS_TR = (
    "sorun",
    "arıza",
    "ariza",
    "problem",
    "tamir",
    "bakım",
    "kronik",
    "şikayet",
    "sikayet",
    "kullanıcı yorumu",
    "uzun kullanım",
    "neden alınmaz",
    "neden alinmaz",
    "alınır mı",
    "alinir mi",
    "neleri bozulur",
    "masraf",
    "eksikleri",
)

# Global variables that will be swapped based on language
_QUERY_TEMPLATES = _QUERY_TEMPLATES_EN
_MECHANIC_SIGNALS = _MECHANIC_SIGNALS_EN
_LIST_FORMAT_SIGNALS = _LIST_FORMAT_SIGNALS_EN
_HYPE_SIGNALS = _HYPE_SIGNALS_EN
_FAULT_OR_OWNERSHIP_SIGNALS = _FAULT_OR_OWNERSHIP_SIGNALS_EN


def _title_blob(video: dict) -> str:
    return f"{video.get('title', '')} {video.get('channel', '')}".lower()


def _has_signal(blob: str, signals: tuple[str, ...]) -> bool:
    return any(sig in blob for sig in signals)


# ── Cross-brand title filter ────────────────────────────────────────────────
# YouTube's search results sometimes surface videos from a different OEM that
# happen to rank for the query (e.g. a Ford 1.0 EcoBoost teardown matching a
# "Renault Clio chronic issues" search). These contaminate the transcript
# corpus with wrong-brand engine wording that the LLM then absorbs. We drop
# any video whose title mentions a foreign OEM or a foreign engine-family
# token *and* doesn't mention the target make/model from the scaffold.
_BRAND_GROUPS: list[set[str]] = [
    {"vw", "volkswagen", "audi", "seat", "skoda", "cupra", "porsche", "bentley"},
    {"renault", "dacia", "nissan", "infiniti", "mitsubishi"},
    {"ford", "lincoln"},
    {"toyota", "lexus", "subaru"},
    {"honda", "acura"},
    {"hyundai", "kia", "genesis"},
    {"peugeot", "citroen", "citroën", "opel", "vauxhall", "fiat",
     "alfa", "lancia", "chrysler", "dodge", "jeep", "ram", "maserati", "ds"},
    {"bmw", "mini"},
    {"mercedes", "mercedes-benz", "smart"},
    {"volvo", "polestar"},
    {"mazda"},
    {"tesla"},
    {"jaguar", "land rover", "range rover"},
]
_FOREIGN_ENGINE_TOKENS: dict[str, set[str]] = {
    "ford":     {"ecoboost", "duratec", "duratorq"},
    "bmw":      {"n20", "n47", "n54", "n55", "b48", "b58"},
    "toyota":   {"2ar-fe", "1zz", "2zz"},
    "honda":    {"k20", "k24"},
    "peugeot":  {"puretech", "hdi", "bluehdi"},
    "mazda":    {"skyactiv"},
    "mercedes": {"cdi", "bluetec"},
    "vw":       {"tsi", "tdi", "tfsi"},
}


def _scaffold_allowed_brand_group(scaffold: dict) -> set[str]:
    make = ((scaffold or {}).get("meta") or {}).get("make", "").lower().strip()
    if not make:
        return set()
    for group in _BRAND_GROUPS:
        if make in group:
            return group
    return {make}


_ROMAN_MAP: dict[str, int] = {
    "i": 1, "ii": 2, "iii": 3, "iv": 4, "v": 5, "vi": 6, "vii": 7, "viii": 8,
}


_ORDINAL_SUFFIX = {1: "st", 2: "nd", 3: "rd"}


def _gen_number(gen: str) -> int | None:
    """Extract integer generation from a gen label like ``MK7``/``IV``."""
    g = (gen or "").strip().lower()
    if not g:
        return None
    m = re.fullmatch(r"mk\s*(\d+)(?:\.\d+)?", g)
    if m:
        return int(m.group(1))
    if g in _ROMAN_MAP:
        return _ROMAN_MAP[g]
    m = re.fullmatch(r"mk(i{1,3}|iv|v|vi|vii|viii)", g)
    if m and m.group(1) in _ROMAN_MAP:
        return _ROMAN_MAP[m.group(1)]
    return None


def _gen_label_tokens(meta: dict, facelifts: list[dict]) -> list[str]:
    """Tokens that name the generation (mk1, mk7, mk7.5, phase 1, ``4th gen``
    ...). Emits only phrases ≥3 chars with ≥1 digit-or-dash so generic words
    like ``phase`` or bare roman ``i`` can't anchor a match.
    """
    out: list[str] = []
    gen = str(meta.get("generation", "")).strip().lower()
    if gen and len(gen) >= 3:
        out.append(gen)
    if gen:
        m = re.fullmatch(r"mk\s*(\d+(?:\.\d+)?)", gen)
        if m:
            n = m.group(1)
            out.extend([f"mk{n}", f"mk {n}", f"mk-{n}", f"mark {n}"])
        n_int = _gen_number(gen)
        if n_int is not None:
            out.extend([f"mk{n_int}", f"mk {n_int}", f"mark {n_int}"])
            # Ordinal phrasings: "4th gen", "4th generation", "gen 4".
            suffix = _ORDINAL_SUFFIX.get(n_int % 10 if n_int % 100 not in (11, 12, 13) else 0, "th")
            out.extend([
                f"{n_int}{suffix} gen",
                f"{n_int}{suffix} generation",
                f"gen {n_int}",
                f"generation {n_int}",
            ])
    for fl in facelifts or []:
        for key in ("label", "pre_label"):
            v = str((fl or {}).get(key, "")).strip().lower()
            # Only keep multi-word labels (e.g. "phase 2", "mk7.5"). Don't
            # split off the head — "phase" alone is too generic.
            if v and len(v) >= 4 and re.search(r"[\d.\-]", v):
                out.append(v)
    return out


def _corpus_year_tokens(meta: dict) -> list[str]:
    yrs = meta.get("corpus_years") or []
    if len(yrs) < 2:
        return []
    try:
        lo, hi = int(yrs[0]), int(yrs[1])
    except (TypeError, ValueError):
        return []
    if lo > hi or lo < 1950 or hi > 2100:
        return []
    return [str(y) for y in range(lo, hi + 1)]


def _scaffold_target_tokens(scaffold: dict) -> dict:
    """Categorize title tokens used by the on-topic filter.

    Returns two lists:
      - ``model``: the **model head** word(s) only (``clio``, ``golf``). The
        make alone (``vw``, ``renault``) is **not** a model token — a ``VW
        Polo`` video shares the brand but is the wrong nameplate. The filter
        enforces brand-group correctness separately via
        :func:`_scaffold_allowed_brand_group`.
      - ``scope``: generation-scoping signals — gen labels (``mk7``,
        ``phase 1``), corpus-window years, distinctive engine-family codes
        (``ea888``, ``h5ft``, ``k9k`` — anything containing a digit), and
        qualified displacements with a ≥3-char family suffix (``1.4 tsi``,
        ``1.5 dci``). Bare numeric displacements (``1.2``, ``2.0``) are
        excluded — they match half of YouTube.

    Acceptance rule: ``model hit`` AND ``scope hit`` (see
    :func:`cross_brand_title_filter`).
    """
    meta = (scaffold or {}).get("meta") or {}
    facelifts = scaffold.get("facelifts") or []
    model = str(meta.get("model", "")).lower().strip()

    model_toks: list[str] = []
    for part in re.split(r"\s+", model):
        part = part.strip()
        if not part or len(part) < 3:
            continue
        # Strip gen tokens out of the model set — they belong in scope.
        if re.fullmatch(r"mk\s*\d+(\.\d+)?", part):
            continue
        if re.fullmatch(r"mk?[iv]+", part):
            continue
        model_toks.append(part)

    # Performance-trim nicknames (gti, golf r, williams, rs 200) are nameplate-
    # specific enough to stand in for the model head when combined with a
    # scope hit. "MK7 GTI common problems" → gti + mk7 → kept as Golf Mk7.
    perf = (scaffold or {}).get("performance_trims") or {}
    for tok in perf.get("tokens") or []:
        tok = str(tok or "").strip().lower()
        if tok and len(tok) >= 2:
            model_toks.append(tok)

    scope_toks: list[str] = []
    family_suffixes: set[str] = set()
    for ef in scaffold.get("engine_families") or []:
        fam = str(ef.get("code", "")).strip().lower()
        # Distinctive family code = has a digit (EA888, H5Ft, K9K, EA211).
        # Skips English-word families (ENERGY, F_TYPE, F_DIESEL, CLEON).
        if fam and len(fam) >= 3 and re.search(r"\d", fam):
            scope_toks.append(fam)
        for d in ef.get("displacements") or []:
            code = d.get("code") if isinstance(d, dict) else d
            code = str(code or "").strip().lower()
            if not code or "_" not in code:
                # Bare "1.2"/"2.0" — too generic, drop entirely.
                continue
            head, _, tail = code.partition("_")
            if len(tail) < 3:
                # Short suffix (e.g. "1.9_d") — single-letter family, ambiguous.
                continue
            scope_toks.extend([f"{head} {tail}", f"{head}{tail}"])
            family_suffixes.add(tail)
    # Bare family suffixes (tce, dci, tsi, tdi) as scope tokens. Catches titles
    # that split displacement and family across other words, e.g.
    # "0.9 Renault Clio TCE Engine Layout". Combined with the model-head
    # requirement, cross-model leaks stay contained to the same nameplate.
    scope_toks.extend(sorted(family_suffixes))

    scope_toks.extend(_gen_label_tokens(meta, facelifts))
    scope_toks.extend(_corpus_year_tokens(meta))

    # "{model_head} {N}" compounds — catches the common shorthand where the
    # title writes "Golf 7" / "Clio 4" instead of "Mk7" / "Mk4". These hit
    # both model and scope simultaneously (the head word covers model).
    n_int = _gen_number(str(meta.get("generation", "")))
    if n_int is not None:
        for head in model_toks:
            if " " in head or len(head) < 3:
                continue
            scope_toks.extend([f"{head} {n_int}", f"{head}{n_int}", f"{head}-{n_int}"])

    def _dedup(xs: list[str]) -> list[str]:
        seen: set[str] = set()
        out: list[str] = []
        for x in xs:
            if x and x not in seen:
                seen.add(x)
                out.append(x)
        return out

    return {"model": _dedup(model_toks), "scope": _dedup(scope_toks)}


def cross_brand_title_filter(
    videos: list[dict], scaffold: dict
) -> tuple[list[dict], list[dict]]:
    """On-topic title gate. Accepts a video only when its title either
    (a) names a generation-unique hardware token (distinctive engine family or
    qualified displacement), or (b) names the make/model AND a gen-scoping
    token (mk7, phase 1, corpus year, bare displacement).

    Rejects tagged with ``foreign_brand:*`` / ``foreign_engine:*`` when a
    competing OEM is named, ``wrong_generation`` when the nameplate matches
    but no gen signal is present, else ``off_topic_title``.

    Cheapest validation point — runs before transcript fetch / LLM call.
    """
    allowed = _scaffold_allowed_brand_group(scaffold)
    toks = _scaffold_target_tokens(scaffold)
    model_toks = toks["model"]
    scope_toks = toks["scope"]
    if not allowed or not model_toks or not scope_toks:
        return videos, []

    def _any_hit(title: str, tlist: list[str]) -> bool:
        return any(re.search(r"\b" + re.escape(t) + r"\b", title) for t in tlist)

    accepted: list[dict] = []
    rejected: list[dict] = []
    for v in videos:
        title = str(v.get("title", "")).lower()
        if not title:
            accepted.append(v)
            continue

        model_hit = _any_hit(title, model_toks)
        scope_hit = _any_hit(title, scope_toks)
        if model_hit and scope_hit:
            accepted.append(v)
            continue

        # Reject — classify the reason for audit.
        reason = "off_topic_title"
        if model_hit and not scope_hit:
            reason = "wrong_generation"
        elif scope_hit and not model_hit:
            reason = "wrong_model"
        else:
            for group in _BRAND_GROUPS:
                if group == allowed:
                    continue
                for brand in group:
                    if re.search(r"\b" + re.escape(brand) + r"\b", title):
                        reason = f"foreign_brand:{brand}"
                        break
                if reason != "off_topic_title":
                    break
            if reason == "off_topic_title":
                for brand, tokens in _FOREIGN_ENGINE_TOKENS.items():
                    if brand in allowed:
                        continue
                    for tok in tokens:
                        if re.search(r"\b" + re.escape(tok) + r"\b", title):
                            reason = f"foreign_engine:{tok}"
                            break
                    if reason != "off_topic_title":
                        break

        v["prefilter_reason"] = reason
        rejected.append(v)
    return accepted, rejected


def relevancy_prefilter(
    videos: list[dict],
    viral_list_view_threshold: int = 1_500_000,
) -> tuple[list[dict], list[dict]]:
    """
    Split candidates into (accepted, rejected) based on content signals.

    Model-agnostic rules only — trim/variant filters belong in scaffolds.

    Rules:
      1. Always accept if the video reads as niche mechanic content.
      2. Reject viral list-format videos (buyer's guide / common problems)
         whose view count is above `viral_list_view_threshold`. These are the
         curated-enumeration videos that inflate mention_count.
      3. Reject hype/entertainment videos with no fault or ownership signal.
      4. Otherwise accept.
    """
    accepted: list[dict] = []
    rejected: list[dict] = []

    for video in videos:
        blob = _title_blob(video)
        view_count = video.get("view_count_raw")

        is_list_format = _has_signal(blob, _LIST_FORMAT_SIGNALS)
        if (
            is_list_format
            and isinstance(view_count, int)
            and view_count > viral_list_view_threshold
        ):
            video["prefilter_reason"] = "viral_list_format"
            rejected.append(video)
            continue

        if _is_mechanic_niche(video):
            accepted.append(video)
            continue

        if _has_signal(blob, _HYPE_SIGNALS) and not _has_signal(
            blob, _FAULT_OR_OWNERSHIP_SIGNALS
        ):
            video["prefilter_reason"] = "hype_no_fault_signal"
            rejected.append(video)
            continue

        accepted.append(video)

    return accepted, rejected


def _get_video_type_category(video: dict) -> str:
    title = str(video.get("title", "")).lower()
    if any(sig in title for sig in _LIST_FORMAT_SIGNALS):
        return "list_format"
    return "organic"

_YDL_BASE_OPTS = {
    "quiet": True,
    "no_warnings": True,
    "skip_download": True,
    "extractor_args": {"youtube": {"player_client": ["web", "android"]}},
}
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}


def _parse_json3(url: str, video_id: str) -> dict[str, Any]:
    """Fetch and parse a YouTube JSON3 subtitle URL into segments."""
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=20)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        logging.warning(f"Failed to fetch/parse subtitle URL for {video_id}: {e}")
        return {"status": "error", "segments": [], "text": ""}

    segments = []
    for event in data.get("events", []):
        segs = event.get("segs")
        if not segs:
            continue
        text = "".join(s.get("utf8", "") for s in segs).strip()
        if not text or text == "\n":
            continue
        start = event.get("tStartMs", 0) / 1000.0
        dur = event.get("dDurationMs", 0) / 1000.0
        segments.append({"text": text, "start": start, "duration": dur})

    if not segments:
        return {"status": "error", "segments": [], "text": ""}
    return {
        "status": "ok",
        "segments": segments,
        "text": "\n".join(s["text"] for s in segments),
    }


def fetch_transcript_structured(
    video_id: str,
    cookies_file: str | None = None,
    target_lang: str = "en",
) -> dict[str, Any]:
    """
    Fetch transcript via yt-dlp (web client, android fallback for bot detection).

    Returns:
        {
            "status": "ok" | "no_english" | "disabled" | "error",
            "video_language": str | None,
            "segments": [...],
            "text": str
        }
    """
    opts = dict(_YDL_BASE_OPTS)
    if cookies_file:
        opts["cookiefile"] = cookies_file

    url = f"https://www.youtube.com/watch?v={video_id}"
    try:
        with yt_dlp.YoutubeDL(cast(Any, opts)) as ydl:
            info = ydl.extract_info(url, download=False)
        if not info:
            return {
                "status": "error",
                "video_language": None,
                "segments": [],
                "text": "",
            }

        video_lang = info.get("language") or ""

        if video_lang and not video_lang.lower().startswith(target_lang):
            logging.info(
                f"Skipping {video_id}: video language is '{video_lang}' (want '{target_lang}')"
            )
            return {
                "status": "no_english",
                "video_language": video_lang,
                "segments": [],
                "text": "",
            }

        target_langs = [target_lang, f"{target_lang}-US", f"{target_lang}-GB"]
        for source in [info.get("subtitles", {}), info.get("automatic_captions", {})]:
            for lang in target_langs:
                formats = source.get(lang, [])
                if not formats:
                    continue
                sub_url = next(
                    (f["url"] for f in formats if f.get("ext") == "json3"), None
                )
                if not sub_url:
                    sub_url = formats[0].get("url")
                if sub_url:
                    result = _parse_json3(sub_url, video_id)
                    result["video_language"] = video_lang or target_lang
                    return result

        all_sub_langs = set(info.get("subtitles", {}).keys()) | set(
            info.get("automatic_captions", {}).keys()
        )
        if all_sub_langs and not any(l.startswith(target_lang) for l in all_sub_langs):
            return {
                "status": "no_english",
                "video_language": video_lang or "unknown",
                "segments": [],
                "text": "",
            }

        return {
            "status": "disabled",
            "video_language": video_lang or None,
            "segments": [],
            "text": "",
        }

    except Exception as e:
        logging.warning(f"Could not fetch transcript for {video_id}: {e}")
        return {"status": "error", "video_language": None, "segments": [], "text": ""}


def build_queries(car_label: str) -> list[str]:
    """Generate broad, model-level search queries from templates."""
    return [t.format(car=car_label) for t in _QUERY_TEMPLATES]


def _pretty_engine_code(code: str) -> str:
    """'1.4_TSI' -> '1.4 TSI'. Leaves non-displacement codes (e.g. 'manual') alone."""
    return str(code or "").replace("_", " ").strip()


def build_queries_scaffold(
    car_label: str, scaffold: dict | None, target_lang: str = "en"
) -> list[str]:
    """Base queries + one per-engine set per scaffold displacement.

    agents.md §2-safe: per-engine queries are {model} + {displacement} +
    {generic problem phrase}. No failure vocabulary is added — just the
    engine taxonomy already on disk, which balances corpus coverage across
    petrol/diesel and high/low displacement instead of letting YouTube's
    ranker concentrate on the loudest trim.
    """
    base = build_queries(car_label)
    if not scaffold:
        return base

    engine_tpls = (
        _PER_ENGINE_TEMPLATES_TR if target_lang == "tr" else _PER_ENGINE_TEMPLATES_EN
    )
    extras: list[str] = []
    seen_engines: set[str] = set()
    for fam in scaffold.get("engine_families") or []:
        for d in fam.get("displacements") or []:
            code = d.get("code") if isinstance(d, dict) else d
            # Use search_alias terms when available — they use real-world names
            # (e.g. "1.2 16V") instead of internal codes ("1.2 NA") that nobody
            # searches for on YouTube.
            aliases = (d.get("search_alias") or []) if isinstance(d, dict) else []
            search_terms = aliases if aliases else [_pretty_engine_code(code)]
            for eng in search_terms:
                if not eng or eng in seen_engines:
                    continue
                seen_engines.add(eng)
                for tpl in engine_tpls:
                    extras.append(tpl.format(car=car_label, engine=eng))

    seen: set[str] = set()
    out: list[str] = []
    for q in base + extras:
        if q and q not in seen:
            seen.add(q)
            out.append(q)
    return out


# Entity-level query templates — engine family/code or transmission code as
# the primary search term, no model name required. This lets a "K9K" query
# surface Megane/Duster/Kangoo content that carries identical engine fault
# evidence to the Clio Mk4. agents.md §2-safe: still generic problem phrases.
_ENTITY_QUERY_TEMPLATES_EN = [
    "{entity} problems",
    "{entity} issues",
    "{entity} common problems",
    "{entity} known faults",
    "{entity} reliability issues",
    "{entity} long term reliability",
    "{entity} owner experience",
    "{entity} buyers guide",
]
_ENTITY_QUERY_TEMPLATES_TR = [
    "{entity} sorunları",
    "{entity} kronik sorunları",
    "{entity} arızaları",
    "{entity} sorunlar",
    "{entity} güvenilirlik",
    "{entity} kullanıcı deneyimi",
    "{entity} alınır mı",
]


def _scaffold_entities(scaffold: dict) -> list[str]:
    """All search-worthy tokens from scaffold: family codes, displacement aliases,
    transmission codes. Internal codes like '1.2_NA' are skipped in favour of
    search_alias when available."""
    seen: set[str] = set()
    out: list[str] = []

    def _add(tok: str) -> None:
        tok = tok.strip()
        if tok and tok not in seen:
            seen.add(tok)
            out.append(tok)

    for fam in scaffold.get("engine_families") or []:
        _add(fam.get("code", ""))
        for d in fam.get("displacements") or []:
            aliases = (d.get("search_alias") or []) if isinstance(d, dict) else []
            if aliases:
                for a in aliases:
                    _add(a)
            else:
                code = d.get("code") if isinstance(d, dict) else d
                _add(_pretty_engine_code(code))

    for t in scaffold.get("transmissions") or []:
        code = t.get("code", "")
        if code and code not in {"manual", "automatic", "EDC", "DSG"}:
            _add(code)

    return out


def build_entity_queries(
    scaffold: dict,
    target_lang: str = "en",
    entity_terms: list[str] | None = None,
) -> list[tuple[str, str]]:
    """Return (entity, query) pairs for every scaffold entity × query template."""
    tpls = (
        _ENTITY_QUERY_TEMPLATES_TR if target_lang == "tr"
        else _ENTITY_QUERY_TEMPLATES_EN
    )
    if entity_terms:
        seen_entities: set[str] = set()
        entities: list[str] = []
        for raw in entity_terms:
            entity = str(raw or "").strip()
            if not entity:
                continue
            key = entity.lower()
            if key in seen_entities:
                continue
            seen_entities.add(key)
            entities.append(entity)
    else:
        entities = _scaffold_entities(scaffold)
    seen_q: set[str] = set()
    out: list[tuple[str, str]] = []
    for entity in entities:
        for tpl in tpls:
            q = tpl.format(entity=entity)
            if q not in seen_q:
                seen_q.add(q)
                out.append((entity, q))
    return out


def scrape_entity_videos(
    slug: str,
    max_per_entity: int = 30,
    candidates_per_query: int = 30,
    min_view_count: int | None = 5_000,
    target_lang: str = "en",
    scaffold_slug: str | None = None,
    entity_terms: list[str] | None = None,
    cookies_file: str | None = None,
    request_delay: float = 2.0,
    search_workers: int = 1,
    transcript_workers: int = 1,
    out_dir: Path | None = None,
) -> Path:
    """Scrape per-entity (engine family / displacement / transmission) videos.

    Differs from model-level scraping:
    - Queries are "{entity} common problems" with no car model prefix.
    - Cross-brand model title requirement is dropped — a K9K failure video
      about a Megane is valid evidence for a Clio Mk4 K9K buyer.
    - Lower default view floor (niche technical content has fewer views).
    - Deduplicates against nothing; caller merges with existing raw file.
    """
    global _QUERY_TEMPLATES, _MECHANIC_SIGNALS, _LIST_FORMAT_SIGNALS
    global _HYPE_SIGNALS, _FAULT_OR_OWNERSHIP_SIGNALS

    if target_lang == "tr":
        _QUERY_TEMPLATES = _QUERY_TEMPLATES_TR
        _MECHANIC_SIGNALS = _MECHANIC_SIGNALS_TR
        _LIST_FORMAT_SIGNALS = _LIST_FORMAT_SIGNALS_TR
        _HYPE_SIGNALS = _HYPE_SIGNALS_TR
        _FAULT_OR_OWNERSHIP_SIGNALS = _FAULT_OR_OWNERSHIP_SIGNALS_TR
    else:
        _QUERY_TEMPLATES = _QUERY_TEMPLATES_EN
        _MECHANIC_SIGNALS = _MECHANIC_SIGNALS_EN
        _LIST_FORMAT_SIGNALS = _LIST_FORMAT_SIGNALS_EN
        _HYPE_SIGNALS = _HYPE_SIGNALS_EN
        _FAULT_OR_OWNERSHIP_SIGNALS = _FAULT_OR_OWNERSHIP_SIGNALS_EN

    scaffold_key = scaffold_slug or slug
    try:
        scaffold = load_scaffold(scaffold_key)
    except Exception:
        scaffold = {}

    out_dir = out_dir or (ROOT / "data" / "raw" / "videos")
    out_dir.mkdir(parents=True, exist_ok=True)
    suffix = "tr" if target_lang == "tr" else "en"
    out_path = out_dir / f"{slug}_entities_{suffix}_raw.json"

    entity_queries = build_entity_queries(scaffold, target_lang, entity_terms=entity_terms)
    logging.info(
        f"Entity scrape: {len(set(e for e,_ in entity_queries))} entities, "
        f"{len(entity_queries)} queries"
    )

    query_results: dict[str, list[dict]] = {}
    if search_workers <= 1:
        for _, query in entity_queries:
            logging.info(f"  Searching: '{query}'")
            query_results[query] = search_youtube_videos(query, max_results=candidates_per_query)
    else:
        max_search_workers = max(1, int(search_workers))
        logging.info(f"Running query search with workers={max_search_workers}")
        with ThreadPoolExecutor(max_workers=max_search_workers) as executor:
            futures = {
                executor.submit(search_youtube_videos, query, max_results=candidates_per_query): query
                for _, query in entity_queries
            }
            for future in as_completed(futures):
                query = futures[future]
                results = future.result()
                query_results[query] = results
                logging.info(f"  Search done: '{query}' ({len(results)} results)")

    # Collect per-entity, capped at max_per_entity unique videos each.
    all_candidates: dict[str, dict] = {}
    entity_video_counts: dict[str, int] = {}

    for entity, query in entity_queries:
        results = query_results.get(query, [])
        count = 0
        for video in results:
            vid_id = video["video_id"]
            if not vid_id:
                continue
            if vid_id in all_candidates:
                all_candidates[vid_id]["matched_queries"].append(query)
            else:
                if entity_video_counts.get(entity, 0) >= max_per_entity:
                    continue
                all_candidates[vid_id] = {**video, "matched_queries": [query]}
                entity_video_counts[entity] = entity_video_counts.get(entity, 0) + 1
                count += 1
        logging.info(f"    → {count} new candidates for '{entity}'")

    logging.info(f"Total unique candidates: {len(all_candidates)}")

    # Standard filtering — but skip cross-brand MODEL title filter.
    # Hype/viral filter still applies (drag race videos help no one).
    qualifying, rejected = filter_and_rank_candidates(
        all_candidates,
        min_seconds=120,
        min_views=min_view_count,
        enable_prefilter=True,
    )
    logging.info(f"After quality filter: {len(qualifying)} qualifying")

    def _build_output_video(video: dict, transcript: dict) -> dict:
        vid_id = video["video_id"]
        return {
            "video_id": vid_id,
            "url": f"https://www.youtube.com/watch?v={vid_id}",
            "title": video.get("title", ""),
            "channel": video.get("channel", ""),
            "matched_queries": video.get("matched_queries", []),
            "duration_raw": video.get("duration", ""),
            "duration_seconds": video["duration_seconds"],
            "view_count": video.get("view_count", ""),
            "view_count_raw": video.get("view_count_raw"),
            "selection_score": video.get("selection_score"),
            "is_niche_mechanic_candidate": video.get("is_niche_mechanic_candidate", False),
            "video_type_category": _get_video_type_category(video),
            "video_language": transcript.get("video_language"),
            "transcript_status": transcript["status"],
            "transcript_text": transcript["text"],
            "transcript_segments": transcript["segments"],
        }

    # Fetch transcripts
    videos_out: list[dict] = []
    if transcript_workers <= 1:
        logging.info(f"Fetching transcripts for {len(qualifying)} videos...")
        for i, video in enumerate(tqdm(qualifying, desc="Entity transcripts")):
            vid_id = video["video_id"]
            if i > 0 and request_delay > 0:
                time.sleep(request_delay)
            transcript = fetch_transcript_structured(
                vid_id, cookies_file=cookies_file, target_lang=target_lang
            )
            videos_out.append(_build_output_video(video, transcript))
    else:
        max_transcript_workers = max(1, int(transcript_workers))
        logging.info(
            f"Fetching transcripts for {len(qualifying)} videos with workers={max_transcript_workers}..."
        )

        def _fetch_one(idx: int, video: dict) -> tuple[int, dict]:
            if request_delay > 0:
                stagger = request_delay * (idx % max_transcript_workers) / max_transcript_workers
                if stagger > 0:
                    time.sleep(stagger)
            transcript = fetch_transcript_structured(
                video["video_id"], cookies_file=cookies_file, target_lang=target_lang
            )
            return idx, _build_output_video(video, transcript)

        ordered_results: dict[int, dict] = {}
        with ThreadPoolExecutor(max_workers=max_transcript_workers) as executor:
            futures = [
                executor.submit(_fetch_one, idx, video)
                for idx, video in enumerate(qualifying)
            ]
            for future in tqdm(as_completed(futures), total=len(futures), desc="Entity transcripts"):
                idx, payload = future.result()
                ordered_results[idx] = payload

        for idx in range(len(qualifying)):
            if idx in ordered_results:
                videos_out.append(ordered_results[idx])

    total_ok = sum(1 for v in videos_out if v["transcript_status"] == "ok")
    output = {
        "meta": {
            "slug": slug,
            "mode": "entity",
            "target_lang": target_lang,
            "scraped_at": datetime.now(timezone.utc).isoformat(),
            "entity_queries": entity_queries,
            "total_videos": len(videos_out),
            "total_with_transcript": total_ok,
            "min_view_count": min_view_count,
        },
        "videos": videos_out,
    }
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    logging.info(
        f"Saved {len(videos_out)} videos ({total_ok} with transcripts) → {out_path}"
    )
    return out_path


def collect_videos(
    car_label: str,
    candidates_per_query: int = 30,
    queries: list[str] | None = None,
) -> dict[str, dict]:
    """
    Search YouTube with broad model-level queries and deduplicate results.

    Returns dict[video_id -> video_dict]. Each video tracks which queries
    surfaced it (for provenance, not for topic assignment).
    """
    if queries is None:
        queries = build_queries(car_label)
    candidates: dict[str, dict] = {}

    for query in queries:
        results = search_youtube_videos(query, max_results=candidates_per_query)
        for video in results:
            vid_id = video["video_id"]
            if not vid_id:
                continue
            if vid_id in candidates:
                candidates[vid_id]["matched_queries"].append(query)
            else:
                candidates[vid_id] = {**video, "matched_queries": [query]}

    logging.info(
        f"Collected {len(candidates)} unique candidates from {len(queries)} queries"
    )
    return candidates


def _coerce_view_count(value: Any) -> int | None:
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        digits = re.sub(r"\D", "", value)
        if digits:
            return int(digits)
    return None


def _is_mechanic_niche(video: dict) -> bool:
    title = str(video.get("title", ""))
    channel = str(video.get("channel", ""))
    blob = f"{title} {channel}".lower()
    return any(signal in blob for signal in _MECHANIC_SIGNALS)


def _view_count_score(view_count: int | None) -> int:
    """Higher views = more credible signal (engagement, reach, corroboration)."""
    if view_count is None:
        return 0
    if view_count >= 3_000_000:
        return 4
    if view_count >= 1_000_000:
        return 3
    if view_count >= 500_000:
        return 2
    if view_count >= 200_000:
        return 1
    return 0


def filter_and_rank_candidates(
    candidates: dict[str, dict],
    min_seconds: int = 480,
    min_views: int | None = 20_000,
    enable_prefilter: bool = True,
) -> tuple[list[dict], list[dict]]:
    """
    Keep candidates above min_seconds and min_views, rank by credibility.

    Ranking prefers:
      1) mechanic/workshop-style content
      2) videos surfaced by multiple broad model-level queries
      3) higher view counts (views = engagement / corroboration signal)
      4) longer duration as a weak tie-breaker

    If min_views is set, videos below that threshold are dropped. If that
    would drop every candidate, the floor is relaxed and we fall back to
    ranking-only.
    """
    filtered: list[dict] = []
    for video in candidates.values():
        secs = video.get("duration_seconds")
        if secs is None or secs < min_seconds:
            continue
        view_count_raw = _coerce_view_count(
            video.get("view_count_raw", video.get("view_count"))
        )
        video["view_count_raw"] = view_count_raw
        filtered.append(video)

    if min_views is not None:
        gated = [
            v
            for v in filtered
            if v.get("view_count_raw") is None or v["view_count_raw"] >= min_views
        ]
        if gated:
            dropped = len(filtered) - len(gated)
            if dropped:
                logging.info(
                    f"Applied min view floor ({min_views:,}): dropped {dropped} low-view videos"
                )
            filtered = gated
        else:
            logging.warning(
                f"No videos above min view floor ({min_views:,}); falling back to ranking-only"
            )

    rejected: list[dict] = []
    if enable_prefilter:
        filtered, rejected = relevancy_prefilter(filtered)
        if rejected:
            reasons: dict[str, int] = {}
            for r in rejected:
                reasons[r.get("prefilter_reason", "unknown")] = (
                    reasons.get(r.get("prefilter_reason", "unknown"), 0) + 1
                )
            reason_str = ", ".join(f"{k}={v}" for k, v in sorted(reasons.items()))
            logging.info(
                f"Pre-filter rejected {len(rejected)}/{len(filtered) + len(rejected)} "
                f"candidates ({reason_str})"
            )

    for video in filtered:
        query_hits = len(video.get("matched_queries", []))
        mechanic_bonus = 4 if _is_mechanic_niche(video) else 0
        views_bonus = _view_count_score(video.get("view_count_raw"))
        video["selection_score"] = (query_hits * 2) + mechanic_bonus + views_bonus
        video["is_niche_mechanic_candidate"] = mechanic_bonus > 0

    filtered.sort(
        key=lambda v: (
            int(v.get("selection_score", 0)),
            len(v.get("matched_queries", [])),
            int(v["view_count_raw"]) if v.get("view_count_raw") is not None else 0,
            int(v.get("duration_seconds") or 0),
        ),
        reverse=True,
    )
    return filtered, rejected


def scrape_car_issues(
    car_label: str,
    slug: str | None = None,
    max_videos: int = 30,
    min_duration_seconds: int = 120,
    candidates_per_query: int = 30,
    min_view_count: int | None = 20_000,
    enable_prefilter: bool = True,
    out_dir: Path | None = None,
    cookies_file: str | None = None,
    request_delay: float = 2.0,
    target_lang: str = "en",
    scaffold_slug: str | None = None,
) -> Path:
    """
    Full pipeline for one car model:
      1. collect_videos → broad model-level search, deduplicated
      2. filter_and_rank_candidates → prioritize niche mechanic videos,
         de-prioritize mainstream high-view videos
      3. fetch_transcript_structured for selected videos
      4. Write structured JSON output
    """
    global _QUERY_TEMPLATES, _MECHANIC_SIGNALS, _LIST_FORMAT_SIGNALS
    global _HYPE_SIGNALS, _FAULT_OR_OWNERSHIP_SIGNALS

    if target_lang == "tr":
        _QUERY_TEMPLATES = _QUERY_TEMPLATES_TR
        _MECHANIC_SIGNALS = _MECHANIC_SIGNALS_TR
        _LIST_FORMAT_SIGNALS = _LIST_FORMAT_SIGNALS_TR
        _HYPE_SIGNALS = _HYPE_SIGNALS_TR
        _FAULT_OR_OWNERSHIP_SIGNALS = _FAULT_OR_OWNERSHIP_SIGNALS_TR
    else:
        _QUERY_TEMPLATES = _QUERY_TEMPLATES_EN
        _MECHANIC_SIGNALS = _MECHANIC_SIGNALS_EN
        _LIST_FORMAT_SIGNALS = _LIST_FORMAT_SIGNALS_EN
        _HYPE_SIGNALS = _HYPE_SIGNALS_EN
        _FAULT_OR_OWNERSHIP_SIGNALS = _FAULT_OR_OWNERSHIP_SIGNALS_EN

    slug = slug or car_label.lower().replace(" ", "_")

    out_dir = out_dir or (ROOT / "data" / "raw" / "videos")
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{slug}_raw.json"

    scaffold_key = scaffold_slug or slug
    try:
        scaffold_early = load_scaffold(scaffold_key)
    except Exception:
        scaffold_early = {}
    queries_used = build_queries_scaffold(car_label, scaffold_early, target_lang=target_lang)
    logging.info(
        f"Built {len(queries_used)} queries "
        f"({len(build_queries(car_label))} base + {len(queries_used) - len(build_queries(car_label))} per-engine)"
    )

    logging.info(f"Collecting candidates for '{car_label}'...")
    candidates = collect_videos(car_label, candidates_per_query, queries=queries_used)

    qualifying, rejected = filter_and_rank_candidates(
        candidates,
        min_duration_seconds,
        min_views=min_view_count,
        enable_prefilter=enable_prefilter,
    )

    # Scaffold-driven performance-trim balancing. No-op when the scaffold does
    # not declare a ``performance_trims`` block, so this generalises to any
    # model without model-specific scraper logic.
    try:
        scaffold = load_scaffold(scaffold_key)
    except Exception as e:
        logging.info(f"No scaffold loaded for '{scaffold_key}' ({e}); skipping trim balancing")
        scaffold = {}

    # Cross-brand title filter — drops foreign-OEM videos that leaked through
    # YouTube's search ranking for the target query.
    qualifying, cross_brand_rejected = cross_brand_title_filter(qualifying, scaffold)
    if cross_brand_rejected:
        reasons: dict[str, int] = {}
        for r in cross_brand_rejected:
            reasons[r.get("prefilter_reason", "unknown")] = (
                reasons.get(r.get("prefilter_reason", "unknown"), 0) + 1
            )
        logging.info(
            f"Cross-brand title filter rejected {len(cross_brand_rejected)} videos "
            f"({', '.join(f'{k}={v}' for k, v in sorted(reasons.items()))})"
        )
        rejected.extend(cross_brand_rejected)

    qualifying = downsample_performance_videos(qualifying, scaffold)

    selected = qualifying[:max_videos]

    if rejected:
        rejected_path = out_dir / f"{slug}_rejected.json"
        with open(rejected_path, "w", encoding="utf-8") as f:
            json.dump(
                [
                    {
                        "video_id": r.get("video_id"),
                        "title": r.get("title", ""),
                        "channel": r.get("channel", ""),
                        "view_count_raw": r.get("view_count_raw"),
                        "duration_seconds": r.get("duration_seconds"),
                        "prefilter_reason": r.get("prefilter_reason"),
                        "matched_queries": r.get("matched_queries", []),
                    }
                    for r in rejected
                ],
                f,
                ensure_ascii=False,
                indent=2,
            )
        logging.info(f"Wrote {len(rejected)} rejected candidates → {rejected_path}")
    logging.info(
        f"Selected {len(selected)} videos (from {len(qualifying)} qualifying, "
        f"{len(candidates)} total candidates)"
    )

    logging.info(f"Fetching transcripts for {len(selected)} videos...")
    videos_out = []
    for i, video in enumerate(tqdm(selected, desc="Fetching transcripts")):
        vid_id = video["video_id"]
        if i > 0 and request_delay > 0:
            time.sleep(request_delay)
        transcript = fetch_transcript_structured(
            vid_id, cookies_file=cookies_file, target_lang=target_lang
        )
        videos_out.append(
            {
                "video_id": vid_id,
                "url": f"https://www.youtube.com/watch?v={vid_id}",
                "title": video.get("title", ""),
                "channel": video.get("channel", ""),
                "matched_queries": video.get("matched_queries", []),
                "duration_raw": video.get("duration", ""),
                "duration_seconds": video["duration_seconds"],
                "view_count": video.get("view_count", ""),
                "view_count_raw": video.get("view_count_raw"),
                "selection_score": video.get("selection_score"),
                "is_niche_mechanic_candidate": video.get(
                    "is_niche_mechanic_candidate", False
                ),
                "video_type_category": _get_video_type_category(video),
                "video_language": transcript.get("video_language"),
                "transcript_status": transcript["status"],
                "transcript_text": transcript["text"],
                "transcript_segments": transcript["segments"],
            }
        )

    total_ok = sum(1 for v in videos_out if v["transcript_status"] == "ok")
    skipped_lang = [v for v in videos_out if v["transcript_status"] == "no_english"]
    if skipped_lang:
        logging.info(
            f"Skipped {len(skipped_lang)} non-English videos: "
            + ", ".join(
                f"{v['title'][:40]} ({v['video_language']})" for v in skipped_lang
            )
        )

    output = {
        "meta": {
            "car_model": car_label,
            "slug": slug,
            "scraped_at": datetime.now(timezone.utc).isoformat(),
            "queries": queries_used,
            "total_videos": len(videos_out),
            "total_with_transcript": total_ok,
            "duration_filter_seconds": min_duration_seconds,
            "min_view_count": min_view_count,
            "prefilter_enabled": enable_prefilter,
            "rejected_candidates": len(rejected),
            "selection_strategy": "mechanic_niche_plus_low_view_count_plus_relevancy_prefilter",
        },
        "videos": videos_out,
    }

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    logging.info(
        f"Saved {len(videos_out)} videos ({total_ok} with transcripts) → {out_path}"
    )
    return out_path


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Scrape YouTube transcripts for car issue discovery (broad model-level search)"
    )
    parser.add_argument(
        "--car",
        required=True,
        help='Car model label, e.g. "VW Golf MK7", "Renault Clio MK4"',
    )
    parser.add_argument(
        "--slug",
        default=None,
        help="Output slug (default: derived from --car). E.g. vw_golf_mk7",
    )
    parser.add_argument(
        "--max-videos",
        type=int,
        default=30,
        help="Max videos to fetch transcripts for (default: 30)",
    )
    parser.add_argument(
        "--min-duration",
        type=int,
        default=120,
        help="Min duration in seconds (default: 120)",
    )
    parser.add_argument("--candidates-per-query", type=int, default=30)
    parser.add_argument(
        "--min-views",
        type=int,
        default=80_000,
        help=(
            "Minimum view count to qualify (default: 80000). Views are treated "
            "as a credibility / engagement signal. If no candidates pass the "
            "floor, fallback uses soft ranking."
        ),
    )
    parser.add_argument(
        "--disable-prefilter",
        action="store_true",
        help="Disable the relevancy pre-filter (viral list-format / hype rejection).",
    )
    parser.add_argument(
        "--cookies-file",
        default=None,
        help="Path to Netscape cookies.txt — use if YouTube blocks transcript requests.",
    )
    parser.add_argument("--request-delay", type=float, default=2.0)
    parser.add_argument(
        "--lang",
        default="en",
        help="ISO 639-1 language prefix to require (default: en).",
    )
    parser.add_argument(
        "--scaffold-slug",
        default=None,
        help=(
            "Override the slug used to look up the scaffold YAML. Useful when "
            "scraping with language-suffixed output slugs (e.g. --slug "
            "vw_golf_mk7_en --scaffold-slug vw_golf_mk7)."
        ),
    )
    parser.add_argument(
        "--mode",
        default="model",
        choices=["model", "entities"],
        help=(
            "'model' (default): broad model-level queries. "
            "'entities': per-engine/transmission queries without model name prefix."
        ),
    )
    parser.add_argument(
        "--max-per-entity",
        type=int,
        default=30,
        help="Max videos per scaffold entity in --mode entities (default: 30).",
    )
    parser.add_argument(
        "--search-workers",
        type=int,
        default=1,
        help="Concurrent query-search workers in --mode entities (default: 1).",
    )
    parser.add_argument(
        "--transcript-workers",
        type=int,
        default=1,
        help="Concurrent transcript-fetch workers in --mode entities (default: 1).",
    )
    args = parser.parse_args()

    if args.mode == "entities":
        scrape_entity_videos(
            slug=args.slug or args.car.lower().replace(" ", "_"),
            max_per_entity=args.max_per_entity,
            candidates_per_query=args.candidates_per_query,
            min_view_count=args.min_views,
            target_lang=args.lang,
            scaffold_slug=args.scaffold_slug,
            cookies_file=args.cookies_file,
            request_delay=args.request_delay,
            search_workers=args.search_workers,
            transcript_workers=args.transcript_workers,
        )
        return

    scrape_car_issues(
        car_label=args.car,
        slug=args.slug,
        max_videos=args.max_videos,
        min_duration_seconds=args.min_duration,
        candidates_per_query=args.candidates_per_query,
        min_view_count=args.min_views,
        enable_prefilter=not args.disable_prefilter,
        cookies_file=args.cookies_file,
        request_delay=args.request_delay,
        target_lang=args.lang,
        scaffold_slug=args.scaffold_slug,
    )


if __name__ == "__main__":
    main()
