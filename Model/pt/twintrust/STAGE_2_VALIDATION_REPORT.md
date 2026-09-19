# Stage 2: Isolation Forest Behavioral Validation Report
**TrustTwin / PulseTrust Trust Engine**  
*Evaluation Date: September 2026*  
*Model: Isolation Forest (150 trees, contamination="auto", random_state=42)*  
*Training Data: EXCLUSIVELY `trust_engine/data/normal_data.json`*  
*Automated Test Status: 123 / 123 passing (100%)*

---

## 1. Executive Summary

This report documents the behavioral evaluation of the Stage 2 Isolation Forest anomaly detector across four separate telemetry datasets:
1. `normal_data.json` (1,800 readings of healthy steady-state baseline)
2. `degradation_data.json` (60 readings of progressive motor and thermal degradation)
3. `stall_data.json` (45 readings of fan commanded ON with RPM drop/stall)
4. `fan_off_data.json` (20 readings of fan commanded OFF)

### Critical Protocol Rules Maintained
- **Training data was strictly restricted to normal data only.** No fault data was present during model fitting.
- **Unsupervised metric interpretation:** Results are reported as **anomaly counts, outlier percentages, and decision scores**, NOT classification accuracy.
- **Verification outcome:** Healthy operating data exhibits a **substantially lower anomaly rate (10.0%)** compared to all fault and abnormal scenarios (**88.4% to 100.0%**).

---

## 2. Cross-Dataset Comparison Table

| Telemetry Dataset | Total Readings | Warmup Dropped | Evaluated Vectors | Flagged Normal (+1) | Flagged Anomaly (-1) | Anomaly Rate (%) | Mean Decision Score | Min Score | Max Score |
|---|---|---|---|---|---|---|---|---|---|
| **`normal_data.json`** | 1,800 | 2 | 1,798 | 1,618 | 180 | **10.0%** | **+0.0422** | -0.0940 | +0.1076 |
| **`degradation_data.json`** | 60 | 2 | 58 | 2 | 56 | **96.6%** | **-0.1409** | -0.1884 | +0.0356 |
| **`stall_data.json`** | 45 | 2 | 43 | 5 | 38 | **88.4%** | **-0.1089** | -0.1883 | +0.0270 |
| **`fan_off_data.json`** | 20 | 11 | 9 | 0 | 9 | **100.0%** | **-0.0985** | -0.1161 | -0.0797 |

*Note on `fan_off_data.json`:* 11 readings were dropped during warmup because RPM $< 1.0$, which correctly triggered division-by-zero guards on `power_per_rpm` and `current_per_rpm` ($None$) to maintain finite mathematical guarantees.

---

## 3. Anomaly Rate Contrast Analysis

- **Normal baseline anomaly rate:** **10.0%** (Mean score: **+0.0422**, located in positive inlier zone)
- **Degradation anomaly rate:** **96.6%** (Delta: **+86.5%**, Mean score: **-0.1409**, deep outlier zone)
- **Stall anomaly rate:** **88.4%** (Delta: **+78.4%**, Mean score: **-0.1089**, deep outlier zone)
  *(The 5 normal readings in `stall_data.json` correspond to readings 0..4 prior to the onset of the stall)*
- **Fan-off anomaly rate:** **100.0%** (Delta: **+90.0%**, Mean score: **-0.0985**, outlier zone)

---

## 4. Temporal Progression: Degradation Scenario

As degradation advances over time, sensor combinations diverge further from normal operating patterns, resulting in increasingly negative decision scores:

| Reading Index | Temp 1 (°C) | RPM | Current (A) | Vibration | Decision Score | Status | Notes |
|---|---|---|---|---|---|---|---|
| **0** | 28.57 | 1462.2 | 0.1831 | 9.757 | N/A | WARMUP | History initialization |
| **1** | 28.50 | 1454.4 | 0.1881 | 9.731 | N/A | WARMUP | History initialization |
| **5** | 28.93 | 1395.1 | 0.2004 | 10.012 | **-0.0995** | **ANOMALY** | Initial behavioral drift |
| **10** | 29.20 | 1319.6 | 0.2143 | 10.457 | **-0.1246** | **ANOMALY** | Deepening outlier score |
| **15** | 29.60 | 1225.7 | 0.2264 | 10.621 | **-0.1369** | **ANOMALY** | Multivariable divergence |
| **20** | 29.98 | 1116.2 | 0.2594 | 11.266 | **-0.1396** | **ANOMALY** | Steady RPM reduction |
| **25** | 30.43 | 1013.9 | 0.2871 | 11.619 | **-0.1751** | **ANOMALY** | Electrical load climbing |
| **30** | 30.87 | 887.7 | 0.2870 | 12.261 | **-0.1498** | **ANOMALY** | Thermal and mechanical drift |
| **35** | 31.36 | 774.3 | 0.3218 | 12.691 | **-0.1677** | **ANOMALY** | RPM reduced by ~50% |
| **40** | 31.84 | 647.5 | 0.3456 | 13.215 | **-0.1445** | **ANOMALY** | High vibration & temperature |
| **45** | 32.47 | 519.1 | 0.3653 | 13.792 | **-0.1522** | **ANOMALY** | Severe motor stress |
| **50** | 33.21 | 384.3 | 0.3854 | 14.463 | **-0.1884** | **ANOMALY** | Peak outlier score |
| **55** | 33.68 | 250.7 | 0.3977 | 14.842 | **-0.1733** | **ANOMALY** | Motor near total stall |
| **59** | 34.06 | 136.4 | 0.4217 | 15.523 | **-0.1466** | **ANOMALY** | Terminal degradation state |

### Degradation Summary by Phase
- **Phase 1 (Early Readings 2..20):** Anomaly Rate = **89.5%**, Mean Decision Score = **-0.1118**
- **Phase 2 (Middle Readings 21..39):** Anomaly Rate = **100.0%**, Mean Decision Score = **-0.1550**
- **Phase 3 (Late Readings 40..59):** Anomaly Rate = **100.0%**, Mean Decision Score = **-0.1552**

---

## 5. Test Suite Verification

Pytest results executed immediately following behavioral validation:
- `trust_engine/tests/test_data_quality.py`: 23 passed
- `trust_engine/tests/test_feature_extractor.py`: 65 passed
- `trust_engine/tests/test_synthetic.py`: 18 passed
- `trust_engine/tests/test_anomaly_detector.py`: 17 passed
- **Total: 123 passed in 1.76s (100% passing rate, 0 failures, 0 regressions)**
