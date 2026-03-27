# STM Analysis – Golf Forum Issue Extraction
# Adapted from R_code_STM.R (original: gig economy academic abstracts)
# Goal: extract recurring car issues/topics from Turkish forum messages
#       with mileage (km) and other metadata as covariates.
#
# Install missing packages with:
#   install.packages(c("stm","tidytext","tidyverse","readr","quanteda",
#                      "quanteda.textstats","furrr","future","future.apply","openxlsx"))

library(stm)
library(tidytext)
library(tidyverse)
library(readr)
library(quanteda)
library(quanteda.textstats)
library(furrr)          # parallel-purrr (future backend)
library(future)         # orchestrates the worker pool
library(future.apply)   # future_lapply
library(openxlsx)       # multi-sheet Excel export

# ── 0. Parallelism setup ──────────────────────────────────────────────────────
# Uses all available logical cores minus one so the machine stays responsive.
n_workers <- max(1L, parallel::detectCores() - 1L)
plan(multisession, workers = n_workers)
cat(sprintf("Parallel workers: %d\n", n_workers))

# ── 1. Load data ──────────────────────────────────────────────────────────────

df_raw <- read_csv(
  "cleaned_messages.csv",
  show_col_types = FALSE
)

to_int_km <- function(x) {
  if (is.na(x) || x == "") return(NA_integer_)
  as.integer(gsub("[^0-9]", "", x))
}

extract_mileage_info <- function(text) {
  if (is.na(text) || text == "") {
    return(list(km = NA_integer_, confidence = "none"))
  }

  t <- stringr::str_to_lower(text)

  # e.g. "30-40 bin km" -> keep lower bound
  m <- stringr::str_match(t,
                 "\\b(\\d{1,3})\\s*[-–]\\s*(\\d{1,3})\\s*(k|bin)\\s*(?:km|kilometre|kilometrede|kilometresi)?\\b")
  if (!is.na(m[1, 1])) {
    lo <- to_int_km(m[1, 2])
    if (!is.na(lo)) {
      return(list(km = lo * 1000L, confidence = "range"))
    }
  }

  # e.g. "216k km", "125 bin kilometrede"
  m <- stringr::str_match(t,
                 "\\b(\\d{1,3})\\s*(k|bin)\\s*(?:km|kilometre|kilometrede|kilometresi)?\\b")
  if (!is.na(m[1, 1])) {
    base <- to_int_km(m[1, 2])
    if (!is.na(base)) {
      return(list(km = base * 1000L, confidence = "medium"))
    }
  }

  # e.g. "239890 km", "126.000 kilometrede"
  m <- stringr::str_match(t,
                 "\\b(\\d{1,3}(?:[\\.,]\\d{3})+|\\d{4,})\\s*(?:km|kilometre|kilometrede|kilometresi)\\b")
  if (!is.na(m[1, 1])) {
    return(list(km = to_int_km(m[1, 2]), confidence = "high"))
  }

  # e.g. "kilometre: 94450"
  m <- stringr::str_match(t,
                 "\\bkilometre(?:de|si|yi|ye)?\\s*[:=]?\\s*(\\d{1,3}(?:[\\.,]\\d{3})+|\\d{4,})\\b")
  if (!is.na(m[1, 1])) {
    return(list(km = to_int_km(m[1, 2]), confidence = "high"))
  }

  # e.g. "mileage: 239890"
  m <- stringr::str_match(t,
                 "\\bmileage\\s*[:=]?\\s*(\\d{1,3}(?:[\\.,]\\d{3})+|\\d{4,})\\b")
  if (!is.na(m[1, 1])) {
    return(list(km = to_int_km(m[1, 2]), confidence = "high"))
  }

  list(km = NA_integer_, confidence = "none")
}

TECHNICAL_PATTERNS <- c(
  "\\bmotor\\b", "\\bmekatronik\\b", "\\bdsg\\b", "\\bsanziman\\b", "\\bşanzıman\\b",
  "\\bkavrama\\b", "\\bdebriyaj\\b", "\\bturbo\\b", "\\benjektor\\b", "\\benjektör\\b",
  "\\btriger\\b", "\\bkayis\\b", "\\bkayış\\b", "\\btermostat\\b", "\\bdevirdaim\\b",
  "\\bhararet\\b", "\\bkalorifer\\b", "\\bpetek\\b", "\\bradyator\\b", "\\bradyatör\\b",
  "\\bdpf\\b", "\\bepc\\b", "\\babs\\b", "\\bbuji\\b", "\\bbobin\\b",
  "\\bvolan\\b", "\\bvolantin\\b", "\\bfren\\b", "\\bbalata\\b", "\\brot\\b",
  "\\bsalincak\\b", "\\bsalıncak\\b", "\\bamortisor\\b", "\\bamortisör\\b", "\\baks\\b",
  "\\baku\\b", "\\bakü\\b", "\\bxenon\\b", "\\bhalojen\\b", "\\bfar\\b", "\\bsensor\\b", "\\bsensör\\b"
)

CHRONIC_PATTERNS <- c(
  "\\bkronik\\b", "\\bsurekli\\b", "\\bsürekli\\b", "\\byine\\b", "\\btekrar\\b",
  "\\btekrarlayan\\b", "\\bduzelmedi\\b", "\\bdüzelmedi\\b", "\\bcozulmedi\\b", "\\bçözülmedi\\b",
  "\\buzun suredir\\b", "\\buzun süredir\\b", "\\bher sefer\\b", "\\bdevam ediyor\\b"
)

# Patterns that identify cosmetic / body-damage content (accident reports, paint, mods).
# Threads dominated by these are filtered OUT before STM to prevent a "body damage"
# or "modification" topic from consuming a topic slot that should be a mechanical issue.
COSMETIC_PATTERNS <- c(
  "\\btramer\\b", "\\btramere\\b", "\\btramerde\\b",   # body-damage assessor
  "\\bgocuk\\b",                                         # dent
  "\\brutus\\b",  "\\brotus\\b",                        # touch-up paint brands
  "\\blokal\\b",                                         # localized body repair
  "\\bmarspiyel\\b",                                     # side sill / rocker panel
  "\\bboyanacak\\b", "\\bboyattim\\b",                  # paint jobs
  "\\bppf\\b",                                           # paint protection film
  "\\bkazadan\\b"                                        # "from an accident"
)

# Patterns that identify infotainment / phone content (CarPlay, Bluetooth, nav…).
# Pure infotainment threads also consume mechanical topic slots.
INFOTAINMENT_PATTERNS <- c(
  "\\bcarplay\\b", "\\brcd\\b", "\\brns\\b",
  "\\bandroid\\s+auto\\b",
  "\\bbluetooth\\b",
  "\\bnavigasyon\\b",
  "\\bkamera\\b"
)

count_pattern_hits <- function(text, patterns) {
  if (is.na(text) || text == "") return(0L)
  txt <- stringr::str_to_lower(text)
  sum(vapply(patterns, function(p) stringr::str_detect(txt, p), logical(1)))
}

# ── 2. Aggregate to thread level ──────────────────────────────────────────────
# STM works better with longer documents. Combine all messages per thread
# into one document; keep thread_name and dominant reason as metadata.

df <- df_raw %>%
  group_by(thread_name, thread_url) %>%
  summarise(
    txt = {
      msgs <- message
      if (length(msgs) == 0L) {
        ""
      } else if (length(msgs) == 1L) {
        msgs[[1L]]
      } else {
        # Score each message individually so we can drop cosmetic follow-ups.
        cosm <- vapply(msgs, count_pattern_hits, integer(1), patterns = COSMETIC_PATTERNS)
        tech <- vapply(msgs, count_pattern_hits, integer(1), patterns = TECHNICAL_PATTERNS)
        # Always keep the first post (the original question/complaint).
        # For follow-up messages, keep only if they are low-cosmetic AND carry
        # at least one technical keyword or have no cosmetic keywords at all.
        keep <- c(TRUE, (cosm[-1L] < 2L) & (tech[-1L] > 0L | cosm[-1L] == 0L))
        filtered <- msgs[keep]
        if (length(filtered) == 0L) filtered <- msgs[1L]
        # Give the first post double weight by prepending it once more; this
        # anchors each thread document to its original problem description.
        paste(c(filtered[1L], filtered), collapse = " ")
      }
    },
    reason      = first(reason),       # dominant reason tag for the thread
    engine_code = first(engine_code),  # engine variant extracted per thread
    mileage_pick = list({
      infos <- lapply(message, extract_mileage_info)
      km_vals <- vapply(infos, function(x) x$km, integer(1))
      idx <- which(!is.na(km_vals))
      if (length(idx) == 0) {
        list(km = NA_integer_, confidence = "none")
      } else {
        infos[[idx[1]]]
      }
    }),
    n_messages  = n(),
    .groups     = "drop"
  ) %>%
  mutate(
    mileage_mentioned = vapply(mileage_pick, function(x) x$km, integer(1)),
    mileage_confidence = vapply(mileage_pick, function(x) x$confidence, character(1))
  ) %>%
  select(-mileage_pick) %>%
  mutate(
    doc_id = row_number(),
    doc_name = sprintf("doc_%05d", doc_id)
  )

technical_reason_tags <- c(
  "engine", "motor", "transmission", "dsg", "brake", "electrical", "cooling", "suspension", "exhaust"
)

df <- df %>%
  mutate(
    technical_score    = vapply(txt, count_pattern_hits, integer(1), patterns = TECHNICAL_PATTERNS),
    chronic_score      = vapply(txt, count_pattern_hits, integer(1), patterns = CHRONIC_PATTERNS),
    cosmetic_score     = vapply(txt, count_pattern_hits, integer(1), patterns = COSMETIC_PATTERNS),
    infotainment_score = vapply(txt, count_pattern_hits, integer(1), patterns = INFOTAINMENT_PATTERNS),
    reason_lower = stringr::str_to_lower(replace_na(reason, "")),
    reason_technical_hint = if_else(
      stringr::str_detect(reason_lower, paste(technical_reason_tags, collapse = "|")),
      1L,
      0L
    ),
    # Penalise cosmetic content so cosmetic-heavy threads sink to "low" focus bucket
    # and don't drive topic formation.  Cap the penalty at 3 to avoid over-penalising
    # threads that happen to mention a body part alongside a real mechanical issue.
    focus_score = technical_score + (2L * chronic_score) + reason_technical_hint
                  - pmin(cosmetic_score, 3L),
    technical_bucket = factor(
      if_else(focus_score >= 4L, "high", if_else(focus_score >= 2L, "medium", "low")),
      levels = c("low", "medium", "high")
    )
  ) %>%
  select(-reason_lower)

# Collapse rare engine codes (< 2 threads) into a single 'other' bucket
df <- df %>%
  mutate(engine_group = case_when(
    engine_code %in% c("1.2_TSI", "1.2TSI", "EA211_TSI",
                       "1.2_TSI_CJZ", "1.2_TSI_CZC", "1.2_TSI_CBZ") ~ "1.2_TSI",
    engine_code %in% c("1.4_TSI", "1.4_TSI_CHPA")                    ~ "1.4_TSI",
    engine_code %in% c("1.5_TSI")                                     ~ "1.5_TSI",
    engine_code %in% c("1.6_TDI", "1.6_TDI_CZD", "EA288_TDI")        ~ "1.6_TDI",
    engine_code %in% c("2.0_TDI")                                     ~ "2.0_TDI",
    engine_code == "unknown"                                           ~ "unknown",
    TRUE                                                               ~ "other"
  ))

# ── 2b. Remove threads where cosmetic / infotainment content dominates ─────────
# These threads corrupt STM topics: instead of a genuine mechanical issue topic
# the model would allocate a slot to "body damage assessor reports" or "CarPlay".
# A thread is dropped only when cosmetic/infotainment signals clearly outweigh
# the technical signal AND no real mechanical keyword is present.
nrow_before_cosm <- nrow(df)
df <- df %>%
  filter(
    # Keep if there is any technical content, or if cosmetic score is low
    !(cosmetic_score > pmax(1L, technical_score) & technical_score < 2L)
  ) %>%
  filter(
    # Drop pure infotainment threads (CarPlay / Bluetooth / nav with no mechanical signal)
    !(infotainment_score > 3L & technical_score < 1L)
  )
cat(sprintf(
  "Pre-STM noise filter: removed %d cosmetic/infotainment threads (%d -> %d)\n",
  nrow_before_cosm - nrow(df), nrow_before_cosm, nrow(df)
))

cat("Engine group distribution:\n")
print(table(df$engine_group))
cat("Technical focus bucket distribution:\n")
print(table(df$technical_bucket))
cat("Threads (documents):", nrow(df), "\n")

# ── 3. Basic text normalisation ───────────────────────────────────────────────

df$txt <- tolower(df$txt)

# ── 3.5 Resolve stop-words file ───────────────────────────────────────────────

get_script_dir <- function() {
  cmdArgs <- commandArgs(trailingOnly = FALSE)
  needle  <- "--file="
  match   <- grep(needle, cmdArgs)
  if (length(match) > 0) {
    return(dirname(normalizePath(sub(needle, "", cmdArgs[match]))))
  } else {
    if (requireNamespace("rstudioapi", quietly = TRUE) && rstudioapi::isAvailable()) {
      return(dirname(rstudioapi::getActiveDocumentContext()$path))
    } else {
      return(getwd())
    }
  }
}

stop_words_path <- file.path(get_script_dir(), "turkce-stop-words.txt")

# ── 4. Discover bigrams / collocations ───────────────────────────────────────

dfToken  <- quanteda::tokens(df$txt)
dfBigram <- dfToken %>%
  quanteda::tokens_remove(readLines(stop_words_path, encoding = "UTF-8")) %>%
  quanteda::tokens_select(
    pattern          = "^[a-züşğıöçâîû]",
    valuetype        = "regex",
    case_insensitive = FALSE,
    padding          = TRUE
  ) %>%
  quanteda.textstats::textstat_collocations(
    min_count = 3,
    tolower   = FALSE,
    size      = 2
  )

print(dfBigram)

# ── 5. Build corpus and compound known multi-word terms ───────────────────────

dfCorpus <- corpus(df$txt) %>%
  tokens(
    remove_punct   = TRUE,
    remove_numbers = FALSE,  # keep numbers – km figures matter
    remove_symbols = TRUE,
    remove_url     = TRUE
  )

  compound_dict <- dictionary(list(
      # Motor Çekirdek & Mekanik
      motor_arizasi        = c("motor arızası",    "motor arizasi"),
      yag_degisimi         = c("yağ değişimi",     "yag degisimi"),
      fren_pedi            = c("fren pedi",        "fren balata"),
      hata_kodu            = c("hata kodu",        "ariza kodu"),
      start_stop           = c("start stop"),
      egzoz_uyarisi        = c("egzoz uyarısı",   "egzoz uyarisi"),
      turbo_arizasi        = c("turbo arızası",    "turbo arizasi"),
      bakim_zamani         = c("bakım zamanı",     "bakim zamani"),
      garanti_suresi       = c("garanti süresi",   "garanti suresi"),
      kilometre_servisi    = c("km servisi",       "kilometre servisi"),
      sogutma_sistemi      = c("soğutma sistemi",  "sogutma sistemi"),
      vites_kutusu         = c("vites kutusu"),
      direksiyon_kumandasi = c("direksiyon kumandası", "direksiyon kumandasi"),
      yakit_pompasi        = c("yakıt pompası",    "yakit pompasi"),
      debriyaj_diski       = c("debriyaj diski"),
      triger_kayisi        = c("triger kayışı",    "triger kayisi"),
      silindir_kapagi      = c("silindir kapağı",  "silindir kapagi"),
      krank_mili           = c("krank mili"),
      eksantrik_mili       = c("eksantrik mili"),
      motor_takozu         = c("motor takozu"),
      karter               = c("karter",           "yağ karteri", "yag karteri"),
      subap                = c("subap",            "supap"),
      piston_sekman        = c("piston",           "sekman"),
      # Ateşleme & Elektrik
      buji                 = c("buji"),
      atesleme_bobini      = c("ateşleme bobini",  "atesleme bobini"),
      sarj_dinamosu        = c("şarj dinamosu",    "sarj dinamosu", "alternatör", "alternator"),
      mars_motoru          = c("marş motoru",      "mars motoru"),
      # Yakıt & Hava Sistemi
      enjektor             = c("enjektör",         "enjektor"),
      gaz_kelebegi         = c("gaz kelebeği",     "gaz kelebegi"),
      hava_filtresi        = c("hava filtresi"),
      emme_manifoldu       = c("emme manifoldu",   "egzoz manifoldu"),
      # Soğutma & Yağlama
      radyator             = c("radyatör",         "radyator"),
      su_pompasi           = c("su pompası",       "su pompasi", "devirdaim pompası", "devirdaim pompasi"),
      termostat            = c("termostat"),
      yag_pompasi          = c("yağ pompası",      "yag pompasi", "yağ filtresi", "yag filtresi"),
      # Aktarma Organları (Drivetrain)
      sanziman             = c("şanzıman",         "sanziman"),
      baski_balata         = c("baskı balata",     "baski balata"),
      volan                = c("volan",            "volan dişlisi", "volan dislisi"),
      # Egzoz & Emisyon
      katalitik_konvertor  = c("katalitik konvertör", "katalitik konvertor"),
      egr_valfi            = c("egr valfi"),
      dpf                  = c("dizel partikül filtresi", "dpf", "partikül filtresi", "partikul filtresi"),
      oksijen_sensoru      = c("oksijen sensörü",  "oksijen sensoru", "lambda sensörü", "lambda sensoru"),
      # Süspansiyon, Fren & Yürüyen Aksam
      amortisor            = c("amortisör",        "amortisor"),
      helezon_yayi         = c("helezon yayı",     "helezon yayi", "süspansiyon yayı", "suspansiyon yayi"),
      salincak             = c("salıncak",         "salincak", "alt salıncak", "alt salincak"),
      rot_aksami           = c("rot başı",         "rot basi", "rotil", "rot kolu"),
      aks_sistemi          = c("aks",              "aks mili", "aks kafası", "aks kafasi", "aks körüğü", "aks korugu"),
      porya_rulman         = c("porya",            "tekerlek bilyası", "tekerlek bilyasi", "tekerlek rulmanı"),
      z_rot_viraj          = c("z rot",            "z rotu", "viraj demiri", "viraj çubuğu", "viraj cubugu"),
      direksiyon_kutusu    = c("direksiyon kutusu", "direksiyon pompası", "direksiyon pompasi", "kramayer"),
      fren_diski           = c("fren diski",       "fren aynası", "fren aynasi", "kampana"),
      fren_kaliperi        = c("fren kaliperi",    "kaliper", "fren merkezi", "el freni teli"),
      triger_zinciri       = c("triger zinciri", "zincir uzaması", "zincir sesi", "sente atlaması"),
      dsg_mekatronik       = c("mekatronik arızası", "mekatronik beyni", "kavrama titremesi"),
      sunroof_sorunu       = c("sunroof", "cam tavan", "fitil sesi", "su alma", "su sızıntısı"),
      multimedya_ekran     = c("hayalet ekran", "ghost touch", "dokunmatik donması", "teyp donuyor"),
      turbo_wastegate      = c("wastegate", "şıngırtı sesi", "turbo sesi")
    ))

compound_dict <- dictionary(list(
  # Motor Çekirdek & Mekanik
  motor_arizasi = c("motor arızası", "motor arizasi"),
  yag_degisimi = c("yağ değişimi", "yag degisimi"),
  fren_pedi = c("fren pedi", "fren balata"),
  hata_kodu = c("hata kodu", "ariza kodu"),
  start_stop = c("start stop"),
  egzoz_uyarisi = c("egzoz uyarısı", "egzoz uyarisi"),
  turbo_arizasi = c("turbo arızası", "turbo arizasi"),
  bakim_zamani = c("bakım zamanı", "bakim zamani"),
  garanti_suresi = c("garanti süresi", "garanti suresi"),
  kilometre_servisi = c("km servisi", "kilometre servisi"),
  sogutma_sistemi = c("soğutma sistemi", "sogutma sistemi"),
  vites_kutusu = c("vites kutusu"),
  direksiyon_kumandasi = c("direksiyon kumandası", "direksiyon kumandasi"),
  yakit_pompasi = c("yakıt pompası", "yakit pompasi"),
  debriyaj_diski = c("debriyaj diski"),
  triger_kayisi = c("triger kayışı", "triger kayisi"),
  silindir_kapagi = c("silindir kapağı", "silindir kapagi"),
  krank_mili = c("krank mili"),
  eksantrik_mili = c("eksantrik mili"),
  motor_takozu = c("motor takozu"),
  karter = c("karter", "yağ karteri", "yag karteri"),
  subap = c("subap", "supap"),
  piston_sekman = c("piston", "sekman"),
  # Ateşleme & Elektrik
  buji = c("buji"),
  atesleme_bobini = c("ateşleme bobini", "atesleme bobini"),
  sarj_dinamosu = c("şarj dinamosu", "sarj dinamosu", "alternatör", "alternator"),
  mars_motoru = c("marş motoru", "mars motoru"),
  # Yakıt & Hava Sistemi
  enjektor = c("enjektör", "enjektor"),
  gaz_kelebegi = c("gaz kelebeği", "gaz kelebegi"),
  hava_filtresi = c("hava filtresi"),
  emme_manifoldu = c("emme manifoldu", "egzoz manifoldu"),
  # Soğutma & Yağlama
  radyator = c("radyatör", "radyator"),
  su_pompasi = c("su pompası", "su pompasi", "devirdaim pompası", "devirdaim pompasi"),
  termostat = c("termostat"),
  yag_pompasi = c("yağ pompası", "yag pompasi", "yağ filtresi", "yag filtresi"),
  # Aktarma Organları (Drivetrain)
  sanziman = c("şanzıman", "sanziman"),
  baski_balata = c("baskı balata", "baski balata"),
  volan = c("volan", "volan dişlisi", "volan dislisi"),
  # Egzoz & Emisyon
  katalitik_konvertor = c("katalitik konvertör", "katalitik konvertor"),
  egr_valfi = c("egr valfi"),
  dpf = c("dizel partikül filtresi", "dpf", "partikül filtresi", "partikul filtresi"),
  oksijen_sensoru = c("oksijen sensörü", "oksijen sensoru", "lambda sensörü", "lambda sensoru"),
  # Süspansiyon, Fren & Yürüyen Aksam
  amortisor = c("amortisör", "amortisor"),
  helezon_yayi = c("helezon yayı", "helezon yayi", "süspansiyon yayı", "suspansiyon yayi"),
  salincak = c("salıncak", "salincak", "alt salıncak", "alt salincak"),
  rot_aksami = c("rot başı", "rot basi", "rotil", "rot kolu"),
  aks_sistemi = c("aks", "aks mili", "aks kafası", "aks kafasi", "aks körüğü", "aks korugu"),
  porya_rulman = c("porya", "tekerlek bilyası", "tekerlek bilyasi", "tekerlek rulmanı"),
  z_rot_viraj = c("z rot", "z rotu", "viraj demiri", "viraj çubuğu", "viraj cubugu"),
  direksiyon_kutusu = c("direksiyon kutusu", "direksiyon pompası", "direksiyon pompasi", "kramayer"),
  fren_diski = c("fren diski", "fren aynası", "fren aynasi", "kampana"),
  fren_kaliperi = c("fren kaliperi", "kaliper", "fren merkezi", "el freni teli"),
  triger_zinciri = c("triger zinciri", "zincir uzaması", "zincir sesi", "sente atlaması"),
  dsg_mekatronik = c("mekatronik arızası", "mekatronik beyni", "kavrama titremesi"),
  sunroof_sorunu = c("sunroof", "cam tavan", "fitil sesi", "su alma", "su sızıntısı"),
  multimedya_ekran = c("hayalet ekran", "ghost touch", "dokunmatik donması", "teyp donuyor"),
  turbo_wastegate = c("wastegate", "şıngırtı sesi", "turbo sesi")
))



dfCorpusCompound <- tokens_compound(dfCorpus, compound_dict)

# ── 6. Build DFM and pre-process ──────────────────────────────────────────────

dfDfm <- dfCorpusCompound %>% dfm()

tr_stopwords <- readLines(stop_words_path, encoding = "UTF-8")

custom_stopwords <- c(
  # meta / forum language
  "konu", "mesaj", "forum", "yazan", "alıntı", "alinti", "sayfa",
  "cevap", "yorum", "link", "golftutkusu",
  # generic filler
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
  # high-frequency domain noise
  "sorun", "sorunlu", "sorunum", "sorunu", "sorununun", "sorununu",
  "aynı", "ayni",
  "olabilir",
  "hocam",
  "bi",
  "şekilde", "sekilde",
  "aracı", "araci",
  "tekrar", "tekrarlayan",
  "usta",
  "ustad",
  "bir",
  "ustadim",
  "parça", "parca",
  # cosmetic / body-damage noise – suppress from becoming FREX terms
  "tramer", "tramere", "tramerde", "gocuk", "rutus", "rotus",
  "lokal", "marspiyel", "boyanacak", "boyattim", "ppf", "kaplama", "kazadan",
  # infotainment noise
  "carplay", "rcd330", "rns510", "bluetooth", "navigasyon",
  # Selamlama & Forum Jargonu
  "selam", "merhaba", "teşekkürler", "tesekkurler", "sağol", "sagol", "sağolun", "sagolun",
  "herkese", "arkadaşlar", "arkadaslar", "günler", "gunler", "kolay", "gelsin",
  "maşallah", "masallah", "hayırlı", "hayirli", "olsun", "geçmiş", "gecmis", "eyvallah",

  # Ekstra Bağlaç & Dolgu (Fiil/Zaman/Durum)
  "yaptım", "yaptim", "ettim", "ediyor", "yapıyor", "yapiyor", "dedim", "gittim", "geldim",
  "aldım", "aldim", "bence", "sence", "böyle", "boyle", "şöyle", "soyle", "falan", "filan",
  "göre", "gore", "diye", "olarak", "olan", "olduğu", "oldugu",
  "zaman", "gün",
  "gun", "ay", "yıl", "yil",
  "kendi", "kendim", "içinde", "icinde", "üzerinde", "uzerinde",

    # Kozmetik, Kaporta & Detayling (Genişletilmiş)
    "çizik", "cizik", "boya", "boyasız", "boyasiz", "pasta", "cila", "seramik", "tampon",
    "çamurluk", "camurluk", "kaput", "tavan", "bagaj", "kapı", "kapi", "taş", "tas", "izi",
    "vuruk", "sürtme", "surtme", "yıkama", "yikama", "köpük", "kopuk", "detaylı", "detayli",

    # Multimedya & İç Aksesuar (Genişletilmiş)
    "teyp", "ekran", "multimedya", "kamera", "görüş", "gorus", "hoparlör", "hoparlor",
    "amfi", "kılıf", "kilif", "paspas", "havuz", "havuzu",

    # Alım-Satım & Piyasa Gürültüsü
    "fiyat", "satılık", "satilik", "ilan", "lira", "tl", "bin", "kuruş", "kurus",
    "pazarlık", "pazarlik", "takas", "hasar", "kaydı", "kaydi", "eksper", "ekspertiz", "ikinci", "el",
    # Kasko, Sigorta & Resmi Evrak
      "kasko", "sigorta", "poliçe", "police", "muafiyet", "muafiyetli",
      "prim", "yenileme", "acente", "tutanak", "hasarsızlık", "hasarsizlik",
      "indirim", "muayene", "tüvtürk", "tuvturk", "ruhsat", "noter"

)

preProcessing <- dfDfm %>%
  dfm_remove(tr_stopwords) %>%
  dfm_remove(custom_stopwords) %>%
  dfm_tolower(keep_acronyms = FALSE)

preProcessing <- dfm_trim(
  preProcessing,
  min_termfreq  = 2,
  termfreq_type = "count",
  max_docfreq   = 0.40, # used to be 0.85
  docfreq_type  = "prop"
)

cat("DFM dimensions after trimming:\n")
print(dim(preProcessing))

# ── 7. Convert to STM format ──────────────────────────────────────────────────

stmOp <- convert(preProcessing, to = "stm", docvars = df)
str(stmOp, max.level = 1)

# ── 8. Find optimal K  (PARALLEL) ────────────────────────────────────────────
# furrr::future_map distributes each K-fit to a separate worker.
# The STM package itself is not thread-safe for shared memory, but
# multisession (separate R processes) avoids that issue entirely.

# Search space: 15 removed because with cosmetic/infotainment filtering the
# corpus is cleaner and fewer noise-absorbing topics are needed.
K_CANDIDATES <- c(4, 6, 8, 10, 12)

cat(sprintf("Fitting %d candidate models in parallel...\n", length(K_CANDIDATES)))

stmOptimal <- tibble(K = K_CANDIDATES) %>%
  mutate(
    model = future_map(
      K,
      ~ stm(
        documents = stmOp$documents,
        vocab     = stmOp$vocab,
        data      = stmOp$meta,
        K         = .x,
        verbose   = FALSE,
        init.type = "Spectral"
      ),
      .options = furrr_options(seed = 42L)
    )
  )

stmScores <- stmOptimal %>%
  mutate(
    exclusivity       = map(model, exclusivity),
    semanticCoherence = map(model, semanticCoherence, stmOp$documents)
  ) %>%
  select(K, exclusivity, semanticCoherence)

stm_k_metrics <- stmScores %>%
  unnest(c(exclusivity, semanticCoherence)) %>%
  group_by(K) %>%
  mutate(topic = row_number()) %>%
  ungroup() %>%
  rename(semantic_coherence = semanticCoherence)

stm_k_summary <- stm_k_metrics %>%
  group_by(K) %>%
  summarise(
    exclusivity_mean = mean(exclusivity),
    semantic_coherence_mean = mean(semantic_coherence),
    exclusivity_sd = sd(exclusivity),
    semantic_coherence_sd = sd(semantic_coherence),
    .groups = "drop"
  )

# ── 9. Run final STM ──────────────────────────────────────────────────────────

# K = 10 maps cleanly onto the main mechanical systems present in the data:
# engine/oil, DSG-clutch, cooling, battery, DPF, lighting, suspension,
# brakes/ignition, HVAC/interior, electrical/sensors.
# At K = 12 the two extra topics were consistently absorbed by cosmetic and
# infotainment content (body-damage assessor threads, CarPlay threads) which
# are now filtered out above, making those extra slots unnecessary.
K_FINAL <- 20 # used to be 15, testing with 20

cat(sprintf("Fitting final STM with K = %d...\n", K_FINAL))

stmTopics <- stm(
  documents  = stmOp$documents,
  vocab      = stmOp$vocab,
  data       = stmOp$meta,
  prevalence = ~ reason + engine_group + technical_bucket,
  max.em.its = 500,
  K          = K_FINAL,
  verbose    = TRUE,
  init.type  = "Spectral"
)

summary(stmTopics)

# ── 10. Extract top terms (PROB + FREX) ───────────────────────────────────────

betaScores <- tidy(stmTopics)

topTermsProb <- betaScores %>%
  group_by(topic) %>%
  slice_max(beta, n = 10) %>%
  arrange(topic, desc(beta)) %>%
  summarise(terms_prob = paste(term, collapse = ", "))

stmLabels  <- labelTopics(stmTopics, n = 10)
frexMatrix <- stmLabels$frex

topTermsFrex <- tibble(
  topic      = seq_len(nrow(frexMatrix)),
  terms_frex = apply(frexMatrix, 1, paste, collapse = ", ")
)

topTermsCombined <- topTermsProb %>%
  left_join(topTermsFrex, by = "topic")

# Alias: downstream code that expects a `terms` column gets the FREX version
topTerms <- topTermsCombined %>% mutate(terms = terms_frex)

# Thread-level topic proportions (gamma)
gammaScores <- tidy(stmTopics, matrix = "gamma",
                    document_names = df$doc_name)

# ── 11. Estimate covariate effects  (PARALLEL) ───────────────────────────────

stmEffect <- estimateEffect(
  formula  = 1:K_FINAL ~ reason + engine_group + technical_bucket,
  stmobj   = stmTopics,
  metadata = stmOp$meta
)

effect_summary_text <- capture.output(summary(stmEffect))

engine_levels <- sort(unique(df$engine_group))

# Build tidy effect table in parallel across engine groups
effect_rows <- bind_rows(
  future_lapply(engine_levels, function(eng) {
    eff <- plot(stmEffect,
                covariate  = "engine_group",
                topics     = 1:K_FINAL,
                model      = stmTopics,
                method     = "pointestimate",
                cov.value1 = eng,
                plot       = FALSE)
    data.frame(
      engine_group = eng,
      topic        = 1:K_FINAL,
      estimate     = unlist(eff$means),
      ci_lower     = sapply(eff$cis, `[`, 1),
      ci_upper     = sapply(eff$cis, `[`, 2)
    )
  }, future.seed = TRUE)
)

# ── 12. Dominant topic per thread ────────────────────────────────────────────

dominant_topic <- gammaScores %>%
  group_by(document) %>%
  slice_max(gamma, n = 1) %>%
  rename(doc_name = document, dominant_topic = topic, topic_gamma = gamma)

df_out <- df %>%
  left_join(dominant_topic, by = "doc_name")

gamma_vector_df <- gammaScores %>%
  arrange(document, topic) %>%
  group_by(document) %>%
  summarise(
    gamma_vector = paste0("[", paste(sprintf("%.6f", gamma), collapse = ", "), "]"),
    .groups = "drop"
  ) %>%
  rename(doc_name = document)

thread_topic_vectors <- df %>%
  select(doc_name, thread_name, engine_group, mileage_mentioned, mileage_confidence) %>%
  left_join(dominant_topic %>% select(doc_name, dominant_topic), by = "doc_name") %>%
  left_join(gamma_vector_df, by = "doc_name") %>%
  select(doc_name, thread_name, engine_group, dominant_topic, mileage_mentioned, mileage_confidence, gamma_vector)

# ── 13. Consolidated output ───────────────────────────────────────────────────
# Instead of scattering 10 files, we write:
#   • stm_plots.pdf          – all diagnostic / result plots (1 document)
#   • stm_results.xlsx       – all tabular outputs as named sheets
#   • stm_top_terms_frex.csv – standalone; consumed by the LLM labeller
#   • stm_thread_topics.csv  – standalone; pipeline downstream input
#   • stm_thread_topic_vectors.csv – compact per-thread topic vectors
#   • stm_effect_summary.txt – plain-text covariate summary

out_dir <- "data/processed"
dir.create(out_dir, showWarnings = FALSE, recursive = TRUE)

# ── 13a. All plots → one PDF ─────────────────────────────────────────────────
plots_path <- file.path(out_dir, "stm_plots.pdf")
pdf(plots_path, width = 11, height = 8.5)

# Page 1 – K selection: scatter
p1 <- stmScores %>%
  unnest(c(exclusivity, semanticCoherence)) %>%
  mutate(K = as.factor(K)) %>%
  ggplot(aes(semanticCoherence, exclusivity, color = K)) +
  geom_point(size = 4, alpha = 0.8) +
  labs(title = "STM model selection – all K",
       x = "Semantic coherence", y = "Exclusivity") +
  theme_bw()
print(p1)

# Page 2 – K selection: average per K
p2 <- stmScores %>%
  unnest(c(exclusivity, semanticCoherence)) %>%
  group_by(K) %>%
  summarise(exclusivity = mean(exclusivity),
            semanticCoherence = mean(semanticCoherence)) %>%
  ggplot(aes(semanticCoherence, exclusivity,
             color = as.factor(K), label = K)) +
  geom_point(size = 4) +
  geom_text(hjust = 0, vjust = -0.5) +
  theme_bw() +
  labs(title = "Average exclusivity vs coherence per K",
       x = "Semantic coherence", y = "Exclusivity", color = "K")
print(p2)

# Page 3 – Top terms per topic (base STM plot)
plot(stmTopics, n = 8, main = paste0("Top terms per topic (K = ", K_FINAL, ")"))

# Page 4 – Expected topic prevalence bar chart
p4_data <- gammaScores %>%
  group_by(topic) %>%
  summarise(gamma = mean(gamma)) %>%
  left_join(topTerms, by = "topic") %>%
  mutate(
    label = paste0("T", topic, ": ", str_trunc(terms, 45)),
    label = reorder(label, gamma)
  )

p4 <- ggplot(p4_data, aes(label, gamma, fill = as.factor(topic))) +
  geom_col(show.legend = FALSE) +
  coord_flip() +
  theme_minimal() +
  labs(title = "Expected topic proportions – Golf Forum Issues",
       x = NULL, y = "Mean gamma")
print(p4)

# Pages 5+ – Engine-group point estimates (one page per engine)
for (eng in engine_levels) {
  plot(stmEffect,
       covariate     = "engine_group",
       topics        = 1:K_FINAL,
       model         = stmTopics,
       method        = "pointestimate",
       cov.value1    = eng,
       xlab          = "Expected topic proportion",
       main          = paste0("Topic prevalence \u2014 engine: ", eng),
       labeltype     = "custom",
       custom.labels = paste0("T", 1:K_FINAL))
}

dev.off()
cat("Saved:", plots_path, "\n")

# ── 13b. All tables → one Excel workbook ─────────────────────────────────────
xlsx_path <- file.path(out_dir, "stm_results.xlsx")

wb <- createWorkbook()

# Sheet 1 – Top terms (PROB + FREX)
addWorksheet(wb, "top_terms")
writeData(wb, "top_terms", topTermsCombined)

# Sheet 2 – Full gamma matrix (document × topic proportions)
addWorksheet(wb, "gamma_full")
writeData(wb, "gamma_full", gammaScores)

# Sheet 3 – Engine covariate effect estimates
addWorksheet(wb, "engine_effects")
writeData(wb, "engine_effects", effect_rows)

# Sheet 4 – Thread-level dominant topic assignments
addWorksheet(wb, "thread_topics")
writeData(wb, "thread_topics", df_out)

# Sheet 5 – Compact thread vectors for downstream use
addWorksheet(wb, "thread_topic_vectors")
writeData(wb, "thread_topic_vectors", thread_topic_vectors)

saveWorkbook(wb, xlsx_path, overwrite = TRUE)
cat("Saved:", xlsx_path,
  "(sheets: top_terms, gamma_full, engine_effects, thread_topics, thread_topic_vectors)\n")

# ── 13c. Standalone CSV files consumed by downstream scripts ─────────────────
frex_path   <- file.path(out_dir, "stm_top_terms_frex.csv")
thread_path <- file.path(out_dir, "stm_thread_topics.csv")
vector_path <- file.path(out_dir, "stm_thread_topic_vectors.csv")
k_metrics_path <- file.path(out_dir, "stm_k_metrics.csv")
k_summary_path <- file.path(out_dir, "stm_k_summary.csv")

write_csv(topTermsFrex, frex_path)
cat("Saved:", frex_path, "\n")

write_csv(df_out, thread_path)
cat("Saved:", thread_path, "\n")

write_csv(thread_topic_vectors, vector_path)
cat("Saved:", vector_path, "\n")

write_csv(stm_k_metrics, k_metrics_path)
cat("Saved:", k_metrics_path, "\n")

write_csv(stm_k_summary, k_summary_path)
cat("Saved:", k_summary_path, "\n")

# ── 13d. Plain-text covariate summary ────────────────────────────────────────
effect_txt_path <- file.path(out_dir, "stm_effect_summary.txt")
writeLines(effect_summary_text, effect_txt_path)
cat("Saved:", effect_txt_path, "\n")

# ── 14. Shut down parallel workers ───────────────────────────────────────────
plan(sequential)
cat("\nDone. Output files written to", out_dir, ":\n")
cat("  stm_plots.pdf          – all plots\n")
cat("  stm_results.xlsx       – all tables (5 sheets)\n")
cat("  stm_top_terms_frex.csv – FREX terms for LLM labeller\n")
cat("  stm_thread_topics.csv  – thread assignments for pipeline\n")
cat("  stm_thread_topic_vectors.csv – compact per-thread topic vectors\n")
cat("  stm_effect_summary.txt – covariate effect summary\n")


# ── 15. Generate LLM-Ready "Known Issues" Data ───────────────────────────────

cat("Generating LLM-ready issue report...\n")

# 1. Calculate Prevalence (The "Bar" length)
topic_prevalence <- gammaScores %>%
  left_join(df %>% select(doc_name, technical_score, chronic_score),
            by = c("document" = "doc_name")) %>%
  mutate(
    technical_score = replace_na(technical_score, 0L),
    chronic_score = replace_na(chronic_score, 0L),
    focus_weight = pmax(1, technical_score + (2 * chronic_score))
  ) %>%
  group_by(topic) %>%
  summarise(
    prevalence = mean(gamma),
    prevalence_tech = weighted.mean(gamma, w = focus_weight, na.rm = TRUE),
    technical_signal = weighted.mean(technical_score, w = gamma, na.rm = TRUE),
    chronic_signal = weighted.mean(chronic_score, w = gamma, na.rm = TRUE)
  )

# 2. Calculate Mileage Range per Topic
# We look at threads where the topic is the dominant one (> 30% gamma)
topic_mileage <- gammaScores %>%
  filter(gamma > 0.3) %>%
  left_join(df %>% select(doc_name, mileage_mentioned), by = c("document" = "doc_name")) %>%
  filter(!is.na(mileage_mentioned)) %>%
  group_by(topic) %>%
  summarise(
    min_km = quantile(mileage_mentioned, 0.2, na.rm = TRUE),
    max_km = quantile(mileage_mentioned, 0.8, na.rm = TRUE),
    avg_km = median(mileage_mentioned, na.rm = TRUE)
  )

# 3. Get Representative Snippets for Narrative Context
# For each topic, find top 3 threads and grab the first 200 characters
top_snippets <- gammaScores %>%
  left_join(df %>% select(doc_name, txt, technical_score, chronic_score),
            by = c("document" = "doc_name")) %>%
  mutate(
    technical_score = replace_na(technical_score, 0L),
    chronic_score = replace_na(chronic_score, 0L),
    rank_score = gamma * (1 + pmin(technical_score + (2 * chronic_score), 8) / 8)
  ) %>%
  group_by(topic) %>%
  slice_max(rank_score, n = 3, with_ties = FALSE) %>%
  mutate(snippet = paste0("[...", substr(txt, 1, 300), "...]")) %>%
  group_by(topic) %>%
  summarise(representative_text = paste(snippet, collapse = " | "))

# 4. Combine everything into one "LLM Input" Table
llm_report_data <- topTermsCombined %>%
  select(topic, terms_frex) %>%
  left_join(topic_prevalence, by = "topic") %>%
  left_join(topic_mileage, by = "topic") %>%
  left_join(top_snippets, by = "topic") %>%
  mutate(
    prevalence_blended = (0.55 * prevalence) + (0.45 * prevalence_tech),
    prevalence_pct = round(prevalence_blended * 100, 1),
    mileage_range = paste0(round(min_km, -3), " - ", round(max_km, -3), " km")
  )

# Write to CSV
llm_report_path <- file.path(out_dir, "llm_issue_input.csv")
write_csv(llm_report_data, llm_report_path)

cat("Saved:", llm_report_path, "\n")

# ── 16. Step 1 exports ────────────────────────────────────────────────────────

# ─ 16a. Derive year, displacement, mileage_bucket on df_out ──────────────────
df_out <- df_out %>%
  mutate(
    # Year: thread_name is prepended so it wins on first-match
    year = as.integer(
      str_extract(str_c(thread_name, " ", txt),
                  "\\b(200[0-9]|201[0-9]|202[0-4])\\b")
    ),
    # Displacement: parse leading "N.N" from engine_group label (NA for unknown/other)
    displacement = str_extract(engine_group, "^[0-9]\\.[0-9]"),
    # Fuel type: TDI → diesel, TSI/GTI/GTE → petrol, else unknown
    fuel_type = case_when(
      str_detect(engine_group, "TDI")       ~ "diesel",
      str_detect(engine_group, "TSI|GTI|GTE") ~ "petrol",
      TRUE                                  ~ "unknown"
    ),
    # Mileage bucket – 30 k intervals, last bucket 210 k+
    mileage_bucket = case_when(
      is.na(mileage_mentioned)   ~ "unknown",
      mileage_mentioned <  30000 ~ "0-30k",
      mileage_mentioned <  60000 ~ "30-60k",
      mileage_mentioned <  90000 ~ "60-90k",
      mileage_mentioned < 120000 ~ "90-120k",
      mileage_mentioned < 150000 ~ "120-150k",
      mileage_mentioned < 180000 ~ "150-180k",
      mileage_mentioned < 210000 ~ "180-210k",
      TRUE                       ~ "210k+"
    )
  )

# ─ 16b. Export A: stm_thread_enriched.csv ────────────────────────────────────
stm_thread_enriched <- df_out %>%
  left_join(gamma_vector_df, by = "doc_name") %>%
  select(
    doc_name, thread_name, thread_url,
    dominant_topic, topic_gamma,
    displacement, fuel_type, year,
    mileage_km = mileage_mentioned, mileage_bucket,
    engine_group, technical_bucket, chronic_score, n_messages,
    gamma_vector
  )

enriched_path <- file.path(out_dir, "stm_thread_enriched.csv")
write_csv(stm_thread_enriched, enriched_path)
cat("Saved:", enriched_path, "\n")

# ─ 16c. Export B: stm_topic_engine_effects.csv ───────────────────────────────
stm_topic_engine_effects <- effect_rows %>%
  mutate(significant = (ci_lower > 0) | (ci_upper < 0))

effects_path <- file.path(out_dir, "stm_topic_engine_effects.csv")
write_csv(stm_topic_engine_effects, effects_path)
cat("Saved:", effects_path, "\n")
