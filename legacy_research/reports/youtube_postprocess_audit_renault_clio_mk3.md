# YouTube Issue Post-Processing Audit — renault_clio_mk3

## Summary

- Input rows: **92**
- Cross-brand contamination dropped: **2**
- After dedup: **52**
- Merge groups (> 1 row collapsed): **1**
- Engine scope warnings: **0** on **0** issues
- Trim scope warnings: **0**
- Non-powertrain issues with engine scope cleared: **30**
- Mono-trim issues: **52** / 52 (100.0%)
- Year-triangulated (emitted): **28** / 52
- Year confidence distribution: high=2, low=24, medium=26

## Dedup — merged groups

- 1 rows: `diesel_exhaust_issues`

## Cross-brand contamination — dropped issues

- `poor_rear_visibility_parking` — foreign_brand:seat (label: 'Poor rear visibility when parking')
- `poor_rear_visibility_parking` — foreign_brand:seat (label: 'Poor rear visibility when parking')

## Engine-scope warnings

_(no engine-scope rules fired)_

## Trim distribution

| Trim | Count | Share |
|---|---:|---:|
| base | 55 | 100.0% |

## Trim scope warnings

_(none)_

## Cleared-engine issues (non-powertrain)

- `wiper_motor_failure` (electrical) — cleared `['all']`, model_scope=['all_renault_clio_mk3']
- `scuttle_panel_drain_blockage` (body) — cleared `['1.2_16V', '1.2_TCE', '1.4_16V', '1.5_DCI', '1.6_16V', '2.0_16V', '2.0_RS']`, model_scope=['all_renault_clio_mk3']
- `base_model_cheap_interior` (body) — cleared `['all']`, model_scope=['all_renault_clio_mk3']
- `brake_performance_issues` (brakes) — cleared `['2.0_RS']`, model_scope=['all_renault_clio_mk3']
- `electrical_controls_quality` (electrical) — cleared `['1.2_16V', '1.2_TCE', '1.4_16V', '1.5_DCI', '1.6_16V', '2.0_16V', '2.0_RS']`, model_scope=['all_renault_clio_mk3']
- `electrical_interior_quirks` (electrical) — cleared `['1.2_16V']`, model_scope=['all_renault_clio_mk3']
- `engine_chassis_earth_strap_failure` (electrical) — cleared `['1.2_16V', '1.2_TCE', '1.4_16V', '1.5_DCI', '1.6_16V', '2.0_16V', '2.0_RS']`, model_scope=['all_renault_clio_mk3']
- `engine_control_relay_stuck_closed` (electrical) — cleared `['1.2_TCE']`, model_scope=['all_renault_clio_mk3']
- `front_cup_holder_size` (body) — cleared `['1.2_16V']`, model_scope=['all_renault_clio_mk3']
- `front_wiper_linkage_seizure` (electrical) — cleared `['1.2_16V', '1.2_TCE', '1.4_16V', '1.5_DCI', '1.6_16V', '2.0_16V', '2.0_RS']`, model_scope=['all_renault_clio_mk3']
- `heater_blower_resistor_connector_melting` (electrical) — cleared `['1.2_16V', '1.2_TCE', '1.4_16V', '1.5_DCI', '1.6_16V', '2.0_16V', '2.0_RS']`, model_scope=['all_renault_clio_mk3']
- `high_speed_wind_noise` (body) — cleared `['0.9_TCE']`, model_scope=['all_renault_clio_mk3']
- `inconsistent_pedal_weights` (brakes) — cleared `['0.9_TCE']`, model_scope=['all_renault_clio_mk3']
- `loose_suspension_at_speed` (suspension) — cleared `['0.9_TCE']`, model_scope=['all_renault_clio_mk3']
- `non_standard_aux_input` (electrical) — cleared `['1.2_16V']`, model_scope=['all_renault_clio_mk3']
- `piano_black_trim_scratches` (body) — cleared `['0.9_TCE']`, model_scope=['all_renault_clio_mk3']
- `r_link_infotainment_system_bugs` (electrical) — cleared `['all']`, model_scope=['all_renault_clio_mk3']
- `rear_wheel_bearing_wear` (suspension) — cleared `['2.0_16V', '2.0_RS']`, model_scope=['all_renault_clio_mk3']
- `rust_fuel_filler_cap` (body) — cleared `['2.0_16V', '2.0_RS']`, model_scope=['all_renault_clio_mk3']
- `rust_rear_arches` (body) — cleared `['2.0_16V', '2.0_RS']`, model_scope=['all_renault_clio_mk3']
- `rust_sills` (body) — cleared `['2.0_16V', '2.0_RS']`, model_scope=['all_renault_clio_mk3']
- `sat_nav_remote_dependency` (electrical) — cleared `['1.2_16V']`, model_scope=['all_renault_clio_mk3']
- `sound_system_distortion` (electrical) — cleared `['0.9_TCE']`, model_scope=['all_renault_clio_mk3']
- `start_stop_battery_drain` (electrical) — cleared `['all']`, model_scope=['all_renault_clio_mk3']
- `steering_wheel_melting` (other) — cleared `['2.0_16V', '2.0_RS']`, model_scope=['all_renault_clio_mk3']
- `suspension_squeak_over_bumps` (suspension) — cleared `['0.9_TCE']`, model_scope=['all_renault_clio_mk3']
- `washer_jet_blockage` (electrical) — cleared `['2.0_16V', '2.0_RS']`, model_scope=['all_renault_clio_mk3']
- `water_ingress_body` (body) — cleared `['2.0_16V', '2.0_RS']`, model_scope=['all_renault_clio_mk3']
- `water_ingress_boot` (body) — cleared `['2.0_16V', '2.0_RS']`, model_scope=['all_renault_clio_mk3']
- `water_ingress_interior` (body) — cleared `['2.0_16V', '2.0_RS']`, model_scope=['all_renault_clio_mk3']

## Year triangulation examples

- `wiper_motor_failure` → **2006** (confidence=medium, sources=None)
  - transcript=[], titles=['2006'], engine_windows=[]
- `scuttle_panel_drain_blockage` → **2006** (confidence=high, sources=None)
  - transcript=[], titles=['2006'], engine_windows=['2005-2014']
- `1_2_16v_underpowered` → **2009-2012** (confidence=medium, sources=None)
  - transcript=[], titles=['2009-2012'], engine_windows=['2005-2014']
- `1_6_vvt_refinement_issue` → **2009-2012** (confidence=medium, sources=None)
  - transcript=[], titles=['2009-2012'], engine_windows=['2005-2014']
- `base_model_cheap_interior` → **2009-2012** (confidence=medium, sources=None)
  - transcript=[], titles=['2009-2012'], engine_windows=[]
- `carbon_buildup_valve_deposits` → **2013-2014** (confidence=medium, sources=None)
  - transcript=[], titles=['2013-2014'], engine_windows=['2007-2014']
- `diesel_exhaust_issues` → **2013-2014** (confidence=medium, sources=None)
  - transcript=[], titles=['2013-2014'], engine_windows=['2005-2014']
- `electrical_controls_quality` → **2005-2012** (confidence=medium, sources=None)
  - transcript=[], titles=['2005-2012'], engine_windows=['2005-2014']
- `electrical_interior_quirks` → **2011** (confidence=medium, sources=None)
  - transcript=[], titles=['2011'], engine_windows=['2005-2014']
- `engine_refinement_1_6_vvt` → **2009-2012** (confidence=medium, sources=None)
  - transcript=[], titles=['2009-2012'], engine_windows=['2005-2014']
- `esp_not_standard` → **2009-2012** (confidence=medium, sources=None)
  - transcript=[], titles=['2009-2012'], engine_windows=[]
- `front_cup_holder_size` → **2011** (confidence=medium, sources=None)
  - transcript=[], titles=['2011'], engine_windows=['2005-2014']
- `front_wiper_linkage_seizure` → **2006** (confidence=high, sources=None)
  - transcript=[], titles=['2006'], engine_windows=['2005-2014']
- `gear_grinding_reverse` → **2013** (confidence=medium, sources=None)
  - transcript=[], titles=['2013'], engine_windows=[]
- `gear_linkage_seizure_binding` → **2011** (confidence=medium, sources=None)
  - transcript=[], titles=['2011'], engine_windows=['2005-2014']
- `gearshift_rubbery_feel` → **2005-2012** (confidence=medium, sources=None)
  - transcript=[], titles=['2005-2012'], engine_windows=['2005-2014']
- `high_speed_wind_noise` → **2013** (confidence=medium, sources=None)
  - transcript=[], titles=['2013'], engine_windows=[]
- `inconsistent_pedal_weights` → **2013** (confidence=medium, sources=None)
  - transcript=[], titles=['2013'], engine_windows=[]
- `light_steering_high_speed` → **2009-2012** (confidence=medium, sources=None)
  - transcript=[], titles=['2009-2012'], engine_windows=[]
- `loose_suspension_at_speed` → **2013** (confidence=medium, sources=None)
  - transcript=[], titles=['2013'], engine_windows=[]
