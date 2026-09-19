"""
models.py
=========
Pydantic data models for the Trust Engine.

Three main structures:
    TelemetryReading  -- one raw ESP32 sensor packet (input)
    FeatureVector     -- fully derived feature set (output of FeatureExtractor)
    TrustResult       -- future output of TrustEngine (stub)

Design rules:
    - Timestamps and device_id are METADATA -- never fed to ML models.
    - All numerical ML features are Optional[float]; None means "not available".
    - to_ml_dict() returns ONLY finite floats -- safe to pass to sklearn/numpy.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator, model_validator


# ---------------------------------------------------------------------------
# Input model
# ---------------------------------------------------------------------------

class TelemetryReading(BaseModel):
    """
    One raw telemetry packet from the ESP32.

    Fields match the ESP32 JSON payload exactly.  All sensor fields are
    Optional so the FeatureExtractor can apply the configured missing-value
    policy rather than crashing on partial readings.
    """

    # --- metadata (never ML features) ---
    device_id: str = Field(default="unknown", description="ESP32 device identifier")
    timestamp: Optional[datetime] = Field(
        default=None,
        description="ISO-8601 timestamp. If absent, FeatureExtractor uses wall-clock time.",
    )

    # --- sensor readings ---
    temp_1: Optional[float] = Field(default=None, description="DS18B20 sensor 1 (°C)")
    temp_2: Optional[float] = Field(default=None, description="DS18B20 sensor 2 (°C)")
    rpm: Optional[float] = Field(default=None, description="Fan RPM (from Hall sensor)")
    hall_raw: Optional[float] = Field(
        default=None,
        description="Raw Hall sensor ADC reading. Diagnostic only -- not an ML feature.",
    )
    vibration: Optional[float] = Field(
        default=None,
        description=(
            "Vibration magnitude from MPU6050. "
            "Currently sqrt(ax^2 + ay^2 + az^2) -- includes gravity (~9.8 m/s^2). "
            "See config.VIBRATION_MEASUREMENT_TYPE."
        ),
    )
    voltage: Optional[float] = Field(default=None, description="INA219 voltage (V)")
    current: Optional[float] = Field(default=None, description="INA219 current (A)")
    power: Optional[float] = Field(default=None, description="INA219 power (W)")
    fan: Optional[bool] = Field(default=None, description="Fan actuator state (True=ON)")

    @field_validator("rpm")
    @classmethod
    def rpm_must_be_non_negative(cls, v: Optional[float]) -> Optional[float]:
        if v is not None and v < 0:
            raise ValueError(f"RPM cannot be negative (got {v}). Check sensor wiring.")
        return v

    @field_validator("temp_1", "temp_2")
    @classmethod
    def temperature_sanity(cls, v: Optional[float]) -> Optional[float]:
        # DS18B20 range: -55 to +125 C. Anything outside is likely a read error.
        if v is not None and not (-60.0 <= v <= 130.0):
            raise ValueError(f"Temperature {v} is outside plausible range [-60, 130] C.")
        return v

    def effective_timestamp(self) -> datetime:
        """Return the reading timestamp, falling back to current UTC time."""
        if self.timestamp is not None:
            return self.timestamp
        return datetime.now(timezone.utc)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TelemetryReading":
        """Convenience constructor from a plain dict (e.g. parsed JSON)."""
        return cls(**data)


# ---------------------------------------------------------------------------
# Feature sub-models
# ---------------------------------------------------------------------------

class FeatureMetadata(BaseModel):
    """Non-numeric context -- never passed to ML."""
    device_id: str
    timestamp: datetime
    reading_index: int = Field(description="How many readings have been processed (0-indexed)")
    hall_raw: Optional[float] = Field(default=None, description="Diagnostic ADC value")


class RawFeatures(BaseModel):
    """
    Cleaned versions of the raw physical sensor values.

    fan_int converts the boolean fan field to 0.0 / 1.0 so it can be used
    numerically without special-casing.
    """
    temp_1: Optional[float] = None
    temp_2: Optional[float] = None
    rpm: Optional[float] = None
    vibration: Optional[float] = None
    voltage: Optional[float] = None
    current: Optional[float] = None
    power: Optional[float] = None
    fan_int: Optional[float] = None   # 1.0 if fan=True, 0.0 if fan=False, None if missing


class DerivedFeatures(BaseModel):
    """
    All computed features from the FeatureExtractor.

    Formula reference
    -----------------
    temp_delta          = temp_1 - temp_2
    temp_avg            = (temp_1 + temp_2) / 2
    temp_rate           = (temp_avg_now - temp_avg_prev) / elapsed_seconds

    rpm_delta           = rpm_now - rpm_prev
    rpm_rate            = rpm_delta / elapsed_seconds

    current_delta       = current_now - current_prev
    current_rate        = current_delta / elapsed_seconds
    power_delta         = power_now - power_prev
    power_rate          = power_delta / elapsed_seconds
    power_per_rpm       = power / rpm  (None if rpm < MIN_RPM_FOR_RATIO)
    current_per_rpm     = current / rpm  (None if rpm < MIN_RPM_FOR_RATIO)

    vibration_delta     = vibration_now - vibration_prev
    vibration_rate      = vibration_delta / elapsed_seconds

    rolling_{x}_{stat}  = statistic over last ROLLING_WINDOW_SIZE readings

    fan_rpm_consistency = fan_int * max(0, 1 - rpm / EXPECTED_FAN_RPM)
                          Range [0, 1]:
                            0 = consistent (fan off, or fan on with expected RPM)
                            1 = maximally inconsistent (fan on, RPM = 0)

    current_vs_rpm_ratio = current / rpm  (alias of current_per_rpm, kept separate
                           for cross-sensor clarity)
    power_vs_rpm_ratio   = power / rpm  (alias of power_per_rpm)
    """

    # temperature
    temp_delta: Optional[float] = None
    temp_avg: Optional[float] = None
    temp_rate: Optional[float] = None

    # rpm
    rpm_delta: Optional[float] = None
    rpm_rate: Optional[float] = None

    # electrical
    current_delta: Optional[float] = None
    current_rate: Optional[float] = None
    power_delta: Optional[float] = None
    power_rate: Optional[float] = None
    power_per_rpm: Optional[float] = None
    current_per_rpm: Optional[float] = None

    # vibration
    vibration_delta: Optional[float] = None
    vibration_rate: Optional[float] = None

    # rolling stats (window = ROLLING_WINDOW_SIZE readings)
    temp_1_mean: Optional[float] = None
    temp_1_std: Optional[float] = None
    temp_2_mean: Optional[float] = None
    temp_2_std: Optional[float] = None
    rpm_mean: Optional[float] = None
    rpm_std: Optional[float] = None
    current_mean: Optional[float] = None
    current_std: Optional[float] = None
    vibration_mean: Optional[float] = None
    vibration_std: Optional[float] = None
    power_mean: Optional[float] = None
    power_std: Optional[float] = None

    # cross-sensor consistency
    fan_rpm_consistency: Optional[float] = None
    current_vs_rpm_ratio: Optional[float] = None
    power_vs_rpm_ratio: Optional[float] = None


class DataQuality(BaseModel):
    """
    Data quality flags for a single feature extraction.

    These are informational -- they help the future TrustEngine weigh
    evidence from low-quality readings appropriately.
    """
    missing_fields: List[str] = Field(
        default_factory=list,
        description="Raw sensor fields that were None in the incoming reading.",
    )
    imputed_fields: List[str] = Field(
        default_factory=list,
        description="Fields where a missing value was replaced (per MISSING_VALUE_POLICY).",
    )
    rate_features_available: bool = Field(
        default=False,
        description="True if a previous reading exists, so delta/rate features could be computed.",
    )
    rolling_features_available: bool = Field(
        default=False,
        description="True if enough history exists for rolling statistics.",
    )
    elapsed_seconds: Optional[float] = Field(
        default=None,
        description="Seconds between this reading and the previous one.",
    )
    history_size: int = Field(
        default=0,
        description="Number of readings currently in the history buffer.",
    )
    warnings: List[str] = Field(
        default_factory=list,
        description="Human-readable data quality warnings (e.g. stale timestamp).",
    )


# ---------------------------------------------------------------------------
# Main output model
# ---------------------------------------------------------------------------

class FeatureVector(BaseModel):
    """
    Complete output of the FeatureExtractor for a single TelemetryReading.

    Attributes
    ----------
    metadata        : Non-numeric context. Never pass to ML.
    raw_features    : Cleaned physical sensor values.
    derived_features: All computed features.
    data_quality    : Flags describing completeness and reliability.
    """

    metadata: FeatureMetadata
    raw_features: RawFeatures
    derived_features: DerivedFeatures
    data_quality: DataQuality

    def to_ml_dict(self) -> Dict[str, float]:
        """
        Return a flat dict of only the features that are finite floats.

        This is what gets passed to sklearn / numpy.  Any feature that is
        None, NaN, or infinite is silently excluded.  The caller (future
        AnomalyDetector) is responsible for deciding how to handle missing
        feature columns (e.g. imputation or excluding the reading).
        """
        result: Dict[str, float] = {}

        def _add(source: BaseModel) -> None:
            for name, value in source.model_dump().items():
                if isinstance(value, (int, float)) and math.isfinite(float(value)):
                    result[name] = float(value)

        _add(self.raw_features)
        _add(self.derived_features)
        return result

    def to_ml_list(self, feature_names: List[str]) -> List[Optional[float]]:
        """
        Return features in a fixed order matching `feature_names`.

        Missing features are represented as None (not NaN) so the caller
        can decide how to handle them.
        """
        ml_dict = self.to_ml_dict()
        return [ml_dict.get(name) for name in feature_names]

    def pretty_print(self) -> str:
        """Human-readable summary for debugging / demo output."""
        lines = [
            "=" * 60,
            f"  FeatureVector  |  device={self.metadata.device_id}",
            f"  timestamp={self.metadata.timestamp.isoformat()}",
            f"  reading #{self.metadata.reading_index}",
            "=" * 60,
            "",
            "[METADATA]",
            f"  hall_raw          = {self.metadata.hall_raw}",
            "",
            "[RAW FEATURES]",
        ]
        for k, v in self.raw_features.model_dump().items():
            lines.append(f"  {k:<25} = {_fmt(v)}")

        lines += ["", "[DERIVED FEATURES]"]
        for k, v in self.derived_features.model_dump().items():
            lines.append(f"  {k:<25} = {_fmt(v)}")

        lines += ["", "[DATA QUALITY]"]
        dq = self.data_quality
        lines.append(f"  missing_fields       = {dq.missing_fields}")
        lines.append(f"  imputed_fields       = {dq.imputed_fields}")
        lines.append(f"  rate_features        = {dq.rate_features_available}")
        lines.append(f"  rolling_features     = {dq.rolling_features_available}")
        lines.append(f"  elapsed_seconds      = {_fmt(dq.elapsed_seconds)}")
        lines.append(f"  history_size         = {dq.history_size}")
        for w in dq.warnings:
            lines.append(f"  WARNING: {w}")

        lines.append("")
        return "\n".join(lines)


def _fmt(v: Any) -> str:
    """Format a feature value for display."""
    if v is None:
        return "None (not available)"
    if isinstance(v, float):
        return f"{v:.6f}"
    return str(v)


# ---------------------------------------------------------------------------
# Stage 2 Anomaly Detection Output Model
# ---------------------------------------------------------------------------

class AnomalyResult(BaseModel):
    """
    Structured output from the Isolation Forest AnomalyDetector.

    Interpretation:
      - is_anomaly: True if Isolation Forest flagged this reading as an anomaly.
      - raw_prediction: 1 for normal (inlier), -1 for anomaly (outlier), 0 if unpredicted (e.g. cold-start).
      - anomaly_score: sklearn decision_function output.
          Positive (> 0)  -> Inlier (normal, familiar machine state).
          Negative (< 0)  -> Outlier (unusual/anomalous compared to normal baseline).
          Magnitude indicates distance from the decision boundary.
      - model_status: "trained" | "loaded" | "insufficient_history"
      - features_used: Number of ML features evaluated.
      - data_quality_warning: Set if temporal/rolling features were unavailable due to cold start.
    """

    is_anomaly: bool = Field(
        description="True if the reading is classified as anomalous, False if normal.",
    )
    raw_prediction: int = Field(
        default=1,
        description="Scikit-learn prediction: 1 = normal, -1 = anomaly, 0 = skipped/cold-start.",
    )
    anomaly_score: Optional[float] = Field(
        default=None,
        description=(
            "Raw Isolation Forest decision_function score. "
            "Higher positive values are more typical/normal; negative values are anomalous."
        ),
    )
    normalized_score: Optional[float] = Field(
        default=None,
        description="Diagnostic reference score (offset-shifted decision score).",
    )
    model_status: str = Field(
        default="unknown",
        description="'trained', 'loaded', or 'insufficient_history'.",
    )
    features_used: int = Field(
        default=0,
        description="Number of feature columns evaluated by the model.",
    )
    data_quality_warning: Optional[str] = Field(
        default=None,
        description="Human-readable warning if cold-start history was insufficient.",
    )
    feature_vector: Optional[FeatureVector] = Field(
        default=None,
        description="The FeatureVector evaluated, if provided.",
    )

    def to_dict(self) -> Dict[str, Any]:
        """Return dict representation."""
        return self.model_dump(exclude={"feature_vector"})

    def pretty_print(self) -> str:
        """Human-readable string summary."""
        lines = [
            "---------------- AnomalyResult ----------------",
            f"  is_anomaly           : {self.is_anomaly}",
            f"  raw_prediction       : {self.raw_prediction} (1=normal, -1=anomaly)",
            f"  anomaly_score        : {_fmt(self.anomaly_score)} (>0 is normal)",
            f"  model_status         : {self.model_status}",
            f"  features_used        : {self.features_used}",
        ]
        if self.data_quality_warning:
            lines.append(f"  warning              : {self.data_quality_warning}")
        lines.append("-----------------------------------------------")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Stage 3 Rule Engine Output Models
# ---------------------------------------------------------------------------

class RuleSeverity(str, Enum):
    """Explicit severity levels for deterministic rule violations."""
    INFO = "INFO"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


class RuleViolation(BaseModel):
    """
    One triggered rule violation produced by the deterministic Rule Engine.

    Attributes
    ----------
    rule_id : str
        Unique rule identifier (e.g. 'FAN_STALL', 'OVERCURRENT', 'HIGH_TEMPERATURE').
    severity : str
        'INFO' | 'WARNING' | 'CRITICAL'.
    message : str
        Clear human-readable description of the condition.
    evidence : dict
        Actual observed values that caused the rule to trigger.
    value : float, optional
        Key measured physical value.
    threshold : float, optional
        Configured engineering threshold that was crossed.
    """
    rule_id: str = Field(description="Unique rule identifier")
    severity: str = Field(description="INFO | WARNING | CRITICAL")
    message: str = Field(description="Clear explanation of the triggered condition")
    evidence: Dict[str, Any] = Field(default_factory=dict, description="Observed sensor data evidence")
    value: Optional[float] = Field(default=None, description="Primary measured value")
    threshold: Optional[float] = Field(default=None, description="Configured threshold crossed")

    def to_dict(self) -> Dict[str, Any]:
        """Serialize violation to dictionary."""
        return self.model_dump()


class RuleEvaluationResult(BaseModel):
    """
    Complete evaluation summary from RuleEngine.evaluate().
    """
    has_violations: bool = Field(description="True if one or more violations were triggered")
    violations: List[RuleViolation] = Field(default_factory=list, description="List of triggered violations")
    evaluated_rules: int = Field(default=0, description="Total number of rules evaluated")
    triggered_rules: int = Field(default=0, description="Number of rules that triggered")
    engine_status: str = Field(default="ok", description="'ok' (no violations) | 'warning' | 'critical'")
    device_id: str = Field(default="unknown", description="Target device identifier")
    timestamp: Optional[datetime] = Field(default=None, description="Timestamp of the evaluated reading")

    def pretty_print(self) -> str:
        """Human-readable string summary."""
        lines = [
            "---------------- RuleEvaluationResult ----------------",
            f"  device_id        : {self.device_id}",
            f"  has_violations   : {self.has_violations}",
            f"  engine_status    : {self.engine_status.upper()}",
            f"  evaluated_rules  : {self.evaluated_rules}",
            f"  triggered_rules  : {self.triggered_rules}",
        ]
        if self.violations:
            lines.append("  Violations:")
            for v in self.violations:
                lines.append(f"    [{v.severity}] {v.rule_id}: {v.message}")
                if v.evidence:
                    lines.append(f"      Evidence: {v.evidence}")
        lines.append("------------------------------------------------------")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Stage 4 Trust Engine Output Models
# ---------------------------------------------------------------------------

class MachineState(str, Enum):
    """
    Standard machine states determined by the Trust Engine.

    Precedence order:
      OFFLINE -> FAULT -> DEGRADING -> CAUTION -> NORMAL
    """
    NORMAL = "NORMAL"        # Healthy / stable operation
    CAUTION = "CAUTION"      # Warning-level abnormalities or mild statistical anomaly
    DEGRADING = "DEGRADING"  # Consistent adverse trend / worsening machine behavior
    FAULT = "FAULT"          # Confirmed critical physical rule violation or collapsed trust
    OFFLINE = "OFFLINE"      # Reserved for confirmed loss of device connectivity


class TrustDecision(str, Enum):
    """
    Operational recommendation produced by the Trust Engine.

    NORMAL    -> ALLOW
    CAUTION   -> WARN
    DEGRADING -> WARN
    FAULT     -> BLOCK
    OFFLINE   -> BLOCK
    """
    ALLOW = "ALLOW"
    WARN = "WARN"
    BLOCK = "BLOCK"


class TrustReason(BaseModel):
    """
    Traceable, structured justification for trust deductions, state, or decision.

    Designed so downstream explanation layers (e.g. future LLMs) can ground
    natural-language narratives strictly in generated facts without hallucination.
    """
    reason_id: str = Field(description="Unique code identifying the finding (e.g. 'FAN_STALL', 'ANOMALY_DETECTED')")
    source: str = Field(description="Originating subsystem: 'rule_engine' | 'anomaly_detector' | 'temporal' | 'context'")
    message: str = Field(description="Clear human-readable summary of the finding")
    severity: Optional[str] = Field(default=None, description="'INFO' | 'WARNING' | 'CRITICAL' | None")
    evidence: Dict[str, Any] = Field(default_factory=dict, description="Concrete sensor / evaluation evidence")

    def to_dict(self) -> Dict[str, Any]:
        """Serialize reason to dictionary."""
        return self.model_dump()


class TrustResult(BaseModel):
    """
    Unified, explainable operational assessment from the Trust Engine.

    Combines evidence from:
      1. Stage 1 FeatureVector (physical state, rates, rolling stats, data quality)
      2. Stage 2 Isolation Forest (unsupervised multivariate anomaly detection)
      3. Stage 3 Rule Engine (deterministic physical boundary and stall checks)
      4. Operational Context (e.g. intentional fan-off state handling)
    """

    trust_score: float = Field(
        description="Deterministic machine trust score bounded [0.0, 100.0].",
    )
    state: MachineState = Field(
        description="Assigned machine state: NORMAL | CAUTION | DEGRADING | FAULT | OFFLINE.",
    )
    decision: TrustDecision = Field(
        description="Action recommendation: ALLOW | WARN | BLOCK.",
    )
    reasons: List[str] = Field(
        default_factory=list,
        description="List of human-readable summary explanations.",
    )
    structured_reasons: List[TrustReason] = Field(
        default_factory=list,
        description="Structured, evidence-backed reasons for UI and downstream explanation layer.",
    )
    anomaly_summary: Dict[str, Any] = Field(
        default_factory=dict,
        description="Stage 2 anomaly summary (is_anomaly, score, penalty applied, suppressed flag).",
    )
    rule_summary: Dict[str, Any] = Field(
        default_factory=dict,
        description="Stage 3 rule summary (total_violations, critical_count, warning_count).",
    )
    temporal_summary: Dict[str, Any] = Field(
        default_factory=dict,
        description="Temporal degradation indicators and detected trend signals.",
    )
    score_breakdown: Dict[str, float] = Field(
        default_factory=dict,
        description="Itemized penalty deductions from base score 100.",
    )
    evidence: Dict[str, Any] = Field(
        default_factory=dict,
        description="Combined structured evidence payload for auditing and UI display.",
    )
    device_id: Optional[str] = Field(
        default=None,
        description="Identifier of the evaluated device.",
    )
    timestamp: Optional[datetime] = Field(
        default=None,
        description="Timestamp of the evaluated telemetry reading.",
    )
    confidence: Optional[float] = Field(
        default=None,
        description="Data quality confidence indicator [0.0, 1.0].",
    )
    feature_vector: Optional[FeatureVector] = Field(
        default=None,
        description="The FeatureVector evaluated, if provided.",
    )

    @field_validator("trust_score")
    @classmethod
    def validate_score_bounds(cls, v: float) -> float:
        if not (0.0 <= v <= 100.0):
            raise ValueError(f"trust_score must be between 0.0 and 100.0 inclusive, got {v}")
        return round(float(v), 2)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize TrustResult to dictionary, excluding heavy raw feature vector."""
        return self.model_dump(exclude={"feature_vector"})

    def pretty_print(self) -> str:
        """Human-readable string summary of TrustResult."""
        lines = [
            "======================= TrustResult =======================",
            f"  Device ID       : {self.device_id or 'unknown'}",
            f"  Timestamp       : {self.timestamp.isoformat() if self.timestamp else 'N/A'}",
            f"  Trust Score     : {self.trust_score:.2f} / 100.0",
            f"  Machine State   : {self.state.value}",
            f"  Decision        : {self.decision.value}",
            "-----------------------------------------------------------",
            f"  Anomaly Summary : is_anomaly={self.anomaly_summary.get('is_anomaly')}, "
            f"score={self.anomaly_summary.get('anomaly_score')}, "
            f"penalty={self.anomaly_summary.get('penalty', 0.0)}",
            f"  Rule Summary    : total={self.rule_summary.get('total_violations', 0)}, "
            f"critical={self.rule_summary.get('critical_count', 0)}, "
            f"warning={self.rule_summary.get('warning_count', 0)}",
            f"  Score Breakdown : {self.score_breakdown}",
        ]
        if self.reasons:
            lines.append("  Reasons:")
            for r in self.reasons:
                lines.append(f"    - {r}")
        lines.append("===========================================================")
        return "\n".join(lines)

