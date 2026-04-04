#!/usr/bin/env Rscript

suppressPackageStartupMessages({
  library(stm)
  library(tidyverse)
  library(readr)
  library(quanteda)
  library(openxlsx)
})

get_script_dir <- function() {
  cmd_args <- commandArgs(trailingOnly = FALSE)
  file_arg <- grep("^--file=", cmd_args, value = TRUE)
  if (length(file_arg) > 0) {
    return(dirname(normalizePath(sub("^--file=", "", file_arg[1]), winslash = "/")))
  }
  getwd()
}

ROOT <- get_script_dir()
PROCESSED_DIR <- file.path(ROOT, "data", "processed")
input_candidates <- c(
  file.path(ROOT, "data", "processed", "forums", "cleaned_messages_clio.csv"),
  file.path(ROOT, "cleaned_messages_clio.csv")
)
INPUT_CSV <- input_candidates[file.exists(input_candidates)][1]
STOPWORDS_FILE <- file.path(ROOT, "turkce-stop-words.txt")

if (is.na(INPUT_CSV)) {
  stop("Input CSV not found. Checked: data/processed/forums/cleaned_messages_clio.csv and cleaned_messages_clio.csv")
}
cat(sprintf("Using input: %s\n", INPUT_CSV))

dir.create(PROCESSED_DIR, recursive = TRUE, showWarnings = FALSE)

to_int_km <- function(x) {
  if (is.na(x) || x == "") return(NA_integer_)
  as.integer(gsub("[^0-9]", "", as.character(x)))
}

extract_mileage_info <- function(text) {
  if (is.na(text) || text == "") {
    return(list(km = NA_integer_, confidence = "none"))
  }

  t <- stringr::str_to_lower(text)

  m <- stringr::str_match(
    t,
    "\\b(\\d{1,3})\\s*[-\\u2013]\\s*(\\d{1,3})\\s*(k|bin)\\s*(?:km|kilometre|kilometrede|kilometresi)?\\b"
  )
  if (!is.na(m[1, 1])) {
    lo <- to_int_km(m[1, 2])
    if (!is.na(lo)) return(list(km = lo * 1000L, confidence = "range"))
  }

  m <- stringr::str_match(
    t,
    "\\b(\\d{1,3})\\s*(k|bin)\\s*(?:km|kilometre|kilometrede|kilometresi)?\\b"
  )
  if (!is.na(m[1, 1])) {
    base <- to_int_km(m[1, 2])
    if (!is.na(base)) return(list(km = base * 1000L, confidence = "medium"))
  }

  m <- stringr::str_match(
    t,
    "\\b(\\d{1,3}(?:[\\.,]\\d{3})+|\\d{4,})\\s*(?:km|kilometre|kilometrede|kilometresi)\\b"
  )
  if (!is.na(m[1, 1])) {
    return(list(km = to_int_km(m[1, 2]), confidence = "high"))
  }

  list(km = NA_integer_, confidence = "none")
}

extract_year <- function(text) {
  if (is.na(text) || text == "") return(NA_integer_)
  m <- stringr::str_match_all(
    stringr::str_to_lower(text),
    "\\b(199[6-9]|200\\d|201\\d|202[0-6])\\b"
  )[[1]]
  if (nrow(m) == 0) return(NA_integer_)
  as.integer(m[1, 2])
}

count_pattern_hits <- function(text, patterns) {
  if (is.na(text) || text == "") return(0L)
  txt <- stringr::str_to_lower(text)
  sum(vapply(patterns, function(p) stringr::str_detect(txt, p), logical(1)))
}

TECHNICAL_PATTERNS <- c(
  "\\bmotor\\b", "\\byag\\b", "\\beksiltme\\b", "\\bturbo\\b", "\\bintercooler\\b",
  "\\btriger\\b", "\\bzincir\\b", "\\bdevirdaim\\b", "\\btermostat\\b",
  "\\bhararet\\b", "\\bradyator\\b", "\\bsogutma\\b", "\\benjektor\\b",
  "\\bdpf\\b", "\\begr\\b", "\\badblue\\b", "\\bkizdirma\\b",
  "\\bsanziman\\b", "\\bvites\\b", "\\bdebriyaj\\b", "\\bkavrama\\b", "\\bmekatronik\\b",
  "\\bbobin\\b", "\\bbuji\\b", "\\bsensor\\b", "\\brolanti\\b", "\\btekleme\\b"
)

CHRONIC_PATTERNS <- c(
  "\\bkronik\\b", "\\bsurekli\\b", "\\btekrar\\b", "\\btekrarlayan\\b",
  "\\bduzelmedi\\b", "\\bcozulmedi\\b", "\\bdevam\\s+ediyor\\b"
)

COSMETIC_PATTERNS <- c(
  "\\bkaporta\\b", "\\bboya\\b", "\\bgocuk\\b", "\\bcizik\\b", "\\btramer\\b",
  "\\bpasta\\s*cila\\b", "\\bdetailing\\b", "\\bppf\\b"
)

INFOTAINMENT_PATTERNS <- c(
  "\\bmultimedya\\b", "\\bcarplay\\b", "\\bandroid\\s*auto\\b",
  "\\bbluetooth\\b", "\\bnavigasyon\\b", "\\bteyp\\b"
)

ENGINE_ORDER <- c(
  "0.9_TCE", "1.0_TCE", "1.2_TCE", "1.3_TCE",
  "1.5_DCI", "1.6_DCI", "1.4_NA", "1.6_NA",
  "TCE_unknown", "DCI_unknown", "CLIO_II", "CLIO_III", "CLIO_IV", "CLIO_V", "unknown"
)

required_cols <- c("thread_name", "thread_url", "message")
df_raw <- read_csv(INPUT_CSV, show_col_types = FALSE)
missing_cols <- setdiff(required_cols, names(df_raw))
if (length(missing_cols) > 0) {
  stop(sprintf("Missing required columns in %s: %s", INPUT_CSV, paste(missing_cols, collapse = ", ")))
}

if (!("engine_code" %in% names(df_raw))) df_raw$engine_code <- "unknown"
if (!("engine_spec" %in% names(df_raw))) df_raw$engine_spec <- "unknown"
if (!("prod_year" %in% names(df_raw))) df_raw$prod_year <- NA_character_
if (!("reason" %in% names(df_raw))) df_raw$reason <- NA_character_

cat(sprintf("Loaded rows: %d\n", nrow(df_raw)))

df <- df_raw %>%
  mutate(prod_year_num = suppressWarnings(as.integer(prod_year))) %>%
  group_by(thread_name, thread_url) %>%
  summarise(
    txt = paste(message, collapse = " "),
    reason = first(reason),
    engine_code = first(engine_code),
    engine_spec = first(engine_spec),
    prod_year = first(prod_year_num),
    mileage_pick = list({
      infos <- lapply(message, extract_mileage_info)
      km_vals <- vapply(infos, function(x) x$km, numeric(1))
      idx <- which(!is.na(km_vals))
      if (length(idx) == 0) list(km = NA_integer_, confidence = "none") else infos[[idx[1]]]
    }),
    n_messages = n(),
    .groups = "drop"
  ) %>%
  mutate(
    engine_code = if_else(is.na(engine_code) | engine_code == "", "unknown", engine_code),
    engine_spec = if_else(is.na(engine_spec) | engine_spec == "", "unknown", engine_spec),
    mileage_km = as.integer(vapply(mileage_pick, function(x) x$km, numeric(1))),
    mileage_confidence = vapply(mileage_pick, function(x) x$confidence, character(1)),
    year = if_else(!is.na(prod_year), as.integer(prod_year), as.integer(vapply(txt, extract_year, integer(1)))),
    doc_id = row_number(),
    doc_name = sprintf("doc_%05d", doc_id)
  ) %>%
  select(-mileage_pick)

df <- df %>%
  mutate(
    engine_group = case_when(
      engine_spec %in% ENGINE_ORDER ~ engine_spec,
      engine_code %in% c("CLIO_II", "CLIO_III", "CLIO_IV", "CLIO_V") ~ engine_code,
      TRUE ~ "unknown"
    )
  )

df <- df %>%
  mutate(
    technical_score = vapply(txt, count_pattern_hits, integer(1), patterns = TECHNICAL_PATTERNS),
    chronic_score = vapply(txt, count_pattern_hits, integer(1), patterns = CHRONIC_PATTERNS),
    cosmetic_score = vapply(txt, count_pattern_hits, integer(1), patterns = COSMETIC_PATTERNS),
    infotainment_score = vapply(txt, count_pattern_hits, integer(1), patterns = INFOTAINMENT_PATTERNS),
    focus_score = technical_score + (2L * chronic_score) - pmin(cosmetic_score, 3L),
    technical_bucket = factor(
      if_else(focus_score >= 4L, "high", if_else(focus_score >= 2L, "medium", "low")),
      levels = c("low", "medium", "high")
    )
  )

pre_filter_n <- nrow(df)
df <- df %>%
  filter(focus_score >= 2L) %>%
  filter(!(cosmetic_score > pmax(1L, technical_score) & technical_score < 2L)) %>%
  filter(!(infotainment_score > 3L & technical_score < 1L))

cat(sprintf("Filtered %d low-signal/cosmetic/infotainment threads (%d -> %d)\n", pre_filter_n - nrow(df), pre_filter_n, nrow(df)))

if (nrow(df) < 20) {
  stop("Too few thread-level documents after filtering (<20). Scrape more data before STM.")
}

df$txt <- stringr::str_to_lower(df$txt)

tr_stopwords <- if (file.exists(STOPWORDS_FILE)) {
  readLines(STOPWORDS_FILE, encoding = "UTF-8")
} else {
  character(0)
}

custom_stopwords <- c(
  "clio", "renault", "arac", "araba", "forum", "arkadaslar", "arkadas",
  "merhaba", "tesekkur", "hocam", "abi", "model", "kasa"
)

corp_tokens <- tokens(
  df$txt,
  remove_punct = TRUE,
  remove_numbers = FALSE,
  remove_symbols = TRUE,
  remove_url = TRUE
)

dfm_obj <- corp_tokens %>%
  dfm() %>%
  dfm_remove(c(tr_stopwords, custom_stopwords), case_insensitive = TRUE, valuetype = "fixed")

min_tf <- if (nrow(df) >= 400) 3 else 2
min_df <- if (nrow(df) >= 250) 2 else 1

dfm_obj <- dfm_trim(dfm_obj, min_termfreq = min_tf, min_docfreq = min_df)

non_empty <- ntoken(dfm_obj) > 0
if (!any(non_empty)) {
  stop("No non-empty documents remain after tokenization.")
}

dfm_obj <- dfm_obj[non_empty, ]
df <- df[non_empty, ]

stm_input <- convert(dfm_obj, to = "stm")
prep <- prepDocuments(stm_input$documents, stm_input$vocab, df, lower.thresh = 1)

docs <- prep$documents
vocab <- prep$vocab
meta <- prep$meta

n_docs <- nrow(meta)
if (n_docs < 20) {
  stop("Too few documents after STM prep (<20).")
}

has_engine_var <- length(unique(meta$engine_group)) > 1
has_bucket_var <- length(unique(meta$technical_bucket)) > 1

prevalence_formula <- ~ 1
if (has_engine_var && has_bucket_var) {
  prevalence_formula <- ~ engine_group + technical_bucket
} else if (has_engine_var) {
  prevalence_formula <- ~ engine_group
} else if (has_bucket_var) {
  prevalence_formula <- ~ technical_bucket
}

if (n_docs >= 500) {
  k_final <- 15L
} else if (n_docs >= 250) {
  k_final <- 12L
} else {
  k_final <- 10L
}

k_final <- min(k_final, max(5L, as.integer(floor(n_docs / 4L))))
k_final <- max(5L, k_final)

k_candidates <- unique(sort(c(max(5L, k_final - 3L), k_final)))

cat(sprintf("Documents after prep: %d\n", n_docs))
cat(sprintf("K candidates: %s | K final: %d\n", paste(k_candidates, collapse = ", "), k_final))

k_metrics_path <- file.path(PROCESSED_DIR, "stm_k_metrics_clio.csv")
if (n_docs >= 120 && length(k_candidates) > 1) {
  k_result <- searchK(
    documents = docs,
    vocab = vocab,
    K = k_candidates,
    prevalence = prevalence_formula,
    data = meta,
    init.type = "Spectral",
    cores = 1L
  )
  k_metrics <- as_tibble(k_result$results)
} else {
  k_metrics <- tibble(
    K = k_candidates,
    exclus = NA_real_,
    semcoh = NA_real_,
    heldout = NA_real_,
    residual = NA_real_,
    bound = NA_real_,
    lbound = NA_real_,
    em.its = NA_real_
  )
}
write_csv(k_metrics, k_metrics_path)

stm_model <- stm(
  documents = docs,
  vocab = vocab,
  data = meta,
  K = k_final,
  prevalence = prevalence_formula,
  init.type = "Spectral",
  max.em.its = 300,
  verbose = TRUE
)

labels <- labelTopics(stm_model, n = 15)
top_terms <- tibble(
  topic = seq_len(k_final),
  terms_prob = apply(labels$prob, 1, function(x) paste(x, collapse = ", ")),
  terms_frex = apply(labels$frex, 1, function(x) paste(x, collapse = ", "))
)

write_csv(top_terms %>% select(topic, terms_frex), file.path(PROCESSED_DIR, "stm_top_terms_frex_clio.csv"))

gamma_wide <- as.data.frame(stm_model$theta)
colnames(gamma_wide) <- paste0("T", seq_len(ncol(gamma_wide)))
gamma_wide$doc_name <- meta$doc_name

gamma_long <- gamma_wide %>%
  pivot_longer(cols = starts_with("T"), names_to = "topic", values_to = "gamma") %>%
  mutate(topic = as.integer(sub("T", "", topic)))

dominant <- gamma_long %>%
  group_by(doc_name) %>%
  slice_max(order_by = gamma, n = 1, with_ties = FALSE) %>%
  ungroup() %>%
  rename(dominant_topic = topic, topic_gamma = gamma)

gamma_vector <- gamma_wide %>%
  mutate(
    gamma_vector = apply(
      select(., starts_with("T")),
      1,
      function(x) paste0("[", paste(sprintf("%.6f", x), collapse = ", "), "]")
    )
  ) %>%
  select(doc_name, gamma_vector)

thread_enriched <- meta %>%
  left_join(dominant, by = "doc_name") %>%
  left_join(gamma_vector, by = "doc_name")

write_csv(thread_enriched, file.path(PROCESSED_DIR, "stm_thread_enriched_clio.csv"))
write_csv(dominant, file.path(PROCESSED_DIR, "stm_thread_topics_clio.csv"))
write_csv(gamma_wide, file.path(PROCESSED_DIR, "stm_thread_topic_vectors_clio.csv"))

effect_path <- file.path(PROCESSED_DIR, "stm_topic_engine_effects_clio.csv")
effect_rows <- tibble(
  engine_group = character(),
  topic = integer(),
  estimate = numeric(),
  ci_lower = numeric(),
  ci_upper = numeric(),
  significant = logical()
)

if (has_engine_var) {
  effect_formula <- if (has_bucket_var) {
    as.formula(paste0("1:", k_final, " ~ engine_group + technical_bucket"))
  } else {
    as.formula(paste0("1:", k_final, " ~ engine_group"))
  }

  stm_effect <- estimateEffect(
    effect_formula,
    stmobj = stm_model,
    metadata = meta
  )

  tmp_rows <- list()
  for (eng in sort(unique(meta$engine_group))) {
    pe <- tryCatch(
      plot(
        stm_effect,
        covariate = "engine_group",
        topics = seq_len(k_final),
        model = stm_model,
        method = "pointestimate",
        cov.value1 = eng,
        plot = FALSE
      ),
      error = function(e) NULL
    )

    if (is.null(pe)) next

    means <- if (is.list(pe$means)) vapply(pe$means, function(x) as.numeric(x[[1]]), numeric(1)) else as.numeric(pe$means)
    cis <- pe$cis
    if (is.list(cis)) {
      ci_lower <- vapply(cis, function(x) as.numeric(x[1]), numeric(1))
      ci_upper <- vapply(cis, function(x) as.numeric(x[2]), numeric(1))
    } else {
      ci_lower <- as.numeric(cis[, 1])
      ci_upper <- as.numeric(cis[, 2])
    }

    tmp_rows[[length(tmp_rows) + 1]] <- tibble(
      engine_group = eng,
      topic = seq_len(k_final),
      estimate = means,
      ci_lower = ci_lower,
      ci_upper = ci_upper,
      significant = (ci_lower > 0) | (ci_upper < 0)
    )
  }

  if (length(tmp_rows) > 0) effect_rows <- bind_rows(tmp_rows)
}

write_csv(effect_rows, effect_path)

safe_quantile <- function(x, q) {
  as.integer(stats::quantile(x, probs = q, na.rm = TRUE, names = FALSE))
}

topic_prevalence <- gamma_long %>%
  group_by(topic) %>%
  summarise(prevalence_pct = round(mean(gamma) * 100, 2), .groups = "drop")

dominant_counts <- dominant %>%
  count(dominant_topic, name = "thread_count") %>%
  rename(topic = dominant_topic)

topic_stats <- gamma_long %>%
  left_join(meta %>% select(doc_name, chronic_score, mileage_km), by = "doc_name") %>%
  group_by(topic) %>%
  summarise(
    chronic_signal = round(weighted.mean(chronic_score, gamma, na.rm = TRUE), 3),
    mileage_thread_count = sum(!is.na(mileage_km) & gamma > 0.3),
    mileage_median_km = if_else(
      mileage_thread_count >= 5,
      as.integer(median(mileage_km[gamma > 0.3], na.rm = TRUE)),
      NA_integer_
    ),
    mileage_p20_km = if_else(
      mileage_thread_count >= 5,
      safe_quantile(mileage_km[gamma > 0.3], 0.2),
      NA_integer_
    ),
    mileage_p80_km = if_else(
      mileage_thread_count >= 5,
      safe_quantile(mileage_km[gamma > 0.3], 0.8),
      NA_integer_
    ),
    .groups = "drop"
  )

llm_issue_input <- top_terms %>%
  select(topic, terms_frex, terms_prob) %>%
  left_join(topic_prevalence, by = "topic") %>%
  left_join(dominant_counts, by = "topic") %>%
  left_join(topic_stats, by = "topic") %>%
  arrange(topic) %>%
  mutate(
    thread_count = replace_na(thread_count, 0L),
    chronic_signal = replace_na(chronic_signal, 0)
  )

write_csv(llm_issue_input, file.path(PROCESSED_DIR, "llm_issue_input_clio.csv"))

gamma_export <- gamma_long %>%
  mutate(document = doc_name) %>%
  select(document, doc_name, topic, gamma)

wb <- createWorkbook()
addWorksheet(wb, "top_terms")
addWorksheet(wb, "gamma_full")
addWorksheet(wb, "thread_topics")

writeData(wb, "top_terms", top_terms)
writeData(wb, "gamma_full", gamma_export)
writeData(wb, "thread_topics", thread_enriched)

xlsx_path <- file.path(PROCESSED_DIR, "stm_results_clio.xlsx")
saveWorkbook(wb, xlsx_path, overwrite = TRUE)

cat("\nOutputs written:\n")
cat(sprintf(" - %s\n", file.path(PROCESSED_DIR, "stm_k_metrics_clio.csv")))
cat(sprintf(" - %s\n", file.path(PROCESSED_DIR, "stm_top_terms_frex_clio.csv")))
cat(sprintf(" - %s\n", file.path(PROCESSED_DIR, "stm_thread_enriched_clio.csv")))
cat(sprintf(" - %s\n", file.path(PROCESSED_DIR, "stm_topic_engine_effects_clio.csv")))
cat(sprintf(" - %s\n", file.path(PROCESSED_DIR, "llm_issue_input_clio.csv")))
cat(sprintf(" - %s\n", xlsx_path))
