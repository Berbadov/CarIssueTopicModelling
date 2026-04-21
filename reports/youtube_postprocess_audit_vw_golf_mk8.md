# YouTube Issue Post-Processing Audit — vw_golf_mk8

## Summary

- Input rows: **82**
- Cross-brand contamination dropped: **0**
- After dedup: **43**
- Merge groups (> 1 row collapsed): **2**
- Engine scope warnings: **0** on **0** issues
- Trim scope warnings: **0**
- Non-powertrain issues with engine scope cleared: **26**
- Mono-trim issues: **43** / 43 (100.0%)
- Year-triangulated (emitted): **31** / 43
- Year confidence distribution: high=1, low=12, medium=30

## Dedup — merged groups

- 2 rows: `touch_controls_unresponsive`, `touch_controls_unresponsive_unlit`
- 2 rows: `water_pump_failure`, `water_pump_thermostat_leak`

## Engine-scope warnings

_(no engine-scope rules fired)_

## Trim distribution

| Trim | Count | Share |
|---|---:|---:|
| base | 60 | 100.0% |

## Trim scope warnings

_(none)_

## Cleared-engine issues (non-powertrain)

- `touch_controls_unresponsive_unlit` (electrical) — cleared `['1.0_ETSI', '1.0_TSI', '1.4_EHYBRID', '1.5_ETSI', '1.5_TSI', '2.0_TDI', '2.0_TSI']`, model_scope=['all_vw_golf_mk8']
- `infotainment_ui_complexity` (electrical) — cleared `['1.0_ETSI', '1.0_TSI', '1.4_EHYBRID', '1.5_ETSI', '1.5_TSI', '2.0_TDI', '2.0_TSI']`, model_scope=['all_vw_golf_mk8']
- `infotainment_system_performance` (electrical) — cleared `['1.0_ETSI', '1.0_TSI', '1.4_EHYBRID', '1.5_ETSI', '1.5_TSI', '2.0_TDI', '2.0_TSI']`, model_scope=['all_vw_golf_mk8']
- `electrical_system_faults` (electrical) — cleared `['2.0_TSI']`, model_scope=['all_vw_golf_mk8']
- `suspension_issues` (suspension) — cleared `['1.0_ETSI', '1.0_TSI', '1.4_EHYBRID', '1.5_ETSI', '1.5_TSI', '2.0_TDI', '2.0_TSI']`, model_scope=['all_vw_golf_mk8']
- `blower_motor_failure` (electrical) — cleared `['all']`, model_scope=['all_vw_golf_mk8']
- `body_panel_misalignment` (body) — cleared `['2.0_TSI']`, model_scope=['all_vw_golf_mk8']
- `bonnet_release_cable_failure` (body) — cleared `['all']`, model_scope=['all_vw_golf_mk8']
- `brake_melting` (brakes) — cleared `['2.0_TSI']`, model_scope=['all_vw_golf_mk8']
- `dcc_adaptive_suspension_failure` (suspension) — cleared `['1.0_ETSI', '1.0_TSI', '1.4_EHYBRID', '1.5_ETSI', '1.5_TSI', '2.0_TDI', '2.0_TSI']`, model_scope=['all_vw_golf_mk8']
- `early_suspension_knocks` (suspension) — cleared `['1.0_ETSI', '1.0_TSI', '1.4_EHYBRID', '1.5_ETSI', '1.5_TSI', '2.0_TDI', '2.0_TSI']`, model_scope=['all_vw_golf_mk8']
- `electrical_system_intermittent_faults` (electrical) — cleared `['2.0_TSI']`, model_scope=['all_vw_golf_mk8']
- `excessive_road_noise` (body) — cleared `['1.0_ETSI', '1.0_TSI', '1.4_EHYBRID', '1.5_ETSI', '1.5_TSI', '2.0_TDI', '2.0_TSI']`, model_scope=['all_vw_golf_mk8']
- `glossy_plastic_fingerprints_dust` (body) — cleared `['1.4_EHYBRID']`, model_scope=['all_vw_golf_mk8']
- `gte_battery_degradation` (electrical) — cleared `['1.4_EHYBRID']`, model_scope=['all_vw_golf_mk8']
- `haptic_steering_wheel_controls` (electrical) — cleared `['2.0_TSI']`, model_scope=['all_vw_golf_mk8']
- `headlight_foreign_object` (body) — cleared `['2.0_TSI']`, model_scope=['all_vw_golf_mk8']
- `infotainment_screen_failure` (electrical) — cleared `['1.0_ETSI', '1.0_TSI', '1.4_EHYBRID', '1.5_ETSI', '1.5_TSI', '2.0_TDI', '2.0_TSI']`, model_scope=['all_vw_golf_mk8']
- `phev_boot_cable_storage` (body) — cleared `['1.4_EHYBRID']`, model_scope=['all_vw_golf_mk8']
- `stone_chips_front_bonnet` (body) — cleared `['1.0_ETSI', '1.0_TSI', '1.4_EHYBRID', '1.5_ETSI', '1.5_TSI', '2.0_TDI', '2.0_TSI']`, model_scope=['all_vw_golf_mk8']
- `subframe_bolt_issue` (suspension) — cleared `['all']`, model_scope=['all_vw_golf_mk8']
- `sunroof_operation_failure` (body) — cleared `['2.0_TSI']`, model_scope=['all_vw_golf_mk8']
- `sunroof_seal_failure` (body) — cleared `['all']`, model_scope=['all_vw_golf_mk8']
- `torsion_beam_ride_quality` (suspension) — cleared `['1.0_ETSI', '1.0_TSI', '1.4_EHYBRID', '1.5_ETSI', '1.5_TSI', '2.0_TDI', '2.0_TSI']`, model_scope=['all_vw_golf_mk8']
- `washer_fluid_sensor_failure` (electrical) — cleared `['all']`, model_scope=['all_vw_golf_mk8']
- `water_ingress_speaker_bracket` (body) — cleared `['all']`, model_scope=['all_vw_golf_mk8']

## Year triangulation examples

- `touch_controls_unresponsive_unlit` → **2020** (confidence=medium, sources=None)
  - transcript=[], titles=['2020'], engine_windows=['2020-2025']
- `infotainment_ui_complexity` → **2020** (confidence=medium, sources=None)
  - transcript=[], titles=['2020'], engine_windows=['2020-2025']
- `infotainment_system_performance` → **2020** (confidence=medium, sources=None)
  - transcript=[], titles=['2020'], engine_windows=['2020-2025']
- `carbon_buildup_intake_valves` → **2020** (confidence=medium, sources=None)
  - transcript=[], titles=['2020'], engine_windows=['2020-2025']
- `dsg_jerky_low_speed` → **2020** (confidence=medium, sources=None)
  - transcript=[], titles=['2020'], engine_windows=['2020-2025']
- `electrical_system_faults` → **2025** (confidence=medium, sources=None)
  - transcript=[], titles=['2025'], engine_windows=['2020-2025']
- `suspension_issues` → **2021-2022** (confidence=high, sources=None)
  - transcript=[], titles=['2020'], engine_windows=['2020-2025']
- `water_pump_thermostat_leak` → **2020** (confidence=medium, sources=None)
  - transcript=[], titles=['2020'], engine_windows=['2020-2025']
- `ac_solenoid_valve_failure` → **2020** (confidence=medium, sources=None)
  - transcript=[], titles=['2020'], engine_windows=[]
- `blower_motor_failure` → **2020** (confidence=medium, sources=None)
  - transcript=[], titles=['2020'], engine_windows=[]
- `body_panel_misalignment` → **2025** (confidence=medium, sources=None)
  - transcript=[], titles=['2025'], engine_windows=['2020-2025']
- `bonnet_release_cable_failure` → **2020** (confidence=medium, sources=None)
  - transcript=[], titles=['2020'], engine_windows=[]
- `clutch_at_power_limit` → **2020** (confidence=medium, sources=None)
  - transcript=[], titles=['2020'], engine_windows=['2020-2025']
- `cooling_system_thermostat_housing_leak` → **2020** (confidence=medium, sources=None)
  - transcript=[], titles=['2020'], engine_windows=['2020-2025']
- `early_suspension_knocks` → **2021-2022** (confidence=medium, sources=None)
  - transcript=[], titles=[], engine_windows=['2020-2025']
- `electrical_system_intermittent_faults` → **2025** (confidence=medium, sources=None)
  - transcript=[], titles=['2025'], engine_windows=['2020-2025']
- `evap_fuel_tank_pump_recall` → **2020** (confidence=medium, sources=None)
  - transcript=[], titles=['2020'], engine_windows=['2020-2025']
- `headlight_foreign_object` → **2025** (confidence=medium, sources=None)
  - transcript=[], titles=['2025'], engine_windows=['2020-2025']
- `ignition_coil_pack_failure` → **2020** (confidence=medium, sources=None)
  - transcript=[], titles=['2020'], engine_windows=['2020-2025']
- `infotainment_screen_failure` → **2021-2022** (confidence=medium, sources=None)
  - transcript=[], titles=[], engine_windows=['2020-2025']
