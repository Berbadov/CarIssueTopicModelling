# Factuality Audit Report: YouTube Topic Final Knowledge Base

**Date:** April 19, 2026
**Scope:** `issue_knowledge_youtube_renault_clio_mk4_topic_final.json` and `issue_knowledge_youtube_vw_golf_mk7_topic_final.json`

## Executive Summary

The audit revealed significant factuality errors in the Renault Clio MK4 dataset, primarily due to cross-contamination from Ford (EcoBoost) engine data. The VW Golf MK7 dataset is generally more accurate regarding engine specifications but lacks depth in several critical failure modes (e.g., DQ200 DSG). Both datasets missed several high-frequency "common" issues identified through secondary research.

---

## 1. Renault Clio MK4 Analysis

### 🔴 Critical Factuality Errors
- **Timing Chain vs. Belt (1.2 TCe):**
  - **Error:** The result `wet_belt_degradation_failure` lists the **1.2 TCe (H5Ft)** as affected.
  - **Fact:** The Renault 1.2 TCe (H5Ft) uses a **Timing Chain**, not a wet belt.
  - **Contamination:** The description explicitly mentions "EcoBoost" and "Ford's recommended 10-year interval." This is a hallucination/contamination from Ford data.
- **Transmission Misalignment (0.9 TCe):**
  - **Error:** The result `edc_gearbox_sport_mode_lack_of_bite` lists the **0.9 TCe** as affected.
  - **Fact:** The 0.9 TCe (H4Bt) engine in the Clio 4 was **exclusively manual (5-speed)**. It was never paired with the EDC (Efficient Dual Clutch) gearbox.
- **General Contamination:**
  - Multiple entries (e.g., `oil_pump_starvation_soot_clogging`) contain references to Ford engines and service intervals that do not apply to Renault.

### 🟡 Identified Missing Issues
- **MediaNav / R-Link Faults:** Highly common issue involving screen freezing, lagging, or "black screen" failure.
- **Wind Noise (A-Pillar):** A very frequent owner complaint regarding poor door seals near the wing mirrors at highway speeds.
- **Front Suspension Bushings/Drop Links:** Known for premature wear, causing knocking sounds over bumps.
- **TPMS False Alarms:** Frequent electrical glitches with the tire pressure monitoring system.
- **Window Wiper Linkage:** Prone to seizing or failure.

---

## 2. VW Golf MK7 Analysis

### ✅ Confirmed Accurate Points
- **Timing Belt (EA211):** Correctly identifies that `1.2 TSI` and `1.4 TSI` (EA211 family) switched to belts in the MK7, reversing the problematic chain design of the MK6.
- **Timing Chain (EA888):** Correctly identifies that `1.8 TSI` and `2.0 TSI` (GTI/R) use chains and are prone to stretch/tensioner wear.
- **Water Pump/Thermostat Housing:** Correctly identifies this as a major, high-frequency failure point.

### 🔴 Critical Factuality Errors & Omissions
- **DSG Gearbox Detail:**
  - **Issue:** The current result `manual_clutch_slippage_dsg_selector_issue` is too generic.
  - **Fact:** The **DQ200 (7-speed dry clutch)** is a major failure point in the MK7 (1.2/1.4 TSI, 1.6 TDI). The report should explicitly mention **Mechatronic failure** (accumulator housing cracks) and **Clutch Shudder** (1st to 2nd gear).
- **Diesel Carbon Buildup:**
  - **Issue:** Lists `2.0 TDI` for `carbon_buildup_intake_valves`.
  - **Fact:** While EGR soot buildup occurs, the "carbon buildup on intake valves due to direct injection" is specifically a petrol (TSI) issue. Mixing them reduces diagnostic clarity.

### 🟡 Identified Missing Issues
- **Rear Suspension "Thumping":** Frequent issue on models with multi-link suspension (dampers failing prematurely).
- **Sunroof Trim Cracking:** The plastic panoramic sunroof surround is notorious for cracking.
- **Infotainment "Ghost Touching":** Specifically affecting the MIB2 units (2015-2017).
- **"Kangarooing" (1.5 TSI):** The EA211 EVO (1.5 TSI) is famous for cold-start hesitation ("kangaroo effect"), requiring a software update.

---

## 3. Recommended Actions

1. **Purge Ford Data from Renault Pipeline:** Filter out any source videos or transcripts mentioning "EcoBoost," "Ford," or "Wet Belt" from the Clio MK4 processing.
2. **Re-map 1.2 TCe Issues:** Associate the 1.2 TCe with **Timing Chain Stretch** and **Excessive Oil Consumption**, which are its true "high-risk" areas.
3. **Enhance DSG Classification:** Create a dedicated "DQ200 DSG Mechatronic/Clutch" topic for the Golf MK7 to distinguish it from manual transmission issues.
4. **Augment with "Common" Faults:** Manually or programmatically inject the "Missing Issues" identified above to ensure the knowledge base covers the most frequent real-world owner complaints.

**Report Status:** High Priority Review Required for Renault Clio MK4 due to data contamination.
