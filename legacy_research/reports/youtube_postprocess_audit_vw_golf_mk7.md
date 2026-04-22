# YouTube Issue Post-Processing Audit — vw_golf_mk7

## Summary

- Input rows: **154**
- Cross-brand contamination dropped: **0**
- After dedup: **70**
- Merge groups (> 1 row collapsed): **12**
- Engine scope warnings: **0** on **0** issues
- Trim scope warnings: **0**
- Non-powertrain issues with engine scope cleared: **22**
- Mono-trim issues: **69** / 70 (98.6%)
- Year-triangulated (emitted): **56** / 70
- Year confidence distribution: high=8, low=14, medium=48

## Dedup — merged groups

- 4 rows: `coolant_leak_thermostat_water_pump`, `thermostat_water_pump_housing_leak`, `water_pump_failure`, `water_pump_thermostat_failure`
- 3 rows: `pcv_failure_rear_main_seal`, `rear_main_seal_failure`, `rear_main_seal_oil_leak`
- 3 rows: `plastic_oil_drain_plug_leak`, `plastic_oil_pan_and_drain_plug_issues`, `plastic_oil_pan_plug_leak`
- 2 rows: `bonnet_release_cable_break`, `bonnet_release_cable_slip`
- 2 rows: `carbon_buildup_intake_valves`, `carbon_buildup_on_valves`
- 2 rows: `ea888_engine_issues`, `pcv_valve_failure`
- 2 rows: `evap_fuel_tank_pump_recall`, `fuel_tank_suction_pump_recall`
- 2 rows: `manual_clutch_slip_wear`, `manual_clutch_wear_limit`
- 2 rows: `subframe_bolt_failure`, `subframe_bolt_issue`
- 2 rows: `timing_chain_tensioner_failure`, `timing_chain_tensioner_wear_1_8_tsi`
- 2 rows: `turbo_failure_early_stop_start`, `turbo_failure_stop_start`
- 1 rows: `mib_module_failure`

## Engine-scope warnings

_(no engine-scope rules fired)_

## Trim distribution

| Trim | Count | Share |
|---|---:|---:|
| base | 90 | 92.8% |
| TDI | 7 | 7.2% |

## Trim scope warnings

_(none)_

## Cleared-engine issues (non-powertrain)

- `bonnet_release_cable_slip` (body) — cleared `['1.8_TSI', '2.0_TSI']`, model_scope=['all_vw_golf_mk7']
- `subframe_bolt_failure` (suspension) — cleared `['2.0_TSI', 'CJXC', 'DJHA', 'DNUE']`, model_scope=['all_vw_golf_mk7']
- `sunroof_problems` (body) — cleared `['all']`, model_scope=['all_vw_golf_mk7']
- `washer_fluid_sensor_failure` (electrical) — cleared `['2.0_TSI', 'CJXC', 'DJHA', 'DNUE']`, model_scope=['all_vw_golf_mk7']
- `alloy_wheel_crack_buckle` (suspension) — cleared `['1.8_TSI', '2.0_TSI']`, model_scope=['all_vw_golf_mk7']
- `blower_motor_failure` (electrical) — cleared `['2.0_TSI']`, model_scope=['all_vw_golf_mk7']
- `body_vent_seal_leak` (body) — cleared `['all']`, model_scope=['all_vw_golf_mk7']
- `bonnet_mechanism_failure` (body) — cleared `['CJXC', 'DJHA', 'DNUE']`, model_scope=['all_vw_golf_mk7']
- `front_strut_top_mount_wear` (suspension) — cleared `['1.8_TSI', '2.0_TSI']`, model_scope=['all_vw_golf_mk7']
- `haldex_system_failure` (other) — cleared `['1.8_TSI', '2.0_TSI']`, model_scope=['all_vw_golf_mk7']
- `mib_module_failure` (electrical) — cleared `['1.8_TSI', '2.0_TSI']`, model_scope=['all_vw_golf_mk7']
- `modern_reliability_decline` (other) — cleared `['1.0_TSI', '1.2_TSI', '1.4_TSI', '1.5_TSI', '1.6_TDI', '1.8_TSI', '2.0_TDI', '2.0_TSI']`, model_scope=['all_vw_golf_mk7']
- `parcel_shelf_clip_failure` (body) — cleared `['CJXC', 'DJHA', 'DNUE']`, model_scope=['all_vw_golf_mk7']
- `premature_front_wheel_bearing_failure` (suspension) — cleared `['all']`, model_scope=['all_vw_golf_mk7']
- `rear_footwell_water_leak` (body) — cleared `['1.8_TSI', '2.0_TSI']`, model_scope=['all_vw_golf_mk7']
- `rear_suspension_knocking` (suspension) — cleared `['CJXC', 'DJHA', 'DNUE']`, model_scope=['all_vw_golf_mk7']
- `start_button_finish_flaking` (electrical) — cleared `['all']`, model_scope=['all_vw_golf_mk7']
- `sunroof_seal_failure` (body) — cleared `['2.0_TSI']`, model_scope=['all_vw_golf_mk7']
- `torsion_beam_suspension_ride` (suspension) — cleared `['1.0_TSI', '1.2_TSI', '1.4_TSI', '1.6_TDI']`, model_scope=['all_vw_golf_mk7']
- `water_ingress_body_seals` (body) — cleared `['all']`, model_scope=['all_vw_golf_mk7']
- `water_ingress_footwell` (body) — cleared `['2.0_TSI']`, model_scope=['all_vw_golf_mk7']
- `wiper_smearing` (body) — cleared `['all']`, model_scope=['all_vw_golf_mk7']

## Year triangulation examples

- `thermostat_water_pump_housing_leak` → **2013-2020** (confidence=medium, sources=None)
  - transcript=[], titles=['2013-2020'], engine_windows=['2013-2020']
- `carbon_buildup_intake_valves` → **2013-2020** (confidence=medium, sources=None)
  - transcript=[], titles=['2013-2020'], engine_windows=['2013-2020']
- `plastic_oil_pan_and_drain_plug_issues` → **2013-2020** (confidence=medium, sources=None)
  - transcript=[], titles=['2013-2020'], engine_windows=['2013-2020']
- `rear_main_seal_failure` → **2013-2020** (confidence=medium, sources=None)
  - transcript=[], titles=['2013-2020'], engine_windows=['2013-2020']
- `timing_chain_tensioner_failure` → **2013-2020** (confidence=medium, sources=None)
  - transcript=[], titles=['2013-2020'], engine_windows=['2013-2020']
- `bonnet_release_cable_slip` → **2013-2020** (confidence=medium, sources=None)
  - transcript=[], titles=['2013-2020'], engine_windows=['2013-2020']
- `clutch_at_power_limit` → **2013-2020** (confidence=medium, sources=None)
  - transcript=[], titles=['2013-2020'], engine_windows=['2013-2020']
- `coolant_leak_thermostat_housing` → **2013-2020** (confidence=medium, sources=None)
  - transcript=[], titles=['2013-2020'], engine_windows=['2013-2020']
- `fuel_pump_nickel_plating_flaking` → **2015** (confidence=high, sources=None)
  - transcript=[], titles=['2015-2020'], engine_windows=[]
- `fuel_tank_suction_pump_recall` → **2013-2020** (confidence=medium, sources=None)
  - transcript=[], titles=['2013-2020'], engine_windows=['2013-2020']
- `manual_clutch_wear_limit` → **2013-2020** (confidence=medium, sources=None)
  - transcript=[], titles=['2013-2020'], engine_windows=['2013-2020']
- `subframe_bolt_failure` → **2013-2020** (confidence=medium, sources=None)
  - transcript=[], titles=['2013-2020'], engine_windows=['2013-2020']
- `sunroof_problems` → **2015-2020** (confidence=medium, sources=None)
  - transcript=[], titles=['2015-2020'], engine_windows=[]
- `turbo_failure_early_models` → **2015** (confidence=high, sources=None)
  - transcript=[], titles=['2015-2020'], engine_windows=[]
- `turbo_failure_early_stop_start` → **2013-2015** (confidence=high, sources=None)
  - transcript=[], titles=['2013-2020'], engine_windows=['2013-2020']
- `washer_fluid_sensor_failure` → **2013-2020** (confidence=medium, sources=None)
  - transcript=[], titles=['2013-2020'], engine_windows=['2013-2020']
- `ac_solenoid_valve_failure` → **2013-2020** (confidence=medium, sources=None)
  - transcript=[], titles=['2013-2020'], engine_windows=['2013-2020']
- `adblue_system_faults` → **2013-2016** (confidence=medium, sources=None)
  - transcript=[], titles=['2013-2016'], engine_windows=['2013-2020']
- `blower_motor_failure` → **2013-2020** (confidence=medium, sources=None)
  - transcript=[], titles=['2013-2020'], engine_windows=['2013-2020']
- `bonnet_mechanism_failure` → **2013-2020** (confidence=medium, sources=None)
  - transcript=[], titles=['2013-2020'], engine_windows=[]
