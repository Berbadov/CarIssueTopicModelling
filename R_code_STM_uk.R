# STM Analysis – Golf GTI Forum UK Issue Extraction
# Source: https://www.golfgtiforum.co.uk/index.php?board=117.0
# Goal: extract recurring car issues/topics from English forum messages
#       with mileage and metadata as covariates.
#
# Install missing packages:
#   install.packages(c("stm","tidytext","tidyverse","readr","quanteda",
#                      "quanteda.textstats","furrr","future","future.apply","openxlsx"))

library(stm)
library(tidytext)
library(tidyverse)
library(readr)
library(quanteda)
library(quanteda.textstats)
library(furrr)
library(future)
library(future.apply)
library(openxlsx)

# Resolve namespace conflicts: dplyr::filter / dplyr::lag get masked by stats
# when stm or other packages are loaded. Pin them explicitly.
filter <- dplyr::filter
lag    <- dplyr::lag

# ── 0. Parallelism ────────────────────────────────────────────────────────────
n_workers <- max(1L, parallel::detectCores() - 1L)
plan(multisession, workers = n_workers)
cat(sprintf("Parallel workers: %d\n", n_workers))

# ── 1. Load data ──────────────────────────────────────────────────────────────

df_raw <- read_csv("cleaned_messages_uk.csv", show_col_types = FALSE)

# ── 1a. Mileage extraction (miles-first, also handles km) ────────────────────

to_int <- function(x) {
  if (is.na(x) || x == "") return(NA_integer_)
  as.integer(gsub("[^0-9]", "", x))
}

extract_mileage_info <- function(text) {
  if (is.na(text) || text == "") return(list(miles = NA_integer_, confidence = "none"))
  t <- stringr::str_to_lower(text)

  # "50k miles", "50k mls", "50k mi", "50K"
  m <- stringr::str_match(t, "\\b(\\d{1,3})\\s*k\\s*(?:miles?|mls?|mi)?\\b")
  if (!is.na(m[1,1])) {
    base <- to_int(m[1,2])
    if (!is.na(base)) return(list(miles = base * 1000L, confidence = "high"))
  }

  # "50,000 miles", "50000 miles"
  m <- stringr::str_match(t, "\\b(\\d{1,3}(?:[,.]\\d{3})+|\\d{4,})\\s*(?:miles?|mls?)\\b")
  if (!is.na(m[1,1])) return(list(miles = to_int(m[1,2]), confidence = "high"))

  # "65000 on the clock"
  m <- stringr::str_match(t, "\\b(\\d{4,})\\s+on\\s+(?:the\\s+)?clock\\b")
  if (!is.na(m[1,1])) return(list(miles = to_int(m[1,2]), confidence = "medium"))

  # "mileage: 65000"
  m <- stringr::str_match(t, "\\bmileage\\s*[:=]?\\s*(\\d{4,})\\b")
  if (!is.na(m[1,1])) return(list(miles = to_int(m[1,2]), confidence = "medium"))

  # km fallback (convert to miles ÷ 1.609)
  m <- stringr::str_match(t, "\\b(\\d{1,3}(?:[,.]\\d{3})+|\\d{4,})\\s*km\\b")
  if (!is.na(m[1,1])) {
    km <- to_int(m[1,2])
    if (!is.na(km)) return(list(miles = as.integer(km / 1.609), confidence = "low"))
  }

  list(miles = NA_integer_, confidence = "none")
}

# ── Pattern sets (English) ────────────────────────────────────────────────────

TECHNICAL_PATTERNS <- c(
  "\\bengine\\b", "\\bgearbox\\b", "\\btransmission\\b", "\\bclutch\\b",
  "\\bturbo\\b", "\\binjector\\b", "\\btiming\\b", "\\bcambelt\\b",
  "\\btiming chain\\b", "\\btiming belt\\b", "\\bthermostat\\b",
  "\\bwater pump\\b", "\\bradiator\\b", "\\bdpf\\b", "\\begr\\b",
  "\\babs\\b", "\\besp\\b", "\\bspark plug\\b", "\\bcoilpack\\b",
  "\\bcoil pack\\b", "\\bbrakes?\\b", "\\bpads?\\b", "\\bdisc\\b",
  "\\bshock absorber\\b", "\\bwishbone\\b", "\\bsteering\\b",
  "\\bsensor\\b", "\\boil\\b", "\\bleak\\b", "\\bnoise\\b",
  "\\bvibration\\b", "\\bknock\\b", "\\bsmoke\\b", "\\bmisfire\\b",
  "\\blimp mode\\b", "\\bfault code\\b", "\\bvcds\\b", "\\bdsg\\b",
  "\\bflywheel\\b", "\\bdmf\\b", "\\bcoolant\\b", "\\boverheating\\b"
)

CHRONIC_PATTERNS <- c(
  "\\bkeeps?\\b", "\\bstill\\b", "\\brecurring\\b", "\\bpersistent\\b",
  "\\bongoing\\b", "\\bagain\\b", "\\brepeat\\b", "\\bunresolved\\b",
  "\\bnever fixed\\b", "\\bkeep having\\b", "\\bhappens again\\b",
  "\\bback again\\b", "\\bstill happening\\b"
)

COSMETIC_PATTERNS <- c(
  "\\brespray\\b", "\\bpaintwork\\b", "\\bbodywork\\b",
  "\\bdent\\b", "\\bscratch\\b", "\\bscuff\\b",
  "\\bppf\\b", "\\bdetailing\\b", "\\bpolish\\b",
  "\\balloy refurb\\b", "\\bpanel\\b"
)

INFOTAINMENT_PATTERNS <- c(
  "\\bcarplay\\b", "\\bandroid auto\\b", "\\bbluetooth\\b",
  "\\bsat nav\\b", "\\binfotainment\\b", "\\bhead unit\\b",
  "\\btouchscreen\\b", "\\bdab\\b"
)

count_pattern_hits <- function(text, patterns) {
  if (is.na(text) || text == "") return(0L)
  txt <- stringr::str_to_lower(text)
  sum(vapply(patterns, function(p) stringr::str_detect(txt, p), logical(1)))
}

# ── 2. Aggregate to thread level ──────────────────────────────────────────────

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
        cosm <- vapply(msgs, count_pattern_hits, integer(1), patterns = COSMETIC_PATTERNS)
        tech <- vapply(msgs, count_pattern_hits, integer(1), patterns = TECHNICAL_PATTERNS)
        keep <- c(TRUE, (cosm[-1L] < 2L) & (tech[-1L] > 0L | cosm[-1L] == 0L))
        filtered <- msgs[keep]
        if (length(filtered) == 0L) filtered <- msgs[1L]
        paste(c(filtered[1L], filtered), collapse = " ")
      }
    },
    reason      = first(reason),
    engine_code = first(engine_code),
    mileage_pick = list({
      infos   <- lapply(message, extract_mileage_info)
      mi_vals <- vapply(infos, function(x) x$miles, integer(1))
      idx     <- which(!is.na(mi_vals))
      if (length(idx) == 0) list(miles = NA_integer_, confidence = "none")
      else infos[[idx[1]]]
    }),
    n_messages = n(),
    .groups    = "drop"
  ) %>%
  mutate(
    mileage_mentioned  = vapply(mileage_pick, function(x) x$miles,      integer(1)),
    mileage_confidence = vapply(mileage_pick, function(x) x$confidence, character(1))
  ) %>%
  select(-mileage_pick) %>%
  mutate(
    doc_id   = row_number(),
    doc_name = sprintf("doc_%05d", doc_id)
  )

technical_reason_tags <- c("engine", "gearbox", "transmission", "brake", "electrical",
                            "cooling", "suspension", "exhaust", "turbo", "clutch")

df <- df %>%
  mutate(
    technical_score    = vapply(txt, count_pattern_hits, integer(1), patterns = TECHNICAL_PATTERNS),
    chronic_score      = vapply(txt, count_pattern_hits, integer(1), patterns = CHRONIC_PATTERNS),
    cosmetic_score     = vapply(txt, count_pattern_hits, integer(1), patterns = COSMETIC_PATTERNS),
    infotainment_score = vapply(txt, count_pattern_hits, integer(1), patterns = INFOTAINMENT_PATTERNS),
    reason_lower       = stringr::str_to_lower(replace_na(reason, "")),
    reason_technical_hint = if_else(
      stringr::str_detect(reason_lower, paste(technical_reason_tags, collapse = "|")), 1L, 0L
    ),
    focus_score = technical_score + (2L * chronic_score) + reason_technical_hint
                  - pmin(cosmetic_score, 3L),
    technical_bucket = factor(
      if_else(focus_score >= 4L, "high", if_else(focus_score >= 2L, "medium", "low")),
      levels = c("low", "medium", "high")
    )
  ) %>%
  select(-reason_lower)

# ── 2a. Collapse rare engine codes ────────────────────────────────────────────

df <- df %>%
  mutate(engine_group = case_when(
    engine_code %in% c("MK8")               ~ "MK8",
    engine_code %in% c("MK7.5")             ~ "MK7.5",
    engine_code %in% c("MK7")               ~ "MK7",
    engine_code %in% c("MK6")               ~ "MK6",
    engine_code %in% c("MK5")               ~ "MK5",
    engine_code %in% c("2.0_TSI", "EA888")  ~ "2.0_TSI",
    engine_code %in% c("1.4_TSI", "EA211")  ~ "1.4_TSI",
    engine_code %in% c("Golf_R")            ~ "Golf_R",
    engine_code == "unknown"                ~ "unknown",
    TRUE                                    ~ "other"
  ))

# ── 2b. Filter cosmetic / infotainment dominated threads ──────────────────────
nrow_before <- nrow(df)
df <- df %>%
  filter(!(cosmetic_score     > pmax(1L, technical_score) & technical_score < 2L)) %>%
  filter(!(infotainment_score > 3L & technical_score < 1L))

cat(sprintf(
  "Pre-STM noise filter: removed %d threads (%d -> %d)\n",
  nrow_before - nrow(df), nrow_before, nrow(df)
))

cat("Engine group distribution:\n");  print(table(df$engine_group))
cat("Technical focus bucket:\n");     print(table(df$technical_bucket))
cat("Threads (documents):", nrow(df), "\n")

# ── 3. Text normalisation ─────────────────────────────────────────────────────

df$txt <- tolower(df$txt)

# ── 3.5 Stop-words ────────────────────────────────────────────────────────────

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

# Use quanteda's built-in English stopwords; optionally supplement with a file
en_stopwords <- quanteda::stopwords("en")

# Extra forum / domain-specific stopwords
extra_stopwords <- c(
  # Forum meta
  "post", "thread", "forum", "reply", "quote", "edited", "page",
  "member", "joined", "posts", "golfgtiforum",
  # Generic filler that survives standard stopword lists
  "just", "also", "get", "got", "know", "think", "would", "could",
  "really", "thing", "bit", "lot", "way", "time", "one", "two",
  "going", "going", "like", "use", "used", "using", "new", "old",
  "car", "golf", "gti",   # too generic for topic discrimination
  # Common forum phrases
  "anyone", "anyone else", "lol", "cheers", "thanks", "mate",
  "tbh", "imo", "afaik", "iirc", "fwiw"
)

all_stopwords <- unique(c(en_stopwords, extra_stopwords))

# ── 4. Bigram / collocation discovery ────────────────────────────────────────

dfToken  <- quanteda::tokens(df$txt)
dfBigram <- dfToken %>%
  quanteda::tokens_remove(all_stopwords) %>%
  quanteda::tokens_select(
    pattern          = "^[a-z]",
    valuetype        = "regex",
    case_insensitive = FALSE,
    padding          = TRUE
  ) %>%
  quanteda.textstats::textstat_collocations(
    min_count = 3,
    tolower   = FALSE,
    size      = 2
  )

print(head(dfBigram, 50))  # cap output; full object can be large

# ── 5. Build corpus and compound significant bigrams ─────────────────────────

dfCorpus <- corpus(df$txt) %>%
  tokens(
    remove_punct   = TRUE,
    remove_numbers = FALSE,
    remove_symbols = TRUE,
    remove_url     = TRUE
  )

# Z > 3: statistically significant collocations — compound automatically
significant_bigrams <- dfBigram[dfBigram$z > 3, ]
cat(sprintf("Significant bigrams (z > 3): %d\n", nrow(significant_bigrams)))
print(significant_bigrams)

dfCorpusCompound <- tokens_compound(dfCorpus, pattern = phrase(significant_bigrams$collocation))

# ── 6. Build DFM and pre-process ──────────────────────────────────────────────

dfDfm <- dfCorpusCompound %>% dfm()

dfDfm <- dfDfm %>%
  dfm_remove(pattern = all_stopwords) %>%
  dfm_select(pattern = "^[a-z]{3,}", valuetype = "regex") %>%
  dfm_trim(min_termfreq = 3, min_docfreq = 2)

cat("DFM dims after trimming:", dim(dfDfm), "\n")

# ── 6b. Remove empty documents from DFM *and* df before converting ────────────
# quanteda::convert() calls dfm2stm() internally, which silently drops any
# all-zero rows.  If we let it do that, out_converted$documents is shorter than
# df, so docs.removed from prepDocuments() indexes into the *wrong* frame.
# Removing empties here keeps df and the DFM perfectly aligned before conversion.

nonempty_mask <- rowSums(dfDfm) > 0
n_empty_dfm   <- sum(!nonempty_mask)
if (n_empty_dfm > 0) {
  dfDfm <- dfDfm[nonempty_mask, ]
  df    <- df[nonempty_mask, ]
  cat(sprintf("Removed %d all-zero DFM rows; df now %d rows.\n", n_empty_dfm, nrow(df)))
}
cat("DFM dims before STM conversion:", dim(dfDfm), "\n")

# ── 6c. Convert to STM format ─────────────────────────────────────────────────

out_converted <- quanteda::convert(dfDfm, to = "stm")

out_prepped <- prepDocuments(
  out_converted$documents,
  out_converted$vocab,
  lower.thresh = 1,
  verbose      = TRUE
)

cat(sprintf("After prepDocuments: %d docs | %d terms\n",
            length(out_prepped$documents), length(out_prepped$vocab)))

stm_docs  <- out_prepped$documents
stm_vocab <- out_prepped$vocab
kept_idx  <- out_prepped$docs.removed  # indices removed by prepDocuments (if any)

# Align metadata: prepDocuments may remove a few more docs (vocab pruning).
# Because we already stripped empty rows above, kept_idx now correctly indexes df.
if (length(kept_idx) > 0) {
  df <- df[-kept_idx, ]
  cat(sprintf("prepDocuments removed %d more docs.\n", length(kept_idx)))
}

stopifnot(
  "STM docs and df row count must match" = length(stm_docs) == nrow(df)
)
cat(sprintf("Alignment check passed: %d STM docs | %d df rows\n",
            length(stm_docs), nrow(df)))

# ── 7. Covariate matrix ───────────────────────────────────────────────────────

df_stm <- df %>%
  mutate(
    mileage_has      = as.integer(!is.na(mileage_mentioned)),
    # Impute unknown mileage with 0 so no NAs reach model.matrix().
    # mileage_has = 0 already flags these rows as "unknown".
    # Without this, model.matrix drops NA rows → prevalence covariate
    # row count < documents row count → STM crashes.
    mileage_log      = log1p(replace_na(mileage_mentioned, 0L)),
    engine_group_fac = factor(engine_group)
  )

covariates_formula <- ~ engine_group_fac + mileage_log + technical_bucket

# ── 8. Select K ──────────────────────────────────────────────────────────────

cat("\n── K selection (searchK) ──\n")
K_range <- c(10, 15, 20, 25, 30)

set.seed(42)
kResult <- searchK(
  documents    = stm_docs,
  vocab        = stm_vocab,
  K            = K_range,
  prevalence   = covariates_formula,
  data         = df_stm,
  heldout.seed = 123,
  init.type    = "Spectral",
  cores        = 1L   # mclapply not supported on Windows
)

print(kResult$results)

pdf("stm_k_diagnostics_uk.pdf", width = 10, height = 6)
plot(kResult)
dev.off()

write_csv(
  as.data.frame(kResult$results),
  "data/processed/stm_k_metrics_uk.csv"
)

# ── 9. Fit final STM ──────────────────────────────────────────────────────────

K <- 20L  # adjust based on searchK results

cat(sprintf("\n── Fitting STM with K=%d ──\n", K))
set.seed(42)

stm_model <- stm(
  documents  = stm_docs,
  vocab      = stm_vocab,
  K          = K,
  prevalence = covariates_formula,
  data       = df_stm,
  init.type  = "Spectral",
  verbose    = TRUE
)

# ── 10. Extract results ───────────────────────────────────────────────────────

# Top terms
top_terms_prob <- labelTopics(stm_model, n = 15)$prob
top_terms_frex <- labelTopics(stm_model, n = 15)$frex

top_terms_df <- data.frame(
  topic      = 1:K,
  terms_prob = apply(top_terms_prob, 1, paste, collapse = ", "),
  terms_frex = apply(top_terms_frex, 1, paste, collapse = ", ")
)

# Topic proportions (gamma)
gamma_mat  <- stm_model$theta
gamma_full <- as.data.frame(gamma_mat)
colnames(gamma_full) <- paste0("topic_", 1:K)
gamma_full$doc_name  <- df$doc_name

gamma_long <- gamma_full %>%
  pivot_longer(-doc_name, names_to = "topic_name", values_to = "gamma") %>%
  mutate(topic = as.integer(sub("topic_", "", topic_name))) %>%
  select(doc_name, topic, gamma)

# Dominant topic per thread
thread_topics <- gamma_full %>%
  pivot_longer(-doc_name, names_to = "topic_name", values_to = "gamma") %>%
  group_by(doc_name) %>%
  slice_max(gamma, n = 1, with_ties = FALSE) %>%
  ungroup() %>%
  mutate(dominant_topic = as.integer(sub("topic_", "", topic_name))) %>%
  select(doc_name, dominant_topic, gamma_dominant = gamma)

# ── 11. STM covariate effects (engine group) ─────────────────────────────────

cat("── Estimating covariate effects ──\n")
effects <- estimateEffect(
  formula    = 1:K ~ engine_group_fac,
  stmobj     = stm_model,
  metadata   = df_stm,
  uncertainty = "Global"
)

engine_levels <- levels(df_stm$engine_group_fac)
effects_rows  <- list()

for (k in 1:K) {
  for (eng in engine_levels) {
    tryCatch({
      s <- summary(effects, topics = k)$tables[[1]]
      row_name <- paste0("engine_group_fac", eng)
      if (row_name %in% rownames(s)) {
        est    <- s[row_name, "Estimate"]
        se_val <- s[row_name, "Std. Error"]
        effects_rows[[length(effects_rows) + 1]] <- data.frame(
          topic        = k,
          engine_group = eng,
          estimate     = est,
          ci_lower     = est - 1.96 * se_val,
          ci_upper     = est + 1.96 * se_val,
          significant  = abs(est / se_val) > 1.96
        )
      }
    }, error = function(e) NULL)
  }
}

effects_df <- bind_rows(effects_rows)

# ── 12. LLM input table ───────────────────────────────────────────────────────

thread_enriched <- df %>%
  left_join(thread_topics, by = "doc_name") %>%
  rename(mileage_miles = mileage_mentioned)

prevalence_df <- gamma_long %>%
  group_by(topic) %>%
  summarise(prevalence_pct = mean(gamma) * 100, .groups = "drop")

chronic_by_topic <- thread_enriched %>%
  left_join(select(thread_topics, doc_name, dominant_topic), by = "doc_name") %>%
  group_by(topic = dominant_topic) %>%
  summarise(chronic_signal = mean(chronic_score, na.rm = TRUE), .groups = "drop")

llm_input <- top_terms_df %>%
  left_join(prevalence_df,   by = "topic") %>%
  left_join(chronic_by_topic, by = "topic")

# ── 13. Export ────────────────────────────────────────────────────────────────

dir.create("data/processed", recursive = TRUE, showWarnings = FALSE)

wb <- createWorkbook()
addWorksheet(wb, "top_terms");     writeData(wb, "top_terms",     top_terms_df)
addWorksheet(wb, "gamma_full");    writeData(wb, "gamma_full",    gamma_long)
addWorksheet(wb, "thread_topics"); writeData(wb, "thread_topics", thread_topics)
addWorksheet(wb, "effects");       writeData(wb, "effects",       effects_df)
saveWorkbook(wb, "data/processed/stm_results_uk.xlsx", overwrite = TRUE)

write_csv(thread_enriched,  "data/processed/stm_thread_enriched_uk.csv")
write_csv(effects_df,       "data/processed/stm_topic_engine_effects_uk.csv")
write_csv(llm_input,        "data/processed/llm_issue_input_uk.csv")

# ── 14. Quick diagnostic plots ────────────────────────────────────────────────

pdf("stm_plots_uk.pdf", width = 12, height = 8)
plot(stm_model, type = "summary", n = 7, main = "Golf GTI Forum UK — STM Topics")
plot(stm_model, type = "labels",  n = 10, main = "Top Terms by Topic")
dev.off()

cat("\n── Done. Output files:\n")
cat("  data/processed/stm_results_uk.xlsx\n")
cat("  data/processed/stm_thread_enriched_uk.csv\n")
cat("  data/processed/stm_topic_engine_effects_uk.csv\n")
cat("  data/processed/llm_issue_input_uk.csv\n")
cat("  stm_plots_uk.pdf\n")
