#### Context & Aim
Build a Python-based RAG retrieval engine for a web extension. The app is a Second-hand Automobile Ad Analyzer focused on identifying possible vehicle issues (engine, powertrain, body, manufacturing quality, and chronic defects). 
The data source is YouTube transcripts embedded and stored in ChromaDB. 

**Task:** Create an independent retrieval pipeline that takes a specific car listing (in a raw text format), matches it to a YAML scaffold, builds strict ChromaDB metadata filters, performs the vector search, and custom-ranks the results.

**Core Rules:**
1. **Independence:** This `vectorApproach` folder must be self-contained. Local `scripts/` and `data_raw/` folders have been populated with necessary tools and data.
2. **No Cheating:** YAML scaffolds are for technical facts (engine ranges, timing types, transmissions) only. They MUST NOT contain lists of known issues or "cheats" for the model.
3. **User-Centric Matching:** Prioritize **production year** and **common engine names** (e.g., "1.4 TSI") as used in ads and videos. Technical codes (e.g., "EA211") are secondary/fallback only.

---

### Step 1 — Resolve the exact variant from the scaffold
Parse the raw listing text to extract the **production year** and the **engine common name**. 

**Example Reference (from `data_raw/vw_golf_1.4_tsi_highline_2016_technical_details.txt`):**
- Make: Volkswagen
- Year: 2016
- Model: 1.4 TSI
- Fuel: Gasoline

Match these against the scaffold's `displacements` and `engine_families`. Lock the following metadata for filtering:
1. **engine_common_name:** e.g., "1.4_TSI"
2. **fuel_type:** e.g., "petrol"
3. **timing_drive:** e.g., "belt"
4. **valid_year_range:** e.g., [2013, 2020]
5. **compatible_transmissions:** (derived from the transmissions block in the YAML)
6. **facelift_status:** (derived from the facelifts block; 2016 is pre-facelift for Golf MK7)

**Validation:** If the listing `year` (2016) is outside the matched range, abort the retrieval.

---

### Step 2 — Metadata Schema & Exclusion Constraints
The local scripts in `scripts/` (e.g., `build_transcript_chunks.py`) must ensure chunks are tagged with:
- `engine_common_names` (List or comma-separated string)
- `fuel_type`, `timing_drive`, `transmissions`, `years`, `onset_km`, `is_flagged`.

**Calculate exclusions for the query:**
```python
# Derive what the car DOES NOT have to exclude irrelevant chunks
exclude_timing = "chain" if resolved.timing_drive == "belt" else "belt"

exclude_transmissions = [
    t.code for t in scaffold.transmissions
    if resolved.engine_common_name not in t.compatible_displacements
    or listing_year not in range(*t.year_range)
]
```

---

### Step 3 — Run Vector Search with Pre-Filtering

1. **Search Query:** Embed the entire raw technical details of the listing:
   ```text
   --- Technical Details ---
   Ad No: 1306075134
   ...
   Model: 1.4 TSI Highline
   Year: 2016
   KM: 79.000
   ...
   ```
2. **Hard Filters (ChromaDB `where` clause):**
   - Use `$ne` and `$nin` operators to exclude `exclude_timing` and `exclude_transmissions`.
   - Ensure `is_flagged == False`.
   - (Optional but recommended): Pre-filter by `fuel_type` if specific to the engine.

3. **Retrieve k=20 chunks.**

---

### Step 4 — Post-Retrieval Custom Ranking

Re-rank retrieved chunks using a Tier system in Python:
- **Tier 1 (Exact Match):** `engine_common_name` + `fuel_type` + confirmed `year` overlap.
- **Tier 2 (Family Match):** `engine_common_name` match, year unconfirmed.
- **Tier 3 (Mileage Approaching):** `onset_km` within 20,000 km of listing's `79.000 KM`.
- **Tier 4 (Generation-level):** General Golf MK7 issues (body, electronics).

*Tiebreaker:* `facelift_status` (MK7 issues for 2016 car).

---

### Step 5 — Final Safety Drops & Return
Perform a final Python-level check to ensure no mismatching timing or transmission data slipped through. Return the final ranked list as dictionaries.