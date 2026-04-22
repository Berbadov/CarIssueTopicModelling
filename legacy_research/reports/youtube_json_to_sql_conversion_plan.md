# YouTube Issue Knowledge JSON → SQL Conversion Plan

## Overview

Convert YouTube-derived car issue knowledge files (`*_final.json`) from `data/processed/` into a normalized relational schema suitable for SQL queries.

## Source Files

- `data/processed/issue_knowledge_youtube_vw_golf_mk7_final.json`
- `data/processed/issue_knowledge_youtube_renault_clio_mk4_final.json`

## Target Schema (7 Tables)

### 1. `car_models` (Lookup Table)

| Column | Type | Description |
|--------|------|-------------|
| `car_model_id` | VARCHAR (PK) | e.g., "vw_golf_mk7" |
| `car_make` | VARCHAR | "vw", "renault" |
| `car_model` | VARCHAR | "golf", "clio" |
| `generation` | VARCHAR | "mk7", "mk4" |
| `source` | VARCHAR | Default "youtube" |

### 2. `car_issues` (Core Issue Table)

| Column | Type | Description |
|--------|------|-------------|
| `issue_id` | VARCHAR (PK) | Unique issue identifier |
| `car_model_id` | VARCHAR (FK) | → car_models.car_model_id |
| `label` | TEXT | Full issue label |
| `label_short` | VARCHAR | Short label |
| `system_component` | VARCHAR | cooling, engine, gearbox, body, etc. |
| `issue_type` | VARCHAR | fluid_leak, chronic_failure, wear_item, etc. |
| `severity` | VARCHAR | high, medium, low |
| `confidence` | VARCHAR | high, medium, low |
| `affected_years` | VARCHAR | Year range (nullable) |
| `onset_km_range` | VARCHAR | Mileage onset range |
| `symptom` | TEXT | Symptom description |
| `cause` | TEXT | Cause description |
| `fix` | TEXT | Fix description |
| `warning_signs` | TEXT | JSON array of warning signs |
| `inspection_advice` | TEXT | Inspection guidance |
| `mention_count` | INTEGER | Video mention count |
| `source` | VARCHAR | Default "youtube" |
| `data_quality` | VARCHAR | high, medium, low |
| `notes` | TEXT | Additional notes |
| `affected_engines_validated` | BOOLEAN | Engine validation flag |
| `engine_scope_warnings` | TEXT | Scope warnings |

### 3. `issue_engines` (Many-to-Many)

| Column | Type | Description |
|--------|------|-------------|
| `issue_id` | VARCHAR (FK) | → car_issues.issue_id |
| `engine_code` | VARCHAR (PK) | 1.4_TSI, 2.0_TSI, etc. |
| `evidence_hits` | INTEGER | Evidence hit count |

### 4. `issue_source_videos` (Many-to-Many)

| Column | Type | Description |
|--------|------|-------------|
| `issue_id` | VARCHAR (FK) | → car_issues.issue_id |
| `video_id` | VARCHAR (PK) | YouTube video ID |
| `video_title` | TEXT | Video title |

### 5. `issue_merged_from` (Consolidation History)

| Column | Type | Description |
|--------|------|-------------|
| `issue_id` | VARCHAR (FK) | → car_issues.issue_id |
| `merged_from_id` | VARCHAR (PK) | Original issue ID |

### 6. `model_scope` (Scope Tags)

| Column | Type | Description |
|--------|------|-------------|
| `issue_id` | VARCHAR (FK) | → car_issues.issue_id |
| `scope_value` | VARCHAR (PK) | all_mk7, mk7_dsg, mk7_manual |

### 7. `engine_year_context` (Per-Engine Year Evidence)

| Column | Type | Description |
|--------|------|-------------|
| `issue_id` | VARCHAR (FK) | → car_issues.issue_id |
| `engine_code` | VARCHAR | Engine identifier |
| `years_range` | VARCHAR | Year range (e.g., "2014-2017") |
| `evidence_hits` | INTEGER | Evidence count |

## Implementation Details

### Files to Generate

1. `schema/youtube_issues.sql` — CREATE TABLE statements (SQLite/PostgreSQL compatible)
2. `scripts/convert_youtube_json_to_sql.py` — Conversion script

### Conversion Logic

1. Read `*_final.json` files from `data/processed/`
2. Extract `car_model` from filename (e.g., "vw_golf_mk7")
3. Insert/update `car_models` lookup table
4. Flatten nested arrays into junction tables:
   - `affected_engines` → `issue_engines`
   - `source_videos` → `issue_source_videos`
   - `merged_from_issue_ids` → `issue_merged_from`
   - `model_scope` → `model_scope`
   - `engine_year_context` → `engine_year_context`
5. Handle nulls, empty arrays, and mixed types

### Indexes

- `car_issues`: on `car_model_id`, `system_component`, `severity`, `confidence`
- `issue_engines`: on `engine_code`
- `issue_source_videos`: on `video_id`