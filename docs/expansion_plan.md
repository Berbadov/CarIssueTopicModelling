# Scaffold Expansion Plan — All Golf & Clio Generations

**Audience:** Gemini (or any small model) producing scaffold YAML files.
**Goal:** One scaffold per car generation, stored at
`data/scaffolds/{make}_{model}_{gen}.yaml`. The pipeline reads the scaffold at
runtime; no Python changes are needed per model. Accuracy of the scaffold is
load-bearing — factuality guardrails (timing chain vs belt, engine↔transmission
compatibility, year windows) derive from these fields.

---

## 1. Targets

Produce one YAML per row. File naming: `{slug}.yaml`, lowercase snake_case.

> **⚠️ Viability note.** YouTube has very little mechanic/ownership content for
> pre-2005 generations. Observed during the expansion scrape:
> Golf Mk1–Mk3, Clio I, and most of Clio II return near-empty corpora after the
> on-topic filter. Scaffold these only if you have budget for speculative
> coverage — they are unlikely to yield usable issue data from the current
> YouTube pipeline. The **viable tier** (where the pipeline produces usable
> output today) is: **Golf Mk5–Mk8, Clio III–V**. Older generations are better
> served by forum/STM data, not YouTube.

### VW Golf

| Slug                | Generation | Production years | Notes                                |
| ------------------- | ---------- | ---------------- | ------------------------------------ |
| `vw_golf_mk1`       | Mk1        | 1974–1983        | GTI from 1976                        |
| `vw_golf_mk2`       | Mk2        | 1983–1992        | GTI 16V, G60, Rallye, Country        |
| `vw_golf_mk3`       | Mk3        | 1991–1999        | VR6 debuts; Syncro; Cabrio           |
| `vw_golf_mk4`       | Mk4        | 1997–2006        | R32, GTI 1.8T                        |
| `vw_golf_mk5`       | Mk5        | 2003–2009        | GTI 2.0 TFSI, R32 VR6                |
| `vw_golf_mk6`       | Mk6        | 2008–2013        | GTI 2.0 TSI, Golf R                  |
| `vw_golf_mk7`       | Mk7        | 2013–2020        | **reference — already shipped**      |
| `vw_golf_mk8`       | Mk8        | 2020–present     | eTSI mild-hybrid; GTI Clubsport      |

### Renault Clio

| Slug                 | Generation | Production years | Notes                               |
| -------------------- | ---------- | ---------------- | ----------------------------------- |
| `renault_clio_mk1`   | I          | 1990–1998        | 16V, Williams                       |
| `renault_clio_mk2`   | II         | 1998–2012*       | RS 172/182, V6; Phase 1/2/3          |
| `renault_clio_mk3`   | III        | 2005–2014        | RS 197/200, dCi range               |
| `renault_clio_mk4`   | IV         | 2013–2019        | **reference — already shipped**     |
| `renault_clio_mk5`   | V          | 2019–present     | E-Tech hybrid; TCe / Blue dCi       |

\* Clio II continued in some markets (Campus/Storia) after Mk3 launch — keep
`corpus_years` tight to mainstream European production.

---

## 2. Output schema (authoritative)

```yaml
meta:
  make: <string>          # "VW", "Renault" — used for cross-brand filtering
  model: <string>         # e.g. "Golf MK7", "Clio MK4" (human-friendly)
  generation: <string>    # e.g. "MK7", "IV"
  corpus_years: [<int>, <int>]   # overall production window (first, last)

facelifts:                # optional, list; omit block when none
  - year: <int>           # first year of facelift (e.g. 2017 for Mk7.5)
    label: <string>       # e.g. "MK7.5"
    pre_label: <string>   # e.g. "MK7 pre-facelift"

engine_families:
  - code: <string>              # e.g. "EA888", "H5Ft"
    fuel_type: petrol | diesel | hybrid | electric
    timing_drive: chain | belt | wet_belt | none
    displacements:
      - code: <string>          # e.g. "2.0_TSI", "1.5_DCI"  (UPPERCASE, underscore)
        year_range: [<int>, <int>]   # first, last year this displacement appears in this gen

performance_trims:              # optional; omit block when none
  max_share: <float 0–1>        # e.g. 0.3 = cap sport trim share at 30%
  tokens:                       # title-matched tokens identifying the sport trim
    - <string>                  # e.g. "gti", "golf r", "rs 200"

transmissions:                  # list; may be empty
  - code: <string>              # e.g. "DQ200", "EDC6", "JR5"
    type: <string>              # e.g. DSG_7speed_dry, manual_5speed, CVT, dual_clutch_6speed_dry
    compatible_displacements: [<string>, ...]  # must match displacement codes above
    year_range: [<int>, <int>]
```

### Field semantics (why each matters)

- `meta.make` — the **cross-brand filter** uses this to decide which OEMs are
  "foreign" at discovery time. Use the canonical brand ("VW", not
  "Volkswagen-Audi-Group"). Platform-sibling brands (Audi/Seat/Skoda for VW) are
  handled by the pipeline's brand-group table.
- `corpus_years` — clamps year triangulation. Title/transcript years outside
  this window get dropped.
- `facelifts[].year` — used to build the semantic-phrase map ("before
  facelift", "post-facelift"). If a generation had *no* mid-cycle refresh,
  omit the block.
- `timing_drive` — **load-bearing**. Drives the chain-vs-belt guardrail. An
  issue text mentioning "chain" will have belt-driven engines stripped from
  `affected_engines`, and vice-versa. Values: `chain`, `belt`, `wet_belt`
  (Ford EcoBoost-style), `none` (electric).
- `displacements[].code` — must be uppercase with an underscore between
  displacement and family, e.g. `2.0_TSI`, `1.5_DCI`, `1.6_TDI`. These strings
  show up in LLM outputs and title filters.
- `displacements[].year_range` — per-displacement, not per-family, because
  engines slide in/out within a generation (e.g. 1.2 TSI dropped in 2017).
  The pipeline uses this to validate LLM-claimed affected years.
- `performance_trims` — declare when the nameplate has a high-search-volume
  sport variant (GTI, R, RS, Williams, Cup). Omit for pure economy lines.
- `transmissions[].compatible_displacements` — **load-bearing**. Must list the
  actual factory pairings only. The pipeline uses this to reject LLM claims
  that pair an engine with an incompatible gearbox (e.g. Clio Mk4 0.9 TCe + EDC
  is not a factory combination; EDC was paired with 1.2 TCe and 1.5 dCi only).

---

## 3. Data-quality rules (non-negotiable)

1. **Every displacement code is listed exactly once**. If the same 2.0 TSI
   appears in two families, you've double-declared; collapse.
2. **`timing_drive` is per-family**, not per-displacement. If two engines
   actually differ (a family with both chain and belt variants), split them
   into two `engine_families` entries with distinct `code`s.
3. **`compatible_displacements` must reference strings that exist in the
   `displacements[].code` list above**. A typo silently disables the guardrail.
4. **`year_range` endpoints are inclusive**. `[2013, 2020]` means model years
   2013 through 2020.
5. **No hand-wavy "all engines"**. If every engine in the generation ships
   with a given gearbox, still enumerate them explicitly.
6. **Omit the block rather than leaving it empty.** If a generation has no
   `facelifts` or no `performance_trims`, delete the whole top-level key.
7. **UTF-8 strings only, no em-dash/curly-quote injection**. Safety for
   downstream CSV emission on Windows.

---

## 4. Common mistakes to avoid (real ones we've hit)

- ❌ **Declaring wet-belt timing where the engine uses a chain.** Renault H5Ft
  (1.2 TCe 120) is a timing chain, not a wet belt. "Wet belt" is specifically
  Ford 1.0 EcoBoost / PSA PureTech territory.
- ❌ **Listing a sport-only transmission on base engines.** Clio Mk4 EDC
  was not paired with 0.9 TCe (manual-only). Check factory option sheets,
  not hearsay.
- ❌ **Copying year ranges from the family when a displacement's window is
  narrower.** Mk7 1.5 TSI only arrives in 2017; the EA211 family window
  (2013–2020) is wrong for this displacement.
- ❌ **Using brand synonyms as `meta.make`.** Write `VW`, not `Volkswagen` —
  match the casing of `vw_golf_mk7.yaml` (the reference).
- ❌ **Listing engines that exist in other regions but not in the European
  mainstream (e.g. NA-market 1.8 TSI Gen3 in a Golf Mk7 EU scaffold).**
  Scope to the European/Turkish/UK market corpus the pipeline targets.

---

## 5. Reference example

The canonical reference is `data/scaffolds/vw_golf_mk7.yaml`. Read it in full
before producing any new file. Mimic its structure, comments, and section
order. Inline copy for convenience:

```yaml
meta:
  make: VW
  model: Golf MK7
  generation: MK7
  corpus_years: [2013, 2020]

facelifts:
  - year: 2017
    label: "MK7.5"
    pre_label: "MK7 pre-facelift"

engine_families:
  - code: EA211
    fuel_type: petrol
    timing_drive: belt
    displacements:
      - code: "1.0_TSI"
        year_range: [2016, 2020]
      - code: "1.2_TSI"
        year_range: [2013, 2017]
      - code: "1.4_TSI"
        year_range: [2013, 2020]
      - code: "1.5_TSI"
        year_range: [2017, 2020]

  - code: EA888
    fuel_type: petrol
    timing_drive: chain
    displacements:
      - code: "1.8_TSI"
        year_range: [2013, 2020]
      - code: "2.0_TSI"
        year_range: [2013, 2020]

  - code: EA288
    fuel_type: diesel
    timing_drive: belt
    displacements:
      - code: "1.6_TDI"
        year_range: [2013, 2020]
      - code: "2.0_TDI"
        year_range: [2013, 2020]

performance_trims:
  max_share: 0.3
  tokens:
    - gti
    - "golf r"
    - "mk7 r"
    - "mk7.5 r"

transmissions:
  - code: DQ200
    type: DSG_7speed_dry
    compatible_displacements: ["1.2_TSI", "1.4_TSI"]
    year_range: [2013, 2020]
  - code: DQ250
    type: DSG_6speed_wet
    compatible_displacements: ["1.8_TSI", "2.0_TSI", "2.0_TDI"]
    year_range: [2013, 2020]
  - code: DQ381
    type: DSG_7speed_wet
    compatible_displacements: ["2.0_TSI", "2.0_TDI"]
    year_range: [2017, 2020]
```

A second reference, `data/scaffolds/renault_clio_mk4.yaml`, shows a non-VAG
platform (Renault H5Ft / K9K / EDC6) — consult it when scaffolding other
Renault / PSA / Ford generations.

---

## 6. Delivery checklist per file

Before marking a scaffold done, verify:

- [ ] Filename matches `{slug}.yaml` from §1
- [ ] `meta.make`, `meta.model`, `meta.generation`, `meta.corpus_years` present
- [ ] Every engine family has `code`, `fuel_type`, `timing_drive`
- [ ] Every displacement has `code` (UPPERCASE `_`) and `year_range`
- [ ] `timing_drive` cross-checked against at least one factory source
- [ ] `transmissions[].compatible_displacements` references existing codes
- [ ] `performance_trims` omitted if the generation has no sport nameplate
- [ ] `facelifts` omitted if no mid-cycle refresh
- [ ] YAML parses (run `python -c "import yaml; yaml.safe_load(open('<path>').read())"`)

---

## 7. Handoff

When you've produced a scaffold, hand back:

1. The YAML file content.
2. A short rationale (3–5 bullets) naming the sources you used for
   `timing_drive`, `compatible_displacements`, and year windows.
3. Any genuinely ambiguous fields where you had to pick — so we can review.

Do **not** run the pipeline or modify any Python files. Scaffolds are the
only deliverable.
