"""Parse a used-car listing description into a structured spec.

Shared matcher vocabulary with scripts/tag_chunks.py so the parsed spec keys
line up exactly with chunk tags (e.g. listing -> {"engines": ["1.4_TSI"]},
chunk -> tags.engines contains "1.4_TSI").

Example:
    python scripts/parse_listing.py --slug vw_golf_mk7 \
        --text "2017 golf 1.4tsi automatic 120000 km"
"""
from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass, field, asdict
from pathlib import Path

from tag_chunks import (
    build_matchers,
    load_scaffold,
    YEAR_RE,
    MILEAGE_RE,
    _normalize_km,
)

ROOT = Path(__file__).resolve().parents[1]


@dataclass
class ListingSpec:
    raw_text: str
    slug: str
    years: list[int] = field(default_factory=list)
    engines: list[str] = field(default_factory=list)
    engine_families: list[str] = field(default_factory=list)
    fuel_types: list[str] = field(default_factory=list)
    drive_types: list[str] = field(default_factory=list)
    transmissions: list[str] = field(default_factory=list)
    trims: list[str] = field(default_factory=list)
    mileage_km: int | None = None
    confidence: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


def parse_listing(text: str, slug: str) -> ListingSpec:
    scaffold = load_scaffold(slug)
    matchers = build_matchers(scaffold)
    haystack = text

    spec = ListingSpec(raw_text=text, slug=slug)

    # engines / families / fuel / drive
    fams: set[str] = set()
    fuels: set[str] = set()
    drives: set[str] = set()
    for code, pat, fam, fuel, drive in matchers["engines"]:
        if pat.search(haystack):
            spec.engines.append(code)
            fams.add(fam)
            fuels.add(fuel)
            drives.add(drive)
    for fam_code, pat in matchers["families"]:
        if pat.search(haystack):
            fams.add(fam_code)

    # CC-based fallback: when no engine matched by displacement code (e.g. listing
    # says "1.2 Icon" not "1.2 NA"), extract engine size in cc and match against
    # displacement_cc fields in the scaffold. Tolerance ±30 cc for rounding.
    if not spec.engines:
        CC_RE = re.compile(r"\b(\d{3,4})\s*(?:cc|cm[³3]|cm\^3)\b", re.IGNORECASE)
        for m in CC_RE.finditer(haystack):
            listing_cc = int(m.group(1))
            for fam in scaffold.get("engine_families", []):
                for d in fam.get("displacements", []):
                    scaffold_cc = d.get("displacement_cc") if isinstance(d, dict) else None
                    if scaffold_cc and abs(listing_cc - scaffold_cc) <= 30:
                        code = d["code"]
                        if code not in spec.engines:
                            spec.engines.append(code)
                            fams.add(fam["code"])
                            fuels.add(fam.get("fuel_type", "unknown"))
                            drives.add(fam.get("timing_drive", "unknown"))

    spec.engine_families = sorted(fams)
    spec.fuel_types = sorted(fuels)
    spec.drive_types = sorted(drives)

    # transmissions
    for code, pat in matchers["transmissions"]:
        if pat.search(haystack) and code not in spec.transmissions:
            spec.transmissions.append(code)
    # Listings often say "automatic" in Turkish/English — map to DSG family for Golf.
    # Same for EDC on Clio. We keep the raw token AND the derived code.
    if "automatic" in spec.transmissions or re.search(r"\botomatik\b", haystack, re.I):
        if "automatic" not in spec.transmissions:
            spec.transmissions.append("automatic")
        # Derive a DSG/EDC hint when the scaffold has one and engine narrows it.
        scaffold_trans = scaffold.get("transmissions", [])
        for t in scaffold_trans:
            tcode = t["code"]
            if tcode in {"manual"} or t.get("type", "").startswith("manual"):
                continue
            compat = set(t.get("compatible_displacements") or [])
            if not spec.engines or (compat & set(spec.engines)):
                if tcode not in spec.transmissions:
                    spec.transmissions.append(tcode)

    # trims
    for label, pat in matchers["trims"]:
        if pat.search(haystack) and label not in spec.trims:
            spec.trims.append(label)

    # years (clip to corpus window)
    y_lo, y_hi = matchers["corpus_years"]
    years = sorted({int(y) for y in YEAR_RE.findall(haystack) if y_lo <= int(y) <= y_hi})
    spec.years = years

    # mileage: pick the largest explicit km number — listings usually have one.
    kms: list[int] = []
    for m in MILEAGE_RE.finditer(haystack):
        try:
            kms.append(_normalize_km(m.group(1), m.group(2)))
        except Exception:
            pass
    # Labeled format: "KM: 79.000" / "Kilometre: 120000" / "Mileage: 45000"
    LABELED_RE = re.compile(
        r"\b(?:km|kilometer|kilometers|kilometre|kilometres|kilometraj|mileage)\s*[:=-]?\s*(\d{1,3}(?:[.,\s]\d{3})+|\d{4,7})\b",
        re.IGNORECASE,
    )
    for m in LABELED_RE.finditer(haystack):
        try:
            kms.append(_normalize_km(m.group(1), "km"))
        except Exception:
            pass
    if not kms:
        tr = re.search(r"\b(\d{2,3})\s*bin\s*km\b", haystack, re.I)
        if tr:
            kms.append(int(tr.group(1)) * 1000)
    if kms:
        spec.mileage_km = max(kms)

    # lightweight confidence scoring (purely informative)
    spec.confidence = {
        "has_year": bool(spec.years),
        "has_engine": bool(spec.engines),
        "has_transmission": bool(spec.transmissions),
        "has_mileage": spec.mileage_km is not None,
    }
    return spec


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--slug", required=True)
    p.add_argument("--text", required=True)
    args = p.parse_args()
    spec = parse_listing(args.text, args.slug)
    print(json.dumps(spec.to_dict(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
