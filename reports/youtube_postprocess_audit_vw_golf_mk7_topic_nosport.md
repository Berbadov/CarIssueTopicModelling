# YouTube Issue Post-Processing Audit — vw_golf_mk7

## Summary

- Input rows: **23**
- After dedup: **23**
- Merge groups (> 1 row collapsed): **0**
- Engine scope warnings: **0** on **0** issues
- Trim scope warnings: **0**
- Non-powertrain issues with engine scope cleared: **0**
- Mono-trim issues: **22** / 23 (95.7%)
- Year-triangulated (emitted): **9** / 23
- Year confidence distribution: high=2, low=14, medium=7

## Dedup — merged groups

_(no clusters merged — input was already deduped)_

## Engine-scope warnings

_(no engine-scope rules fired)_

## Trim distribution

| Trim | Count | Share |
|---|---:|---:|
| base | 46 | 97.9% |
| GTD | 1 | 2.1% |

## Trim scope warnings

_(none)_

## Cleared-engine issues (non-powertrain)

_(none)_

## Year triangulation examples

- `carbon_buildup_intake_valves` → **2013-2020** (confidence=medium, sources=None)
  - transcript=['2013-2020'], titles=[], engine_windows=['2013-2020']
- `climate_control_interface_gremlins` → **2013-2020** (confidence=medium, sources=None)
  - transcript=[], titles=['2013-2020'], engine_windows=[]
- `cooling_system_water_pump_leaks` → **2013-2019** (confidence=high, sources=None)
  - transcript=[], titles=['2013-2019'], engine_windows=['2013-2020']
- `excessive_oil_consumption` → **2013-2019** (confidence=high, sources=None)
  - transcript=['2013-2020'], titles=['2013-2019'], engine_windows=['2013-2020']
- `thermostat_housing_coolant_leak` → **2013-2020** (confidence=medium, sources=None)
  - transcript=['2013-2020'], titles=[], engine_windows=['2013-2020']
- `timing_belt_interval_120k_miles` → **2013-2020** (confidence=medium, sources=None)
  - transcript=['2013-2020'], titles=[], engine_windows=['2013-2020']
- `ea211_early_model_issues` → **2013-2015** (confidence=medium, sources=None)
  - transcript=['2013-2020'], titles=[], engine_windows=['2013-2020']
- `timing_belt_stretch_ea211` → **2013-2020** (confidence=medium, sources=None)
  - transcript=['2013-2020'], titles=[], engine_windows=['2013-2020']
- `turbocharger_failure_ea211` → **2013-2020** (confidence=medium, sources=None)
  - transcript=['2013-2020'], titles=[], engine_windows=['2013-2020']
