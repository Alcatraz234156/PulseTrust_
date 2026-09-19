# Normal Dataset Classification Audit Report
**Project: TrustTwin / PulseTrust Machine Monitoring System**  
*Audit Scope: Investigation of 110 DEGRADING Classifications on `normal_data.json`*  
*Evaluation Date: September 2026*  
*Dataset: 1800 Telemetry Readings (30 minutes of nominal healthy operation)*  

---

## 1. Executive Summary

This audit investigates why **110 readings** out of 1800 in the healthy baseline dataset (`normal_data.json`) were classified as **`DEGRADING`** by the Stage 4 Trust Engine.

### Core Metrics Summary
- **Total Readings Evaluated**: 1800 (100%)
- **State Breakdown**:
  - `NORMAL`: **1620 readings** (90.0%)
  - `CAUTION`: **70 readings** (3.9%)
  - `DEGRADING`: **110 readings** (6.1%)
  - `FAULT`: **0 readings** (0.0%)
- **Operational Decisions**:
  - `ALLOW`: **1620 readings** (90.0%)
  - `WARN`: **180 readings** (10.0%)
  - `BLOCK`: **0 readings** (0.0%)
- **Stage 3 Rule Engine Violations**: **0 violations** (100% clean baseline)
- **Stage 2 Isolation Forest Outliers**: **180 readings** (10.0%, expected with `contamination="auto"`)

---

## 2. Temporal Signals Analysis

### A. Frequency in the 110 DEGRADING Readings
| Temporal Signal | Evaluated Feature & Threshold | Occurrences in 110 DEGRADING Readings | Percentage |
|---|---|---|---|
| **`CURRENT_RISING`** | `current_rate > 0.005 A/s` | **56** | 50.9% |
| **`RPM_FALLING`** | `rpm_rate < -10.0 RPM/s` | **41** | 37.3% |
| **`TEMP_RISING`** | `temp_rate > 0.050 °C/s` | **41** | 37.3% |
| **`VIBRATION_RISING`** | `vibration_rate > 0.100 m/s²/s` | **17** | 15.5% |

### B. Natural Noise Frequency Across All 1800 Baseline Readings
Instantaneous numerical derivatives ($dT/dt$, $dI/dt$, $d\text{RPM}/dt$) computed sample-to-sample frequently spike across normal operating data due to sensor bit-resolution limits and discretization noise:
- `TEMP_RISING`: **431 readings** (23.94%) — *DS18B20 digital step is $0.0625^\circ\text{C}$; a 1-bit step over 1 second computes to $+0.0625 > 0.050$.*
- `CURRENT_RISING`: **350 readings** (19.44%) — *INA219 ADC noise causes natural $5\text{–}10\text{ mA}$ jitter.*
- `RPM_FALLING`: **287 readings** (15.94%) — *Hall sensor timing jitter fluctuates by $\pm 12\text{–}15\text{ RPM}$.*
- `VIBRATION_RISING`: **98 readings** (5.44%)
- **Readings with $\ge 1$ rate signal**: **931 readings (51.72%)**

### C. Signal Concurrence
In the 110 degrading readings:
- Single isolated rate signal alone: **69 readings (62.7%)**
  - `CURRENT_RISING` alone: 27
  - `RPM_FALLING` alone: 21
  - `TEMP_RISING` alone: 15
  - `VIBRATION_RISING` alone: 6
- Two concurrent rate signals: **37 readings (33.6%)**
- Three concurrent rate signals: **4 readings (3.6%)**

---

## 3. The Role of Isolation Forest Anomalies

**Finding: Stage 2 Isolation Forest anomalies are the sole enabler of the `DEGRADING` state.**

1. Rule violations are **0** across the entire dataset (`warning_count == 0`).
2. Exactly **180 readings (10.0%)** receive `is_anomaly = True` from Stage 2 (with borderline decision scores from $-0.0002$ to $-0.0700$).
3. When `is_anomaly == True`:
   - If no temporal rate signals occur: classified as **`CAUTION`** (**70 readings**).
   - If $\ge 1$ temporal rate signal occurs: classified as **`DEGRADING`** (**110 readings**).
4. When `is_anomaly == False`:
   - Even when sample jitter produces rate signals (which occurs in **821 readings**), the machine remains strictly in **`NORMAL`** state (score 92.0 or 85.0).

---

## 4. Sequence Continuity: Isolated Spikes vs. Sustained Trajectories

The 110 degrading readings form **84 distinct contiguous sequences**:

| Sequence Length | Sequences Count | Total Readings | Percentage of Sequences |
|---|---|---|---|
| **Length 1 (isolated 1 reading)** | **63** | **63** | **75.0%** |
| **Length 2 (2 consecutive readings)**| **17** | **34** | **20.2%** |
| **Length 3 (3 consecutive readings)**| **3** | **9** | **3.6%** |
| **Length 4 (4 consecutive readings)**| **1** | **4** | **1.2%** |
| **Total** | **84** | **110** | **100.0%** |

**Conclusion:** **75% of occurrences are 1-second blips**. The state chatters between `NORMAL` and `DEGRADING` from one second to the next.

---

## 5. 10 Representative Samples from `normal_data.json`

| Index | Trust Score | Anomaly Score | Active Rates | Measured Physical Values | State / Decision |
|---|---|---|---|---|---|
| **#5** | 77.00 | -0.0700 | $\text{rpm\_rate} = -19.95\text{ RPM/s}$ | RPM = 1446.9, Temp = 27.96°C, I = 0.183 A | `DEGRADING` / `WARN` |
| **#43** | 77.00 | -0.0175 | $\text{rpm\_rate} = -13.61\text{ RPM/s}$ | RPM = 1480.9, Temp = 28.20°C, I = 0.191 A | `DEGRADING` / `WARN` |
| **#124** | 77.00 | -0.0003 | $\text{temp\_rate} = +0.0530^\circ\text{C/s}$ | RPM = 1478.7, Temp = 28.23°C, I = 0.176 A | `DEGRADING` / `WARN` |
| **#155** | 77.00 | -0.0515 | $\text{temp\_rate} = +0.0795^\circ\text{C/s}$ | RPM = 1467.1, Temp = 28.16°C, I = 0.167 A | `DEGRADING` / `WARN` |
| **#254** | 77.00 | -0.0247 | $\text{vib\_rate} = +0.1087\text{ m/s}^2\text{/s}$ | Vib = 9.73, RPM = 1472.1, I = 0.180 A | `DEGRADING` / `WARN` |
| **#344** | 77.00 | -0.0002 | $\text{current\_rate} = +0.0128\text{ A/s}$ | Current = 0.186 A, Temp = 28.45°C, RPM = 1469.5 | `DEGRADING` / `WARN` |
| **#519** | 70.00 | -0.0159 | $\text{rpm\_rate} = -11.62$, $\text{current\_rate} = +0.0125$ | RPM = 1436.0, Current = 0.187 A | `DEGRADING` / `WARN` |
| **#1126**| 77.00 | -0.0193 | $\text{rpm\_rate} = -10.46\text{ RPM/s}$ | RPM = 1449.3, Temp = 28.68°C, I = 0.172 A | `DEGRADING` / `WARN` |
| **#1530**| 70.00 | -0.0203 | $\text{temp\_rate} = +0.0525$, $\text{current\_rate} = +0.0143$ | Temp = 28.87°C, Current = 0.187 A, RPM = 1488.9 | `DEGRADING` / `WARN` |
| **#1732**| 70.00 | -0.0263 | $\text{temp\_rate} = +0.0745$, $\text{rpm\_rate} = -10.23$ | Temp = 28.99°C, RPM = 1467.3, Current = 0.173 A | `DEGRADING` / `WARN` |

---

## 6. Diagnosis: Root Cause & Defect Identification

### Diagnosis: **Genuine State-Logic Defect**

The issue is **not** that synthetic sensor noise is unexpected. The defect is in **how the Trust Engine evaluates and combines that noise**:

1. **Defect in Trajectory Definition:**
   By design, `DEGRADING` is intended to signify a persistent operational trajectory. Evaluating `len(degradation_signals) > 0` on instantaneous, single-reading numerical derivatives turns sample-to-sample sensor quantization jitter into a state transition.
2. **Artificial Coupling with Borderline Anomalies:**
   Isolation Forest contamination produces baseline outliers with microscopic distance from the hyperplane (scores such as $-0.0002$ or $-0.0003$). The logic:
   ```python
   elif len(degradation_signals) > 0 and (warning_count > 0 or effective_anomaly or trust_score <= 75.0):
       state = MachineState.DEGRADING
   ```
   treats any reading with a $-0.0002$ anomaly score as an open gate for single-variable sensor jitter to trigger `DEGRADING`.

### Recommended Remediation Paths
- **Path 1 (Consecutive Persistence Window)**: Require adverse degradation signals to persist for $\ge 3$ consecutive readings before entering `DEGRADING` (identical to the stateful confirmation used for `FAN_STALL`).
- **Path 2 (Multi-Signal Requirement)**: Require $\ge 2$ concurrent physical degradation signals (or an active Stage 3 rule warning) to trigger `DEGRADING`. Single-variable fluctuations would remain `CAUTION`.
- **Path 3 (Severe Anomaly Gate)**: Only allow statistical anomalies to participate in degradation gating if `anomaly_score < TRUST_ANOMALY_SEVERE_THRESHOLD` ($-0.15$), preventing borderline density outliers from amplifying noise.
