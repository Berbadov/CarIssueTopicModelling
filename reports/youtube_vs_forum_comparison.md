# YouTube vs Forum Issue Extraction — VW Golf MK7

Comparison of the two MK7 Golf pipelines using a Gemini fact-check of the
YouTube output as the reference for factuality.

- Forum output: [issue_knowledge_uk.json](../data/processed/issue_knowledge_uk.json) (UK Briskoda corpus, STM + LLM labelling, 27 topics)
- YouTube output: [issue_knowledge_youtube_vw_golf_mk7_year_enriched.json](../data/processed/issue_knowledge_youtube_vw_golf_mk7_year_enriched.json) (105 issue rows after year enrichment)
- Reference: Gemini factuality ratings on the 105 YT rows (provided by the user)

## TL;DR

YouTube is genuinely better at surfacing **discrete, named failure modes**
(specific recalls, part numbers, design flaws), and the advantage is not
just recency bias. But it pays for that with heavy duplication, almost no
year metadata, and at least one confident hallucination that slipped past
the LLM. Forum output is much less expressive per topic, but every topic
comes with solid prevalence / mileage / engine-mix statistics that the
YouTube pipeline currently cannot produce.

The two outputs are complementary, not substitutable.

## Coverage (signal-bearing rows)

| Pipeline | Raw rows | Non-fault "discussion" rows | Fault/issue rows | Distinct real issues after dedup |
|---|---|---|---|---|
| Forum UK (STM) | 27 | 11 (ownership, purchase, finance, order tracking, tuning, service scheduling, fuel economy, etc.) | 16 | ~13 (most map 1:1) |
| YouTube | 105 | ~0 (pipeline only emits issues) | 105 | ~55–60 (see dedup below) |

Filtering rule for forum non-faults: `issue_type == "other"` with low severity and a
label that is clearly discussion (topics 1, 4, 6, 8, 9, 10, 17, 20, 21, 23, 27).

**YouTube wins ~4–5× on distinct real issues surfaced.** The gap is large enough that
recency bias alone can't explain it.

## Specificity

YouTube routinely pins issues to specific components, part revisions, or recall
numbers. Forum topics cluster at the symptom level.

| YouTube (specific) | Forum analogue (if any) |
|---|---|
| `camshaft_pulley_nut_loosening` (Recall 15E7, 1.2 TSI) | — |
| `evap_fuel_tank_pump_recall` (Recall 20Y6) | — |
| `turbocharger_seal_failure_702n` (early IS20 part number) | — |
| `ac_solenoid_valve_failure` (N280 inside Sanden compressor) | — |
| `coolant_degradation_clogging` (G13 Silikat bag breakdown) | — |
| `haldex_system_failure` (Gen 5 mesh screen, 30k interval) | — |
| `dsg_gear_selector_issue` ("only leave in P" microswitch) | `DSG gear selection` (generic) |
| `switchable_water_pump_sticking` (EA288 shutter mechanism) | — |
| `oil_pump_belt_disintegration` (EA288 wet belt → pickup clog) | `Oil level/leaks` (generic) |
| `front_subframe_bolt_loosening` (subframe clunk TSB / collar kit) | `Suspension rattles` (generic) |
| `water_pump_thermostat_housing_coolant_leak` | `Thermostat/Water Pump` ✓ |
| `sunroof_panoramic_rattle_leak` | — (absent from forum topics) |
| `child_safety_lock_disengagement` (recall) | — |
| `rear_shock_absorber_knocking` (Sachs bad batch) | part of `Suspension rattles` |
| `start_stop_button_flaking` | — |
| `heated_mirror_glass_crack` | — |

Very few of these would be recoverable from the forum corpus at all, even with
a larger `K` — they are failures that owners *show* in a video (or that a
workshop channel dissects), not failures they start a thread about.

Inversely, forum catches some things YouTube misses or under-represents:
`Keyless Security Issues`, `Infotainment faults`, `ADAS false activations`,
`Lighting coding/faults`, `Bridgestone tyre complaints`, `Wheel Alignment`.
These are slow-burn ownership annoyances that don't produce a video.

## Factuality (Gemini ratings on 105 YT rows)

| Rating | Count | Share |
|---|---|---|
| Highly Factual | ~78 | 74% |
| Factual | ~20 | 19% |
| Moderately Factual | ~4 | 4% |
| Low Factuality / Exaggerated | 2 | 2% |

The two low-factuality rows:
- `timing_chain_rattle_tensioner_wear` maps the failure to 1.2/1.4/1.5 TSI — all **belt-driven** EA211 engines. Only the 1.8/2.0 TSI EA888 uses a chain. This is a confident LLM hallucination, not a transcript error.
- `engine_catastrophic_failure` is clickbait-style aggregation; the EA888 Gen 3 is not "commonly imploding".

Forum topics are structurally harder to rate as "wrong" because they are broader
(e.g. "EPC/Limp Mode" is true almost by definition), but that same breadth is
why they are less useful as a knowledge base.

**Bottom line:** ~93% of YouTube rows are at least Factual, and failures are
concentrated in one ID (timing chain) where the model over-generalised engine scope.

## Duplication

YouTube output has a severe dedup problem. Coolant-housing leak alone appears at least **eight** times under different IDs:

```
water_pump_thermostat_housing_coolant_leak
thermostat_water_pump_assembly_leak
coolant_leak_thermostat_housing_water_pump
cooling_system_water_pump_thermostat_leak
water_pump_thermostat_coolant_leak
coolant_leak_thermostat_waterpump
thermostat_housing_coolant_leak
thermostat_housing_water_pump_leak
```

Similar runs for sunroof leaks (≥5), turbo failure (≥5), carbon buildup (4),
rear main seal (3–4), subframe bolts (2), bonnet release (3), washer sensor (4),
DSG clunk (3), clutch slip (3).

Estimated true-unique YT issues: **~55–60 out of 105 rows** (≈45–50% duplication).
The `issue_id` slug is doing nothing to enforce identity — the LLM is allowed to
mint a fresh slug per chunk, and nothing at merge time consolidates them.

This is the single biggest quality deficit in the YouTube pipeline right now.
A clustering/canonicalisation pass (embed the `symptom + cause + system_component`,
agglomerative cluster, pick the best-documented representative) would recover
most of the lost cleanliness.

## Metadata depth

| Field | Forum | YouTube |
|---|---|---|
| `affected_engines` populated | 27 / 27 | 105 / 105 |
| `affected_years` populated | 27 / 27 (all `2013-2020`) | 4 / 105 directly |
| Enriched year context (`engine_year_context`) | — | 6 / 105 |
| Onset mileage / km | 27 / 27 (`onset_mileage_typical_miles` + range) | 8 / 105 (`onset_km_range`) |
| Prevalence | `prevalence_pct`, `chronic_signal`, `thread_count` | `mention_count` (87% = 1) |
| Part codes | `known_part_codes` field present | inline in labels only |

Forum side wins on **quantitative metadata** by a wide margin. The STM model
produces real prevalence numbers because it sees the full corpus distribution;
the YouTube pipeline only knows how many source videos mentioned an issue, and
`mention_count==1` for 92 / 105 rows (88%), which makes the field
almost useless for ranking severity.

On years specifically: the user has already confirmed the current prompt cannot
reliably extract production years and hallucinates when pushed. That is consistent
with what's in the file — only 4 of 105 rows have a non-null `affected_years`.

## Is this recency bias?

Not mostly. Four reasons the YouTube advantage is structural, not perceptual:

1. **Content format.** A "MK7 common problems" video is literally a list of
   known failures narrated by someone who has seen many of them. A forum
   corpus is noisy — threads span purchases, finance, tuning, reviews, and the
   STM has to allocate topic mass to all of that (≈41% of forum topics are non-fault).
2. **Evidence concentration.** Multiple YouTube channels (mechanics, long-term
   owners) independently list the *same* specific items (N280, 702N, Sachs, G13
   Silikat, Haldex Gen 5), producing strong per-item evidence per video. Forum
   threads scatter the same evidence across dozens of posts that never name
   the part.
3. **Unit of analysis.** STM operates at thread-topic granularity; the LLM
   labels a cluster. A single cluster that mixes "sunroof rattle" and "rear
   shock knock" becomes `Suspension rattles`. The YouTube pipeline extracts
   per-claim from a transcript, so it can keep the two separate.
4. **Gemini grading.** An independent LLM confirmed ~93% factuality against
   outside knowledge. The win isn't only about how the output *feels*.

What **would** be recency bias: concluding YT is 10× better. It isn't. It's
4–5× more specific, with two offsetting weaknesses (duplication, thin
metadata), and one real factuality hole (engine-scope hallucination on the
timing chain).

## Concrete improvement list (ordered by payoff)

1. **Dedup pass on YouTube output.** Embed `label + symptom + cause + system_component`
   per row, agglomerate at a tight threshold (e.g. 0.85 cosine), keep the row with
   the highest `mention_count` and merge `source_videos` + `affected_engines`. This
   alone shrinks 105 → ~55–60 and fixes the biggest complaint when using the output.
2. **Engine-scope sanity check.** Before accepting `affected_engines`, validate
   against a per-issue allowlist (timing belt vs chain engines, TDI-only
   features like wet oil-pump belt / switchable water pump, AWD-only Haldex,
   etc.). This would have caught the chain-on-EA211 hallucination.
3. **Year extraction: stop asking the LLM.** Infer `affected_years` post-hoc
   from the year spans of the source videos that mention each issue, weighted
   by transcript match count. Don't let the model guess years; let it aggregate
   them.
4. **Borrow the forum statistics.** Use forum prevalence as a secondary ranker
   for YouTube issues where a forum analogue exists (e.g. `Thermostat/Water Pump`
   5.9%, `Suspension rattles` 7.4%). That gives a real severity signal that
   `mention_count` cannot.
5. **Reject vague YT rows.** Filter rows whose `label_short` is a system bucket
   (`Fuel system failures`, `Cooling Failures`, `Engine Failure`, `Interior leaks`)
   and nothing more — they contribute nothing over their specific siblings and
   inflate duplication.

## Verdict

YouTube extraction is the stronger discovery pipeline for this project's
stated goal (find *unknown* failure modes from a model name alone). It
produces ~4–5× more distinct failure modes than forum STM and names parts,
recalls, and mechanisms the forum pipeline fundamentally cannot name.

Forum STM is the stronger pipeline for *quantifying* those modes — prevalence,
onset mileage, engine mix. It should be treated as the ranker/validator layer
on top of the YouTube knowledge base, not as a competing source.

The right combined workflow: YouTube to discover, forum to weigh, fact-check
to gate.
