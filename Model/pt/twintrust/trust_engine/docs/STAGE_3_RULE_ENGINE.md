# Stage 3: Deterministic Rule Engine Documentation
**TrustTwin / PulseTrust Machine Monitoring System**

---

## 1. Purpose

The Rule Engine is a **deterministic, domain-logic verification component**. Unlike Stage 2 (Isolation Forest), which answers:
> *"Does this telemetry look statistically unusual relative to healthy baselines?"*

The Rule Engine answers:
> *"Does this telemetry violate an explicit physical boundary, operational mandate, or cross-sensor law?"*

It provides structured, transparent explanations with explicit rule IDs, severity ratings, human-readable messages, and exact empirical evidence.

> **CRITICAL STAGE BOUNDARY:**  
> Stage 3 does **NOT** produce the final Trust Score. It does not compute aggregate trust percentages, nor does it perform ALLOW/WARN/BLOCK decision actions. Those synthesis responsibilities belong to **Stage 4**.

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
    - is_anomaly                      - severity
    - raw_prediction                  - evidence dict
            │                                 │
            └────────────────┬────────────────┘
                             │
                             ▼
                   [Stage 4: TrustEngine]
                     (Future Milestone)
```

---

## 3. Rule Catalog & Identifiers

| Rule ID | Severity | Monitored Condition | Trigger Logic | Subsumption / Duplication Control |
|---|---|---|---|---|
| `HIGH_TEMPERATURE` | `WARNING` | Elevated operating temperature | $T_{\text{avg}} \ge 31.0^\circ\text{C}$ and $< 33.5^\circ\text{C}$ | Subsumed if `CRITICAL_TEMPERATURE` fires |
| `CRITICAL_TEMPERATURE` | `CRITICAL` | Hazardous thermal buildup | $T_{\text{avg}} \ge 33.5^\circ\text{C}$ | Prevents `HIGH_TEMPERATURE` from firing |
| `HIGH_CURRENT` | `WARNING` | Motor electrical strain | $I \ge 0.28\text{ A}$ and $< 0.40\text{ A}$ | Subsumed if `OVERCURRENT` fires |
| `OVERCURRENT` | `CRITICAL` | Severe overcurrent / lockup | $I \ge 0.40\text{ A}$ | Prevents `HIGH_CURRENT` from firing |
| `FAN_STALL` | `CRITICAL` | Fan commanded ON but halted | $\text{fan} == \text{True}$ AND $\text{RPM} \le 150.0$ for $\ge 3$ consecutive readings | Subsumes `LOW_RPM`; stateful confirmation |
| `LOW_RPM` | `WARNING` | Degraded fan rotation speed | $\text{fan} == \text{True}$ AND $150.0 < \text{RPM} < 1000.0$ | Does not fire if stalled |
| `UNEXPECTED_RPM_WHEN_FAN_OFF` | `WARNING` | Rotation without command | $\text{fan} == \text{False}$ AND $\text{RPM} > 50.0$ | Catches command/state mismatch |
| `TEMP_SENSOR_DISAGREEMENT` | `WARNING` | Sensor divergence | $\|T_1 - T_2\| > 2.0^\circ\text{C}$ | Flags sensor drift/fault |
| `INVALID_TELEMETRY` | `WARNING` | Physical range violation | Out-of-bounds voltage, current, RPM, etc. | Data quality integrity check |

### Intentional "Fan OFF" Rule Behavior
When the fan is commanded OFF ($\text{fan} == \text{False}$) and RPM is near zero ($\le 50.0\text{ RPM}$), **NO VIOLATION** is produced. An intentional machine shutdown is normal operation, not a mechanical fault.

---

## 4. Severity Levels

The engine uses three explicit severities defined in `RuleSeverity`:
- **`CRITICAL`**: Serious physical or operational fault requiring immediate attention (`CRITICAL_TEMPERATURE`, `OVERCURRENT`, `FAN_STALL`).
- **`WARNING`**: Degraded performance, early drift, or sensor disagreement (`HIGH_TEMPERATURE`, `HIGH_CURRENT`, `LOW_RPM`, `TEMP_SENSOR_DISAGREEMENT`, `INVALID_TELEMETRY`, `UNEXPECTED_RPM_WHEN_FAN_OFF`).
- **`INFO`**: Advisory notices.

---

## 5. Centralized Threshold Configuration

All thresholds are centralized in `trust_engine/config.py`:

```python
# Temperature thresholds (deg C)
RULE_TEMP_WARNING = 31.0
RULE_TEMP_CRITICAL = 33.5
RULE_TEMP_DISAGREEMENT_THRESHOLD = 2.0

# Current thresholds (Amperes)
RULE_CURRENT_WARNING = 0.28
RULE_CURRENT_CRITICAL = 0.40

# RPM thresholds
RULE_RPM_STALL_THRESHOLD = 150.0
RULE_RPM_LOW_THRESHOLD = 1000.0
RULE_UNEXPECTED_RPM_FAN_OFF_THRESHOLD = 50.0

# Stateful confirmation
RULE_FAN_STALL_CONFIRMATION_COUNT = 3
```

> **Notice:** These thresholds are initial engineering and demo calibration values for TrustTwin. They must be re-calibrated against physical hardware before deployment in production environments.

---

## 6. Stateful Stall Confirmation

A fan motor requires finite time to spin up after receiving a start command. A single instantaneous reading showing low RPM does not necessarily constitute a stall.
- The `RuleEngine` maintains an internal counter `_consecutive_low_rpm[device_id]`.
- When $\text{fan} == \text{True}$ and $\text{RPM} \le 150.0$, the counter increments.
- Only when the counter reaches `RULE_FAN_STALL_CONFIRMATION_COUNT` (default 3) does `FAN_STALL` trigger.
- If RPM recovers or the fan command turns OFF, the counter immediately resets to 0.
- State is partitioned by `device_id`, preventing cross-device interference.

---

## 7. Missing Value & Incomplete Data Policy

- Missing fields (`None`) are **NEVER converted to zero**.
- If a sensor field is `None`, rules dependent on that sensor are cleanly skipped.
- If only one temperature sensor is available, the engine evaluates rules on that sensor and skips dual-sensor disagreement checks without raising exceptions.
- The engine guarantees structural validity on incomplete feature vectors.

---

## 8. Dataset Validation Summary

Evaluating `test_rule_engine.py` across the four project telemetry datasets demonstrates clear physical differentiation:

1. **`normal_data.json` (1,800 readings):**
   - **0 violations triggered (0.0%).** Zero false positive alarms during normal continuous operation.
2. **`degradation_data.json` (60 readings):**
   - **35 readings with violations (58.3%).**
   - At reading #25: `HIGH_CURRENT` ($I \ge 0.28\text{ A}$).
   - At reading #26: `LOW_RPM` ($\text{RPM} < 1000$).
   - At reading #32: `HIGH_TEMPERATURE` ($T \ge 31.0^\circ\text{C}$).
   - At reading #54: `CRITICAL_TEMPERATURE` ($T \ge 33.5^\circ\text{C}$) and `OVERCURRENT` ($I \ge 0.40\text{ A}$).
3. **`stall_data.json` (45 readings):**
   - **20 readings with violations (44.4%).**
   - Readings 0..24: Normal operation (clean).
   - Reading #25 onwards: Current rises and RPM drops.
   - Reading #44: `FAN_STALL` confirmed after 3 consecutive readings below $150\text{ RPM}$.
4. **`fan_off_data.json` (20 readings):**
   - **0 violations triggered (0.0%).** Correctly recognizes intentional shutdown with near-zero RPM.

---

## 9. Limitations & What Stage 4 Will Consume

- **Deterministic rules alone lack novelty detection:** A subtle multivariate drift that stays within individual sensor bounds will not trigger a rule. That is why Stage 2's Isolation Forest runs in parallel.
- **Stage 4 Consumption:**
  Stage 4 (`TrustEngine`) will combine:
  1. `FeatureVector` from Stage 1
  2. `AnomalyResult` from Stage 2
  3. `RuleEvaluationResult` from Stage 3
  4. Temporal degradation trends from `TrendAnalyzer`
  To compute a coherent 0–100 Trust Score with explanatory reasons.
