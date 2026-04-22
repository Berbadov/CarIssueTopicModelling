#!/usr/bin/env python3
"""
cleaner_clio.py
---------------
Filter and flatten scraped Renault Clio forum messages.

Input:
    data/raw/forums/messages_clio.json

Outputs:
    data/processed/forums/cleaned_messages_clio.json
    data/processed/forums/rejected_messages_clio.json
    data/processed/forums/cleaned_messages_clio.csv

Usage:
  python scrapers/cleaner_clio.py
    python scrapers/cleaner_clio.py --input data/raw/forums/messages_clio.json
"""

import argparse
import csv
import json
import re
import string
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

TRANSLIT = str.maketrans("çÇğĞıİöÖşŞüÜ", "cCgGiIoOsSuU")

MECHANICAL_KEYWORDS = [
    "motor", "yag", "eksiltme", "yakma", "segman", "piston", "silindir",
    "supap", "subap", "conta", "turbo", "wastegate", "intercooler",
    "triger", "zincir", "kayis", "devirdaim", "termostat", "radyator",
    "antifriz", "sogutma", "hararet", "enjektor", "pompa", "yakit",
    "dpf", "egr", "adblue", "kizdirma", "ariza", "ikaz", "epc",
    "sanziman", "vites", "debriyaj", "kavrama", "mekatronik", "edc",
    "volan", "titreme", "vuruntu", "rolanti", "tekleme", "misfire",
    "sensor", "bobin", "buji", "aku", "alternator", "mars", "fren",
    "balata", "disk", "rot", "salincak", "amortisor", "direksiyon",
    "0.9 tce", "1.0 tce", "1.2 tce", "1.3 tce", "1.5 dci", "1.6 dci",
]

NOISE_PHRASES = [
    "tesekkur", "tesekkurler", "sagol", "eyvallah", "gecmis olsun",
    "merhaba", "selam", "hocam", "abi", "reis", "iyi forumlar",
    "takip", "guncel", "rez", "up", "mesajim bulunsun", "tamam",
]

SHORT_ACK_PATTERNS = [
    r"^(tesekkur(ler)?|sagol|eyvallah|tamam|ok|anladim)[.! ]*$",
    r"^(merhaba|selam|hocam|abi)[.! ]*$",
    r"^(takip|rez|up|guncel)[.! ]*$",
]

_GENERIC_NOISE = re.compile(
    r"\b(" \
    r"satildi(\s*mi)?|hala\s*satilik|fiyat(\s*nedir|\s*ne\s*kadar)?|" \
    r"telefon|numara|iletisim|arayabilir\s*miyim|" \
    r"fotograf|resim|detay\s*verir\s*misiniz|" \
    r"takip|up|rez|guncel" \
    r")\b",
    re.IGNORECASE,
)

_NON_CRITICAL = re.compile(
    r"\b(" \
    r"multimedya|carplay|android\s*auto|bluetooth|navigasyon|teyp|" \
    r"kaporta|boya|gocuk|cizik|tramer|pasta\s*cila|detailing|ppf|" \
    r"xenon|led\s*far|ampul|mercek" \
    r")\b",
    re.IGNORECASE,
)

_CONTENT_SIGNAL = re.compile(
    r"\b(" \
    r"ariza|problem|sorun|ses|titresim|vuruntu|hararet|" \
    r"kacak|sizinti|yag|dpf|egr|enjektor|sanziman|debriyaj" \
    r")\b",
    re.IGNORECASE,
)

ENGINE_SPEC_PATTERNS = [
    (re.compile(r"\b0[\.,]?9\s*tce\b", re.IGNORECASE), "0.9_TCE"),
    (re.compile(r"\b1[\.,]?0\s*tce\b", re.IGNORECASE), "1.0_TCE"),
    (re.compile(r"\b1[\.,]?2\s*tce\b", re.IGNORECASE), "1.2_TCE"),
    (re.compile(r"\b1[\.,]?3\s*tce\b", re.IGNORECASE), "1.3_TCE"),
    (re.compile(r"\b1[\.,]?5\s*dci\b", re.IGNORECASE), "1.5_DCI"),
    (re.compile(r"\b1[\.,]?6\s*dci\b", re.IGNORECASE), "1.6_DCI"),
    (re.compile(r"\b1[\.,]?4\s*16v\b", re.IGNORECASE), "1.4_NA"),
    (re.compile(r"\b1[\.,]?6\s*16v\b", re.IGNORECASE), "1.6_NA"),
]

GENERATION_PATTERNS = [
    (re.compile(r"\bclio\s*(ii|2)\b", re.IGNORECASE), "CLIO_II"),
    (re.compile(r"\bclio\s*(iii|3)\b", re.IGNORECASE), "CLIO_III"),
    (re.compile(r"\bclio\s*(iv|4)\b", re.IGNORECASE), "CLIO_IV"),
    (re.compile(r"\bclio\s*(v|5)\b", re.IGNORECASE), "CLIO_V"),
]

YEAR_RE = re.compile(r"\b(199[6-9]|200\d|201\d|202[0-6])\b")


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower()).translate(TRANSLIT)


def word_count(text: str) -> int:
    return len(text.split())


def has_mechanical_keywords(text: str) -> bool:
    return any(k in text for k in MECHANICAL_KEYWORDS)


def has_km_mention(text: str) -> bool:
    return bool(
        re.search(
            r"\b\d[\d\.,\s]*\s*(km|kilometre)\b|\b\d+\s*[kK]\s*(km)?\b|\b\d+\s*bin\s*(km)?\b",
            text,
            re.IGNORECASE,
        )
    )


def is_pure_noise(text: str) -> bool:
    if any(p in text for p in NOISE_PHRASES):
        return True
    if any(re.match(pat, text) for pat in SHORT_ACK_PATTERNS):
        return True
    return False


def should_keep(message: str) -> tuple[bool, str]:
    txt = message.strip()
    if not txt:
        return False, "empty"

    n = normalize(txt)
    wc = word_count(n)

    if re.fullmatch(r"\d+", n):
        return False, "only_number"
    if re.fullmatch(r"https?://\S+", n):
        return False, "only_link"
    if len(n.strip(string.punctuation + " ")) == 0:
        return False, "punctuation_only"
    if _NON_CRITICAL.search(n):
        return False, "non_critical_topic"

    has_signal = bool(has_mechanical_keywords(n) or has_km_mention(n) or _CONTENT_SIGNAL.search(n))

    if is_pure_noise(n) and not has_signal:
        return False, "pure_noise"

    noise_hits = len(_GENERIC_NOISE.findall(n))
    if noise_hits > 0 and (noise_hits / max(wc, 1)) > 0.35 and not has_signal:
        return False, "noise_dominated"

    if wc < 3:
        return (True, "very_short_signal") if has_signal else (False, "very_short")

    if wc < 7:
        return (True, "short_signal") if has_signal else (False, "short_no_signal")

    if has_signal:
        return True, "mechanical_or_context_signal"

    if wc >= 8 and noise_hits == 0:
        return True, "medium_length_no_noise"

    return False, "no_signal"


def _compose_thread_text(thread_name: str, messages: list[str]) -> str:
    return normalize(" ".join([thread_name] + messages[:3]))


def extract_engine_spec(thread_name: str, messages: list[str]) -> str:
    blob = _compose_thread_text(thread_name, messages)
    for pat, label in ENGINE_SPEC_PATTERNS:
        if pat.search(blob):
            return label
    if "dci" in blob:
        return "DCI_unknown"
    if "tce" in blob:
        return "TCE_unknown"
    return "unknown"


def extract_generation(thread_name: str, messages: list[str]) -> str | None:
    blob = _compose_thread_text(thread_name, messages)
    for pat, label in GENERATION_PATTERNS:
        if pat.search(blob):
            return label
    return None


def extract_engine_code(thread_name: str, messages: list[str]) -> str:
    spec = extract_engine_spec(thread_name, messages)
    if spec != "unknown":
        return spec
    gen = extract_generation(thread_name, messages)
    if gen:
        return gen
    return "unknown"


def extract_prod_year(thread_name: str, messages: list[str]) -> str | None:
    blob = _compose_thread_text(thread_name, messages)
    years = YEAR_RE.findall(blob)
    if not years:
        return None
    return Counter(years).most_common(1)[0][0]


def filter_main(input_file: str, output_file: str, rejected_file: str, csv_file: str) -> None:
    input_path = Path(input_file)
    output_path = Path(output_file)
    rejected_path = Path(rejected_file)
    csv_path = Path(csv_file)

    if not input_path.exists():
        raise FileNotFoundError(f"Input file not found: {input_path}")

    threads = json.loads(input_path.read_text(encoding="utf-8"))

    kept_threads = []
    rejected_threads = []
    csv_rows = []

    total = kept_n = rej_n = 0
    reasons: dict[str, int] = {}

    for thread in threads:
        thread_name = str(thread.get("thread_name", "Unknown Thread"))
        thread_url = str(thread.get("thread_url", ""))
        raw_messages = [str(m) for m in thread.get("messages", [])]

        engine_spec = extract_engine_spec(thread_name, raw_messages)
        engine_code = extract_engine_code(thread_name, raw_messages)
        prod_year = extract_prod_year(thread_name, raw_messages)

        kept_msgs = []
        rej_msgs = []

        for msg in raw_messages:
            total += 1
            keep, reason = should_keep(msg)
            clean_msg = msg.translate(TRANSLIT)

            if keep:
                kept_n += 1
                kept_msgs.append({"message": clean_msg, "reason": reason})
                csv_rows.append(
                    {
                        "thread_name": thread_name.translate(TRANSLIT),
                        "thread_url": thread_url,
                        "engine_code": engine_code,
                        "engine_spec": engine_spec,
                        "prod_year": prod_year,
                        "message": clean_msg,
                        "reason": reason,
                    }
                )
            else:
                rej_n += 1
                rej_msgs.append({"message": clean_msg, "reason": reason})
                reasons[reason] = reasons.get(reason, 0) + 1

        if kept_msgs:
            kept_threads.append(
                {
                    "thread_name": thread_name.translate(TRANSLIT),
                    "thread_url": thread_url,
                    "engine_code": engine_code,
                    "engine_spec": engine_spec,
                    "prod_year": prod_year,
                    "messages": kept_msgs,
                }
            )

        if rej_msgs:
            rejected_threads.append(
                {
                    "thread_name": thread_name.translate(TRANSLIT),
                    "thread_url": thread_url,
                    "messages": rej_msgs,
                }
            )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    rejected_path.parent.mkdir(parents=True, exist_ok=True)
    csv_path.parent.mkdir(parents=True, exist_ok=True)

    output_path.write_text(json.dumps(kept_threads, ensure_ascii=False, indent=2), encoding="utf-8")
    rejected_path.write_text(json.dumps(rejected_threads, ensure_ascii=False, indent=2), encoding="utf-8")

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
            ],
        )
        writer.writeheader()
        writer.writerows(csv_rows)

    print(f"Total     : {total}")
    print(f"Kept      : {kept_n}  ({kept_n / max(total, 1) * 100:.1f}%)")
    print(f"Rejected  : {rej_n}  ({rej_n / max(total, 1) * 100:.1f}%)")
    print(f"\nCleaned JSON : {output_path}")
    print(f"Rejected JSON: {rejected_path}")
    print(f"CSV          : {csv_path}")
    print("\nRejection breakdown:")
    for reason, count in sorted(reasons.items(), key=lambda x: -x[1]):
        print(f"  {reason}: {count}")


def main() -> None:
    root = ROOT / "data"
    input_default = root / "raw" / "forums" / "messages_clio.json"
    if not input_default.exists():
        input_default = root / "raw" / "messages_clio.json"

    parser = argparse.ArgumentParser(description="Filter and flatten Clio forum messages")
    parser.add_argument("--input", default=str(input_default))
    parser.add_argument("--output", default=str(root / "processed" / "forums" / "cleaned_messages_clio.json"))
    parser.add_argument("--rejected", default=str(root / "processed" / "forums" / "rejected_messages_clio.json"))
    parser.add_argument("--csv", default=str(root / "processed" / "forums" / "cleaned_messages_clio.csv"))
    args = parser.parse_args()

    filter_main(args.input, args.output, args.rejected, args.csv)


if __name__ == "__main__":
    main()
