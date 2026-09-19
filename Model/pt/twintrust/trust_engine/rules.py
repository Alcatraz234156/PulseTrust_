"""
rules.py
========
Stage 3: Deterministic Physical and Operational Rule Engine.

Evaluates known physical limits, operational states, and cross-sensor
consistency rules on incoming FeatureVectors.

Key Principles:
  1. DETERMINISTIC DOMAIN LOGIC:
     Answers "Does this telemetry violate a known physical law or operating limit?"
     Independent of statistical anomaly detection (Isolation Forest).
  2. STRUCTURED EXPLANATIONS:
     Every violation includes rule_id, severity, descriptive message, and
     observed evidence dictionary.
  3. NO SILENT FABRICATION:
     Missing/None values are never converted to zero. Incomplete sensor fields
     cause dependent rules to be skipped cleanly.
  4. STATEFUL CONFIRMATION:
     FAN_STALL requires consecutive readings below stall threshold to prevent
     spurious triggers during normal fan spin-up.
  5. RULE PRIORITY & DUPLICATION CONTROL:
     More severe states subsume less severe warnings on the same physical
     measurement (e.g., CRITICAL_TEMPERATURE subsumes HIGH_TEMPERATURE).
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional

from . import config
from .models import (
    FeatureVector,
    RuleEvaluationResult,
    RuleSeverity,
    RuleViolation,
    TelemetryReading,
)


class RuleEngine:
    """
    Deterministic domain rule engine for TrustTwin machine monitoring.

    Parameters
    ----------
    temp_warning : float
        Warning threshold for operating temperature in °C.
    temp_critical : float
        Critical overtemperature threshold in °C.
    temp_disagreement : float
        Max acceptable gap between temp_1 and temp_2 in °C.
    current_warning : float
        Warning threshold for electrical current draw in Amperes.
    current_critical : float
        Severe overcurrent threshold in Amperes.
    rpm_stall : float
        Stall threshold for fan RPM when commanded ON.
    rpm_low : float
        Degraded low-speed threshold for fan RPM when commanded ON.
    unexpected_rpm_fan_off : float
        Max acceptable residual RPM when fan is commanded OFF.
    stall_confirmation_count : int
        Number of consecutive low-RPM readings required to confirm FAN_STALL.
    """

    def __init__(
        self,
        temp_warning: float = config.RULE_TEMP_WARNING,
        temp_critical: float = config.RULE_TEMP_CRITICAL,
        temp_disagreement: float = config.RULE_TEMP_DISAGREEMENT_THRESHOLD,
        current_warning: float = config.RULE_CURRENT_WARNING,
        current_critical: float = config.RULE_CURRENT_CRITICAL,
        rpm_stall: float = config.RULE_RPM_STALL_THRESHOLD,
        rpm_low: float = config.RULE_RPM_LOW_THRESHOLD,
        unexpected_rpm_fan_off: float = config.RULE_UNEXPECTED_RPM_FAN_OFF_THRESHOLD,
        stall_confirmation_count: int = config.RULE_FAN_STALL_CONFIRMATION_COUNT,
        temp_min: float = config.RULE_VALID_TEMP_MIN,
        temp_max: float = config.RULE_VALID_TEMP_MAX,
        voltage_min: float = config.RULE_VALID_VOLTAGE_MIN,
        voltage_max: float = config.RULE_VALID_VOLTAGE_MAX,
        current_min: float = config.RULE_VALID_CURRENT_MIN,
        current_max: float = config.RULE_VALID_CURRENT_MAX,
        rpm_min: float = config.RULE_VALID_RPM_MIN,
        power_min: float = config.RULE_VALID_POWER_MIN,
    ) -> None:
        self.temp_warning = temp_warning
        self.temp_critical = temp_critical
        self.temp_disagreement = temp_disagreement
        self.current_warning = current_warning
        self.current_critical = current_critical
        self.rpm_stall = rpm_stall
        self.rpm_low = rpm_low
        self.unexpected_rpm_fan_off = unexpected_rpm_fan_off
        self.stall_confirmation_count = stall_confirmation_count

        # Physical sanity bounds
        self.temp_min = temp_min
        self.temp_max = temp_max
        self.voltage_min = voltage_min
        self.voltage_max = voltage_max
        self.current_min = current_min
        self.current_max = current_max
        self.rpm_min = rpm_min
        self.power_min = power_min

        # Stateful tracking per device_id:
        # device_id -> consecutive readings where fan=ON and rpm <= rpm_stall
        self._consecutive_low_rpm: Dict[str, int] = {}

    # ----------------------------------------------------------------------
    # Public API
    # ----------------------------------------------------------------------

    def evaluate(self, feature_vector: FeatureVector) -> RuleEvaluationResult:
        """
        Evaluate all deterministic rules against a FeatureVector.

        Parameters
        ----------
        feature_vector : FeatureVector
            The extracted features from Stage 1 FeatureExtractor.

        Returns
        -------
        RuleEvaluationResult
            Structured summary containing all triggered violations.
        """
        device_id = feature_vector.metadata.device_id or "unknown"
        timestamp = feature_vector.metadata.timestamp
        raw = feature_vector.raw_features
        derived = feature_vector.derived_features

        violations: List[RuleViolation] = []
        total_rules_evaluated = 9

        # ------------------------------------------------------------------
        # Rule 9: Physical Range Sanity (INVALID_TELEMETRY)
        # ------------------------------------------------------------------
        invalid_fields = self._check_physical_validity(raw)
        if invalid_fields:
            violations.append(
                RuleViolation(
                    rule_id="INVALID_TELEMETRY",
                    severity=RuleSeverity.WARNING.value,
                    message=(
                        f"Physically impossible telemetry detected in {len(invalid_fields)} field(s): "
                        f"{', '.join(invalid_fields.keys())}."
                    ),
                    evidence=invalid_fields,
                    value=None,
                    threshold=None,
                )
            )

        # ------------------------------------------------------------------
        # Dual-Sensor Consistency (TEMP_SENSOR_DISAGREEMENT)
        # ------------------------------------------------------------------
        if raw.temp_1 is not None and raw.temp_2 is not None:
            temp_diff = abs(raw.temp_1 - raw.temp_2)
            if temp_diff > self.temp_disagreement:
                violations.append(
                    RuleViolation(
                        rule_id="TEMP_SENSOR_DISAGREEMENT",
                        severity=RuleSeverity.WARNING.value,
                        message=(
                            f"Dual temperature sensors disagree: |T1 - T2| = {temp_diff:.2f}C "
                            f"exceeds tolerance of {self.temp_disagreement:.2f}C."
                        ),
                        evidence={
                            "temp_1": raw.temp_1,
                            "temp_2": raw.temp_2,
                            "absolute_difference": round(temp_diff, 4),
                            "threshold": self.temp_disagreement,
                        },
                        value=temp_diff,
                        threshold=self.temp_disagreement,
                    )
                )

        # ------------------------------------------------------------------
        # Rule 1 & 2: Thermal Rules (CRITICAL_TEMPERATURE / HIGH_TEMPERATURE)
        # ------------------------------------------------------------------
        # Prefer temp_avg from derived features if available; fallback to temp_1 / temp_2
        effective_temp = derived.temp_avg if derived.temp_avg is not None else raw.temp_1
        if effective_temp is None:
            effective_temp = raw.temp_2

        if effective_temp is not None:
            if effective_temp >= self.temp_critical:
                violations.append(
                    RuleViolation(
                        rule_id="CRITICAL_TEMPERATURE",
                        severity=RuleSeverity.CRITICAL.value,
                        message=(
                            f"Critical overtemperature: {effective_temp:.2f}C >= "
                            f"{self.temp_critical:.2f}C safety threshold."
                        ),
                        evidence={
                            "temperature": round(effective_temp, 2),
                            "threshold": self.temp_critical,
                            "temp_1": raw.temp_1,
                            "temp_2": raw.temp_2,
                            "temp_avg": derived.temp_avg,
                        },
                        value=effective_temp,
                        threshold=self.temp_critical,
                    )
                )
            elif effective_temp >= self.temp_warning:
                violations.append(
                    RuleViolation(
                        rule_id="HIGH_TEMPERATURE",
                        severity=RuleSeverity.WARNING.value,
                        message=(
                            f"High operating temperature: {effective_temp:.2f}C >= "
                            f"{self.temp_warning:.2f}C warning threshold."
                        ),
                        evidence={
                            "temperature": round(effective_temp, 2),
                            "threshold": self.temp_warning,
                            "temp_1": raw.temp_1,
                            "temp_2": raw.temp_2,
                            "temp_avg": derived.temp_avg,
                        },
                        value=effective_temp,
                        threshold=self.temp_warning,
                    )
                )

        # ------------------------------------------------------------------
        # Rule 3 & 4: Electrical Rules (OVERCURRENT / HIGH_CURRENT)
        # ------------------------------------------------------------------
        if raw.current is not None:
            if raw.current >= self.current_critical:
                violations.append(
                    RuleViolation(
                        rule_id="OVERCURRENT",
                        severity=RuleSeverity.CRITICAL.value,
                        message=(
                            f"Overcurrent detected: {raw.current:.4f}A >= "
                            f"{self.current_critical:.4f}A critical threshold."
                        ),
                        evidence={
                            "current": raw.current,
                            "threshold": self.current_critical,
                            "voltage": raw.voltage,
                            "power": raw.power,
                        },
                        value=raw.current,
                        threshold=self.current_critical,
                    )
                )
            elif raw.current >= self.current_warning:
                violations.append(
                    RuleViolation(
                        rule_id="HIGH_CURRENT",
                        severity=RuleSeverity.WARNING.value,
                        message=(
                            f"High electrical load: {raw.current:.4f}A >= "
                            f"{self.current_warning:.4f}A warning threshold."
                        ),
                        evidence={
                            "current": raw.current,
                            "threshold": self.current_warning,
                            "voltage": raw.voltage,
                            "power": raw.power,
                        },
                        value=raw.current,
                        threshold=self.current_warning,
                    )
                )

        # ------------------------------------------------------------------
        # Rule 5, 6, 7, 8: Fan Actuator & RPM Consistency Rules
        # ------------------------------------------------------------------
        fan_state = raw.fan_int  # 1.0 = ON, 0.0 = OFF, None = missing
        rpm_val = raw.rpm

        if fan_state is not None and rpm_val is not None:
            if fan_state == 1.0:
                # --- FAN IS COMMANDED ON ---
                if rpm_val <= self.rpm_stall:
                    # Increment stateful stall confirmation counter
                    current_count = self._consecutive_low_rpm.get(device_id, 0) + 1
                    self._consecutive_low_rpm[device_id] = current_count

                    if current_count >= self.stall_confirmation_count:
                        # Confirmed stall after N consecutive readings
                        violations.append(
                            RuleViolation(
                                rule_id="FAN_STALL",
                                severity=RuleSeverity.CRITICAL.value,
                                message=(
                                    f"Fan is commanded ON but RPM is near zero: {rpm_val:.1f} RPM <= "
                                    f"{self.rpm_stall:.1f} RPM threshold (persisted for "
                                    f"{current_count} consecutive readings)."
                                ),
                                evidence={
                                    "fan": True,
                                    "rpm": rpm_val,
                                    "threshold": self.rpm_stall,
                                    "consecutive_readings": current_count,
                                    "confirmation_count_required": self.stall_confirmation_count,
                                    "current": raw.current,
                                    "power": raw.power,
                                },
                                value=rpm_val,
                                threshold=self.rpm_stall,
                            )
                        )
                else:
                    # RPM is above stall threshold: reset stall counter
                    self._consecutive_low_rpm[device_id] = 0

                    if rpm_val < self.rpm_low:
                        # Degraded fan speed
                        violations.append(
                            RuleViolation(
                                rule_id="LOW_RPM",
                                severity=RuleSeverity.WARNING.value,
                                message=(
                                    f"Fan commanded ON but running below normal speed: {rpm_val:.1f} RPM < "
                                    f"{self.rpm_low:.1f} RPM threshold."
                                ),
                                evidence={
                                    "fan": True,
                                    "rpm": rpm_val,
                                    "threshold": self.rpm_low,
                                },
                                value=rpm_val,
                                threshold=self.rpm_low,
                            )
                        )

            elif fan_state == 0.0:
                # --- FAN IS COMMANDED OFF ---
                # Clear low-rpm counter when fan is intentionally off
                self._consecutive_low_rpm[device_id] = 0

                if rpm_val > self.unexpected_rpm_fan_off:
                    violations.append(
                        RuleViolation(
                            rule_id="UNEXPECTED_RPM_WHEN_FAN_OFF",
                            severity=RuleSeverity.WARNING.value,
                            message=(
                                f"Fan commanded OFF but rotation detected: {rpm_val:.1f} RPM > "
                                f"{self.unexpected_rpm_fan_off:.1f} RPM threshold."
                            ),
                            evidence={
                                "fan": False,
                                "rpm": rpm_val,
                                "threshold": self.unexpected_rpm_fan_off,
                            },
                            value=rpm_val,
                            threshold=self.unexpected_rpm_fan_off,
                        )
                    )
                # Note: Rule 7 - fan == OFF and rpm <= unexpected_rpm_fan_off produces NO VIOLATION.

        # ------------------------------------------------------------------
        # Determine Overall Engine Status
        # ------------------------------------------------------------------
        severities = {v.severity for v in violations}
        if RuleSeverity.CRITICAL.value in severities:
            status = "critical"
        elif RuleSeverity.WARNING.value in severities:
            status = "warning"
        elif RuleSeverity.INFO.value in severities:
            status = "info"
        else:
            status = "ok"

        return RuleEvaluationResult(
            has_violations=len(violations) > 0,
            violations=violations,
            evaluated_rules=total_rules_evaluated,
            triggered_rules=len(violations),
            engine_status=status,
            device_id=device_id,
            timestamp=timestamp,
        )

    def evaluate_batch(
        self,
        feature_vectors: List[FeatureVector],
    ) -> List[RuleEvaluationResult]:
        """Evaluate a sequence of FeatureVectors in order."""
        return [self.evaluate(fv) for fv in feature_vectors]

    def reset(self, device_id: Optional[str] = None) -> None:
        """
        Reset stateful counters.

        Parameters
        ----------
        device_id : str, optional
            If provided, resets state only for that device; otherwise resets all.
        """
        if device_id is not None:
            self._consecutive_low_rpm.pop(device_id, None)
        else:
            self._consecutive_low_rpm.clear()

    def get_consecutive_stall_count(self, device_id: str = "unknown") -> int:
        """Return the current consecutive stall count for a device."""
        return self._consecutive_low_rpm.get(device_id, 0)

    # ----------------------------------------------------------------------
    # Internal Helpers
    # ----------------------------------------------------------------------

    def _check_physical_validity(self, raw) -> Dict[str, Any]:
        """Check for physically impossible or out-of-spec sensor readings."""
        invalid: Dict[str, Any] = {}

        if raw.temp_1 is not None and not (self.temp_min <= raw.temp_1 <= self.temp_max):
            invalid["temp_1"] = {
                "value": raw.temp_1,
                "valid_range": [self.temp_min, self.temp_max],
            }
        if raw.temp_2 is not None and not (self.temp_min <= raw.temp_2 <= self.temp_max):
            invalid["temp_2"] = {
                "value": raw.temp_2,
                "valid_range": [self.temp_min, self.temp_max],
            }
        if raw.voltage is not None and not (self.voltage_min <= raw.voltage <= self.voltage_max):
            invalid["voltage"] = {
                "value": raw.voltage,
                "valid_range": [self.voltage_min, self.voltage_max],
            }
        if raw.current is not None and not (self.current_min <= raw.current <= self.current_max):
            invalid["current"] = {
                "value": raw.current,
                "valid_range": [self.current_min, self.current_max],
            }
        if raw.rpm is not None and raw.rpm < self.rpm_min:
            invalid["rpm"] = {
                "value": raw.rpm,
                "valid_min": self.rpm_min,
            }
        if raw.power is not None and raw.power < self.power_min:
            invalid["power"] = {
                "value": raw.power,
                "valid_min": self.power_min,
            }

        return invalid
