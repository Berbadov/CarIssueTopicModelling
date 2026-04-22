# YouTube Issue Post-Processing Audit — renault_clio_mk4

## Summary

- Input rows: **68**
- Cross-brand contamination dropped: **0**
- After dedup: **37**
- Merge groups (> 1 row collapsed): **1**
- Engine scope warnings: **0** on **0** issues
- Trim scope warnings: **0**
- Non-powertrain issues with engine scope cleared: **15**
- Mono-trim issues: **37** / 37 (100.0%)
- Year-triangulated (emitted): **24** / 37
- Year confidence distribution: high=8, low=13, medium=16

## Dedup — merged groups

- 3 rows: `gearbox_issues_manual`, `gearbox_reverse_grinding`, `notchy_manual_gearbox`

## Engine-scope warnings

_(no engine-scope rules fired)_

## Trim distribution

| Trim | Count | Share |
|---|---:|---:|
| base | 44 | 100.0% |

## Trim scope warnings

_(none)_

## Cleared-engine issues (non-powertrain)

- `excessive_wind_noise` (body) — cleared `['0.9_TCE']`, model_scope=['all_renault_clio_mk4']
- `poor_rear_visibility` (body) — cleared `['0.9_TCE', '1.2_NA', '1.2_TCE', '1.5_DCI']`, model_scope=['all_renault_clio_mk4']
- `suspension_handling_issues` (suspension) — cleared `['1.5_DCI']`, model_scope=['all_renault_clio_mk4']
- `awkward_start_button_placement` (electrical) — cleared `['0.9_TCE', '1.2_NA', '1.2_TCE', '1.5_DCI']`, model_scope=['all_renault_clio_mk4']
- `harsh_ride_quality` (suspension) — cleared `['0.9_TCE']`, model_scope=['all_renault_clio_mk4']
- `infotainment_system_faults` (electrical) — cleared `['0.9_TCE', '1.2_NA', '1.2_TCE', '1.5_DCI']`, model_scope=['all_renault_clio_mk4']
- `r_link_infotainment_bugs` (electrical) — cleared `['0.9_TCE', '1.2_NA', '1.2_TCE', '1.5_DCI']`, model_scope=['all_renault_clio_mk4']
- `speaker_distortion_high_volume` (electrical) — cleared `['0.9_TCE']`, model_scope=['all_renault_clio_mk4']
- `start_stop_battery_drain` (electrical) — cleared `['0.9_TCE', '1.2_NA', '1.2_TCE', '1.5_DCI']`, model_scope=['all_renault_clio_mk4']
- `starter_motor_water_ingress` (electrical) — cleared `['0.9_TCE', '1.2_NA', '1.2_TCE', '1.5_DCI']`, model_scope=['all_renault_clio_mk4']
- `suspension_noise_damaged_roads` (suspension) — cleared `['0.9_TCE', '1.2_NA', '1.2_TCE', '1.5_DCI']`, model_scope=['all_renault_clio_mk4']
- `vague_suspension_at_speed` (suspension) — cleared `['0.9_TCE']`, model_scope=['all_renault_clio_mk4']
- `vent_control_plastic_breakage` (body) — cleared `['0.9_TCE', '1.2_NA', '1.2_TCE', '1.5_DCI']`, model_scope=['all_renault_clio_mk4']
- `wiper_motor_failure` (electrical) — cleared `['0.9_TCE', '1.2_NA', '1.2_TCE', '1.5_DCI']`, model_scope=['all_renault_clio_mk4']
- `wiper_motor_linkage_water_damage` (electrical) — cleared `['0.9_TCE', '1.2_NA', '1.2_TCE', '1.5_DCI']`, model_scope=['all_renault_clio_mk4']

## Year triangulation examples

- `carbon_buildup_intake_valves` → **2013-2016** (confidence=medium, sources=None)
  - transcript=[], titles=['2013-2016'], engine_windows=['2013-2019']
- `egr_clogging` → **2013-2016** (confidence=medium, sources=None)
  - transcript=[], titles=['2013-2016'], engine_windows=['2013-2019']
- `engine_noise_characteristic` → **2013** (confidence=high, sources=None)
  - transcript=[], titles=['2013-2014'], engine_windows=['2013-2019']
- `excessive_wind_noise` → **2013** (confidence=high, sources=None)
  - transcript=[], titles=['2013'], engine_windows=['2013-2019']
- `gearbox_issues_manual` → **2013-2016** (confidence=medium, sources=None)
  - transcript=[], titles=['2013', '2016'], engine_windows=['2013-2019']
- `poor_rear_visibility` → **2013** (confidence=high, sources=None)
  - transcript=[], titles=['2013-2016'], engine_windows=['2013-2019']
- `suspension_handling_issues` → **2013-2014** (confidence=medium, sources=None)
  - transcript=[], titles=['2013-2014'], engine_windows=['2013-2019']
- `automatic_gearbox_performance` → **2016** (confidence=high, sources=None)
  - transcript=[], titles=['2016'], engine_windows=['2013-2019']
- `awkward_start_button_placement` → **2013-2016** (confidence=medium, sources=None)
  - transcript=[], titles=['2013-2016'], engine_windows=['2013-2019']
- `diesel_engine_noise` → **2014** (confidence=medium, sources=None)
  - transcript=[], titles=['2014'], engine_windows=['2013-2019']
- `dpf_clogging_short_trips` → **2013-2016** (confidence=medium, sources=None)
  - transcript=[], titles=['2013-2016'], engine_windows=['2013-2019']
- `edc_dual_clutch_faults` → **2013-2016** (confidence=medium, sources=None)
  - transcript=[], titles=['2013-2016'], engine_windows=['2013-2019']
- `engine_noise_vibration` → **2013** (confidence=high, sources=None)
  - transcript=[], titles=['2013'], engine_windows=['2013-2019']
- `engine_performance_issues_0_9_tce` → **2013** (confidence=medium, sources=None)
  - transcript=[], titles=['2013'], engine_windows=['2013-2019']
- `harsh_ride_quality` → **2013** (confidence=high, sources=None)
  - transcript=[], titles=['2013'], engine_windows=['2013-2019']
- `high_rpm_motorway_cruising` → **2013** (confidence=medium, sources=None)
  - transcript=[], titles=['2013'], engine_windows=['2013-2019']
- `high_rpm_poor_motorway_economy` → **2013** (confidence=medium, sources=None)
  - transcript=[], titles=['2013'], engine_windows=['2013-2019']
- `infotainment_system_faults` → **2016** (confidence=high, sources=None)
  - transcript=[], titles=['2016'], engine_windows=['2013-2019']
- `poor_motorway_fuel_economy` → **2013** (confidence=medium, sources=None)
  - transcript=[], titles=['2013'], engine_windows=['2013-2019']
- `slow_automatic_gearbox` → **2016** (confidence=medium, sources=None)
  - transcript=[], titles=['2016'], engine_windows=['2013-2019']
