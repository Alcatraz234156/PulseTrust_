# Stage 3: Deterministic Rule Engine — Technical Report
**Project: TrustTwin / PulseTrust Trust Engine**  
*Evaluation Date: September 2026*  
*Stage: 3 (Deterministic Rule Engine)*  
*Automated Test Status: 143 / 143 Passed (100%)*

---

## 1. Executive Summary

This report documents the design, implementation, and behavioral validation of **Stage 3: Deterministic Rule Engine** for the TrustTwin machine monitoring system.

Unlike Stage 2 (Isolation Forest), which assesses statistical novelty relative to learned normal baselines, Stage 3 applies **deterministic physical and operational rules**. It identifies explicit limit violations, sensor discrepancies, and actuator/telemetry contradictions with structured, traceable evidence.

### Key Accomplishments
- Implemented `RuleEngine` in `trust_engine/rules.py` covering 9 physical, operational, and cross-sensor rules.
- Implemented stateful consecutive-reading confirmation for `FAN_STALL` to prevent false triggers during fan spin-up.
- Enforced strict rule priority and subsumption to eliminate duplicate redundant alarms.
- Integrated centralized configuration in `trust_engine/config.py` with explicit hardware calibration warnings.
- Created 20 comprehensive unit tests in `trust_engine/tests/test_rule_engine.py` (all 143 total tests pass).
- Evaluated the Rule Engine against all four project datasets, achieving 100% clean normal baseline and accurate physical fault detection.

---

## 2. Architecture & Data Flow

```
                      ESP32 Telemetry Reading
                                 │
                                 ▼
                         FeatureExtractor
                                 │
                ┌────────────────┴────────────────┐
                │                                 │
                ▼                                 ▼
        [Stage 2 Detector]               [Stage 3 RuleEngine]
        Isolation Forest                  Deterministic Rules
        - anomaly_score                   - rule_id
        - is_anomaly                      - severity (CRITICAL/WARNING/INFO)
        - raw_prediction                  - evidence dictionary
                │                                 │
                └────────────────┬────────────────┘
                                 │
                                 ▼
                       [Stage 4: TrustEngine]
                         (Future Milestone)
```

---

## 3. Implemented Rule Catalog

| Rule ID | Severity | Monitored Condition | Trigger Logic | Evidence Logged | Priority / Subsumption |
|---|---|---|---|---|---|
| `HIGH_TEMPERATURE` | `WARNING` | Elevated thermal state | $T_{\text{avg}} \ge 31.0^\circ\text{C}$ and $< 33.5^\circ\text{C}$ | `temperature`, `threshold`, `temp_1`, `temp_2`, `temp_avg` | Subsumed if `CRITICAL_TEMPERATURE` fires |
| `CRITICAL_TEMPERATURE` | `CRITICAL` | Hazardous thermal buildup | $T_{\text{avg}} \ge 33.5^\circ\text{C}$ | `temperature`, `threshold`, `temp_1`, `temp_2`, `temp_avg` | Subsumes `HIGH_TEMPERATURE` |
| `HIGH_CURRENT` | `WARNING` | Elevated motor load | $I \ge 0.28\text{ A}$ and $< 0.40\text{ A}$ | `current`, `threshold`, `voltage`, `power` | Subsumed if `OVERCURRENT` fires |
| `OVERCURRENT` | `CRITICAL` | Severe motor strain / lockup | $I \ge 0.40\text{ A}$ | `current`, `threshold`, `voltage`, `power` | Subsumes `HIGH_CURRENT` |
| `FAN_STALL` | `CRITICAL` | Fan commanded ON but stopped | $\text{fan} == \text{True}$ and $\text{RPM} \le 150.0$ for $\ge 3$ consecutive readings | `fan`, `rpm`, `threshold`, `consecutive_readings`, `current`, `power` | Subsumes `LOW_RPM`; stateful confirmation |
| `LOW_RPM` | `WARNING` | Degraded fan rotation speed | $\text{fan} == \text{True}$ and $150.0 < \text{RPM} < 1000.0$ | `fan`, `rpm`, `threshold` | Does not trigger if stalled |
| `UNEXPECTED_RPM_WHEN_FAN_OFF` | `WARNING` | Rotation without command | $\text{fan} == \text{False}$ and $\text{RPM} > 50.0$ | `fan`, `rpm`, `threshold` | Catches backdrive / drive circuit fault |
| `TEMP_SENSOR_DISAGREEMENT` | `WARNING` | Dual-sensor gap | $\|T_1 - T_2\| > 2.0^\circ\text{C}$ | `temp_1`, `temp_2`, `absolute_difference`, `threshold` | Sensor drift / detachment check |
| `INVALID_TELEMETRY` | `WARNING` | Physically impossible value | Sensor values outside hardware limits | `invalid_field`, `measured_value`, `valid_bounds` | Data quality check |

### Intentional Fan OFF Logic (Rule 7)
When $\text{fan} == \text{False}$ and $\text{RPM} \le 50.0$, the engine produces **zero violations**. An intentional machine shutdown is normal operation and must never trigger a stall alarm.

---

## 4. Centralized Threshold Configuration

Configured in `trust_engine/config.py`:

```python
# Temperature Limits
RULE_TEMP_WARNING = 31.0                  # °C (normal baseline is ~28.5 °C)
RULE_TEMP_CRITICAL = 33.5                 # °C (severe thermal runaway)
RULE_TEMP_DISAGREEMENT_THRESHOLD = 2.0   # °C (acceptable tolerance between dual sensors)

# Electrical Current Limits
RULE_CURRENT_WARNING = 0.28               # A (normal baseline is ~0.18 A)
RULE_CURRENT_CRITICAL = 0.40              # A (stalled/jammed fan draws > 0.40 A)

# RPM Operational Limits
RULE_RPM_STALL_THRESHOLD = 150.0          # RPM (below this with fan ON indicates stall)
RULE_RPM_LOW_THRESHOLD = 1000.0           # RPM (below this with fan ON indicates degraded speed)
RULE_UNEXPECTED_RPM_FAN_OFF_THRESHOLD = 50.0 # RPM (rotation threshold with fan OFF)

# Stateful Stall Confirmation
RULE_FAN_STALL_CONFIRMATION_COUNT = 3     # Consecutive readings required to confirm FAN_STALL

# Physical Range Sanity Limits
RULE_VALID_TEMP_MIN = -40.0;    RULE_VALID_TEMP_MAX = 125.0
RULE_VALID_VOLTAGE_MIN = 0.0;   RULE_VALID_VOLTAGE_MAX = 24.0
RULE_VALID_CURRENT_MIN = 0.0;   RULE_VALID_CURRENT_MAX = 5.0
RULE_VALID_RPM_MIN = 0.0;       RULE_VALID_POWER_MIN = 0.0
```

> **Hardware Calibration Notice:** These values are initial engineering and demo thresholds. Physical sensors (DS18B20, INA219, Hall sensor) and actuator drive transistors (TIP31C) should be profiled on actual hardware before production deployment.

---

## 5. Stateful Stall Confirmation Design

To accommodate motor start-up inertia and prevent false alarms during normal spin-up:
1. The engine tracks an internal dictionary `_consecutive_low_rpm[device_id]`.
2. When $\text{fan} == \text{True}$ and $\text{RPM} \le 150.0$, the counter increments.
3. If the condition clears ($\text{RPM} > 150.0$ or $\text{fan} == \text{False}$), the counter immediately resets to 0.
4. Only when the counter reaches $\ge 3$ consecutive readings is `FAN_STALL` confirmed.
5. Device state is isolated per `device_id` to prevent cross-plant data leakage.

---

## 6. Dataset Evaluation Results

All four telemetry datasets were evaluated sequentially:

| Dataset | Total Readings | Readings with Violations | Readings with CRITICAL | CRITICAL Violations | WARNING Violations | Primary Rules Triggered |
|---|---|---|---|---|---|---|
| **`normal_data.json`** | 1,800 | **0 (0.0%)** | **0 (0.0%)** | 0 | 0 | None (Clean baseline) |
| **`degradation_data.json`** | 60 | **35 (58.3%)** | **6 (10.0%)** | 11 | 84 | `LOW_RPM` (33), `HIGH_CURRENT` (29), `HIGH_TEMP` (22), `CRIT_TEMP` (6), `OVERCURRENT` (5) |
| **`stall_data.json`** | 45 | **20 (44.4%)** | **5 (11.1%)** | 6 | 49 | `LOW_RPM` (17), `HIGH_TEMP` (17), `HIGH_CURRENT` (15), `OVERCURRENT` (5), `FAN_STALL` (1) |
| **`fan_off_data.json`** | 20 | **0 (0.0%)** | **0 (0.0%)** | 0 | 0 | None (Zero false alarms on intentional OFF) |

### Chronological Fault Breakdown

#### `degradation_data.json`
- **Readings 0..24:** Clean (operating within normal tolerances).
- **Reading #25:** `HIGH_CURRENT` ($I = 0.287\text{ A} \ge 0.28\text{ A}$).
- **Reading #26:** `LOW_RPM` ($\text{RPM} = 991.1 < 1000\text{ RPM}$).
- **Reading #32:** `HIGH_TEMPERATURE` ($T = 31.13^\circ\text{C} \ge 31.0^\circ\text{C}$).
- **Reading #54:** `CRITICAL_TEMPERATURE` ($T = 33.54^\circ\text{C} \ge 33.5^\circ\text{C}$) and `OVERCURRENT` ($I = 0.411\text{ A} \ge 0.40\text{ A}$).

#### `stall_data.json`
- **Readings 0..24:** Clean (nominal fan operation at ~1450 RPM).
- **Reading #25:** Speed drops and current rises (`LOW_RPM`, `HIGH_CURRENT`).
- **Reading #28:** `HIGH_TEMPERATURE` triggered as heat accumulates.
- **Reading #40:** `OVERCURRENT` ($0.4037\text{ A}$).
- **Reading #44:** `FAN_STALL` confirmed after 3 consecutive readings below 150 RPM ($\text{RPM} = 1.37$).

---

## 7. Automated Test Suite Verification

Full test suite execution:
```powershell
.\venv\Scripts\python.exe -m pytest trust_engine/tests/ -v
```

```
============================= test session starts =============================
platform win32 -- Python 3.12.10, pytest-9.1.1
collected 143 items

trust_engine\tests\test_anomaly_detector.py .................            [ 11%]
trust_engine\tests\test_data_quality.py .......................          [ 27%]
trust_engine\tests\test_feature_extractor.py ........................... [ 46%]
......................................                                   [ 73%]
trust_engine\tests\test_rule_engine.py ....................              [ 87%]
trust_engine\tests\test_synthetic.py ..................                  [100%]

============================= 143 passed in 1.77s =============================
```

---

## 8. Confirmations & Next Steps (Stage 4)

- **Stage 2 Compatibility:** Stage 2 Isolation Forest implementation, feature ordering, hyperparameters, and trained artifacts were **strictly preserved and unmodified**.
- **Stage 4 Boundary:** Trust score aggregation, ALLOW/WARN/BLOCK decision synthesis, and degradation trend weighting have **not been implemented**.
- **Stage 4 Preview:** In Stage 4 (`TrustEngine`), outputs from Stage 1 (`FeatureVector`), Stage 2 (`AnomalyResult`), and Stage 3 (`RuleEvaluationResult`) will be unified into a single coherent Trust Result with human-readable rationale.
