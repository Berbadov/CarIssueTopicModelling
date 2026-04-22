# YouTube Issue Post-Processing Audit — vw_golf_mk7

## Summary

- Input rows: **111**
- After dedup: **87**
- Merge groups (> 1 row collapsed): **10**
- Engine scope warnings: **0** on **0** issues
- Trim scope warnings: **42**
- Non-powertrain issues with engine scope cleared: **34**
- Mono-trim issues: **74** / 87 (85.1%)
- Year-triangulated (emitted): **48** / 87
- Year confidence distribution: high=15, low=39, medium=33

## Dedup — merged groups

- 6 rows: `cooling_system_failures`, `thermostat_housing_coolant_leak`, `thermostat_housing_water_pump_leak`, `thermostat_waterpump_coolant_leak`, `water_pump_thermostat_failure`, `water_pump_thermostat_housing_coolant_leak`
- 4 rows: `pcv_failure_rear_main_seal_leak`, `rear_main_seal_failure`, `rear_main_seal_leak`, `rear_main_seal_oil_leak`
- 2 rows: `ac_compressor_solenoid_valve_defect`, `ac_solenoid_valve_failure`
- 2 rows: `bonnet_release_cable_failure`, `bonnet_release_cable_slip`
- 2 rows: `carbon_buildup_intake_valves`, `intake_valve_carbon_buildup`
- 2 rows: `clutch_slip_manual`, `manual_clutch_slip_rev_hang`
- 2 rows: `start_stop_button_flaking`, `sticky_start_stop_button`
- 2 rows: `timing_cover_oil_leak`, `upper_timing_chain_cover_oil_leak`
- 2 rows: `washer_fluid_sensor_failure`, `washer_fluid_sensor_rainx_fouling`
- 1 rows: `subframe_bolt_failure`

## Engine-scope warnings

_(no engine-scope rules fired)_

## Trim distribution

| Trim | Count | Share |
|---|---:|---:|
| GTI | 49 | 39.5% |
| base | 42 | 33.9% |
| R | 28 | 22.6% |
| TDI | 5 | 4.0% |

## Trim scope warnings

- `carbon_buildup_intake_valves` — dominant_trim=GTI, model_scope=['golf_gti_mk7'], affected_engines=['2.0_TSI']
- `washer_fluid_sensor_failure` — dominant_trim=GTI, model_scope=['golf_gti_mk7'], affected_engines=[]
- `plastic_oil_pan_cracking` — dominant_trim=GTI, model_scope=['golf_gti_mk7'], affected_engines=['2.0_TSI']
- `early_turbo_failure` — dominant_trim=GTI, model_scope=['golf_gti_mk7'], affected_engines=['2.0_TSI']
- `start_stop_button_flaking` — dominant_trim=GTI, model_scope=['golf_gti_mk7'], affected_engines=[]
- `sunroof_leaks_squeaks_cracks` — dominant_trim=GTI, model_scope=['golf_gti_mk7'], affected_engines=[]
- `airbag_tensioner_recall` — dominant_trim=R, model_scope=['golf_r_mk7'], affected_engines=[]
- `blower_motor_failure` — dominant_trim=GTI, model_scope=['golf_gti_mk7'], affected_engines=[]
- `bonnet_mechanism_failure` — dominant_trim=R, model_scope=['golf_r_mk7'], affected_engines=[]
- `child_lock_recall` — dominant_trim=R, model_scope=['golf_r_mk7'], affected_engines=[]
- `clutch_premature_wear` — dominant_trim=R, model_scope=['golf_r_mk7'], affected_engines=['2.0_TSI']
- `coolant_system_plastic_failures` — dominant_trim=GTI, model_scope=['golf_gti_mk7'], affected_engines=['2.0_TSI']
- `crank_walk_manual` — dominant_trim=GTI, model_scope=['golf_gti_mk7'], affected_engines=['2.0_TSI']
- `dashboard_dust_cover_scratches` — dominant_trim=GTI, model_scope=['golf_gti_mk7'], affected_engines=[]
- `dsg_clunky_low_speed` — dominant_trim=GTI, model_scope=['golf_gti_mk7'], affected_engines=['2.0_TSI']
- `dsg_gear_selector_malfunction` — dominant_trim=R, model_scope=['golf_r_mk7'], affected_engines=['2.0_TSI']
- `early_fuel_pump_failure` — dominant_trim=GTI, model_scope=['golf_gti_mk7'], affected_engines=['2.0_TSI']
- `early_turbo_failure` — dominant_trim=GTI, model_scope=['golf_gti_mk7'], affected_engines=['2.0_TSI']
- `engine_catastrophic_failure` — dominant_trim=GTI, model_scope=['golf_gti_mk7'], affected_engines=['2.0_TSI']
- `evap_pump_recall` — dominant_trim=GTI, model_scope=['golf_gti_mk7'], affected_engines=['2.0_TSI']
- `faulty_battery_batch` — dominant_trim=R, model_scope=['golf_r_mk7'], affected_engines=[]
- `fifth_door_seal_leak` — dominant_trim=R, model_scope=['golf_r_mk7'], affected_engines=[]
- `front_top_mount_wear` — dominant_trim=R, model_scope=['golf_r_mk7'], affected_engines=[]
- `fuel_flap_lock_sticky` — dominant_trim=R, model_scope=['golf_r_mk7'], affected_engines=[]
- `fuel_injector_fouling_misfire` — dominant_trim=GTI, model_scope=['golf_gti_mk7'], affected_engines=['2.0_TSI']
- `fuel_suction_pump_recall` — dominant_trim=GTI, model_scope=['golf_gti_mk7'], affected_engines=['2.0_TSI']
- `haldex_system_failure` — dominant_trim=R, model_scope=['golf_r_mk7'], affected_engines=[]
- `heated_mirror_glass_crack` — dominant_trim=R, model_scope=['golf_r_mk7'], affected_engines=[]
- `ignition_coil_pack_failure` — dominant_trim=GTI, model_scope=['golf_gti_mk7'], affected_engines=['2.0_TSI']
- `interior_water_leaks` — dominant_trim=GTI, model_scope=['golf_gti_mk7'], affected_engines=[]
- `manual_clutch_slippage` — dominant_trim=R, model_scope=['golf_r_mk7'], affected_engines=['2.0_TSI']
- `parcel_shelf_clip_failure` — dominant_trim=R, model_scope=['golf_r_mk7'], affected_engines=[]
- `plastic_oil_pan_plug_leak` — dominant_trim=GTI, model_scope=['golf_gti_mk7'], affected_engines=['2.0_TSI']
- `rear_footwell_water_ingress` — dominant_trim=R, model_scope=['golf_r_mk7'], affected_engines=[]
- `rear_head_restraint_recall` — dominant_trim=R, model_scope=['golf_r_mk7'], affected_engines=[]
- `rear_shock_absorber_knocking` — dominant_trim=R, model_scope=['golf_r_mk7'], affected_engines=[]
- `sunroof_rattle` — dominant_trim=GTI, model_scope=['golf_gti_mk7'], affected_engines=[]
- `sunroof_seal_failure` — dominant_trim=GTI, model_scope=['golf_gti_mk7'], affected_engines=[]
- `takata_airbag_recall` — dominant_trim=R, model_scope=['golf_r_mk7'], affected_engines=[]
- `turbo_wastegate_sticking` — dominant_trim=GTI, model_scope=['golf_gti_mk7'], affected_engines=['2.0_TSI']
- `tyre_placard_recall` — dominant_trim=R, model_scope=['golf_r_mk7'], affected_engines=[]
- `wheel_cracking_buckling` — dominant_trim=R, model_scope=['golf_r_mk7'], affected_engines=[]

## Cleared-engine issues (non-powertrain)

- `washer_fluid_sensor_failure` (electrical) — cleared `['2.0_TSI']`, model_scope=['golf_gti_mk7']
- `blocked_drainage_channels_water_leak` (body) — cleared `['all']`, model_scope=['all_vw_golf_mk7']
- `bonnet_release_cable_failure` (body) — cleared `['2.0_TSI']`, model_scope=['all_vw_golf_mk7']
- `start_stop_button_flaking` (electrical) — cleared `['1.4_TSI', '2.0_TSI']`, model_scope=['golf_gti_mk7']
- `subframe_bolt_failure` (suspension) — cleared `['2.0_TSI']`, model_scope=['all_vw_golf_mk7']
- `sunroof_leaks_squeaks_cracks` (body) — cleared `['all']`, model_scope=['golf_gti_mk7']
- `airbag_tensioner_recall` (body) — cleared `['2.0_TSI']`, model_scope=['golf_r_mk7']
- `blower_motor_failure` (electrical) — cleared `['2.0_TSI']`, model_scope=['golf_gti_mk7']
- `bonnet_mechanism_failure` (body) — cleared `['2.0_TSI']`, model_scope=['golf_r_mk7']
- `child_lock_recall` (body) — cleared `['2.0_TSI']`, model_scope=['golf_r_mk7']
- `dashboard_dust_cover_scratches` (body) — cleared `['all']`, model_scope=['golf_gti_mk7']
- `electronic_handbrake_sticky` (brakes) — cleared `['all']`, model_scope=['all_vw_golf_mk7']
- `faulty_battery_batch` (electrical) — cleared `['2.0_TSI']`, model_scope=['golf_r_mk7']
- `fifth_door_seal_leak` (body) — cleared `['all']`, model_scope=['golf_r_mk7']
- `front_suspension_clunking` (suspension) — cleared `['all']`, model_scope=['all_vw_golf_mk7']
- `front_top_mount_wear` (suspension) — cleared `['2.0_TSI']`, model_scope=['golf_r_mk7']
- `fuel_flap_lock_sticky` (body) — cleared `['all']`, model_scope=['golf_r_mk7']
- `haldex_system_failure` (other) — cleared `['2.0_TSI']`, model_scope=['golf_r_mk7']
- `halogen_bulb_replacement` (electrical) — cleared `['all']`, model_scope=['all_vw_golf_mk7']
- `heated_mirror_glass_crack` (electrical) — cleared `['all']`, model_scope=['golf_r_mk7']
- `interior_water_leaks` (body) — cleared `['1.4_TSI']`, model_scope=['golf_gti_mk7']
- `panoramic_roof_rattle_leak` (body) — cleared `['all']`, model_scope=['all_vw_golf_mk7']
- `parcel_shelf_clip_failure` (body) — cleared `['2.0_TSI']`, model_scope=['golf_r_mk7']
- `rear_footwell_water_ingress` (body) — cleared `['all']`, model_scope=['golf_r_mk7']
- `rear_head_restraint_recall` (body) — cleared `['2.0_TSI']`, model_scope=['golf_r_mk7']
- `rear_shock_absorber_knocking` (suspension) — cleared `['2.0_TSI']`, model_scope=['golf_r_mk7']
- `rear_suspension_bushing_premature_wear` (suspension) — cleared `['all']`, model_scope=['all_vw_golf_mk7']
- `sunroof_leak` (body) — cleared `['1.4_TSI']`, model_scope=['all_vw_golf_mk7']
- `sunroof_rattle` (body) — cleared `['2.0_TSI']`, model_scope=['golf_gti_mk7']
- `sunroof_seal_failure` (body) — cleared `['2.0_TSI']`, model_scope=['golf_gti_mk7']
- `takata_airbag_recall` (body) — cleared `['2.0_TSI']`, model_scope=['golf_r_mk7']
- `tyre_placard_recall` (body) — cleared `['2.0_TSI']`, model_scope=['golf_r_mk7']
- `wheel_cracking_buckling` (suspension) — cleared `['2.0_TSI']`, model_scope=['golf_r_mk7']
- `wiper_smearing` (body) — cleared `['all']`, model_scope=['all_vw_golf_mk7']

## Year triangulation examples

- `water_pump_thermostat_housing_coolant_leak` → **2014-2017** (confidence=high, sources=None)
  - transcript=['2014-2017'], titles=['2013-2020'], engine_windows=['2013-2020']
- `carbon_buildup_intake_valves` → **2013-2020** (confidence=medium, sources=None)
  - transcript=[], titles=['2013-2020'], engine_windows=['2013-2020']
- `pcv_failure_rear_main_seal_leak` → **2014-2017** (confidence=high, sources=None)
  - transcript=['2014-2017'], titles=['2013-2020'], engine_windows=['2013-2020']
- `washer_fluid_sensor_failure` → **2013-2020** (confidence=medium, sources=None)
  - transcript=[], titles=['2013-2020'], engine_windows=['2013-2020']
- `plastic_oil_pan_cracking` → **2013-2020** (confidence=medium, sources=None)
  - transcript=[], titles=['2013-2020'], engine_windows=['2013-2020']
- `ac_solenoid_valve_failure` → **2013-2020** (confidence=medium, sources=None)
  - transcript=[], titles=['2013-2020'], engine_windows=['2013-2020']
- `bonnet_release_cable_failure` → **2013-2020** (confidence=medium, sources=None)
  - transcript=[], titles=['2013-2020'], engine_windows=['2013-2020']
- `cooling_system_issues` → **2013-2020** (confidence=medium, sources=None)
  - transcript=[], titles=['2013-2020'], engine_windows=[]
- `early_turbo_failure` → **2015** (confidence=high, sources=None)
  - transcript=[], titles=['2013-2020'], engine_windows=['2013-2020']
- `subframe_bolt_failure` → **2013-2020** (confidence=medium, sources=None)
  - transcript=[], titles=['2013-2020'], engine_windows=['2013-2020']
- `turbocharger_failure_2_0_tsi` → **2013-2017** (confidence=high, sources=None)
  - transcript=[], titles=['2013-2020'], engine_windows=['2013-2020']
- `upper_timing_chain_cover_oil_leak` → **2013-2020** (confidence=medium, sources=None)
  - transcript=[], titles=['2013-2020'], engine_windows=['2013-2020']
- `vacuum_leaks_pcv_hoses` → **2014-2017** (confidence=high, sources=None)
  - transcript=['2014-2017'], titles=['2013-2020'], engine_windows=['2013-2020']
- `airbag_tensioner_recall` → **2017** (confidence=high, sources=None)
  - transcript=[], titles=['2013-2020'], engine_windows=['2013-2020']
- `blower_motor_failure` → **2013-2020** (confidence=medium, sources=None)
  - transcript=[], titles=['2013-2020'], engine_windows=['2013-2020']
- `bonnet_mechanism_failure` → **2013-2020** (confidence=medium, sources=None)
  - transcript=[], titles=['2013-2020'], engine_windows=['2013-2020']
- `cabin_blower_control_unit_failure` → **2013-2019** (confidence=medium, sources=None)
  - transcript=[], titles=['2013-2019'], engine_windows=[]
- `camshaft_pulley_nut_loosening` → **2013-2019** (confidence=medium, sources=None)
  - transcript=[], titles=['2013-2019'], engine_windows=['2013-2020']
- `child_lock_recall` → **2016** (confidence=high, sources=None)
  - transcript=[], titles=['2013-2020'], engine_windows=['2013-2020']
- `child_safety_lock_disengagement` → **2013-2019** (confidence=medium, sources=None)
  - transcript=[], titles=['2013-2019'], engine_windows=[]
