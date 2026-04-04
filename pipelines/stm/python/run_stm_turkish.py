#!/usr/bin/env python3
"""
run_stm_turkish.py
──────────────────
Python+CUDA port of R_code_STM.R.

Corpus : Golf Tutkusu (golftutkusu.com) — Turkish
K      : 25 (searchK over [4,6,8,10,12])
Mileage: km
Covars : reason + engine_group + technical_bucket
Output : data/processed/*.{csv,xlsx}  (no suffix)

Usage:
    .venv/Scripts/python pipelines/stm/python/run_stm_turkish.py
"""

import sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from stm.dfm import (
    DFMBuilder,
    BigramDetector,
    aggregate_threads,
    _compile,
    _simple_tokenize,
)
from stm.core import STM
from stm._output import write_outputs_turkish
from stm.search_k import search_k

# ── Config ────────────────────────────────────────────────────────────────────

def _resolve_input_csv() -> Path:
    candidates = [
        ROOT / "data" / "processed" / "forums" / "cleaned_messages.csv",
        ROOT / "cleaned_messages.csv",
    ]
    return next((p for p in candidates if p.exists()), candidates[0])


INPUT_CSV = _resolve_input_csv()
STOPWORDS_FILE = ROOT / "turkce-stop-words.txt"
OUT_DIR = ROOT / "data" / "processed"
K_FINAL = 25
K_RANGE = [4, 6, 8, 10, 12]
MAX_EM_ITS = 500
DEVICE = "cuda"

# ── Pattern sets (Turkish — from R_code_STM.R lines 89–128) ──────────────────

TECHNICAL_PATTERNS = _compile([
    r"\bmotor\b", r"\bmekatronik\b", r"\bdsg\b", r"\bsanziman\b", r"\bşanzıman\b",
    r"\bkavrama\b", r"\bdebriyaj\b", r"\bturbo\b", r"\benjektor\b", r"\benjektör\b",
    r"\btriger\b", r"\bkayis\b", r"\bkayış\b", r"\btermostat\b", r"\bdevirdaim\b",
    r"\bhararet\b", r"\bkalorifer\b", r"\bpetek\b", r"\bradyator\b", r"\bradyatör\b",
    r"\bdpf\b", r"\bepc\b", r"\babs\b", r"\bbuji\b", r"\bbobin\b",
    r"\bvolan\b", r"\bvolantin\b", r"\bfren\b", r"\bbalata\b", r"\brot\b",
    r"\bsalincak\b", r"\bsalıncak\b", r"\bamortisor\b", r"\bamortisör\b", r"\baks\b",
    r"\baku\b", r"\bakü\b", r"\bxenon\b", r"\bhalojen\b", r"\bfar\b",
    r"\bsensor\b", r"\bsensör\b",
])

CHRONIC_PATTERNS = _compile([
    r"\bkronik\b", r"\bsurekli\b", r"\bsürekli\b", r"\byine\b", r"\btekrar\b",
    r"\btekrarlayan\b", r"\bduzelmedi\b", r"\bdüzelmedi\b", r"\bcozulmedi\b",
    r"\bçözülmedi\b", r"\buzun suredir\b", r"\buzun süredir\b",
    r"\bher sefer\b", r"\bdevam ediyor\b",
])

COSMETIC_PATTERNS = _compile([
    r"\btramer\b", r"\btramere\b", r"\btramerde\b",
    r"\bgocuk\b", r"\brutus\b", r"\brotus\b",
    r"\blokal\b", r"\bmarspiyel\b",
    r"\bboyanacak\b", r"\bboyattim\b", r"\bppf\b", r"\bkazadan\b",
])

INFOTAINMENT_PATTERNS = _compile([
    r"\bcarplay\b", r"\brcd\b", r"\brns\b",
    r"\bandroid\s+auto\b", r"\bbluetooth\b",
    r"\bnavigasyon\b", r"\bkamera\b",
])

TECHNICAL_REASON_TAGS = [
    "engine", "motor", "transmission", "dsg", "brake", "electrical",
    "cooling", "suspension", "exhaust",
]

# ── Engine group mapping (from R_code_STM.R lines 219–228) ───────────────────

def engine_group_fn(code: str | None) -> str:
    code = str(code) if code else "unknown"
    if code in ("1.2_TSI", "1.2TSI", "EA211_TSI",
                "1.2_TSI_CJZ", "1.2_TSI_CZC", "1.2_TSI_CBZ"): return "1.2_TSI"
    if code in ("1.4_TSI", "1.4_TSI_CHPA"):                      return "1.4_TSI"
    if code in ("1.5_TSI",):                                       return "1.5_TSI"
    if code in ("1.6_TDI", "1.6_TDI_CZD", "EA288_TDI"):          return "1.6_TDI"
    if code in ("2.0_TDI",):                                       return "2.0_TDI"
    if code == "unknown":                                           return "unknown"
    return "other"

# ── Turkish stopwords (from R_code_STM.R lines 452–519) ──────────────────────

CUSTOM_STOPWORDS_TR = [
    # meta / forum
    "konu", "mesaj", "forum", "yazan", "alıntı", "alinti", "sayfa",
    "cevap", "yorum", "link", "golftutkusu",
    # filler
    "bir", "bu", "ama", "daha", "gibi", "için", "ile", "çok", "cok",
    "var", "yok", "mi", "da", "de", "ki", "en", "çünkü", "cunki",
    "ben", "benim", "bende", "bana", "onu", "ona", "onun",
    "aracım", "aracim", "arabam", "araç", "arac", "araba",
    "golf", "vw", "volkswagen",
    "zaten", "sanırım", "saniyorum", "galiba", "herhalde",
    "oldu", "olmuş", "olmus", "olur", "olmaz", "oluyor",
    "diyor", "dedi", "demiş", "demis", "diyorum",
    "şimdi", "simdi", "sonra", "önce", "once", "hala", "artık", "artik",
    "hiç", "hic", "kadar", "nasıl", "nasil", "neden", "acaba",
    "bilmiyorum", "bilmiyoruz", "düşünüyorum", "dusunuyorum",
    "geçen", "gecen", "geliyor", "gidiyor",
    "c", "na", "i", "e", "s", "t",
    # domain noise
    "sorun", "sorunlu", "sorunum", "sorunu", "sorununun", "sorununu",
    "aynı", "ayni", "olabilir", "hocam", "bi", "şekilde", "sekilde",
    "aracı", "araci", "tekrar", "tekrarlayan", "usta", "ustad", "bir",
    "ustadim", "parça", "parca",
    # cosmetic noise
    "tramer", "tramere", "tramerde", "gocuk", "rutus", "rotus",
    "lokal", "marspiyel", "boyanacak", "boyattim", "ppf", "kaplama", "kazadan",
    # infotainment noise
    "carplay", "rcd330", "rns510", "bluetooth", "navigasyon",
    # greetings / forum jargon
    "selam", "merhaba", "teşekkürler", "tesekkurler", "sağol", "sagol",
    "sağolun", "sagolun", "herkese", "arkadaşlar", "arkadaslar",
    "günler", "gunler", "kolay", "gelsin", "maşallah", "masallah",
    "hayırlı", "hayirli", "olsun", "geçmiş", "gecmis", "eyvallah",
    # verb/tense filler
    "yaptım", "yaptim", "ettim", "ediyor", "yapıyor", "yapiyor",
    "dedim", "gittim", "geldim", "aldım", "aldim", "bence", "sence",
    "böyle", "boyle", "şöyle", "soyle", "falan", "filan",
    "göre", "gore", "diye", "olarak", "olan", "olduğu", "oldugu",
    "zaman", "gün", "gun", "ay", "yıl", "yil",
    "kendi", "kendim", "içinde", "icinde", "üzerinde", "uzerinde",
    # cosmetic body
    "çizik", "cizik", "boya", "boyasız", "boyasiz", "pasta", "cila",
    "seramik", "tampon", "çamurluk", "camurluk", "kaput", "tavan",
    "bagaj", "kapı", "kapi", "taş", "tas", "izi", "vuruk", "sürtme",
    "surtme", "yıkama", "yikama", "köpük", "kopuk", "detaylı", "detayli",
    # multimedia
    "teyp", "ekran", "multimedya", "kamera", "görüş", "gorus",
    "hoparlör", "hoparlor", "amfi", "kılıf", "kilif", "paspas",
    "havuz", "havuzu",
    # commercial noise
    "fiyat", "satılık", "satilik", "ilan", "lira", "tl", "bin",
    "kuruş", "kurus", "pazarlık", "pazarlik", "takas", "hasar",
    "kaydı", "kaydi", "eksper", "ekspertiz", "ikinci", "el",
    # insurance / bureaucracy
    "kasko", "sigorta", "poliçe", "police", "muafiyet", "muafiyetli",
    "prim", "yenileme", "acente", "tutanak", "hasarsızlık",
    "hasarsizlik", "indirim", "muayene", "tüvtürk", "tuvturk",
    "ruhsat", "noter",
]

# ── Turkish compound dictionary (from R_code_STM.R lines 308–440) ────────────

COMPOUND_DICT: dict[str, list[str]] = {
    "motor_arizasi":        ["motor arızası",    "motor arizasi"],
    "yag_degisimi":         ["yağ değişimi",     "yag degisimi"],
    "fren_pedi":            ["fren pedi",        "fren balata"],
    "hata_kodu":            ["hata kodu",        "ariza kodu"],
    "start_stop":           ["start stop"],
    "egzoz_uyarisi":        ["egzoz uyarısı",   "egzoz uyarisi"],
    "turbo_arizasi":        ["turbo arızası",    "turbo arizasi"],
    "bakim_zamani":         ["bakım zamanı",     "bakim zamani"],
    "garanti_suresi":       ["garanti süresi",   "garanti suresi"],
    "kilometre_servisi":    ["km servisi",       "kilometre servisi"],
    "sogutma_sistemi":      ["soğutma sistemi",  "sogutma sistemi"],
    "vites_kutusu":         ["vites kutusu"],
    "direksiyon_kumandasi": ["direksiyon kumandası", "direksiyon kumandasi"],
    "yakit_pompasi":        ["yakıt pompası",    "yakit pompasi"],
    "debriyaj_diski":       ["debriyaj diski"],
    "triger_kayisi":        ["triger kayışı",    "triger kayisi"],
    "silindir_kapagi":      ["silindir kapağı",  "silindir kapagi"],
    "krank_mili":           ["krank mili"],
    "eksantrik_mili":       ["eksantrik mili"],
    "motor_takozu":         ["motor takozu"],
    "karter":               ["karter",           "yağ karteri", "yag karteri"],
    "subap":                ["subap",            "supap"],
    "piston_sekman":        ["piston",           "sekman"],
    "buji":                 ["buji"],
    "atesleme_bobini":      ["ateşleme bobini",  "atesleme bobini"],
    "sarj_dinamosu":        ["şarj dinamosu",    "sarj dinamosu", "alternatör", "alternator"],
    "mars_motoru":          ["marş motoru",      "mars motoru"],
    "enjektor":             ["enjektör",         "enjektor"],
    "gaz_kelebegi":         ["gaz kelebeği",     "gaz kelebegi"],
    "hava_filtresi":        ["hava filtresi"],
    "emme_manifoldu":       ["emme manifoldu",   "egzoz manifoldu"],
    "radyator":             ["radyatör",         "radyator"],
    "su_pompasi":           ["su pompası",       "su pompasi", "devirdaim pompası", "devirdaim pompasi"],
    "termostat":            ["termostat"],
    "yag_pompasi":          ["yağ pompası",      "yag pompasi", "yağ filtresi", "yag filtresi"],
    "sanziman":             ["şanzıman",         "sanziman"],
    "baski_balata":         ["baskı balata",     "baski balata"],
    "volan":                ["volan",            "volan dişlisi", "volan dislisi"],
    "katalitik_konvertor":  ["katalitik konvertör", "katalitik konvertor"],
    "egr_valfi":            ["egr valfi"],
    "dpf":                  ["dizel partikül filtresi", "dpf", "partikül filtresi", "partikul filtresi"],
    "oksijen_sensoru":      ["oksijen sensörü",  "oksijen sensoru", "lambda sensörü", "lambda sensoru"],
    "amortisor":            ["amortisör",        "amortisor"],
    "helezon_yayi":         ["helezon yayı",     "helezon yayi", "süspansiyon yayı", "suspansiyon yayi"],
    "salincak":             ["salıncak",         "salincak", "alt salıncak", "alt salincak"],
    "rot_aksami":           ["rot başı",         "rot basi", "rotil", "rot kolu"],
    "aks_sistemi":          ["aks",              "aks mili", "aks kafası", "aks kafasi", "aks körüğü", "aks korugu"],
    "porya_rulman":         ["porya",            "tekerlek bilyası", "tekerlek bilyasi", "tekerlek rulmanı"],
    "z_rot_viraj":          ["z rot",            "z rotu", "viraj demiri", "viraj çubuğu", "viraj cubugu"],
    "direksiyon_kutusu":    ["direksiyon kutusu", "direksiyon pompası", "direksiyon pompasi", "kramayer"],
    "fren_diski":           ["fren diski",       "fren aynası", "fren aynasi", "kampana"],
    "fren_kaliperi":        ["fren kaliperi",    "kaliper", "fren merkezi", "el freni teli"],
    "triger_zinciri":       ["triger zinciri",   "zincir uzaması", "zincir sesi", "sente atlaması"],
    "dsg_mekatronik":       ["mekatronik arızası", "mekatronik beyni", "kavrama titremesi"],
    "sunroof_sorunu":       ["sunroof",          "cam tavan", "fitil sesi", "su alma", "su sızıntısı"],
    "multimedya_ekran":     ["hayalet ekran",    "ghost touch", "dokunmatik donması", "teyp donuyor"],
    "turbo_wastegate":      ["wastegate",        "şıngırtı sesi", "turbo sesi"],
}


def main() -> None:
    print("=" * 60)
    print("run_stm_turkish.py — Golf Tutkusu Turkish STM")
    print("=" * 60)

    # ── 1. Load data ──────────────────────────────────────────────────────────
    print(f"\nLoading {INPUT_CSV}…")
    df_raw = pd.read_csv(INPUT_CSV)
    print(f"  Raw messages: {len(df_raw)}")

    # ── 2. Load stopwords ─────────────────────────────────────────────────────
    tr_stopwords: list[str] = []
    if STOPWORDS_FILE.exists():
        tr_stopwords = [
            ln.strip() for ln in STOPWORDS_FILE.read_text(encoding="utf-8").splitlines()
            if ln.strip()
        ]
        print(f"  Loaded {len(tr_stopwords)} Turkish stopwords from {STOPWORDS_FILE.name}")
    all_stopwords = list(set(tr_stopwords + CUSTOM_STOPWORDS_TR))

    # ── 3. Thread aggregation ─────────────────────────────────────────────────
    print("\nAggregating threads…")
    df = aggregate_threads(
        df_raw,
        mileage_mode="km",
        technical_patterns=TECHNICAL_PATTERNS,
        chronic_patterns=CHRONIC_PATTERNS,
        cosmetic_patterns=COSMETIC_PATTERNS,
        infotainment_patterns=INFOTAINMENT_PATTERNS,
        technical_reason_tags=TECHNICAL_REASON_TAGS,
        engine_group_fn=engine_group_fn,
        cosmetic_filter=True,
        clio_mode=False,
    )

    # ── 4. Build DFM ──────────────────────────────────────────────────────────
    print("\nBuilding DFM with compound dictionary…")
    builder = DFMBuilder(
        stopwords=all_stopwords,
        min_termfreq=2,
        min_docfreq=1,
        max_docfreq_prop=0.40,
        min_charlen=0,
        keep_numbers=True,
    )
    count_matrix, vocab, kept_idx = builder.fit_transform(
        df["txt"].tolist(),
        compound_dict=COMPOUND_DICT,
    )

    df = df.iloc[kept_idx].reset_index(drop=True)
    print(f"  Aligned df: {len(df)} rows, vocab: {len(vocab)} terms")

    # ── 5. K selection ────────────────────────────────────────────────────────
    print(f"\nK selection over {K_RANGE}…")
    k_metrics = search_k(
        count_matrix, vocab, df,
        prevalence_formula="~ reason + engine_group + technical_bucket",
        k_range=K_RANGE,
        max_em_its=100,
        device=DEVICE,
        verbose=True,
    )
    k_summary = k_metrics.groupby("K").agg(
        exclusivity_mean=("exclusivity", "mean"),
        semcoh_mean=("semcoh", "mean"),
    ).reset_index() if "topic" in k_metrics.columns else k_metrics.copy()

    print("\nK metrics:")
    print(k_metrics.to_string(index=False))

    # ── 6. Final STM ──────────────────────────────────────────────────────────
    print(f"\nFitting final STM with K={K_FINAL}…")
    stm = STM(
        K=K_FINAL,
        device=DEVICE,
        max_em_its=MAX_EM_ITS,
        verbose=True,
    )
    stm.fit(
        count_matrix,
        vocab,
        df,
        prevalence_formula="~ reason + engine_group + technical_bucket",
    )

    # ── 7. Write outputs ──────────────────────────────────────────────────────
    print("\nWriting outputs…")
    write_outputs_turkish(stm, df, vocab, OUT_DIR, k_metrics=k_metrics)

    print("\nDone.")


if __name__ == "__main__":
    main()
