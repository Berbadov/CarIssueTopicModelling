# YouTube Issue Post-Processing Audit — vw_golf_mk7

## Summary

- Input rows: **115**
- Cross-brand contamination dropped: **0**
- After dedup: **97**
- Merge groups (> 1 row collapsed): **7**
- Engine scope warnings: **0** on **0** issues
- Trim scope warnings: **31**
- Non-powertrain issues with engine scope cleared: **15**
- Mono-trim issues: **76** / 97 (78.4%)
- Year-triangulated (emitted): **47** / 97
- Year confidence distribution: high=23, low=50, medium=24

## Dedup — merged groups

- 8 rows: `coolant_leak_thermostat_water_pump`, `faulty_thermostat_housing_water_pump`, `thermostat_water_pump_leak`, `water_pump_coolant_leak`, `water_pump_cover_stuck_closed`, `water_pump_failure`, `water_pump_leak`, `water_pump_premature_failure`
- 3 rows: `ignition_coil_failure`, `ignition_coil_misfire_codes`, `ignition_coil_pack_failure`
- 2 rows: `carbon_buildup_intake_valves`, `intake_carbon_buildup`
- 2 rows: `clogged_oil_scraper_rings`, `oil_consumption_clogged_scraper_rings`
- 2 rows: `evap_fuel_tank_pump_recall`, `fuel_tank_suction_pump_recall`
- 2 rows: `front_speaker_housing_leak`, `rear_speaker_housing_leak`
- 2 rows: `key_fob_battery_depletion`, `key_fob_battery_failure`

## Engine-scope warnings

_(no engine-scope rules fired)_

## Trim distribution

| Trim | Count | Share |
|---|---:|---:|
| base | 60 | 38.5% |
| GTI | 48 | 30.8% |
| TDI | 21 | 13.5% |
| R | 16 | 10.3% |
| GTD | 11 | 7.1% |

## Trim scope warnings

- `fuel_tank_suction_pump_recall` — dominant_trim=GTI, model_scope=['golf_gti_mk7'], affected_engines=['2.0_TSI']
- `washer_fluid_sensor_failure` — dominant_trim=GTI, model_scope=['golf_gti_mk7'], affected_engines=[]
- `ac_solenoid_valve_failure` — dominant_trim=GTI, model_scope=['golf_gti_mk7'], affected_engines=['2.0_TSI']
- `blower_motor_failure` — dominant_trim=GTI, model_scope=['golf_gti_mk7'], affected_engines=[]
- `cam_magnet_failure` — dominant_trim=R, model_scope=['golf_r_mk7'], affected_engines=['2.0_TSI']
- `clutch_at_power_limit` — dominant_trim=GTI, model_scope=['golf_gti_mk7'], affected_engines=['2.0_TSI']
- `clutch_failure_under_power` — dominant_trim=GTI, model_scope=['golf_gti_mk7'], affected_engines=['2.0_TSI']
- `cracked_brake_discs` — dominant_trim=R, model_scope=['golf_r_mk7'], affected_engines=[]
- `dashboard_dust_cover_scratches` — dominant_trim=GTI, model_scope=['golf_gti_mk7'], affected_engines=[]
- `dsg_gear_selector_issue` — dominant_trim=R, model_scope=['golf_r_mk7'], affected_engines=['2.0_TSI']
- `early_turbo_failure` — dominant_trim=GTI, model_scope=['golf_gti_mk7'], affected_engines=['2.0_TSI']
- `front_top_mount_wear` — dominant_trim=R, model_scope=['golf_r_mk7'], affected_engines=[]
- `fuel_flap_lock_sticky` — dominant_trim=R, model_scope=['golf_r_mk7'], affected_engines=[]
- `fuel_injector_stuck_open` — dominant_trim=GTI, model_scope=['golf_gti_mk7'], affected_engines=['2.0_TSI']
- `fuel_pump_failure_early_models` — dominant_trim=GTI, model_scope=['golf_gti_mk7'], affected_engines=['2.0_TSI']
- `haldex_system_failure` — dominant_trim=R, model_scope=['golf_r_mk7'], affected_engines=[]
- `manual_clutch_slip` — dominant_trim=R, model_scope=['golf_r_mk7'], affected_engines=['2.0_TSI']
- `plastic_oil_pan_cracking` — dominant_trim=GTI, model_scope=['golf_gti_mk7'], affected_engines=['2.0_TSI']
- `plastic_oil_pan_plug_leak` — dominant_trim=GTI, model_scope=['golf_gti_mk7'], affected_engines=['2.0_TSI']
- `prets_wheel_cracking` — dominant_trim=R, model_scope=['golf_r_mk7'], affected_engines=[]
- `rain_x_sensor_fouling` — dominant_trim=GTI, model_scope=['golf_gti_mk7'], affected_engines=[]
- `rear_damper_leak` — dominant_trim=R, model_scope=['golf_r_mk7'], affected_engines=[]
- `rear_footwell_water_ingress` — dominant_trim=R, model_scope=['golf_r_mk7'], affected_engines=[]
- `start_stop_button_flaking` — dominant_trim=GTI, model_scope=['golf_gti_mk7'], affected_engines=[]
- `subframe_bolt_failure` — dominant_trim=GTI, model_scope=['golf_gti_mk7'], affected_engines=[]
- `sunroof_rattles_and_leaks` — dominant_trim=GTI, model_scope=['golf_gti_mk7'], affected_engines=[]
- `sunroof_seal_failure` — dominant_trim=GTI, model_scope=['golf_gti_mk7'], affected_engines=[]
- `thermostat_housing_coolant_leak` — dominant_trim=GTI, model_scope=['golf_gti_mk7'], affected_engines=['2.0_TSI']
- `turbo_failure_early_models` — dominant_trim=GTI, model_scope=['golf_gti_mk7'], affected_engines=['2.0_TSI']
- `turbocharger_seal_failure_702n` — dominant_trim=GTI, model_scope=['golf_gti_mk7'], affected_engines=['2.0_TSI']
- `water_ingress_speaker_bracket` — dominant_trim=GTI, model_scope=['golf_gti_mk7'], affected_engines=[]

## Cleared-engine issues (non-powertrain)

- `bonnet_release_cable_failure` (body) — cleared `['2.0_TSI']`, model_scope=['all_vw_golf_mk7']
- `washer_fluid_sensor_failure` (electrical) — cleared `['2.0_TSI']`, model_scope=['golf_gti_mk7']
- `blower_motor_failure` (electrical) — cleared `['2.0_TSI']`, model_scope=['golf_gti_mk7']
- `cracked_brake_discs` (brakes) — cleared `['2.0_TSI']`, model_scope=['golf_r_mk7']
- `front_top_mount_wear` (suspension) — cleared `['2.0_TSI']`, model_scope=['golf_r_mk7']
- `fuel_flap_lock_sticky` (body) — cleared `['2.0_TSI']`, model_scope=['golf_r_mk7']
- `haldex_system_failure` (other) — cleared `['2.0_TSI']`, model_scope=['golf_r_mk7']
- `prets_wheel_cracking` (body) — cleared `['2.0_TSI']`, model_scope=['golf_r_mk7']
- `rear_damper_leak` (suspension) — cleared `['2.0_TSI']`, model_scope=['golf_r_mk7']
- `rear_footwell_water_ingress` (body) — cleared `['2.0_TSI']`, model_scope=['golf_r_mk7']
- `start_stop_button_flaking` (electrical) — cleared `['2.0_TSI']`, model_scope=['golf_gti_mk7']
- `subframe_bolt_failure` (suspension) — cleared `['2.0_TSI']`, model_scope=['golf_gti_mk7']
- `sunroof_rattles_and_leaks` (body) — cleared `['2.0_TSI']`, model_scope=['golf_gti_mk7']
- `sunroof_seal_failure` (body) — cleared `['2.0_TSI']`, model_scope=['golf_gti_mk7']
- `water_ingress_speaker_bracket` (body) — cleared `['2.0_TSI']`, model_scope=['golf_gti_mk7']

## Year triangulation examples

- `water_pump_coolant_leak` → **2015** (confidence=high, sources=None)
  - transcript=['2013-2020'], titles=['2013-2020'], engine_windows=['2013-2020']
- `oil_consumption_clogged_scraper_rings` → **2014-2017** (confidence=high, sources=None)
  - transcript=['2014-2017'], titles=['2013-2020'], engine_windows=['2013-2020']
- `sunroof_leak_squeak_crack` → **2013-2020** (confidence=medium, sources=None)
  - transcript=[], titles=['2013-2020'], engine_windows=[]
- `timing_belt_replacement_interval_confusion` → **2013-2020** (confidence=high, sources=None)
  - transcript=['2013-2020'], titles=['2013-2020'], engine_windows=['2013-2020']
- `timing_chain_stretch_tensioner_failure` → **2013-2020** (confidence=medium, sources=None)
  - transcript=[], titles=['2013-2020'], engine_windows=['2013-2020']
- `carbon_buildup_intake_valves` → **2013-2020** (confidence=high, sources=None)
  - transcript=['2013-2020'], titles=['2013-2020'], engine_windows=['2013-2020']
- `carbon_buildup_valve_spring_failure` → **2015-2020** (confidence=medium, sources=None)
  - transcript=[], titles=['2015-2020'], engine_windows=['2013-2020']
- `ea288_diesel_high_mileage_failures` → **2013-2020** (confidence=medium, sources=None)
  - transcript=[], titles=['2013-2020'], engine_windows=['2013-2020']
- `ea888_turbo_failure_pcv_rear_seal` → **2015-2017** (confidence=high, sources=None)
  - transcript=['2013-2020'], titles=['2013-2020'], engine_windows=['2013-2020']
- `manual_clutch_dmf_failure` → **2013-2020** (confidence=medium, sources=None)
  - transcript=[], titles=['2013-2020'], engine_windows=[]
- `water_leakage_multiple_points` → **2015-2020** (confidence=medium, sources=None)
  - transcript=[], titles=['2015-2020'], engine_windows=[]
- `bonnet_release_cable_failure` → **2013-2020** (confidence=high, sources=None)
  - transcript=['2013-2020'], titles=['2013-2020'], engine_windows=['2013-2020']
- `fuel_tank_suction_pump_recall` → **2013-2020** (confidence=high, sources=None)
  - transcript=['2013-2020'], titles=['2013-2020'], engine_windows=['2013-2020']
- `glow_plug_failure` → **2013-2020** (confidence=medium, sources=None)
  - transcript=[], titles=['2013-2020'], engine_windows=['2013-2020']
- `ignition_coil_misfire_codes` → **2013-2020** (confidence=high, sources=None)
  - transcript=['2013-2020'], titles=['2013-2020'], engine_windows=['2013-2020']
- `manual_clutch_slippage_dsg_selector_issue` → **2013-2020** (confidence=medium, sources=None)
  - transcript=[], titles=['2013-2020'], engine_windows=[]
- `parcel_shelf_clips_breaking` → **2013-2020** (confidence=medium, sources=None)
  - transcript=[], titles=['2013-2020'], engine_windows=[]
- `rear_main_seal_oil_leak` → **2013-2020** (confidence=high, sources=None)
  - transcript=['2013-2020'], titles=['2013-2020'], engine_windows=['2013-2020']
- `washer_fluid_sensor_failure` → **2013-2020** (confidence=high, sources=None)
  - transcript=['2013-2020'], titles=['2013-2020'], engine_windows=['2013-2020']
- `ac_solenoid_valve_failure` → **2013-2020** (confidence=high, sources=None)
  - transcript=['2013-2020'], titles=['2013-2020'], engine_windows=['2013-2020']
