# Renault Clio End-to-End Pipeline

This runbook mirrors the Golf workflow for Renault Clio:
1. Extract Clio thread URLs
2. Scrape full thread messages
3. Filter noisy messages and flatten to CSV
4. Run STM with covariates
5. Interpret topics with LLM
6. Benchmark against Clio ground truth

## 1) Extract thread links

```powershell
python scrapers/link_extractor_clio.py --max-list-pages 240
```

Output:
- data/raw/forums/extracted_links_clio.json

## 2) Scrape threads

```powershell
python scrapers/scraper_clio.py --max-pages 15 --workers 6
```

Output:
- data/raw/forums/messages_clio.json

## 3) Filter + flatten

```powershell
python scrapers/cleaner_clio.py
```

Outputs:
- data/processed/forums/cleaned_messages_clio.json
- data/processed/forums/rejected_messages_clio.json
- data/processed/forums/cleaned_messages_clio.csv

## 4) STM modeling

```powershell
Rscript pipelines/stm/r/R_code_STM_clio.R
```

Outputs:
- data/processed/stm_k_metrics_clio.csv
- data/processed/stm_top_terms_frex_clio.csv
- data/processed/stm_thread_enriched_clio.csv
- data/processed/stm_topic_engine_effects_clio.csv
- data/processed/llm_issue_input_clio.csv
- data/processed/stm_results_clio.xlsx

## 5) LLM interpretation

```powershell
$env:DEEPSEEK_API_KEY="<YOUR_KEY>"
python scripts/generate_issue_knowledge_clio.py
```

Outputs:
- data/processed/issue_knowledge_clio.json
- data/processed/issue_knowledge_clio.csv

## 6) Benchmark (ChronicBench)

Ground truth files under `data/benchmarks/ChronicBench/ground_truth_clio` are intentionally template-only.
Populate them from validated findings after your Clio data analysis (STM topics + manual review), then run the benchmark.

```powershell
$env:DEEPSEEK_API_KEY="<YOUR_KEY>"
python data/benchmarks/ChronicBench/evaluate.py `
  --pipeline data/processed/issue_knowledge_clio.json `
  --gt data/benchmarks/ChronicBench/ground_truth_clio `
  --run-id clio_baseline
```

Score output:
- data/benchmarks/ChronicBench/scores/clio_baseline.json

## Optional quick smoke run

Run a short crawl before full scrape:

```powershell
python scrapers/link_extractor_clio.py --max-list-pages 30
python scrapers/scraper_clio.py --max-pages 4 --workers 4
python scrapers/cleaner_clio.py
```
