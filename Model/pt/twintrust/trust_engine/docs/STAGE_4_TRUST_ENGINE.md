# Stage 4: Trust Engine Architecture & Operational Decision Synthesis

## 1. Purpose
The **Trust Engine** is the core decision-synthesis layer of the TrustTwin (PulseTrust) physical plant monitoring system. While individual sensors provide measurements ("what is happening") and Stage 2 / Stage 3 models report anomaly signals and threshold violations, the Trust Engine determines:

> **"Can this machine's current physical behavior be trusted to continue operating safely?"**

It integrates evidence from:
1. **Stage 1 FeatureExtractor**: Physical state, dynamic rate calculations, rolling window statistics, and data quality.
2. **Stage 2 Isolation Forest AnomalyDetector**: Multivariate statistical novelty detection relative to healthy operating history.
3. **Stage 3 Deterministic Rule Engine**: Physical safety boundaries, electrical limits, cross-sensor plausibility, and stateful stall confirmation.
4. **Operational Context**: Intentional actuators (e.g. fan commanded OFF vs. running) and multi-device state tracking.

The Trust Engine produces a unified `TrustResult` with a bounded numerical score ($0.0 \le \text{trust\_score} \le 100.0$), a discrete machine state (`NORMAL`, `CAUTION`, `DEGRADING`, `FAULT`, `OFFLINE`), an operational decision (`ALLOW`, `WARN`, `BLOCK`), and structured reasons traceable to observed physical evidence.

---

## 2. Architecture & Pipeline Flow

```text
               +----------------------------------+
               |   Raw Telemetry Reading (ESP32)  |
               +----------------------------------+
                                |
                                v
               +----------------------------------+
               |    Stage 1: FeatureExtractor     |
               |  - 34 Numerical ML Features      |
               |  - Derived Physical Rates        |
               |  - Rolling Statistics (N=10)     |
               |  - Data Quality Indicators       |
               +----------------------------------+
                                |
                +---------------+---------------+
                |                               |
                v                               v
+-------------------------------+   +-------------------------------+
|   Stage 2: Isolation Forest   |   |   Stage 3: Rule Engine        |
|  - Multivariate Novelty       |   |  - 9 Deterministic Rules      |
|  - Anomaly Score              |   |  - Stateful Stall Persistence |
|  - Inlier vs. Outlier         |   |  - Physical Boundaries        |
+-------------------------------+   +-------------------------------+
                |                               |
                +---------------+---------------+
                                |
                                v
               +----------------------------------+
               |     Stage 4: Trust Engine        |
               |  - Additive Penalty Deductions   |
               |  - Double-Counting Mitigation    |
               |  - Context-Aware Suppression     |
               |  - Strict State Consistency      |
               +----------------------------------+
                                |
                                v
               +----------------------------------+
               |      Structured TrustResult      |
               |  - trust_score: [0.0 - 100.0]    |
               |  - state: NORMAL/CAUTION/...     |
               |  - decision: ALLOW/WARN/BLOCK    |
               |  - structured_reasons            |
               |  - combined_evidence             |
               +----------------------------------+
                                |
                                v (Future Downstream)
               +----------------------------------+
               |     LLM Explanation Adapter      |
               |  (Natural language explanation)  |
               +----------------------------------+
```

---

## 3. Trust Score Formula

The trust score is an engineering metric reflecting operational trustworthiness, starting from an ideal baseline of 100.0:

$$\text{trust\_score} = \operatorname{clamp}\Big(100.0 - \big(\text{penalty}_{\text{anomaly}} + \text{penalty}_{\text{warning}} + \text{penalty}_{\text{critical}} + \text{penalty}_{\text{degradation}}\big),\, 0.0,\, 100.0\Big)$$

Where:
- $\text{penalty}_{\text{anomaly}}$: Statistical outlier deduction ($0.0$ to $25.0$).
- $\text{penalty}_{\text{warning}}$: Warning rule violation deduction ($0.0$ to $25.0$, capped).
- $\text{penalty}_{\text{critical}}$: Critical safety rule deduction ($30.0$ per critical violation, uncapped).
- $\text{penalty}_{\text{degradation}}$: Temporal deterioration deduction ($0.0$ to $15.0$, capped).

---

## 4. Anomaly Contribution (Stage 2)

The Isolation Forest outputs `is_anomaly` and a continuous decision score (`anomaly_score`, where positive indicates inlier and negative indicates outlier):

1. **Nominal State**: If `is_anomaly == False`, $\text{penalty}_{\text{anomaly}} = 0.0$.
2. **Standard Anomaly**: If `is_anomaly == True`, $\text{base\_penalty} = 15.0$.
3. **Severe Anomaly**: If `anomaly_score < TRUST_ANOMALY_SEVERE_THRESHOLD` ($-0.15$), add severe bonus $+10.0$ (totaling $25.0$).
4. **Cap**: Capped at `TRUST_MAX_ANOMALY_PENALTY` ($25.0$).
5. **Context Suppression**: If the fan is commanded OFF and there are zero rule violations, the penalty is completely zeroed ($0.0$).
6. **Mitigation Factor**: Scaled by $0.5$ if critical rules already fired.

---

## 5. Rule Contribution (Stage 3)

Deterministic rules express physical and operational truths that override statistical heuristics:
- **Warning Rules** (`HIGH_TEMPERATURE`, `HIGH_CURRENT`, `LOW_RPM`, `TEMP_SENSOR_DISAGREEMENT`, `INVALID_TELEMETRY`, `UNEXPECTED_RPM_WHEN_FAN_OFF`):
  $$\text{penalty}_{\text{warning}} = \min\big(N_{\text{warnings}} \times 10.0,\, 25.0\big)$$
  Capped at $25.0$ to prevent multiple mild warnings from collapsing trust prematurely.
- **Critical Rules** (`FAN_STALL`, `OVERCURRENT`, `CRITICAL_TEMPERATURE`):
  $$\text{penalty}_{\text{critical}} = N_{\text{critical}} \times 30.0$$
  Each critical violation deducts $30.0$. Furthermore, **any** critical rule immediately forces the state to `FAULT` and the decision to `BLOCK`.

---

## 6. Temporal Contribution (Stage 1 Derived Rates)

The Trust Engine analyzes genuine derived physical rates from Stage 1:
- `temp_rate > 0.05` °C/s $\rightarrow$ `TEMP_RISING`
- `rpm_rate < -10.0` RPM/s $\rightarrow$ `RPM_FALLING`
- `current_rate > 0.005` A/s $\rightarrow$ `CURRENT_RISING`
- `vibration_rate > 0.10` m/s²/s $\rightarrow$ `VIBRATION_RISING`

$$\text{penalty}_{\text{degradation}} = \min\big(N_{\text{signals}} \times 8.0,\, 15.0\big)$$

*Guard policy*: Temporal features are only evaluated when they exist (`rate_features_available == True`). Values are never fabricated during cold-start or missing telemetry.

---

## 7. Double-Counting Mitigation

A single physical failure (e.g., motor rotor stall) will typically manifest across all three stages simultaneously:
- Stage 1: `rpm_rate` drops sharply negative, `current_rate` spikes positive.
- Stage 2: Isolation Forest marks `is_anomaly = True` with a deeply negative score.
- Stage 3: Rule engine triggers `FAN_STALL` (CRITICAL) and `OVERCURRENT` (CRITICAL).

If every subsystem blindly applied full independent penalties, the trust score would arbitrarily collapse to 0.0 multiple times over. 

**Mitigation Strategy**:
1. Critical physical rules are given semantic dominance.
2. When critical rules trigger, the statistical anomaly penalty is scaled by `TRUST_DOUBLE_COUNT_REDUCTION` ($0.5$).
3. Warnings and temporal degradation penalties are capped at reasonable ceilings ($25.0$ and $15.0$).
4. This ensures the trust score remains meaningful, proportional, and explainable.

---

## 8. Machine State Definitions

Precedence: `OFFLINE` $\rightarrow$ `FAULT` $\rightarrow$ `DEGRADING` $\rightarrow$ `CAUTION` $\rightarrow$ `NORMAL`

| State | Condition | Meaning |
|---|---|---|
| `NORMAL` | Score $\ge 75.0$, 0 criticals, 0 warnings, no adverse trends | Nominal, healthy, stable operation. |
| `CAUTION` | Warning violation OR unsuppressed anomaly OR score $\le 75.0$ | Minor abnormality; continuous operation permissible under observation. |
| `DEGRADING` | Temporal trend signals detected alongside warnings/anomalies | Active progressive physical deterioration over time. |
| `FAULT` | $\ge 1$ CRITICAL rule violation OR trust score $\le 30.0$ | Confirmed severe mechanical/electrical failure. Immediate intervention required. |
| `OFFLINE` | Confirmed loss of telemetry connectivity (architecture-reserved) | Communication lost. |

---

## 9. Decision Definitions & Mapping

| State | Default Decision | Guard Override |
|---|---|---|
| `NORMAL` | `ALLOW` | Clamped to `WARN` if score $\le 75.0$ |
| `CAUTION` | `WARN` | Clamped to `BLOCK` if score $\le 30.0$ |
| `DEGRADING` | `WARN` | Clamped to `BLOCK` if score $\le 30.0$ |
| `FAULT` | `BLOCK` | Always `BLOCK` |
| `OFFLINE` | `BLOCK` | Always `BLOCK` |

**Consistency Invariants**:
- Any CRITICAL rule strictly enforces `state = FAULT` and `decision = BLOCK`.
- $\text{trust\_score} \le 30.0$ strictly enforces `decision = BLOCK`.
- $\text{trust\_score} \le 75.0$ strictly prevents `decision = ALLOW`.

---

## 10. Centralized Thresholds & Calibration Parameters

All parameters reside in `trust_engine/config.py`:

```python
TRUST_BASE_SCORE = 100.0

TRUST_ANOMALY_BASE_PENALTY = 15.0
TRUST_ANOMALY_SEVERE_THRESHOLD = -0.15
TRUST_ANOMALY_SEVERE_BONUS = 10.0
TRUST_MAX_ANOMALY_PENALTY = 25.0

TRUST_WARNING_PENALTY = 10.0
TRUST_CRITICAL_PENALTY = 30.0
TRUST_MAX_WARNING_PENALTY = 25.0

TRUST_DOUBLE_COUNT_REDUCTION = 0.5

TRUST_DEGRADATION_PENALTY = 8.0
TRUST_MAX_DEGRADATION_PENALTY = 15.0

TRUST_TEMP_RATE_THRESHOLD = 0.05       # °C/s
TRUST_RPM_RATE_THRESHOLD = -10.0       # RPM/s
TRUST_CURRENT_RATE_THRESHOLD = 0.005   # A/s
TRUST_VIBRATION_RATE_THRESHOLD = 0.1   # m/s²/s

TRUST_FAULT_THRESHOLD = 30.0
TRUST_CAUTION_THRESHOLD = 75.0
TRUST_ALLOW_THRESHOLD = 75.0
TRUST_WARN_THRESHOLD = 30.0
```

---

## 11. Concrete Behavioral Examples

### Example 1: Healthy Operation
- Reading: Temp = 28.1°C, RPM = 1450, Current = 0.18 A, Fan = True
- Anomaly: `is_anomaly = False`, score = $+0.06$
- Rules: 0 violations
- **Result**: `trust_score = 100.0`, `state = NORMAL`, `decision = ALLOW`

### Example 2: Mild Anomaly (Statistical Only)
- Reading: Slight multivariate shift not violating physical bounds
- Anomaly: `is_anomaly = True`, score = $-0.07$
- Rules: 0 violations
- **Result**: `trust_score = 85.0`, `state = CAUTION`, `decision = WARN`

### Example 3: Progressive Degradation
- Reading #40 (degradation sequence): Temp rising (+0.07°C/s), Current = 0.32 A (Warning)
- Anomaly: `is_anomaly = True`, score = $-0.13$
- Rules: `HIGH_CURRENT` (WARNING)
- **Result**: `trust_score = 59.0`, `state = DEGRADING`, `decision = WARN`

### Example 4: Confirmed Mechanical Stall
- Reading #44 (stall sequence): Fan = True, RPM = 1.37 for 3 readings, Current = 0.38 A
- Anomaly: `is_anomaly = True`, score = $-0.17$
- Rules: `FAN_STALL` (CRITICAL)
- Double-counting mitigation: Anomaly penalty halved ($25 \times 0.5 = 12.5$)
- **Result**: `trust_score = 45.0` (or lower), `state = FAULT`, `decision = BLOCK`

---

## 12. Fan OFF Handling

When the cooling fan is commanded OFF (`fan_int == 0.0`), RPM naturally settles near 0:
- Stage 2 Isolation Forest was trained on healthy running data and flags this operating point as an anomaly ($100\%$ detection rate, score $\approx -0.098$).
- Stage 3 Rule Engine checks operational context and emits **0 violations**.
- **Stage 4 TrustEngine recognizes intentional context**:
  - The statistical anomaly penalty is completely suppressed.
  - A structured reason `ANOMALY_SUPPRESSED_FAN_OFF` is recorded for transparency.
  - The machine remains in `NORMAL` state with `ALLOW` decision.

---

## 13. Fan STALL Handling

When the cooling fan is commanded ON (`fan_int == 1.0`) but RPM drops below $150$:
- Single transient dips do not trigger a critical fault (preventing false alarms during startup).
- On the 3rd consecutive reading below threshold, Stage 3 confirms `FAN_STALL` (CRITICAL).
- Stage 4 immediately forces:
  - `state = FAULT`
  - `decision = BLOCK`
  - Structured reason detailing confirmed stall reading index, RPM, and threshold.

---

## 14. Degradation Trajectory

In long-running sequences (e.g. `degradation_data.json`):
1. **Readings 0–24**: Healthy baseline $\rightarrow$ `NORMAL` / `ALLOW`.
2. **Readings 25–35**: Current rises above 0.28 A (`HIGH_CURRENT`), RPM dips below 1000 (`LOW_RPM`), rates become adverse $\rightarrow$ `CAUTION` / `DEGRADING` / `WARN`.
3. **Readings 36–53**: Temperature rises above 31.0°C (`HIGH_TEMPERATURE`), score drops into 40–60 range $\rightarrow$ `DEGRADING` / `WARN`.
4. **Readings 54–60**: Temperature crosses 33.5°C (`CRITICAL_TEMPERATURE`) and current exceeds 0.40 A (`OVERCURRENT`) $\rightarrow$ `FAULT` / `BLOCK`.

---

## 15. Limitations & Operating Bounds

1. **Demo/Prototype Thresholds**: Thresholds are calibrated for the physical hardware testbench (TIP31C + 5V 4010 fan + ESP32) and require operational profiling before deployment on other equipment.
2. **Offline Detection**: `OFFLINE` state is reserved in the schema; heartbeat timeout detection requires application-level transport monitoring (e.g., FastAPI / Supabase ingestion worker).
3. **Not a Scientific Probability**: A trust score of $80.0$ does NOT denote an "80% probability of non-failure". It is a normalized deterministic multi-factor trust metric.

---

## 16. Future LLM Explanation Architecture

The structured `TrustResult` is designed to feed a future downstream LLM natural-language explanation adapter:

```json
{
  "trust_score": 45.0,
  "state": "FAULT",
  "decision": "BLOCK",
  "reasons": [
    "[CRITICAL] Fan stall confirmed: fan commanded ON but RPM <= 150.0 for 3 consecutive readings",
    "Current consumption rising: +0.00820 A/s"
  ],
  "structured_reasons": [
    {
      "reason_id": "FAN_STALL",
      "source": "rule_engine",
      "severity": "CRITICAL",
      "message": "Fan stall confirmed",
      "evidence": {"rpm": 1.37, "threshold": 150.0, "confirmation_count": 3}
    }
  ],
  "evidence": {
    "key_sensors": {"temp_1": 28.5, "rpm": 1.37, "current": 0.38, "fan_int": 1.0}
  }
}
```

The future LLM will consume this payload with a strict system prompt:
> *"Translate the provided structured reasons and sensor evidence into a clear explanation for the plant operator. You may NOT alter the trust_score, state, or decision. You may NOT infer unmeasured physical phenomena."*

---

## 17. Why the LLM Does Not Make the Machine Decision

1. **Safety and Determinism**: In industrial safety and physical plant automation, decisions to ALLOW or BLOCK electrical machinery cannot be subject to stochastic token sampling, prompt drift, non-deterministic latency, or hallucination.
2. **Auditability**: Regulatory compliance and forensic accident analysis require exact mathematical reconstruction of why a machine was shut down.
3. **Speed & Offline Resilience**: The ESP32 edge and local Trust Engine evaluate in $<1$ millisecond without external internet or cloud API dependencies.
