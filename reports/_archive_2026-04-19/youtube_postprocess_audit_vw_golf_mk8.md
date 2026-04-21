# YouTube Issue Post-Processing Audit — vw_golf_mk8

## Summary

- Input rows: **4**
- Cross-brand contamination dropped: **0**
- After dedup: **4**
- Merge groups (> 1 row collapsed): **0**
- Engine scope warnings: **0** on **0** issues
- Trim scope warnings: **0**
- Non-powertrain issues with engine scope cleared: **4**
- Mono-trim issues: **4** / 4 (100.0%)
- Year-triangulated (emitted): **0** / 4
- Year confidence distribution: low=4

## Dedup — merged groups

_(no clusters merged — input was already deduped)_

## Engine-scope warnings

_(no engine-scope rules fired)_

## Trim distribution

| Trim | Count | Share |
|---|---:|---:|
| base | 6 | 100.0% |

## Trim scope warnings

_(none)_

## Cleared-engine issues (non-powertrain)

- `infotainment_system_issues` (electrical) — cleared `['1.0_ETSI', '1.0_TSI', '1.4_EHYBRID', '1.5_ETSI', '1.5_TSI', '2.0_TDI', '2.0_TSI']`, model_scope=['all_vw_golf_mk8']
- `touch_controls_unlit_night` (electrical) — cleared `['1.0_ETSI', '1.0_TSI', '1.4_EHYBRID', '1.5_ETSI', '1.5_TSI', '2.0_TDI', '2.0_TSI']`, model_scope=['all_vw_golf_mk8']
- `capacitive_steering_controls` (electrical) — cleared `['1.0_ETSI', '1.0_TSI', '1.4_EHYBRID', '1.5_ETSI', '1.5_TSI', '2.0_TDI', '2.0_TSI']`, model_scope=['all_vw_golf_mk8']
- `glossy_plastic_fingerprint_magnet` (body) — cleared `['1.4_EHYBRID']`, model_scope=['all_vw_golf_mk8']

## Year triangulation examples

