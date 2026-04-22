# YouTube Issue Post-Processing Audit — renault_clio_mk1

## Summary

- Input rows: **26**
- Cross-brand contamination dropped: **0**
- After dedup: **26**
- Merge groups (> 1 row collapsed): **0**
- Engine scope warnings: **0** on **0** issues
- Trim scope warnings: **0**
- Non-powertrain issues with engine scope cleared: **15**
- Mono-trim issues: **26** / 26 (100.0%)
- Year-triangulated (emitted): **0** / 26
- Year confidence distribution: low=26

## Dedup — merged groups

_(no clusters merged — input was already deduped)_

## Engine-scope warnings

_(no engine-scope rules fired)_

## Trim distribution

| Trim | Count | Share |
|---|---:|---:|
| base | 32 | 100.0% |

## Trim scope warnings

_(none)_

## Cleared-engine issues (non-powertrain)

- `water_ingress_blocked_drains` (body) — cleared `['1.1', '1.2', '1.4', '1.7', '1.8', '1.9_D', '2.0']`, model_scope=['all_renault_clio_mk1']
- `immobiliser_ecu_electrical_faults` (electrical) — cleared `['1.1', '1.2', '1.4', '1.7', '1.8', '1.9_D', '2.0']`, model_scope=['all_renault_clio_mk1']
- `suspension_noise_and_harshness` (suspension) — cleared `['1.1', '1.2', '1.4', '1.7', '1.8', '1.9_D', '2.0']`, model_scope=['all_renault_clio_mk1']
- `wiper_motor_failure` (electrical) — cleared `['2.0']`, model_scope=['all_renault_clio_mk1']
- `airbag_system_electrical_fault` (electrical) — cleared `['1.1', '1.2', '1.4', '1.7', '1.8', '1.9_D', '2.0']`, model_scope=['all_renault_clio_mk1']
- `body_rust_multiple_areas` (body) — cleared `['2.0']`, model_scope=['all_renault_clio_mk1']
- `crankshaft_position_sensor_failure` (electrical) — cleared `['1.2']`, model_scope=['all_renault_clio_mk1']
- `drive_shaft_wear_vibration` (suspension) — cleared `['2.0']`, model_scope=['all_renault_clio_mk1']
- `front_wiper_linkage_seizure` (electrical) — cleared `['1.1', '1.2', '1.4', '1.7', '1.8', '1.9_D', '2.0']`, model_scope=['all_renault_clio_mk1']
- `ignition_coil_failure` (electrical) — cleared `['1.2']`, model_scope=['all_renault_clio_mk1']
- `poor_rear_visibility` (body) — cleared `['1.1', '1.2', '1.4', '1.7', '1.8', '1.9_D', '2.0']`, model_scope=['all_renault_clio_mk1']
- `power_steering_switch_leak` (other) — cleared `['2.0']`, model_scope=['all_renault_clio_mk1']
- `rear_wheel_bearing_wear` (suspension) — cleared `['2.0']`, model_scope=['all_renault_clio_mk1']
- `steering_wheel_melting` (other) — cleared `['2.0']`, model_scope=['all_renault_clio_mk1']
- `washer_jet_blockage` (electrical) — cleared `['2.0']`, model_scope=['all_renault_clio_mk1']

## Year triangulation examples

