# A data Preprocessor to clean up the raw messages.json output from Scrapy, removing duplicates and irrelevant content, and structuring it for easier analysis.
# Note: We need also classify; another script or handle it here?
import translate
import json
import re
import string
import sys
import os
import argparse
from pathlib import Path

EXTRA_MECHANICAL = [
    "mekatronik", "volant", "basinc tupu", "egr", "dpf", "partikul", "adblue",
    "amortisor", "salincak", "z rot", "balata", "disk", "aks", "porya",
    "sensor", "beyin", "ecu", "yazilim", "epc", "abs", "esp", "lambda",
    "manifolt", "kasnak", "eksantrik", "krank", "itici", "fincan",
    "terleme", "eksiltme", "yatak", "subap", "itici", "sanziman",
        # Engine & oil
    "motor", "yag", "yaglama", "eksiltme", "yakma",
    "segman", "piston", "silindir", "supap", "kulbutor",
    "conta", "contasi", "contanin",
    "turbo", "turbonun", "turbosu",
    "rektefiye", "revizyon",
    # Timing
    "triger", "zincir", "kayis", "zamanlama",
    # Transmission & drivetrain
    "dsg", "vites", "debriyaj", "kavrama", "diferansiyel",
    # Cooling & fuel
    "sogutma", "radyator", "termostat", "antifiriz",
    "yakit", "enjekter", "pompasi", "pompanin",
    # Electrical
    "aku", "alternator", "mars",
    # Common fault terms
    "ariza", "hata", "problem", "bozuk", "bozuldu", # "sorun", too generic and often used for mentioning mechanical issues without actually being noise, e.g. "sorun cozuldu mu"
    "uyari", "ikaz",
    "ses", "titresim", "vuruntu",
    "kacak", "sizinti", "terleme",
    "duman", "yaniyor",
    # Parts & service
    "filtre", "buji", "atesleme",
    "servis", "usta", "tamirci", "yetkili",
    "kompresyon", "basinc",
    # Common engine codes mentioned in VW forums
    "tsi", "tdi", "fsi", "tfsi", "bluemotion",
    "czc", "czca", "cze", "blf", "bse",
]

NOISE_PHRASES = [
    # Tesekkur & Vedalar
    "gecmis olsun", "tesekkur", "tsk",
    "sagolun", "saolun", "saol", "eyv", "eyvallah", "eywallah",
    "tesekkurler", "tskler",

    # Selamlasma & Hitap
    "merhaba", "selam", "s.a", "as", "a.s", "selamun aleykum",
    "hocam", "ustad", "ustadim", "abi", "reis", "beyler",
    "iyi forumlar", "hayirli forumlar", "kolay gelsin", "iyi aksamlar",

    # Etkilesim & Takip
    "sorun cozuldu mu", "rez", "takip", "up",
    "guncel", "+++", "beklemedeyim", "mesajim bulunsun",

    # Temenniler
    "basarilar", "hayirli olsun", "h.olsun", "masallah", "kazasiz belasiz",
    "allah razi olsun", "kesene bereket"
]


SHORT_ACK_PATTERNS = [
    r"^(merhaba\.?|merhabalar\.?)$",
    r"^(tamam|anladim|ok|okay)\.?$",
    r"^(tesekkur(ler)?)( ederim| ederiz)?\.?$",
    r"^(gecmis olsun)\.?$",
    r"^(basarilar)\.?$",
    r"^\+1$",
]

# Translation table: Turkish characters → ASCII equivalents.
# Applied to every raw message before any matching/classification logic.
# Mapping: ç→c, Ç→C, ğ→g, Ğ→G, ı→i, İ→I, ö→o, Ö→O, ş→s, Ş→S, ü→u, Ü→U
translation_table = str.maketrans("çÇğĞıİöÖşŞüÜ", "cCgGiIoOsSuU")

# Safety-net loops: all literals above are already ASCII, so these loops
# are effectively no-ops. They remain as a guard against future additions
# that accidentally include Turkish characters.
for phrase in list(NOISE_PHRASES):
    _norm = phrase.translate(translation_table)
    if _norm != phrase:
        NOISE_PHRASES.append(_norm)

for pattern in list(SHORT_ACK_PATTERNS):
    _norm = pattern.translate(translation_table)
    if _norm != pattern:
        SHORT_ACK_PATTERNS.append(_norm)

for kw in list(EXTRA_MECHANICAL):
    _norm = kw.translate(translation_table)
    if _norm != kw:
        EXTRA_MECHANICAL.append(_norm)


# def normalize(text: str) -> str:
#     return re.sub(r'\s+', ' ', text.strip().lower()) # Usual normalization: remove whitespace, lowercase, collapse spaces
#     # Learning Note: Whitespace characters include spaces, tabs (\t), and newline characters (\n or \r).

def has_mechanical_keywords(text: str) -> bool:
    t = text
    return any(kw in t for kw in EXTRA_MECHANICAL)

def has_km_mention(text: str) -> bool:
    pattern = (
        # Standard km formats: "150000 km", "150.000 km", "150 000 km", "150,000 km"
        r"\b\d[\d\.,\s]*\s*km\b"
        # Kilometre written out: "150000 kilometre", "150.000 kilometre"
        r"|\b\d[\d\.,\s]*\s*kilometre\b"
        # Short k notation: "150k km", "150K km", "150k", "150K"
        r"|\b\d+\s*[kK]\s*(?:km)?\b"
        # Mileage with "bin": "150 bin km", "150bin kilometre"
        r"|\b\d+\s*bin\s*(?:km|kilometre)?\b"
        # Written-out thousands: "yuzelli bin km"
        r"|\b(?:yuz|iki yuz|uc yuz|dort yuz|bes yuz)?\s*"
        r"(?:on|yirmi|otuz|kirk|elli|altmis|yetmis|seksen|doksan)?\s*"
        r"bin\s*(?:km|kilometre)?\b"
        # Any standalone 4+ digit number (raw mileage mention)
        # r"|\b\d{4,}\b" | Causing false positives
        # Formats like "150.000'de", "150bin'de" (Turkish suffix attached)
        r"|\b\d[\d\.]*\s*(?:km|bin)?['\u2019][a-z]{1,4}\b"
        # "km'de", "km'ye", "km'yi" etc. (km with Turkish suffixes, now ASCII)
        r"|\bkm['\u2019][a-z]{1,4}\b"
        # Approximate: "yaklasik 150000", "~150000", "+-150000"
        r"|[~±≈]\s*\d{4,}"
        r"|\byaklasik\s*\d[\d\.\,]*\b"
        # "kilometre tasi", "km siniri" etc.
        r"|\bkm\s*(?:tasi|siniri|limiti|bakimi|servisi|muayenesi)\b"
    )
    return bool(re.search(pattern, text, re.IGNORECASE | re.UNICODE))

def is_pure_noise(text: str) -> bool:
    t = text
    if any(phrase in t for phrase in NOISE_PHRASES):
        return True
    if any(re.match(pattern, t) for pattern in SHORT_ACK_PATTERNS):
        return True
    words = t.split()
    if len(words) <= 3 and all(word in NOISE_PHRASES for word in words):
        # making sure no sneaking in
        if not has_mechanical_keywords(t) and not has_km_mention(t):
            return True
    return False


def word_count(text: str) -> int:
    return len(text.split())


# Filtering

# ── Additional noise phrase sets ──────────────────────────────────────────────

# Forum chatter that carries zero mechanical/condition signal
_GENERIC_NOISE_PHRASES = re.compile(
    r"\b("
    r"satildi(\s*mi)?|hala\s*satilik\s*(mi)?|hala\s*satilik|"
    r"musait\s*mi|el\s*degistirdi\s*mi|"
    r"fiyati?\s*(nedir|neden|ne\s*kadar)?|"
    r"ne\s*kadar(\s*istiyorsunuz)?|kaca\s*verir(siniz)?|"
    r"[iy]lgileniyorum|ilgilenir\s*misiniz|"
    r"(telefon|numara|iletisim|irtibat)\s*(numarasi|verir\s*misiniz|alabilir\s*miyim)?|"
    r"arayabilir\s*miyim|mesaj\s*atar\s*misiniz|"
    r"up|takip|guncel\s*mi|hala\s*guncel|rezerve\s*ettim|rez\b|"
    r"goruselim|nerede\s*(bu\s*arac)?|"
    r"bilgi\s*alabilir\s*miyim|detay\s*verir\s*misiniz|"
    r"fotograf\s*(var\s*mi|atar\s*misiniz)|resim\s*yok\s*mu"
    r")\b",
    re.IGNORECASE,
)

# Price-only patterns — these appear in long messages too
_PRICE_ONLY = re.compile(
    r"^[\d\s.,]+(tl|bin|milyon|k\b)?[\s!.]*$",
    re.IGNORECASE,
)

# Positive content signals beyond mechanical/km
_CONTENT_SIGNALS = re.compile(
    r"\b("
    # Mechanical maintenance/failure context
    r"servis|bakim|yag|filtre|"
    r"fren|balata|disk|"
    # Problem descriptions
    r"sorun|problem|ariza|ses|titresim|"
    r"sizinti|yakar|iciyor"
    r")\b",
    re.IGNORECASE,
)

# Cosmetic, multimedia, and lighting-modification content that should be
# excluded from chronic issue analysis unless strong mechanical context exists.
_NON_CRITICAL_TOPIC_PATTERNS = re.compile(
    r"\b("
    # Infotainment / multimedia
    r"multimedya|multimedia|carplay|android\s*auto|bluetooth|"
    r"navigasyon|navimex|teyp|teyip|ekran|dokunmatik|"
    r"hoparlor|amfi|subwoofer|ses\s*sistemi|"
    # Body/cosmetic damage & appearance
    r"kaporta|boya|gocuk|cizik|tramer|hasar\s*kaydi|"
    r"lokal\s*boya|pasta\s*cila|detailing|ppf|seramik|"
    r"far\s*parlatma|boyasiz\s*duzeltme|"
    # Lighting replacements / retrofits
    r"far\s*degisim|far\s*degistim|far\s*degisti|"
    r"xenon|bi\s*xenon|led\s*far|led\s*ampul|ampul\s*degisim|"
    r"mercek|stop\s*lambasi|gunduz\s*fari"
    r")\b",
    re.IGNORECASE,
)


def _non_critical_topic_hits(text: str) -> int:
    return len(_NON_CRITICAL_TOPIC_PATTERNS.findall(text))


def _is_noise_dominated(text: str) -> bool:
    """True if the message is mostly generic forum noise even if long."""
    noise_matches = len(_GENERIC_NOISE_PHRASES.findall(text))
    total_words = word_count(text)
    # More than half the semantic content is noise phrases → drop
    return noise_matches > 0 and (noise_matches / max(total_words, 1)) > 0.35


def _has_content_signal(normalized: str) -> bool:
    return bool(
        has_mechanical_keywords(normalized)
        or has_km_mention(normalized)
        or _CONTENT_SIGNALS.search(normalized)
    )


def should_keep(message: str) -> tuple[bool, str]:
    """
    Filtering logic for Turkish automotive forum messages.
    Returns (keep: bool, reason: str)

    Design goal: only pass messages that carry mechanical condition,
    history, or ownership signal — not social chatter or inquiries.
    Raw input is normalised by lowercasing and converting all Turkish
    characters to their ASCII equivalents before any matching is done.
    """
    text = message.strip()
    if not text:
        return False, "empty"

    normalized = text.lower().translate(translation_table)
    wc = word_count(normalized)

    # ── 1. Structural junk ───────────────────────────────────────────────────
    if re.fullmatch(r"\d+", normalized):
        return False, "only_number"
    if re.fullmatch(r"https?://\S+", normalized):
        return False, "only_link"
    if _PRICE_ONLY.fullmatch(normalized):
        return False, "price_only"
    if len(normalized.strip(string.punctuation + " ")) == 0:
        return False, "punctuation_only"
    if re.fullmatch(r"[\W_]+", normalized):
        return False, "emoji_or_symbol_only"

    # ── 1b. Exclude non-critical cosmetic/media/light-mod threads ───────────
    if _non_critical_topic_hits(normalized) > 0:
        return False, "non_critical_topic"

    # ── 2. Pure noise regardless of length ──────────────────────────────────
    # This is the key fix: length alone no longer saves a message
    if is_pure_noise(normalized) and not _has_content_signal(normalized):
        return False, "pure_noise"

    if _is_noise_dominated(normalized) and not _has_content_signal(normalized):
        return False, "noise_dominated"

    # ── 3. Very short: only keep with explicit signal ────────────────────────
    if wc < 3:
        if _has_content_signal(normalized):
            return True, "very_short_but_signal"
        return False, "very_short"

    # ── 4. Short range: require signal ──────────────────────────────────────
    if wc < 7:
        if _has_content_signal(normalized):
            return True, "short_but_signal"
        if re.match(
            r"^(evet|hayir|var|yok|bilmiyorum|bakarim|bakacagim|bakicam|"
            r"gorusuruz|tamam|ok|okey|anladim|"
            r"tesekkurler|sagol|eyvallah|"
            r"up|takip|guncel|rez|beklemedeyim|"
            r"mesajim bulunsun)$",
            normalized,
        ):
            return False, "short_ack"
        return False, "short_no_signal"

    # ── 5. Hard signal → keep immediately ───────────────────────────────────
    if has_mechanical_keywords(normalized):
        return True, "mechanical_keywords"
    if has_km_mention(normalized):
        return True, "km_mention"
    if _CONTENT_SIGNALS.search(normalized):
        return True, "content_signal"

    # ── 6. Medium/long messages: require at least weak content signal ────────
    # Previously: wc >= 15 → keep unconditionally. That was the main noise source.
    if wc >= 8:
        # Check that it's not a long noise-only message (e.g. long price negotiation)
        if _is_noise_dominated(normalized):
            return False, "long_but_noise_dominated"
        # Generic help requests that happen to be verbose
        if re.fullmatch(
            r"(yardim|acil|lutfen|acil yardim|"
            r"yardim lutfen)(\s+\w+){0,3}",
            normalized,
        ):
            return False, "generic_help"
        # Survived all noise filters and is substantive length → keep
        return True, "medium_length_no_noise"

    return False, "no_signal"


# Main

def filter_main(
    input_file: str,
    output_file: str,
    rejected_file: str,
    preserve_diacritics: bool = False,
):
    input_file = Path(input_file)
    output_file = Path(output_file)
    rejected_file = Path(rejected_file)

    if output_file.exists():
        match = re.search(r'_(\d+)$', output_file.stem)
        curr_iteration = int(match.group(1)) if match else 0
        new_output_file = output_file.with_name(f"{output_file.stem}_{curr_iteration + 1}{output_file.suffix}")
        print(f"Output file {output_file} already exists. Renaming to {new_output_file}")
        output_file = new_output_file

    if rejected_file.exists():
        match = re.search(r'_(\d+)$', rejected_file.stem)
        curr_iteration = int(match.group(1)) if match else 0
        new_rejected_file = rejected_file.with_name(f"{rejected_file.stem}_{curr_iteration + 1}{rejected_file.suffix}")
        print(f"Rejected file {rejected_file} already exists. Renaming to {new_rejected_file}")
        rejected_file = new_rejected_file

    if not os.path.exists(input_file):
        print(f"Input file {input_file} does not exist.")
        return

    with open(input_file, "r", encoding="utf-8") as f:
        threads = json.load(f)

    kept_threads = []
    rejected_threads = []
    total = kept_n = rej_n = 0
    reasons: dict[str, int] = {}

    for thread in threads:
        thread_name = thread.get('thread_name', 'Unknown Thread')
        thread_url  = thread.get('thread_url', '')
        messages    = thread.get('messages', [])

        kept_msgs = []
        rejected_msgs = []

        for msg in messages:
            total += 1
            keep, reason = should_keep(msg)
            clean_msg = msg if preserve_diacritics else msg.translate(translation_table)
            if keep:
                kept_n += 1
                kept_msgs.append({"message": clean_msg, "reason": reason})
            else:
                rej_n += 1
                rejected_msgs.append({"message": clean_msg, "reason": reason})
                reasons[reason] = reasons.get(reason, 0) + 1

        clean_thread_name = (
            thread_name if preserve_diacritics else thread_name.translate(translation_table)
        )
        if kept_msgs:
            kept_threads.append({
                "thread_name": clean_thread_name,
                "thread_url":  thread_url,
                "messages":    kept_msgs,
            })
        if rejected_msgs:
            rejected_threads.append({
                "thread_name": clean_thread_name,
                "thread_url":  thread_url,
                "messages":    rejected_msgs,
            })

    Path(output_file).write_text(
        json.dumps(kept_threads, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

    Path(rejected_file).write_text(
        json.dumps(rejected_threads, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

    if total == 0:
        print("No messages to process.")
    else:
        print(f"Total messages : {total}")
        print(f"Kept           : {kept_n}  ({kept_n/total*100:.1f}%)")
        print(f"Rejected       : {rej_n}  ({rej_n/total*100:.1f}%)")
    print(f"\nFiltered output : {output_file}")
    print(f"Rejection log   : {rejected_file}")

    print("\nRejection breakdown:")
    for reason, count in reasons.items():
        print(f"  {reason}: {count}")

if __name__ == "__main__":
    _root = Path(__file__).parent.parent / 'data'

    parser = argparse.ArgumentParser(
        description="Filter Turkish forum messages and write cleaned/rejected outputs."
    )
    parser.add_argument(
        "--input",
        default=str(_root / 'raw' / 'messages.json'),
        help="Input raw messages JSON path.",
    )
    parser.add_argument(
        "--output",
        default=str(_root / 'processed' / 'cleaned_messages.json'),
        help="Output cleaned JSON path.",
    )
    parser.add_argument(
        "--rejected",
        default=str(_root / 'processed' / 'rejected_messages.json'),
        help="Output rejected JSON path.",
    )
    parser.add_argument(
        "--preserve-diacritics",
        action="store_true",
        help="Keep original Turkish characters in output text fields.",
    )
    args = parser.parse_args()

    filter_main(
        args.input,
        args.output,
        args.rejected,
        preserve_diacritics=args.preserve_diacritics,
    )
