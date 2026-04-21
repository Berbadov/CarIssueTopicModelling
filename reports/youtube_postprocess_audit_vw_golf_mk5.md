# YouTube Issue Post-Processing Audit — vw_golf_mk5

## Summary

- Input rows: **115**
- Cross-brand contamination dropped: **0**
- After dedup: **62**
- Merge groups (> 1 row collapsed): **4**
- Engine scope warnings: **0** on **0** issues
- Trim scope warnings: **0**
- Non-powertrain issues with engine scope cleared: **19**
- Mono-trim issues: **61** / 62 (98.4%)
- Year-triangulated (emitted): **27** / 62
- Year confidence distribution: low=35, medium=27

## Dedup — merged groups

- 3 rows: `door_hatch_wiring_harness_failure`, `door_wiring_harness_failure`, `hatch_wiring_harness_failure`
- 2 rows: `1_6_engine_oil_consumption_egr`, `oil_consumption_egr_problems_1_6`
- 2 rows: `engine_cover_breather_pipe_breakage`, `engine_cover_pipe_breakage`
- 1 rows: `pcv_valve_failure`

## Engine-scope warnings

_(no engine-scope rules fired)_

## Trim distribution

| Trim | Count | Share |
|---|---:|---:|
| base | 53 | 80.3% |
| GTI | 13 | 19.7% |

## Trim scope warnings

_(none)_

## Cleared-engine issues (non-powertrain)

- `front_wings_rust` (body) — cleared `['1.4', '1.4_FSI', '1.4_TSI', '1.6', '1.6_FSI', '1.9_TDI', '2.0_FSI', '2.0_SDI', '2.0_TDI_PD', '2.0_TFSI', '3.2_R32']`, model_scope=['all_vw_golf_mk5']
- `door_wiring_harness_failure` (electrical) — cleared `['1.9_TDI']`, model_scope=['all_vw_golf_mk5']
- `airbag_system_faults` (electrical) — cleared `['all']`, model_scope=['all_vw_golf_mk5']
- `bonnet_catch_sticking` (body) — cleared `['1.4', '1.4_FSI', '1.4_TSI', '1.6', '1.6_FSI', '1.9_TDI', '2.0_FSI', '2.0_SDI', '2.0_TDI_PD', '2.0_TFSI', '3.2_R32']`, model_scope=['all_vw_golf_mk5']
- `brake_pad_sensor_connector_failure` (brakes) — cleared `['1.9_TDI']`, model_scope=['all_vw_golf_mk5']
- `coil_pack_failure` (electrical) — cleared `['1.6_FSI']`, model_scope=['all_vw_golf_mk5']
- `cv_boot_split` (suspension) — cleared `['all']`, model_scope=['all_vw_golf_mk5']
- `early_cars_rust` (body) — cleared `['1.4', '1.4_FSI', '1.4_TSI', '1.6', '1.6_FSI', '1.9_TDI', '2.0_FSI', '2.0_SDI', '2.0_TDI_PD', '2.0_TFSI', '3.2_R32']`, model_scope=['all_vw_golf_mk5']
- `headliner_sagging` (body) — cleared `['all']`, model_scope=['all_vw_golf_mk5']
- `ignition_switch_wear` (electrical) — cleared `['all']`, model_scope=['all_vw_golf_mk5']
- `radio_battery_drain` (electrical) — cleared `['1.9_TDI']`, model_scope=['all_vw_golf_mk5']
- `rear_wiper_stalk_failure` (electrical) — cleared `['1.9_TDI']`, model_scope=['all_vw_golf_mk5']
- `reverse_light_switch_failure` (electrical) — cleared `['1.9_TDI']`, model_scope=['all_vw_golf_mk5']
- `side_airbag_crash_sensor_failure` (electrical) — cleared `['1.9_TDI']`, model_scope=['all_vw_golf_mk5']
- `soft_touch_material_peeling` (body) — cleared `['all']`, model_scope=['all_vw_golf_mk5']
- `sunroof_motor_failure` (electrical) — cleared `['all']`, model_scope=['all_vw_golf_mk5']
- `suspension_boot_splits` (suspension) — cleared `['all']`, model_scope=['all_vw_golf_mk5']
- `throttle_pedal_response_loss` (electrical) — cleared `['2.0_TDI_PD']`, model_scope=['all_vw_golf_mk5']
- `tie_rod_boot_split` (suspension) — cleared `['all']`, model_scope=['all_vw_golf_mk5']

## Year triangulation examples

- `front_wings_rust` → **2006** (confidence=medium, sources=None)
  - transcript=[], titles=['2006'], engine_windows=['2003-2009']
- `fsi_carbon_buildup_intake_valves` → **2003-2008** (confidence=medium, sources=None)
  - transcript=[], titles=['2003-2008'], engine_windows=['2003-2008']
- `1_4_tsi_twincharger_compressor` → **2005-2008** (confidence=medium, sources=None)
  - transcript=[], titles=['2003-2008'], engine_windows=['2005-2009']
- `2_0_tdi_pd_multiple_failures` → **2003-2008** (confidence=medium, sources=None)
  - transcript=[], titles=['2003-2008'], engine_windows=['2003-2008']
- `air_conditioning_system_problems` → **2003-2008** (confidence=medium, sources=None)
  - transcript=[], titles=['2003-2008'], engine_windows=[]
- `carbon_buildup_oil_consumption_1_4` → **2003-2006** (confidence=medium, sources=None)
  - transcript=[], titles=['2003-2008'], engine_windows=['2003-2006']
- `carbon_buildup_spark_plugs` → **2005** (confidence=medium, sources=None)
  - transcript=[], titles=[], engine_windows=['2003-2008']
- `coil_pack_failure` → **2005** (confidence=medium, sources=None)
  - transcript=[], titles=[], engine_windows=['2003-2008']
- `damaged_cable_harness_engine` → **2003-2008** (confidence=medium, sources=None)
  - transcript=[], titles=['2003-2008'], engine_windows=[]
- `dsg_gearbox_problems` → **2003-2008** (confidence=medium, sources=None)
  - transcript=[], titles=['2003-2008'], engine_windows=[]
- `early_cars_rust` → **2003-2005** (confidence=medium, sources=None)
  - transcript=[], titles=[], engine_windows=['2003-2009']
- `electric_radiator_cooling_fan_failure` → **2003-2008** (confidence=medium, sources=None)
  - transcript=[], titles=['2003-2008'], engine_windows=[]
- `electrical_system_faults` → **2003-2008** (confidence=medium, sources=None)
  - transcript=[], titles=['2003-2008'], engine_windows=[]
- `engine_cover_breather_pipe_breakage` → **2005** (confidence=medium, sources=None)
  - transcript=[], titles=[], engine_windows=['2003-2008']
- `engine_management_system_faults` → **2003-2008** (confidence=medium, sources=None)
  - transcript=[], titles=['2003-2008'], engine_windows=[]
- `fsi_injector_carbon_buildup_timing_chain` → **2003-2008** (confidence=medium, sources=None)
  - transcript=[], titles=['2003-2008'], engine_windows=['2003-2008']
- `fsi_injector_problems_carbon_buildup` → **2003-2008** (confidence=medium, sources=None)
  - transcript=[], titles=['2003-2008'], engine_windows=['2003-2008']
- `oil_consumption_egr_problems_1_6` → **2004-2008** (confidence=medium, sources=None)
  - transcript=[], titles=['2003-2008'], engine_windows=['2004-2009']
- `oil_leak_lambda_sensor` → **2005** (confidence=medium, sources=None)
  - transcript=[], titles=[], engine_windows=['2003-2008']
- `oxygen_sensor_fault` → **2005** (confidence=medium, sources=None)
  - transcript=[], titles=[], engine_windows=['2003-2008']
