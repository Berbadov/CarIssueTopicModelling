# YouTube Issue Post-Processing Audit — vw_golf_mk7

## Summary

- Input rows: **35**
- After dedup: **33**
- Merge groups (> 1 row collapsed): **1**
- Engine scope warnings: **0** on **0** issues
- Trim scope warnings: **4**
- Non-powertrain issues with engine scope cleared: **1**
- Mono-trim issues: **13** / 33 (39.4%)
- Year-triangulated (emitted): **23** / 33
- Year confidence distribution: high=10, low=10, medium=13

## Dedup — merged groups

- 3 rows: `cooling_system_water_pump_leaks`, `thermostat_water_pump_coolant_leak`, `water_pump_leak`

## Engine-scope warnings

_(no engine-scope rules fired)_

## Trim distribution

| Trim | Count | Share |
|---|---:|---:|
| base | 53 | 57.6% |
| GTI | 24 | 26.1% |
| R | 15 | 16.3% |

## Trim scope warnings

- `early_mk7_gti_r_turbo_failures` — dominant_trim=GTI, model_scope=['golf_gti_mk7'], affected_engines=['2.0_TSI']
- `ea888_timing_chain_issues` — dominant_trim=GTI, model_scope=['golf_gti_mk7'], affected_engines=['2.0_TSI']
- `hot_weather_power_decrease` — dominant_trim=R, model_scope=['golf_r_mk7'], affected_engines=['2.0_TSI']
- `takata_airbag_recall` — dominant_trim=R, model_scope=['golf_r_mk7'], affected_engines=[]

## Cleared-engine issues (non-powertrain)

- `rear_beam_suspension_tank_clearance` (suspension) — cleared `['1.6_TDI', '2.0_TDI']`, model_scope=['diesel_only']

## Year triangulation examples

- `cooling_system_water_pump_leaks` → **2013-2020** (confidence=high, sources=None)
  - transcript=['2013-2020'], titles=['2013-2020'], engine_windows=['2013-2020']
- `rear_wiper_squeak` → **2013-2020** (confidence=medium, sources=None)
  - transcript=[], titles=['2013-2020'], engine_windows=[]
- `carbon_buildup_oil_consumption` → **2013-2020** (confidence=high, sources=None)
  - transcript=['2013-2020'], titles=['2013-2020'], engine_windows=['2013-2020']
- `early_turbo_failure` → **2015** (confidence=medium, sources=None)
  - transcript=[], titles=[], engine_windows=['2013-2020']
- `rear_main_seal_failure` → **2013-2020** (confidence=medium, sources=None)
  - transcript=[], titles=['2013-2020'], engine_windows=[]
- `cabin_blower_motor_failure` → **2013-2019** (confidence=high, sources=None)
  - transcript=[], titles=['2013-2019'], engine_windows=[]
- `dq200_dsg_dry_clutch_problems` → **2013-2020** (confidence=medium, sources=None)
  - transcript=[], titles=['2013-2020'], engine_windows=['2013-2020']
- `water_pump_failure_carbon_buildup` → **2013-2020** (confidence=high, sources=None)
  - transcript=['2013-2020'], titles=['2013-2020'], engine_windows=['2013-2020']
- `dsg_clutch_flywheel_wear` → **2013-2020** (confidence=medium, sources=None)
  - transcript=[], titles=['2013-2020'], engine_windows=['2013-2020']
- `rear_caliper_seizing` → **2013-2020** (confidence=medium, sources=None)
  - transcript=[], titles=['2013-2020'], engine_windows=[]
- `suspension_rattling_noise` → **2013-2015** (confidence=high, sources=None)
  - transcript=[], titles=['2013-2020'], engine_windows=[]
- `thermostat_housing_coolant_leak` → **2013-2020** (confidence=high, sources=None)
  - transcript=['2013-2020'], titles=['2013-2020'], engine_windows=['2013-2020']
- `trim_peeling_interior_plastic` → **2018** (confidence=medium, sources=None)
  - transcript=[], titles=['2018'], engine_windows=[]
- `turbocharger_failure_early_models` → **2013-2014** (confidence=high, sources=None)
  - transcript=['2013-2020'], titles=['2013-2020'], engine_windows=['2013-2020']
- `dpf_egr_clogging_city_driving` → **2018** (confidence=medium, sources=None)
  - transcript=[], titles=['2018'], engine_windows=['2013-2020']
- `excessive_oil_consumption` → **2013-2019** (confidence=high, sources=None)
  - transcript=['2013-2020'], titles=['2013-2019'], engine_windows=['2013-2020']
- `modified_examples_clutch_wear` → **2013-2020** (confidence=medium, sources=None)
  - transcript=[], titles=['2013-2020'], engine_windows=[]
- `rear_beam_suspension_tank_clearance` → **2015** (confidence=medium, sources=None)
  - transcript=[], titles=[], engine_windows=['2013-2020']
- `rear_shock_replacement_difficulty` → **2013-2020** (confidence=medium, sources=None)
  - transcript=[], titles=['2013-2020'], engine_windows=[]
- `ea211_timing_belt_stretch_risk` → **2013-2015** (confidence=medium, sources=None)
  - transcript=['2013-2020'], titles=[], engine_windows=['2013-2020']
