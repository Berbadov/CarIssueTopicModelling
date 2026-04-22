# YouTube Issue Post-Processing Audit — renault_clio_mk4

## Summary

- Input rows: **47**
- Cross-brand contamination dropped: **4**
- After dedup: **42**
- Merge groups (> 1 row collapsed): **1**
- Engine scope warnings: **0** on **0** issues
- Trim scope warnings: **0**
- Non-powertrain issues with engine scope cleared: **4**
- Mono-trim issues: **42** / 42 (100.0%)
- Year-triangulated (emitted): **5** / 42
- Year confidence distribution: low=37, medium=5

## Dedup — merged groups

- 2 rows: `egr_valve_stuck_closed`, `egr_valve_stuck_open`

## Cross-brand contamination — dropped issues

- `wet_belt_failure_oil_contamination` — foreign_engine_family:ecoboost (label: 'EcoBoost wet belt degradation contaminates oil')
- `wrong_head_gasket_factory_installation` — foreign_brand:ford (label: 'Wrong head gaskets from factory')
- `wet_belt_degradation_failure` — foreign_brand:ford (label: 'Wet belt degradation and premature failure')
- `wet_belt_failure` — foreign_engine_family:ecoboost (label: 'EcoBoost wet belt degradation and failure')

## Engine-scope warnings

_(no engine-scope rules fired)_

## Trim distribution

| Trim | Count | Share |
|---|---:|---:|
| base | 89 | 100.0% |

## Trim scope warnings

_(none)_

## Cleared-engine issues (non-powertrain)

- `folded_seat_step_limits_cargo` (body) — cleared `['0.9_TCE', '1.2_NA', '1.2_TCE', '1.5_DCI']`, model_scope=['all_renault_clio_mk4']
- `jittery_low_speed_ride` (suspension) — cleared `['0.9_TCE', '1.2_NA', '1.2_TCE', '1.5_DCI']`, model_scope=['all_renault_clio_mk4']
- `pedal_offset` (other) — cleared `['0.9_TCE', '1.2_NA', '1.2_TCE', '1.5_DCI']`, model_scope=['all_renault_clio_mk4']
- `rear_visibility_obstructed` (body) — cleared `['0.9_TCE', '1.2_NA', '1.2_TCE', '1.5_DCI']`, model_scope=['all_renault_clio_mk4']

## Year triangulation examples

- `airbag_service_light_fault` → **2013** (confidence=medium, sources=None)
  - transcript=[], titles=['2013'], engine_windows=[]
- `edc_gearbox_sport_mode_lack_of_bite` → **2013** (confidence=medium, sources=None)
  - transcript=[], titles=['2013'], engine_windows=['2013-2019']
- `oil_dilution_dpf_regeneration` → **2013-2019** (confidence=medium, sources=None)
  - transcript=[], titles=[], engine_windows=[]
- `timing_chain_tensioner_failure` → **2013-2019** (confidence=medium, sources=None)
  - transcript=[], titles=[], engine_windows=[]
- `wet_timing_belt_degradation` → **2013-2019** (confidence=medium, sources=None)
  - transcript=[], titles=[], engine_windows=[]
