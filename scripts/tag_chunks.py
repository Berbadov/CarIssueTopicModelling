"""Enrich transcript chunks with neutral car-attribute tags.

Reads  data/processed/chunks/{slug}_chunks.jsonl
       data/scaffolds/{slug}.yaml
Writes data/processed/chunks/{slug}_chunks_tagged.jsonl

Tags added per chunk (descriptors the chunk actually mentions — NOT failure
predictions, per agents.md §2):
    engines       e.g. ["1.4_TSI", "2.0_TDI"]
    transmissions e.g. ["DQ200", "manual"]
    trims         e.g. ["gti"]
    drive_types   e.g. ["belt"]         (derived from matched engines)
    fuel_types    e.g. ["petrol"]       (derived from matched engines)
    engine_codes  e.g. ["EA211"]        (family codes mentioned directly)
    years         e.g. [2015, 2017]     (4-digit years inside corpus window)
    mileages_km   e.g. [150000, 200000] (km numbers the speaker mentions)

Matching scope: chunk text + video title (many videos scope by trim in title).
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
CHUNKS_DIR = ROOT / "data" / "processed" / "chunks"
SCAFFOLD_DIR = ROOT / "data" / "scaffolds"


# ─────────────────────────── regex helpers ──────────────────────────────

def _displacement_pattern(disp_code: str) -> re.Pattern[str]:
    """Turn "1.4_TSI" into a tolerant regex.

    Matches: "1.4 tsi", "1.4tsi", "1,4 tsi", "1.4-litre tsi", "1.4 l tsi".
    """
    num, suffix = disp_code.split("_", 1)
    num_re = re.escape(num).replace(r"\.", "[.,]")
    liter = r"(?:[\s-]*(?:l|litre|liter|liters|litres))?"
    gap = r"[\s-]*"
    return re.compile(
        rf"(?<![\d.,]){num_re}{liter}{gap}{re.escape(suffix)}(?![A-Za-z])",
        re.IGNORECASE,
    )


def _word_pattern(token: str) -> re.Pattern[str]:
    return re.compile(rf"(?<![A-Za-z0-9]){re.escape(token)}(?![A-Za-z0-9])", re.IGNORECASE)


def _alias_pattern(alias: str) -> re.Pattern[str]:
    """Tolerant matcher for search aliases such as '1.5 dCi' or '900 TCE'."""
    a = alias.strip()
    if not a:
        return _word_pattern(alias)
    escaped = re.escape(a)
    escaped = escaped.replace(r"\ ", r"[\s-]*")
    escaped = escaped.replace(r"\.", r"[.,]")
    return re.compile(rf"(?<![A-Za-z0-9]){escaped}(?![A-Za-z0-9])", re.IGNORECASE)


YEAR_RE = re.compile(r"\b(19[89]\d|20[0-3]\d)\b")

# Neutral generation/family tokens — NOT failure terms. Used to flag chunks
# that reference an older-generation car while discussing an engine.
CROSS_GEN_TOKENS = [
    # Generation markers — any Golf Mk1..Mk8 / Clio Mk1..Mk5 not matching the
    # current scaffold generation is potentially off-scope.
    r"\bMk[\s-]?([1-8])\b",
    r"\bmark[\s-]?([1-8])\b",
    # Phase markers (Renault) are same-generation sub-variants — NOT flagged.
    # Phrasing:
    r"\bprevious generation\b",
    r"\bearlier (?:golf|clio)\b",
    r"\bold (?:golf|clio)\b",
    r"\bold(?:er)? tsi\b",
    r"\bearlier tsi\b",
    r"\boriginal tsi\b",
    r"\bfirst[-\s]generation tsi\b",
    # Older VW engine families that are NOT EA211/EA288/EA888 (neutral codes):
    r"\bEA111\b",
    r"\bEA113\b",
    r"\bEA888[\s-]?gen[\s-]?[12]\b",  # early EA888 gen1/2 before Mk7's gen3
]
CROSS_GEN_RES = [re.compile(p, re.IGNORECASE) for p in CROSS_GEN_TOKENS]

# Phrasing like "pre-2013" / "before 2013" — threshold resolved from scaffold.
PRE_YEAR_RE = re.compile(
    r"\b(?:pre[-\s]?|before[-\s]|prior to )(\d{4})\b", re.IGNORECASE
)

# Mileage: "200,000 km", "200000 km", "200.000 km", "200k km", "150k miles"
MILEAGE_RE = re.compile(
    r"\b(\d{2,3}(?:[.,\s]\d{3})+|\d{2,3}k|\d{4,7})\s*(km|kilomet(?:re|er)s?|miles?|mi)\b",
    re.IGNORECASE,
)

# Timing-drive phrases. Detects when a speaker discusses the wrong timing
# mechanism for the engine tagged in the chunk (e.g. "chain tensioner" while
# talking about a belt-drive EA211 1.4 TSI — a clear pre-facelift EA111 leak).
CHAIN_PHRASE_RE = re.compile(
    r"\b(?:timing|cam(?:shaft)?)[\s-]+chain|\bchain[\s-]+tensioner|\bchain[\s-]+stretch|\bcam[\s-]+chain\b",
    re.IGNORECASE,
)
BELT_PHRASE_RE = re.compile(
    r"\b(?:timing|cam(?:shaft)?)[\s-]+belt|\bcambelt\b|\bbelt[\s-]+replacement\s+interval\b",
    re.IGNORECASE,
)


# ─────────────────────────── scaffold loading ───────────────────────────

def load_scaffold(slug: str) -> dict:
    path = SCAFFOLD_DIR / f"{slug}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"Scaffold missing: {path}")
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def build_matchers(scaffold: dict) -> dict:
    """Precompile all regex matchers from the scaffold."""
    engine_matchers: list[tuple[str, re.Pattern, str, str, str]] = []
    # (displacement_code, pattern, family_code, fuel_type, timing_drive)
    family_matchers: list[tuple[str, re.Pattern]] = []
    for fam in scaffold.get("engine_families", []):
        fam_code = fam["code"]
        fuel = fam.get("fuel_type", "unknown")
        drive = fam.get("timing_drive", "unknown")
        family_matchers.append((fam_code, _word_pattern(fam_code)))
        for disp in fam.get("displacements", []):
            if isinstance(disp, dict):
                code = disp["code"]
                aliases = disp.get("search_alias") or []
            else:
                code = str(disp)
                aliases = []

            engine_matchers.append((code, _displacement_pattern(code), fam_code, fuel, drive))
            for alias in aliases:
                alias_text = str(alias or "").strip()
                if not alias_text:
                    continue
                engine_matchers.append((code, _alias_pattern(alias_text), fam_code, fuel, drive))

    trans_matchers: list[tuple[str, re.Pattern]] = []
    generic_trans = {
        "DSG": re.compile(r"\bDSG\b", re.IGNORECASE),
        "manual": re.compile(r"\b(manual|stick[\s-]shift)\b", re.IGNORECASE),
        "automatic": re.compile(r"\bautomatic\b", re.IGNORECASE),
        "EDC": re.compile(r"\bEDC\b", re.IGNORECASE),
    }
    for tcode in generic_trans:
        trans_matchers.append((tcode, generic_trans[tcode]))
    for t in scaffold.get("transmissions", []):
        tcode = t["code"]
        if tcode in {"DSG", "manual", "automatic", "EDC"}:
            continue
        trans_matchers.append((tcode, _word_pattern(tcode)))

    trim_tokens = (scaffold.get("performance_trims") or {}).get("tokens") or []
    trim_matchers: list[tuple[str, re.Pattern]] = []
    for tok in trim_tokens:
        label = tok.split()[-1].lower() if " " in tok else tok.lower()
        pat = re.compile(rf"(?<![A-Za-z0-9]){re.escape(tok)}(?![A-Za-z0-9])", re.IGNORECASE)
        trim_matchers.append((label, pat))

    generation = str(scaffold.get("meta", {}).get("generation") or "").upper().strip()
    # e.g. "MK7" -> digit "7"
    gen_digit = ""
    m = re.search(r"(\d)", generation)
    if m:
        gen_digit = m.group(1)

    return {
        "engines": engine_matchers,
        "families": family_matchers,
        "transmissions": trans_matchers,
        "trims": trim_matchers,
        "corpus_years": tuple(scaffold.get("meta", {}).get("corpus_years") or (1980, 2040)),
        "generation": generation,
        "gen_digit": gen_digit,
    }


# ─────────────────────────── tagging ────────────────────────────────────

def _normalize_km(num_text: str, unit: str) -> int:
    unit = unit.lower()
    s = num_text.lower().replace(" ", "")
    if s.endswith("k"):
        val = float(s[:-1]) * 1000
    else:
        val = float(s.replace(",", "").replace(".", ""))
        # 200.000 vs 200000 — both look like 200000 after stripping; OK.
    if unit.startswith("mi"):
        val *= 1.60934
    return int(round(val))


def tag_chunk(chunk: dict, matchers: dict) -> dict:
    haystack = f"{chunk.get('title','')}\n{chunk.get('text','')}"

    engines: list[str] = []
    fuels: set[str] = set()
    drives: set[str] = set()
    inferred_family: set[str] = set()
    for code, pat, fam, fuel, drive in matchers["engines"]:
        if pat.search(haystack):
            if code not in engines:
                engines.append(code)
            inferred_family.add(fam)
            fuels.add(fuel)
            drives.add(drive)

    families: list[str] = []
    for fam_code, pat in matchers["families"]:
        if pat.search(haystack):
            families.append(fam_code)
    for fc in inferred_family:
        if fc not in families:
            families.append(fc)

    transmissions: list[str] = []
    for code, pat in matchers["transmissions"]:
        if pat.search(haystack):
            transmissions.append(code)

    trims: list[str] = []
    for label, pat in matchers["trims"]:
        if pat.search(haystack) and label not in trims:
            trims.append(label)

    y_lo, y_hi = matchers["corpus_years"]
    years = sorted({int(y) for y in YEAR_RE.findall(haystack) if y_lo <= int(y) <= y_hi})

    mileages: list[int] = []
    for m in MILEAGE_RE.finditer(haystack):
        try:
            mileages.append(_normalize_km(m.group(1), m.group(2)))
        except Exception:
            pass
    mileages = sorted(set(mileages))

    # Cross-generation detection: only meaningful if this chunk also has an
    # engine mention. Explicit generation/family tokens (Mk6, EA111, "pre-2013")
    # are checked in the full haystack; bare out-of-corpus year numbers are
    # checked in CHUNK TEXT ONLY to avoid title-production-window false positives
    # (e.g. title "VW Golf MK7 Issues 2012-2020" should not flag every chunk).
    cross_gen_markers: list[str] = []
    if engines or families:
        gen_digit = matchers.get("gen_digit", "")
        for pat in CROSS_GEN_RES:
            for m in pat.finditer(haystack):
                if m.groups() and gen_digit and m.group(1) == gen_digit:
                    continue
                cross_gen_markers.append(m.group(0).strip())
        y_lo, _ = matchers["corpus_years"]
        for m in PRE_YEAR_RE.finditer(haystack):
            try:
                threshold = int(m.group(1))
                if threshold <= y_lo:
                    cross_gen_markers.append(m.group(0).strip())
            except ValueError:
                pass
        # Bare out-of-corpus years: text only, and only when near an engine mention
        # (within ~80 chars) to keep the signal specific.
        text_only = chunk.get("text", "")
        engine_spans: list[tuple[int, int]] = []
        for _code, pat, *_ in matchers["engines"]:
            for m in pat.finditer(text_only):
                engine_spans.append((m.start(), m.end()))
        for m in YEAR_RE.finditer(text_only):
            y = int(m.group(0))
            if y >= y_lo:
                continue
            pos = m.start()
            if any(abs(pos - s) <= 80 or abs(pos - e) <= 80 for s, e in engine_spans):
                cross_gen_markers.append(m.group(0))

        # Timing-drive mismatch: all tagged engines share one drive type, but
        # the chunk discusses the opposite. Deterministic anachronism signal —
        # a Mk7 1.4 TSI (belt) that "stretches the timing chain" is describing
        # the pre-Mk7 EA111 variant.
        if drives and len(drives) == 1:
            drive = next(iter(drives))
            if drive == "belt" and CHAIN_PHRASE_RE.search(text_only):
                cross_gen_markers.append(f"drive_mismatch:{drive}_engine_chain_phrase")
            elif drive == "chain" and BELT_PHRASE_RE.search(text_only):
                cross_gen_markers.append(f"drive_mismatch:{drive}_engine_belt_phrase")

    tagged = dict(chunk)
    tagged["tags"] = {
        "engines": engines,
        "engine_families": families,
        "fuel_types": sorted(fuels),
        "drive_types": sorted(drives),
        "transmissions": transmissions,
        "trims": trims,
        "years": years,
        "mileages_km": mileages,
        "cross_generation_risk": bool(cross_gen_markers),
        "cross_generation_markers": sorted(set(cross_gen_markers)),
    }
    return tagged


# ─────────────────────────── driver ─────────────────────────────────────

def tag_slug(slug: str, scaffold_slug: str | None = None) -> Path:
    src = CHUNKS_DIR / f"{slug}_chunks.jsonl"
    if not src.exists():
        raise FileNotFoundError(f"Missing chunks: {src}")
    scaffold = load_scaffold(scaffold_slug or slug)
    matchers = build_matchers(scaffold)

    out = CHUNKS_DIR / f"{slug}_chunks_tagged.jsonl"
    n = 0
    stats = {
        "engine_hits": 0,
        "trans_hits": 0,
        "trim_hits": 0,
        "year_hits": 0,
        "km_hits": 0,
        "cross_gen_flagged": 0,
    }
    with src.open("r", encoding="utf-8") as fin, out.open("w", encoding="utf-8") as fout:
        for line in fin:
            if not line.strip():
                continue
            chunk = json.loads(line)
            tagged = tag_chunk(chunk, matchers)
            t = tagged["tags"]
            if t["engines"]:
                stats["engine_hits"] += 1
            if t["transmissions"]:
                stats["trans_hits"] += 1
            if t["trims"]:
                stats["trim_hits"] += 1
            if t["years"]:
                stats["year_hits"] += 1
            if t["mileages_km"]:
                stats["km_hits"] += 1
            if t.get("cross_generation_risk"):
                stats["cross_gen_flagged"] += 1
            fout.write(json.dumps(tagged, ensure_ascii=False) + "\n")
            n += 1

    print(f"[{slug}] tagged {n} chunks -> {out.relative_to(ROOT)}")
    print(
        f"[{slug}] coverage: engines={stats['engine_hits']}/{n} "
        f"trans={stats['trans_hits']}/{n} trims={stats['trim_hits']}/{n} "
        f"years={stats['year_hits']}/{n} km={stats['km_hits']}/{n} "
        f"cross_gen_flagged={stats['cross_gen_flagged']}/{n}"
    )
    return out


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--slug", required=True)
    p.add_argument("--scaffold-slug", default=None,
                   help="Override scaffold lookup (e.g. component_K9K -> renault_clio_mk4)")
    args = p.parse_args()
    tag_slug(args.slug, scaffold_slug=args.scaffold_slug)


if __name__ == "__main__":
    main()
