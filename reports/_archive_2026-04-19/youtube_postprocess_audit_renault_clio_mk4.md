# YouTube Issue Post-Processing Audit — renault_clio_mk4

## Summary

- Input rows: **57**
- After dedup: **53**
- Merge groups (> 1 row collapsed): **1**
- Engine scope warnings: **0** on **0** issues
- Trim scope warnings: **0**
- Non-powertrain issues with engine scope cleared: **29**
- Mono-trim issues: **53** / 53 (100.0%)
- Year-triangulated (emitted): **12** / 53
- Year confidence distribution: low=41, medium=12

## Dedup — merged groups

- 3 rows: `carbon_deposits_excessive_oil_consumption`, `excessive_oil_consumption`, `excessive_oil_consumption_1_2_tce`

## Engine-scope warnings

_(no engine-scope rules fired)_

## Trim distribution

| Trim | Count | Share |
|---|---:|---:|
| base | 59 | 100.0% |

## Trim scope warnings

_(none)_

## Cleared-engine issues (non-powertrain)

- `suspension_firm_crashy_pre_2016` (suspension) — cleared `['0.9_TCE', '1.2_TCE', '1.2_NA', '1.5_DCI']`, model_scope=['pre_facelift']
- `wiper_motor_failure` (electrical) — cleared `['all']`, model_scope=['all_renault_clio_mk4']
- `body_interior_quality_issues` (body) — cleared `['0.9_TCE', '1.2_TCE', '1.2_NA', '1.5_DCI']`, model_scope=['all_renault_clio_mk4']
- `boot_latch_confusion` (body) — cleared `['0.9_TCE']`, model_scope=['all_renault_clio_mk4']
- `boot_lip_seat_snag` (body) — cleared `['0.9_TCE', '1.2_TCE', '1.2_NA', '1.5_DCI']`, model_scope=['all_renault_clio_mk4']
- `boot_lock_motor_failure` (electrical) — cleared `['all']`, model_scope=['all_renault_clio_mk4']
- `center_windshield_visibility_limited` (body) — cleared `['0.9_TCE', '1.2_TCE', '1.2_NA', '1.5_DCI']`, model_scope=['all_renault_clio_mk4']
- `chrome_peeling` (body) — cleared `['all']`, model_scope=['all_renault_clio_mk4']
- `cruise_control_ui_obscures_display` (electrical) — cleared `['0.9_TCE', '1.2_TCE', '1.2_NA', '1.5_DCI']`, model_scope=['all_renault_clio_mk4']
- `fragile_air_vent_controls` (body) — cleared `['all']`, model_scope=['all_renault_clio_mk4']
- `infotainment_system_laggy_slow` (electrical) — cleared `['0.9_TCE', '1.2_TCE', '1.2_NA', '1.5_DCI']`, model_scope=['all_renault_clio_mk4']
- `infotainment_usb_audio_glitch` (electrical) — cleared `['0.9_TCE', '1.2_TCE', '1.2_NA', '1.5_DCI']`, model_scope=['all_renault_clio_mk4']
- `keyless_entry_sensor_intermittent_failure` (electrical) — cleared `['0.9_TCE', '1.2_TCE', '1.2_NA', '1.5_DCI']`, model_scope=['all_renault_clio_mk4']
- `no_rear_usb_ports` (electrical) — cleared `['0.9_TCE', '1.2_TCE', '1.2_NA', '1.5_DCI']`, model_scope=['all_renault_clio_mk4']
- `no_wipers_fault` (electrical) — cleared `['all']`, model_scope=['all_renault_clio_mk4']
- `numerous_minor_electrical_faults` (electrical) — cleared `['all']`, model_scope=['all_renault_clio_mk4']
- `r_link_infotainment_bugs_crashes` (electrical) — cleared `['all']`, model_scope=['all_renault_clio_mk4']
- `rear_seat_space_tight` (body) — cleared `['0.9_TCE', '1.2_TCE', '1.2_NA', '1.5_DCI']`, model_scope=['all_renault_clio_mk4']
- `rlink_system_malfunction` (electrical) — cleared `['all']`, model_scope=['all_renault_clio_mk4']
- `start_stop_battery_drain` (electrical) — cleared `['all']`, model_scope=['all_renault_clio_mk4']
- `starter_failure` (electrical) — cleared `['all']`, model_scope=['all_renault_clio_mk4']
- `starter_motor_water_ingress_freezing` (electrical) — cleared `['all']`, model_scope=['all_renault_clio_mk4']
- `stop_start_malfunction` (electrical) — cleared `['all']`, model_scope=['all_renault_clio_mk4']
- `suspension_noise_rough_roads` (suspension) — cleared `['all']`, model_scope=['all_renault_clio_mk4']
- `touchscreen_volume_controls` (electrical) — cleared `['0.9_TCE']`, model_scope=['all_renault_clio_mk4']
- `usb_port_low_power` (electrical) — cleared `['0.9_TCE', '1.2_TCE', '1.2_NA', '1.5_DCI']`, model_scope=['all_renault_clio_mk4']
- `warning_lights_systems_freezing` (electrical) — cleared `['all']`, model_scope=['all_renault_clio_mk4']
- `wind_noise_side_window` (body) — cleared `['all']`, model_scope=['all_renault_clio_mk4']
- `wireless_charger_warning_persistence` (electrical) — cleared `['0.9_TCE']`, model_scope=['all_renault_clio_mk4']

## Year triangulation examples

- `excessive_oil_consumption_1_2_tce` → **2013-2019** (confidence=medium, sources=None)
  - transcript=[], titles=['2013-2019'], engine_windows=['2013-2019']
- `suspension_firm_crashy_pre_2016` → **2013-2016** (confidence=medium, sources=None)
  - transcript=[], titles=[], engine_windows=['2013-2019']
- `crankshaft_bearing_wear` → **2013-2019** (confidence=medium, sources=None)
  - transcript=[], titles=['2013-2019'], engine_windows=['2013-2019']
- `dci_oil_consumption` → **2013-2019** (confidence=medium, sources=None)
  - transcript=[], titles=['2013-2019'], engine_windows=['2013-2019']
- `dual_mass_flywheel_failure` → **2013-2018** (confidence=medium, sources=None)
  - transcript=[], titles=['2013-2019'], engine_windows=['2013-2018']
- `edc_gearbox_control_problems` → **2013-2018** (confidence=medium, sources=None)
  - transcript=[], titles=['2013-2019'], engine_windows=['2013-2018']
- `gearbox_bearing_failure` → **2013-2019** (confidence=medium, sources=None)
  - transcript=[], titles=['2013-2019'], engine_windows=[]
- `imprecise_manual_gearbox` → **2013-2019** (confidence=medium, sources=None)
  - transcript=[], titles=['2013-2019'], engine_windows=[]
- `no_wipers_fault` → **2013-2019** (confidence=medium, sources=None)
  - transcript=[], titles=['2013-2019'], engine_windows=[]
- `numerous_minor_electrical_faults` → **2013-2019** (confidence=medium, sources=None)
  - transcript=[], titles=['2013-2019'], engine_windows=[]
- `timing_chain_stretch` → **2013-2019** (confidence=medium, sources=None)
  - transcript=[], titles=['2013-2019'], engine_windows=['2013-2019']
- `warning_lights_systems_freezing` → **2013-2019** (confidence=medium, sources=None)
  - transcript=[], titles=['2013-2019'], engine_windows=[]
