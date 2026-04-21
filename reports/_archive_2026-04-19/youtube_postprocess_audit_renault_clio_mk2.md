# YouTube Issue Post-Processing Audit — renault_clio_mk2

## Summary

- Input rows: **22**
- Cross-brand contamination dropped: **1**
- After dedup: **21**
- Merge groups (> 1 row collapsed): **0**
- Engine scope warnings: **0** on **0** issues
- Trim scope warnings: **0**
- Non-powertrain issues with engine scope cleared: **11**
- Mono-trim issues: **21** / 21 (100.0%)
- Year-triangulated (emitted): **0** / 21
- Year confidence distribution: low=21

## Dedup — merged groups

_(no clusters merged — input was already deduped)_

## Cross-brand contamination — dropped issues

- `airbag_system_faults` — foreign_brand:seat (label: 'Airbag system electrical faults')

## Engine-scope warnings

_(no engine-scope rules fired)_

## Trim distribution

| Trim | Count | Share |
|---|---:|---:|
| base | 22 | 100.0% |

## Trim scope warnings

_(none)_

## Cleared-engine issues (non-powertrain)

- `wiper_motor_failure` (electrical) — cleared `['2.0_16V']`, model_scope=['all_renault_clio_mk2']
- `power_steering_switch_leak` (other) — cleared `['2.0_16V']`, model_scope=['all_renault_clio_mk2']
- `rear_wheel_bearing_wear` (suspension) — cleared `['2.0_16V']`, model_scope=['all_renault_clio_mk2']
- `rust_fuel_filler_cap` (body) — cleared `['2.0_16V']`, model_scope=['all_renault_clio_mk2']
- `rust_rear_arches` (body) — cleared `['2.0_16V']`, model_scope=['all_renault_clio_mk2']
- `rust_sills` (body) — cleared `['2.0_16V']`, model_scope=['all_renault_clio_mk2']
- `steering_wheel_melting` (other) — cleared `['2.0_16V']`, model_scope=['all_renault_clio_mk2']
- `washer_jet_blockage` (electrical) — cleared `['2.0_16V']`, model_scope=['all_renault_clio_mk2']
- `water_ingress_boot` (body) — cleared `['2.0_16V']`, model_scope=['all_renault_clio_mk2']
- `water_ingress_flooding` (body) — cleared `['all']`, model_scope=['all_renault_clio_mk2']
- `water_ingress_interior` (body) — cleared `['2.0_16V']`, model_scope=['all_renault_clio_mk2']

## Year triangulation examples

