# YouTube Issue Post-Processing Audit — vw_golf_mk6

## Summary

- Input rows: **174**
- Cross-brand contamination dropped: **0**
- After dedup: **82**
- Merge groups (> 1 row collapsed): **6**
- Engine scope warnings: **0** on **0** issues
- Trim scope warnings: **0**
- Non-powertrain issues with engine scope cleared: **22**
- Mono-trim issues: **79** / 82 (96.3%)
- Year-triangulated (emitted): **49** / 82
- Year confidence distribution: high=10, low=33, medium=39

## Dedup — merged groups

- 3 rows: `pcv_failure`, `pcv_system_failure`, `pcv_valve_failure_blows_seal`
- 3 rows: `wheel_bearing_failure`, `wheel_bearing_hub_failure`, `wheel_hub_failure`
- 2 rows: `carbon_buildup_intake_valves`, `intake_valve_carbon_buildup`
- 2 rows: `dpf_clogging`, `dpf_failure`
- 2 rows: `dual_mass_flywheel_failure`, `dual_mass_flywheel_failure_tdi`
- 2 rows: `timing_chain_premature_wear`, `timing_chain_wear_fsi`

## Engine-scope warnings

_(no engine-scope rules fired)_

## Trim distribution

| Trim | Count | Share |
|---|---:|---:|
| base | 99 | 94.3% |
| R | 3 | 2.9% |
| GTI | 2 | 1.9% |
| TDI | 1 | 1.0% |

## Trim scope warnings

_(none)_

## Cleared-engine issues (non-powertrain)

- `body_rust_and_trim_issues` (body) — cleared `['2.0_TSI_R']`, model_scope=['all_vw_golf_mk6']
- `wheel_bearing_hub_failure` (suspension) — cleared `['1.6_TDI', '2.0_TDI']`, model_scope=['all_vw_golf_mk6']
- `abs_esp_sensor_failure` (electrical) — cleared `['all']`, model_scope=['all_vw_golf_mk6']
- `air_conditioning_failure` (other) — cleared `['1.6']`, model_scope=['all_vw_golf_mk6']
- `body_rust_and_water_ingress` (body) — cleared `['2.0_TSI_R']`, model_scope=['all_vw_golf_mk6']
- `brake_light_switch_failure` (electrical) — cleared `['all']`, model_scope=['all_vw_golf_mk6']
- `door_drainage_clogging` (body) — cleared `['2.0_TSI_R']`, model_scope=['all_vw_golf_mk6']
- `engine_harness_damage` (electrical) — cleared `['all']`, model_scope=['all_vw_golf_mk6']
- `glow_plug_module_fault` (electrical) — cleared `['1.6']`, model_scope=['all_vw_golf_mk6']
- `haldex_system_troubles` (other) — cleared `['2.0_TSI_R']`, model_scope=['all_vw_golf_mk6']
- `headlight_condensation` (body) — cleared `['all']`, model_scope=['all_vw_golf_mk6']
- `headlight_failure` (electrical) — cleared `['1.8_TSI', '2.0_TSI']`, model_scope=['all_vw_golf_mk6']
- `headliner_sagging` (body) — cleared `['1.2_TSI', '1.4', '1.4_TSI', '1.6', '1.6_TDI', '1.8_TSI', '2.0_TDI', '2.0_TSI', '2.0_TSI_R']`, model_scope=['all_vw_golf_mk6']
- `interior_plastic_components_brittle` (body) — cleared `['1.6']`, model_scope=['all_vw_golf_mk6']
- `passenger_seat_sensor_failure` (electrical) — cleared `['all']`, model_scope=['all_vw_golf_mk6']
- `power_folding_mirror_faults` (electrical) — cleared `['2.0_TSI_R']`, model_scope=['all_vw_golf_mk6']
- `rear_door_controller_power_fault` (electrical) — cleared `['1.6']`, model_scope=['all_vw_golf_mk6']
- `rear_suspension_arm_bush_wear` (suspension) — cleared `['1.6']`, model_scope=['all_vw_golf_mk6']
- `sunroof_drain_clogging` (body) — cleared `['2.0_TSI_R']`, model_scope=['all_vw_golf_mk6']
- `water_ingress_multiple_points` (body) — cleared `['2.0_TSI_R']`, model_scope=['all_vw_golf_mk6']
- `water_leak_into_interior` (body) — cleared `['all']`, model_scope=['all_vw_golf_mk6']
- `worn_steering_poles` (suspension) — cleared `['2.0_TSI_R']`, model_scope=['all_vw_golf_mk6']

## Year triangulation examples

- `timing_chain_tensioner_failure` → **2008-2013** (confidence=medium, sources=None)
  - transcript=[], titles=['2008-2013'], engine_windows=['2008-2013']
- `carbon_buildup_intake_valves` → **2008-2013** (confidence=medium, sources=None)
  - transcript=[], titles=['2008-2013'], engine_windows=['2008-2013']
- `dual_mass_flywheel_failure` → **2008-2013** (confidence=medium, sources=None)
  - transcript=[], titles=['2008-2009', '2013'], engine_windows=['2008-2013']
- `fuel_injector_failure` → **2008-2013** (confidence=medium, sources=None)
  - transcript=[], titles=['2008-2013'], engine_windows=['2008-2013']
- `pcv_system_failure` → **2008-2013** (confidence=medium, sources=None)
  - transcript=[], titles=['2008-2013'], engine_windows=['2008-2013']
- `body_rust_and_trim_issues` → **2009-2013** (confidence=medium, sources=None)
  - transcript=[], titles=['2009', '2013'], engine_windows=['2009-2013']
- `cp4_high_pressure_fuel_pump_failure` → **2008-2013** (confidence=high, sources=None)
  - transcript=[], titles=['2008-2013'], engine_windows=['2008-2013']
- `egr_valve_failure` → **2008-2013** (confidence=high, sources=None)
  - transcript=[], titles=['2008-2013'], engine_windows=['2008-2013']
- `timing_chain_premature_wear` → **2008-2011** (confidence=high, sources=None)
  - transcript=[], titles=['2008-2013'], engine_windows=['2008-2013']
- `abs_esp_sensor_failure` → **2008** (confidence=medium, sources=None)
  - transcript=[], titles=['2008'], engine_windows=[]
- `ac_system_failure` → **2008** (confidence=medium, sources=None)
  - transcript=[], titles=['2008'], engine_windows=[]
- `brake_light_switch_failure` → **2008** (confidence=medium, sources=None)
  - transcript=[], titles=['2008'], engine_windows=[]
- `camshaft_bridge_screen_fallout` → **2009** (confidence=high, sources=None)
  - transcript=[], titles=['2008-2013'], engine_windows=['2009-2013']
- `camshaft_cradle_sealant_leak` → **2008-2013** (confidence=medium, sources=None)
  - transcript=[], titles=['2008-2013'], engine_windows=['2008-2013']
- `carbon_buildup_fsi` → **2008** (confidence=medium, sources=None)
  - transcript=[], titles=['2008'], engine_windows=['2008-2013']
- `center_locking_system_failure` → **2008** (confidence=medium, sources=None)
  - transcript=[], titles=['2008'], engine_windows=[]
- `compressor_failure_1_4_tsi_twincharger` → **2008** (confidence=medium, sources=None)
  - transcript=[], titles=['2008'], engine_windows=['2008-2013']
- `compressor_magnetic_clutch_failure` → **2008-2013** (confidence=medium, sources=None)
  - transcript=[], titles=['2008-2013'], engine_windows=['2008-2013']
- `cracked_cylinder_head_2_0_tdi` → **2008** (confidence=medium, sources=None)
  - transcript=[], titles=['2008'], engine_windows=['2008-2013']
- `diesel_emissions_recall` → **2008-2012** (confidence=medium, sources=None)
  - transcript=[], titles=[], engine_windows=['2008-2013']
