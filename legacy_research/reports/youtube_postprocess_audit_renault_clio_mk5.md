# YouTube Issue Post-Processing Audit — renault_clio_mk5

## Summary

- Input rows: **13**
- Cross-brand contamination dropped: **2**
- After dedup: **11**
- Merge groups (> 1 row collapsed): **0**
- Engine scope warnings: **0** on **0** issues
- Trim scope warnings: **0**
- Non-powertrain issues with engine scope cleared: **6**
- Mono-trim issues: **11** / 11 (100.0%)
- Year-triangulated (emitted): **11** / 11
- Year confidence distribution: high=7, medium=4

## Dedup — merged groups

_(no clusters merged — input was already deduped)_

## Cross-brand contamination — dropped issues

- `tight_footwell_space_left_clutch` — foreign_brand:seat (label: 'Tight footwell space left of clutch')
- `no_lumbar_support` — foreign_brand:seat (label: 'No lumbar support adjustment')

## Engine-scope warnings

_(no engine-scope rules fired)_

## Trim distribution

| Trim | Count | Share |
|---|---:|---:|
| base | 15 | 100.0% |

## Trim scope warnings

_(none)_

## Cleared-engine issues (non-powertrain)

- `a_pillar_blind_spot` (body) — cleared `['1.0_TCE']`, model_scope=['all_renault_clio_mk5']
- `ambient_light_limited` (electrical) — cleared `['1.6_E_TECH']`, model_scope=['all_renault_clio_mk5']
- `infotainment_screen_tilt` (electrical) — cleared `['1.6_E_TECH']`, model_scope=['all_renault_clio_mk5']
- `manual_handbrake_only` (other) — cleared `['1.0_TCE']`, model_scope=['all_renault_clio_mk5']
- `rear_camera_resolution_poor` (electrical) — cleared `['1.6_E_TECH']`, model_scope=['all_renault_clio_mk5']
- `telematics_sos_battery_failure` (electrical) — cleared `['1.0_SCE', '1.0_TCE', '1.3_TCE', '1.5_BLUE_DCI', '1.6_E_TECH']`, model_scope=['all_renault_clio_mk5']

## Year triangulation examples

- `engine_1_0_tce_sluggish_turbo_lag` → **2020** (confidence=medium, sources=None)
  - transcript=[], titles=['2020'], engine_windows=['2019-2025']
- `manual_gearbox_notchy_imprecise` → **2020-2023** (confidence=medium, sources=None)
  - transcript=[], titles=['2020-2021', '2023'], engine_windows=['2019-2025']
- `a_pillar_blind_spot` → **2024** (confidence=high, sources=None)
  - transcript=[], titles=['2024'], engine_windows=['2019-2025']
- `ambient_light_limited` → **2024** (confidence=high, sources=None)
  - transcript=[], titles=['2024'], engine_windows=['2020-2025']
- `automatic_gearbox_clunks` → **2021** (confidence=medium, sources=None)
  - transcript=[], titles=['2021'], engine_windows=['2019-2025']
- `engine_1_0_tce_rough_cold_start` → **2020** (confidence=medium, sources=None)
  - transcript=[], titles=['2020'], engine_windows=['2019-2025']
- `engine_cover_missing` → **2024** (confidence=high, sources=None)
  - transcript=[], titles=['2024'], engine_windows=['2019-2025']
- `infotainment_screen_tilt` → **2024** (confidence=high, sources=None)
  - transcript=[], titles=['2024'], engine_windows=['2020-2025']
- `manual_handbrake_only` → **2024** (confidence=high, sources=None)
  - transcript=[], titles=['2024'], engine_windows=['2019-2025']
- `rear_camera_resolution_poor` → **2024** (confidence=high, sources=None)
  - transcript=[], titles=['2024'], engine_windows=['2020-2025']
- `telematics_sos_battery_failure` → **2021** (confidence=high, sources=None)
  - transcript=[], titles=['2021'], engine_windows=['2019-2025']
