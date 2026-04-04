#!/usr/bin/env python3
"""
cleaner_uk.py
──────────────
Filters and classifies messages from golfgtiforum.co.uk raw scrape.
Produces:
    data/processed/forums/cleaned_messages_uk.json  — kept threads (structured)
    data/processed/forums/rejected_messages_uk.json — rejected (for inspection)
    data/processed/forums/cleaned_messages_uk.csv   — flat CSV for R pipeline

Output CSV columns: thread_name, thread_url, engine_code, message, reason

Usage:
    python scrapers/cleaner_uk.py [--input ...] [--output ...] [--rejected ...]
"""

import argparse
import csv
import json
import re
import string
from pathlib import Path

# ── Mechanical keywords (English) ─────────────────────────────────────────────

MECHANICAL_KEYWORDS = [
    # Engine & oil
    "engine",
    "motor",
    "oil",
    "leak",
    "burning oil",
    "consumption",
    "piston",
    "cylinder",
    "head gasket",
    "gasket",
    "valve",
    "camshaft",
    "crankshaft",
    "sump",
    "compression",
    "blow-by",
    "blowby",
    "turbo",
    "turbocharger",
    "wastegate",
    "boost",
    "injector",
    "injection",
    "fuelling",
    "fuel",
    # Timing
    "timing belt",
    "timing chain",
    "cambelt",
    "cam belt",
    "tensioner",
    "sprocket",
    "chain rattle",
    "chain stretch",
    # Transmission / drivetrain
    "gearbox",
    "transmission",
    "dsg",
    "clutch",
    "flywheel",
    "dmf",
    "dual mass",
    "diff",
    "differential",
    "driveshaft",
    "cv joint",
    "gear",
    "shift",
    "shudder",
    "judder",
    # Cooling & fuel system
    "coolant",
    "overheating",
    "thermostat",
    "water pump",
    "radiator",
    "intercooler",
    "hose",
    "antifreeze",
    # Electrical
    "battery",
    "alternator",
    "starter",
    "ecu",
    "abs",
    "esp",
    "sensor",
    "lambda",
    "o2 sensor",
    "maf",
    "map sensor",
    "coilpack",
    "coil pack",
    "spark plug",
    "misfire",
    # Exhaust & emissions
    "dpf",
    "egr",
    "egr valve",
    "cat",
    "catalytic",
    "exhaust",
    "regen",
    "regeneration",
    "adblue",
    # Suspension & brakes
    "brakes",
    "brake",
    "pad",
    "disc",
    "rotor",
    "caliper",
    "shock",
    "absorber",
    "strut",
    "wishbone",
    "control arm",
    "steering",
    "rack",
    "power steering",
    "wheel bearing",
    "hub",
    "knuckle",
    # Fault / warning
    "fault",
    "warning light",
    "epc",
    "eml",
    "check engine",
    "limp mode",
    "limp home",
    "dtc",
    "fault code",
    "vag-com",
    "vcds",
    "error",
    "p0",
    "p1",
    "p2",
    "p3",  # OBD codes
    # Symptom words
    "noise",
    "rattle",
    "knock",
    "vibration",
    "judder",
    "squeal",
    "smoke",
    "smell",
    "burning",
    "rough idle",
    "stall",
    "hesitation",
    "flat spot",
    "surge",
    # Service / repair
    "service",
    "repair",
    "replace",
    "replaced",
    "dealer",
    "vw",
    "recall",
    "warranty",
    "labour",
    "garage",
]

# ── Noise phrases (English) ────────────────────────────────────────────────────

NOISE_PHRASES = [
    # Greetings
    "hi",
    "hello",
    "hey",
    "good morning",
    "good evening",
    # Farewells / thanks
    "thanks",
    "thank you",
    "cheers",
    "ta",
    "many thanks",
    "thanks in advance",
    "thanks for the help",
    # Acknowledgements
    "lol",
    "haha",
    "ha",
    "yep",
    "yup",
    "nope",
    "ok",
    "okay",
    "sure",
    "agreed",
    "noted",
    # Forum-only chatter
    "bump",
    "sub",
    "following",
    "subscribed",
    "watching",
    "same here",
    "me too",
    "+1",
    # Praise
    "great post",
    "nice one",
    "well done",
    "good shout",
]

SHORT_ACK_PATTERNS = [
    r"^(hi|hello|hey|cheers?|thanks?|thank you)[\s!.]*$",
    r"^(ok|okay|yep|yup|nope|lol|haha)[\s!.]*$",
    r"^bump[\s!.]*$",
    r"^\+1[\s!.]*$",
    r"^(following|subscribed?|watching)[\s!.]*$",
    r"^(same here|me too)[\s!.]*$",
]

# ── Cosmetic / non-mechanical patterns ────────────────────────────────────────

_COSMETIC_PATTERN = re.compile(
    r"\b("
    r"respray|resprayed|paintwork|bodywork|dent|scratch|scuff|"
    r"ppf|ceramic coat|detailing|polish|wax|alloy refurb|"
    r"bodyshop|panel|wing mirror cover|colour change"
    r")\b",
    re.IGNORECASE,
)

_INFOTAINMENT_PATTERN = re.compile(
    r"\b("
    r"carplay|android auto|bluetooth|sat nav|satnav|navigation|"
    r"dab radio|head unit|touchscreen|infotainment|discover pro|"
    r"rcd 330|rcd330|rns 315|rns315|mirror link"
    r")\b",
    re.IGNORECASE,
)

_MOT_PATTERNS = {
    "brakes": re.compile(
        r"\b(brake|brakes|pad|pads|disc|discs|caliper|handbrake|abs|brake fluid|braking)\b",
        re.I,
    ),
    "lights": re.compile(
        r"\b(headlight|headlights|taillight|taillights|indicator|indicators|brake light|fog light|number plate|daylight|bulb|headlamp)\b",
        re.I,
    ),
    "steering": re.compile(
        r"\b(steering|steering rack|power steering|ball joint|steering column|steering wheel)\b",
        re.I,
    ),
    "suspension": re.compile(
        r"\b(shock|shocks|absorber|spring|springs|wishbone|control arm|wheel bearing|bump stop|strut|damper)\b",
        re.I,
    ),
    "tyres": re.compile(
        r"\b(tyres|tire|tread|wheel|alloys|rims| tyre|alloy wheel)\b", re.I
    ),
    "exhaust_emissions": re.compile(
        r"\b(exhaust|dpf|cat|catalytic|emissions|co2|smoke|lambda sensor|egr|adblue|regen)\b",
        re.I,
    ),
    "body_structure": re.compile(
        r"\b(rust|corrosion|chassis|body panel|wing|bonnet|boot|fender|subframe|rot|corroded)\b",
        re.I,
    ),
    "windscreen": re.compile(
        r"\b(windscreen|windshield|wiper|washer|crack|glass|mirror|window)\b", re.I
    ),
    "seatbelts": re.compile(r"\b(seatbelt|belt|pre-tensioner|airbag)\b", re.I),
    "engine": re.compile(
        r"\b(engine|motor|oil|leak|burning|turbo|injector|compression|misfire|start|starting)\b",
        re.I,
    ),
    "transmission": re.compile(
        r"\b(gearbox|transmission|dsg|clutch|flywheel|dmf|gear|gears|shifting)\b", re.I
    ),
    "cooling": re.compile(
        r"\b(coolant|overheating|thermostat|water pump|radiator|fan|temperature|heating|heater)\b",
        re.I,
    ),
    "electrical": re.compile(
        r"\b(battery|alternator|ecu|sensor|lambda|maf|map|coilpack|spark plug|fuse|relay)\b",
        re.I,
    ),
}


def extract_mot_items(text: str) -> str:
    """Extract MOT-relevant categories from message text."""
    found = [cat for cat, pattern in _MOT_PATTERNS.items() if pattern.search(text)]
    return ",".join(found) if found else ""


_QUOTE_PREFIX = re.compile(
    r"^quote\s+from\s*:[^.!?\n]{0,80}",
    re.IGNORECASE,
)


def strip_quote_prefix(text: str) -> str:
    """Remove leading 'Quote from: X on DATE' header, return remainder."""
    return _QUOTE_PREFIX.sub("", text).strip()


_NOISE_DOMINATED = re.compile(
    r"\b("
    r"for sale|selling|sold|price drop|how much|what.s it worth|"
    r"pm sent|dm me|contact me|available|still available|"
    r"wanted|wtt|wtb"
    r")\b",
    re.IGNORECASE,
)

_CONTENT_SIGNALS = re.compile(
    r"\b("
    r"fault|warning|noise|rattle|leak|smoke|fail|broke|broken|"
    r"repair|service|replace|misfire|judder|hesit|limp|shudder|"
    r"burning|overheating|stall"
    r")\b",
    re.IGNORECASE,
)

# ── Miles / km detection (UK forum, primarily miles) ──────────────────────────

_MILEAGE_RE = re.compile(
    r"\b\d[\d,\.]*\s*(?:miles?|mls?|mi\b)"  # 50,000 miles / 50k mi
    r"|\b\d+\s*k\s*(?:miles?|mls?)?"  # 50k miles / 50k
    r"|\b\d[\d,\.]+\s*(?:km|kilometres?)"  # 80,000km (some members use km)
    r"|\bmileage\s*[:=]?\s*\d"  # mileage: 65000
    r"|\b\d{4,}\s*on\s*(?:the\s*)?clock"  # 65000 on the clock
    r"|\b(?:high|low)\s*mileage",
    re.IGNORECASE,
)

# ── Engine code extraction (MK-generation) ───────────────────────────────────
# Golf GTI UK: primarily MK5/6/7/8, engines 2.0 TSI (EA888), 1.4 TSI (EA211),
# also rare 1.8 TSI.

_ENGINE_PATTERNS = [
    (re.compile(r"\b(mk\s*8|golf\s*8|8th\s*gen)\b", re.IGNORECASE), "MK8"),
    (re.compile(r"\b(mk\s*7\.?5|7\.?5)\b", re.IGNORECASE), "MK7.5"),
    (re.compile(r"\b(mk\s*7|golf\s*7|7th\s*gen)\b", re.IGNORECASE), "MK7"),
    (re.compile(r"\b(mk\s*6|golf\s*6|6th\s*gen)\b", re.IGNORECASE), "MK6"),
    (re.compile(r"\b(mk\s*5|golf\s*5|5th\s*gen)\b", re.IGNORECASE), "MK5"),
    (re.compile(r"\bea888\b", re.IGNORECASE), "EA888"),
    (re.compile(r"\bea211\b", re.IGNORECASE), "EA211"),
    (re.compile(r"\b2\.0\s*tsi\b", re.IGNORECASE), "2.0_TSI"),
    (re.compile(r"\b1\.4\s*tsi\b", re.IGNORECASE), "1.4_TSI"),
    (re.compile(r"\b1\.8\s*tsi\b", re.IGNORECASE), "1.8_TSI"),
    (re.compile(r"\bcupra\b", re.IGNORECASE), "Cupra"),
    (re.compile(r"\br\s+line\b", re.IGNORECASE), "R_Line"),
    (re.compile(r"\bgolf\s*r\b", re.IGNORECASE), "Golf_R"),
]


def extract_engine_code(thread_name: str, messages: list[str]) -> str:
    combined = (thread_name + " " + " ".join(messages[:5])).lower()
    for pattern, code in _ENGINE_PATTERNS:
        if pattern.search(combined):
            return code
    return "unknown"


# ── Engine spec extraction (displacement + fuel type) ─────────────────────────
# Captures the actual powertrain: "2.0 TDI", "1.4 TSI", "1.5 TSI" etc.
# These are the common Golf displacement+fuel combos found in the corpus.

_ENGINE_SPEC_PATTERNS = [
    # displacement + fuel type — order: most specific first
    (re.compile(r"\b2\.0\s*tdi\b", re.IGNORECASE), "2.0_TDI"),
    (re.compile(r"\b2\.0\s*tsi\b", re.IGNORECASE), "2.0_TSI"),
    (
        re.compile(r"\b2\.0\s*tfsi\b", re.IGNORECASE),
        "2.0_TSI",
    ),  # TFSI = Audi badge for TSI
    (re.compile(r"\b1\.6\s*tdi\b", re.IGNORECASE), "1.6_TDI"),
    (re.compile(r"\b1\.5\s*tsi\b", re.IGNORECASE), "1.5_TSI"),
    (re.compile(r"\b1\.5\s*tfsi\b", re.IGNORECASE), "1.5_TSI"),
    (re.compile(r"\b1\.4\s*tsi\b", re.IGNORECASE), "1.4_TSI"),
    (re.compile(r"\b1\.4\s*tfsi\b", re.IGNORECASE), "1.4_TSI"),
    (re.compile(r"\b1\.2\s*tsi\b", re.IGNORECASE), "1.2_TSI"),
    (re.compile(r"\b1\.8\s*tsi\b", re.IGNORECASE), "1.8_TSI"),
    (re.compile(r"\b1\.8\s*tfsi\b", re.IGNORECASE), "1.8_TSI"),
    (re.compile(r"\b1\.9\s*tdi\b", re.IGNORECASE), "1.9_TDI"),
    (re.compile(r"\b1\.0\s*tsi\b", re.IGNORECASE), "1.0_TSI"),
    # EA-family codes → map to most common displacement
    (re.compile(r"\bea888\b", re.IGNORECASE), "2.0_TSI"),
    (re.compile(r"\bea211\b", re.IGNORECASE), "1.4_TSI"),
    (re.compile(r"\bea189\b", re.IGNORECASE), "2.0_TDI"),
    (re.compile(r"\bea288\b", re.IGNORECASE), "2.0_TDI"),
]

# Production year extraction — 4-digit years in plausible Golf range
_PROD_YEAR_RE = re.compile(r"\b(200[3-9]|201\d|202[0-6])\b")


# Inference rules for implicit engine spec from model variant names.
# On golfgtiforum.co.uk: GTI = 2.0 TSI, GTD = 2.0 TDI, Golf R = 2.0 TSI, etc.
_VARIANT_INFERENCE = [
    (re.compile(r"\bgti\b", re.IGNORECASE), "2.0_TSI"),
    (re.compile(r"\bgtd\b", re.IGNORECASE), "2.0_TDI"),
    (re.compile(r"\bgolf\s*r\b", re.IGNORECASE), "2.0_TSI"),
    (re.compile(r"\br32\b", re.IGNORECASE), "3.2_VR6"),
    (re.compile(r"\bgte\b", re.IGNORECASE), "1.4_GTE"),
]

_BARE_FUEL_INFERENCE = [
    (re.compile(r"\btdi\b", re.IGNORECASE), "TDI_unknown"),
    (re.compile(r"\btsi\b", re.IGNORECASE), "TSI_unknown"),
]


def extract_engine_spec(thread_name: str, messages: list[str]) -> str:
    """Extract displacement+fuel type from thread title + first messages.

    Priority: explicit displacement+fuel > EA-family code > variant inference > bare fuel type.
    """
    combined = thread_name + " " + " ".join(messages[:5])
    for pattern, spec in _ENGINE_SPEC_PATTERNS:
        if pattern.search(combined):
            return spec
    for pattern, spec in _VARIANT_INFERENCE:
        if pattern.search(combined):
            return spec
    for pattern, spec in _BARE_FUEL_INFERENCE:
        if pattern.search(combined):
            return spec
    return "unknown"


def extract_prod_year(thread_name: str, messages: list[str]) -> str | None:
    """Extract the most likely production year from thread title + early messages."""
    combined = thread_name + " " + " ".join(messages[:5])
    matches = _PROD_YEAR_RE.findall(combined)
    if not matches:
        return None
    # Most frequently mentioned year in early text is likely the car's year
    from collections import Counter

    counts = Counter(matches)
    return counts.most_common(1)[0][0]


# ── Filtering logic ───────────────────────────────────────────────────────────


def word_count(text: str) -> int:
    return len(text.split())


def has_mechanical_keywords(text: str) -> bool:
    t = text.lower()
    return any(kw in t for kw in MECHANICAL_KEYWORDS)


def has_mileage(text: str) -> bool:
    return bool(_MILEAGE_RE.search(text))


def is_pure_noise(text: str) -> bool:
    t = text.lower().strip()
    if any(phrase in t for phrase in NOISE_PHRASES):
        return True
    if any(re.match(p, t) for p in SHORT_ACK_PATTERNS):
        return True
    words = t.split()
    if len(words) <= 3 and all(w in NOISE_PHRASES for w in words):
        return True
    return False


def has_content_signal(text: str) -> bool:
    return (
        has_mechanical_keywords(text)
        or has_mileage(text)
        or bool(_CONTENT_SIGNALS.search(text))
    )


def is_noise_dominated(text: str) -> bool:
    matches = len(_NOISE_DOMINATED.findall(text))
    return matches > 0 and (matches / max(word_count(text), 1)) > 0.3


def should_keep(message: str) -> tuple[bool, str]:
    text = message.strip()
    if not text:
        return False, "empty"

    # Strip leading "Quote from: X on DATE" before evaluating — the quoted body
    # was already removed at scrape time; what remains after stripping the header
    # is purely the author's own reply. If nothing remains, drop the message.
    text = strip_quote_prefix(text)
    if not text:
        return False, "quote_only"

    normalized = text.lower()
    wc = word_count(normalized)

    # Structural junk
    if re.fullmatch(r"\d+", normalized):
        return False, "only_number"
    if re.fullmatch(r"https?://\S+", normalized):
        return False, "only_link"
    if len(normalized.strip(string.punctuation + " ")) == 0:
        return False, "punctuation_only"

    # Non-critical topics (cosmetic or infotainment dominated)
    cosm_hits = len(_COSMETIC_PATTERN.findall(normalized))
    info_hits = len(_INFOTAINMENT_PATTERN.findall(normalized))
    mech_score = sum(1 for kw in MECHANICAL_KEYWORDS if kw in normalized)
    if cosm_hits > mech_score and not has_mechanical_keywords(normalized):
        return False, "cosmetic_dominated"
    if info_hits > 2 and mech_score < 1:
        return False, "infotainment_only"

    # Pure noise
    if is_pure_noise(normalized) and not has_content_signal(normalized):
        return False, "pure_noise"
    if is_noise_dominated(normalized) and not has_content_signal(normalized):
        return False, "noise_dominated"

    # Very short: keep if has MOT content or mechanical keywords (more permissive)
    if wc < 3:
        return (
            (True, "very_short_mot")
            if extract_mot_items(normalized) or has_mechanical_keywords(normalized)
            else (False, "very_short")
        )
    if wc < 5:
        if (
            extract_mot_items(normalized)
            or has_mechanical_keywords(normalized)
            or has_content_signal(normalized)
        ):
            return True, "short_mot_signal"
        return False, "short_no_signal"

    # Hard signal
    if has_mechanical_keywords(normalized):
        return True, "mechanical_keywords"
    if has_mileage(normalized):
        return True, "mileage_mention"
    if _CONTENT_SIGNALS.search(normalized):
        return True, "content_signal"

    # Medium/long: keep if not noise-dominated
    if wc >= 8:
        if is_noise_dominated(normalized):
            return False, "long_noise_dominated"
        return True, "medium_length_no_noise"

    return False, "no_signal"


# ── Main ─────────────────────────────────────────────────────────────────────


def filter_main(input_file: str, output_file: str, rejected_file: str, csv_file: str):
    input_path = Path(input_file)
    output_path = Path(output_file)
    reject_path = Path(rejected_file)
    csv_path = Path(csv_file)

    if not input_path.exists():
        raise FileNotFoundError(f"Input not found: {input_path}")

    with open(input_path, encoding="utf-8") as f:
        threads = json.load(f)

    kept_threads = []
    rejected_threads = []
    csv_rows = []
    total = kept_n = rej_n = 0
    reasons: dict[str, int] = {}

    for thread in threads:
        thread_name = thread.get("thread_name", "Unknown Thread")
        thread_url = thread.get("thread_url", "")
        raw_messages = thread.get("messages", [])

        # engine code from thread title + first messages
        engine_code = extract_engine_code(thread_name, raw_messages)
        engine_spec = extract_engine_spec(thread_name, raw_messages)
        prod_year = extract_prod_year(thread_name, raw_messages)

        kept_msgs = []
        rejected_msgs = []

        for msg in raw_messages:
            total += 1
            keep, reason = should_keep(msg)
            mot_items = extract_mot_items(msg)
            if keep:
                kept_n += 1
                kept_msgs.append({"message": msg, "reason": reason})
                csv_rows.append(
                    {
                        "thread_name": thread_name,
                        "thread_url": thread_url,
                        "engine_code": engine_code,
                        "engine_spec": engine_spec,
                        "prod_year": prod_year,
                        "message": msg,
                        "reason": reason,
                        "mot_items": mot_items,
                    }
                )
            else:
                rej_n += 1
                rejected_msgs.append({"message": msg, "reason": reason})
                reasons[reason] = reasons.get(reason, 0) + 1

        if kept_msgs:
            kept_threads.append(
                {
                    "thread_name": thread_name,
                    "thread_url": thread_url,
                    "engine_code": engine_code,
                    "engine_spec": engine_spec,
                    "prod_year": prod_year,
                    "messages": kept_msgs,
                }
            )
        if rejected_msgs:
            rejected_threads.append(
                {
                    "thread_name": thread_name,
                    "thread_url": thread_url,
                    "messages": rejected_msgs,
                }
            )

    for path, data in [(output_path, kept_threads), (reject_path, rejected_threads)]:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "thread_name",
                "thread_url",
                "engine_code",
                "engine_spec",
                "prod_year",
                "message",
                "reason",
                "mot_items",
            ],
        )
        writer.writeheader()
        writer.writerows(csv_rows)

    print(f"Total     : {total}")
    print(f"Kept      : {kept_n}  ({kept_n / max(total, 1) * 100:.1f}%)")
    print(f"Rejected  : {rej_n}  ({rej_n / max(total, 1) * 100:.1f}%)")
    print(f"\nCleaned JSON : {output_path}")
    print(f"Rejected JSON: {reject_path}")
    print(f"CSV          : {csv_path}")
    print("\nRejection breakdown:")
    for r, c in sorted(reasons.items(), key=lambda x: -x[1]):
        print(f"  {r}: {c}")


if __name__ == "__main__":
    _root = Path(__file__).parent.parent / "data"
    input_default = _root / "raw" / "forums" / "messages_uk.json"
    if not input_default.exists():
        input_default = _root / "raw" / "messages_uk.json"

    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default=str(input_default))
    parser.add_argument(
        "--output", default=str(_root / "processed" / "forums" / "cleaned_messages_uk.json")
    )
    parser.add_argument(
        "--rejected", default=str(_root / "processed" / "forums" / "rejected_messages_uk.json")
    )
    parser.add_argument(
        "--csv", default=str(_root / "processed" / "forums" / "cleaned_messages_uk.csv")
    )
    args = parser.parse_args()

    filter_main(args.input, args.output, args.rejected, args.csv)
