"""
trust_engine.py
===============
Stage 4: TrustEngine orchestrator and operational decision synthesizer.

Combines multivariate evidence from:
    1. Stage 1: FeatureExtractor (FeatureVector -- raw, derived rates, rolling stats, data quality)
    2. Stage 2: AnomalyDetector (AnomalyResult -- Isolation Forest score)
    3. Stage 3: RuleEngine (RuleEvaluationResult -- deterministic physical/electrical/stall rules)
    4. Operational Context (fan intentional state, device isolation)

Produces a unified, deterministic, and explainable TrustResult containing:
    - trust_score (0.0 to 100.0)
    - state (NORMAL | CAUTION | DEGRADING | FAULT | OFFLINE)
    - decision (ALLOW | WARN | BLOCK)
    - structured traceable reasons
    - full evidence payload for UI and future downstream explanation layers

IMPORTANT ARCHITECTURAL CONSTRAINTS:
    - Strictly deterministic: No LLM is used for trust score, state, or decision.
    - Double-counting mitigation: Critical physical rules dominate and scale down statistical penalties.
    - Operational context aware: Intentional fan OFF with no rule violations does not penalize trust.
    - All thresholds and weights are centralized in config.py as engineering calibration parameters.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Union

from . import config
from .anomaly_detector import AnomalyDetector
from .feature_extractor import FeatureExtractor
from .models import (
    AnomalyResult,
    FeatureVector,
    MachineState,
    RuleEvaluationResult,
    TelemetryReading,
    TrustDecision,
    TrustReason,
    TrustResult,
)
from .rules import RuleEngine

logger = logging.getLogger(__name__)


class TrustEngine:
    """
    Top-level deterministic evaluator and pipeline orchestrator.

    Can be used either:
      1. As a full pipeline runner:
         result = engine.evaluate(reading: TelemetryReading)
      2. As a multi-stage evidence synthesizer:
         result = engine.evaluate(feature_vector, anomaly_result, rule_result)
    """

    def __init__(
        self,
        feature_extractor: Optional[FeatureExtractor] = None,
        anomaly_detector: Optional[AnomalyDetector] = None,
        rule_engine: Optional[RuleEngine] = None,
        auto_load_model: bool = True,
    ) -> None:
        self.feature_extractor = feature_extractor or FeatureExtractor()
        self.anomaly_detector = anomaly_detector or AnomalyDetector()
        self.rule_engine = rule_engine or RuleEngine()

        # Attempt to load pre-trained Isolation Forest if model exists
        if auto_load_model and not self.anomaly_detector.is_trained:
            try:
                self.anomaly_detector.load()
            except Exception as e:
                logger.warning(
                    "TrustEngine: Pre-trained Isolation Forest model not loaded: %s. "
                    "AnomalyDetector will report 'untrained' until trained or loaded.",
                    e,
                )

        # Per-device, per-signal temporal degradation persistence counters.
        # Structure: { device_id: { signal_name: consecutive_count } }
        # A signal must persist for TRUST_DEGRADATION_PERSISTENCE_COUNT consecutive
        # readings before it contributes to degradation_signals and DEGRADING state.
        self._degradation_persistence: Dict[str, Dict[str, int]] = {}

    def reset(self, device_id: Optional[str] = None) -> None:
        """
        Reset stateful history in feature extractor, rule engine, and
        degradation persistence counters.
        Ensures strict isolation across test datasets or device resets.
        """
        self.feature_extractor.reset()
        self.rule_engine.reset(device_id)
        if device_id is not None:
            self._degradation_persistence.pop(device_id, None)
        else:
            self._degradation_persistence.clear()

    def evaluate(
        self,
        reading_or_fv: Union[TelemetryReading, FeatureVector],
        anomaly_result: Optional[AnomalyResult] = None,
        rule_result: Optional[RuleEvaluationResult] = None,
    ) -> TrustResult:
        """
        Synthesize Stage 1, Stage 2, and Stage 3 evidence into a coherent TrustResult.

        Parameters
        ----------
        reading_or_fv : Union[TelemetryReading, FeatureVector]
            Incoming raw TelemetryReading or pre-extracted FeatureVector.
        anomaly_result : Optional[AnomalyResult]
            Stage 2 anomaly evaluation. If None and reading_or_fv is provided,
            computed automatically using self.anomaly_detector.
        rule_result : Optional[RuleEvaluationResult]
            Stage 3 rule evaluation. If None and reading_or_fv is provided,
            computed automatically using self.rule_engine.

        Returns
        -------
        TrustResult
            Comprehensive structured evaluation result.
        """
        # --- Stage 1: Feature Extraction ---
        if isinstance(reading_or_fv, TelemetryReading):
            reading = reading_or_fv
            fv = self.feature_extractor.process(reading)
        elif isinstance(reading_or_fv, FeatureVector):
            fv = reading_or_fv
        else:
            raise TypeError(
                f"Expected TelemetryReading or FeatureVector, got {type(reading_or_fv)}"
            )

        device_id = fv.metadata.device_id
        timestamp = fv.metadata.timestamp

        # --- Stage 2: Anomaly Detection ---
        if anomaly_result is None:
            anomaly_result = self.anomaly_detector.predict(fv, strict=False)

        # --- Stage 3: Rule Evaluation ---
        if rule_result is None:
            rule_result = self.rule_engine.evaluate(fv)

        # --- Stage 4: Evidence Synthesis & Scoring ---
        reasons: List[str] = []
        structured_reasons: List[TrustReason] = []
        score_breakdown: Dict[str, float] = {
            "base_score": float(config.TRUST_BASE_SCORE),
            "anomaly_penalty": 0.0,
            "warning_penalty": 0.0,
            "critical_penalty": 0.0,
            "degradation_penalty": 0.0,
        }

        # 1. Operational Context (Fan OFF check)
        # In fan_off condition (fan commanded OFF and RPM ~ 0), Stage 2 flags anomaly
        # because the model learned healthy spinning operation. But if Stage 3 has zero
        # rule violations and fan is OFF, this is expected machine state.
        is_fan_off_context = (
            fv.raw_features.fan_int == 0.0
            and not rule_result.has_violations
        )

        # 2. Rule Penalties (Stage 3)
        warning_count = sum(1 for v in rule_result.violations if v.severity == "WARNING")
        critical_count = sum(1 for v in rule_result.violations if v.severity == "CRITICAL")

        uncapped_warning_penalty = warning_count * config.TRUST_WARNING_PENALTY
        warning_penalty = min(uncapped_warning_penalty, config.TRUST_MAX_WARNING_PENALTY)
        critical_penalty = critical_count * config.TRUST_CRITICAL_PENALTY

        score_breakdown["warning_penalty"] = float(warning_penalty)
        score_breakdown["critical_penalty"] = float(critical_penalty)

        for v in rule_result.violations:
            reasons.append(f"[{v.severity}] {v.message}")
            structured_reasons.append(
                TrustReason(
                    reason_id=v.rule_id,
                    source="rule_engine",
                    message=v.message,
                    severity=v.severity,
                    evidence=v.evidence,
                )
            )

        # 3. Anomaly Penalties (Stage 2) & Double-Counting Mitigation
        anomaly_penalty = 0.0
        anomaly_suppressed = False

        if anomaly_result.is_anomaly:
            if is_fan_off_context:
                # Operational context suppression:
                # Fan is commanded OFF and operating within nominal parameters.
                anomaly_suppressed = True
                reasons.append(
                    "Statistical anomaly detected by Isolation Forest, but suppressed "
                    "due to expected non-running fan context."
                )
                structured_reasons.append(
                    TrustReason(
                        reason_id="ANOMALY_SUPPRESSED_FAN_OFF",
                        source="context",
                        message="Isolation Forest anomaly suppressed: fan is intentionally OFF.",
                        severity="INFO",
                        evidence={
                            "fan_int": fv.raw_features.fan_int,
                            "anomaly_score": anomaly_result.anomaly_score,
                        },
                    )
                )
            else:
                base_anom = float(config.TRUST_ANOMALY_BASE_PENALTY)
                score_val = anomaly_result.anomaly_score
                if score_val is not None and score_val < config.TRUST_ANOMALY_SEVERE_THRESHOLD:
                    base_anom += float(config.TRUST_ANOMALY_SEVERE_BONUS)

                base_anom = min(base_anom, float(config.TRUST_MAX_ANOMALY_PENALTY))

                # Double-counting mitigation:
                # When critical physical rules (e.g. FAN_STALL, OVERCURRENT) have already fired,
                # the underlying event is physically accounted for. We scale down the anomaly
                # penalty to prevent double penalizing the same physical failure.
                if critical_count > 0:
                    base_anom *= float(config.TRUST_DOUBLE_COUNT_REDUCTION)

                anomaly_penalty = base_anom
                anom_score_str = f"{score_val:.4f}" if score_val is not None else "N/A"
                reasons.append(
                    f"Multivariate anomaly detected by Isolation Forest (score: {anom_score_str})"
                )
                structured_reasons.append(
                    TrustReason(
                        reason_id="ISOLATION_FOREST_ANOMALY",
                        source="anomaly_detector",
                        message=f"Statistical anomaly detected (anomaly score: {anom_score_str}).",
                        severity="WARNING" if critical_count == 0 else "INFO",
                        evidence={
                            "anomaly_score": score_val,
                            "raw_prediction": anomaly_result.raw_prediction,
                            "double_count_reduced": critical_count > 0,
                        },
                    )
                )

        score_breakdown["anomaly_penalty"] = float(anomaly_penalty)

        # 4. Temporal / Degradation Evidence (Stage 1 derived rates)
        #    with STATEFUL PER-SIGNAL PERSISTENCE tracking.
        #
        #    A temporal signal (e.g. TEMP_RISING) must exceed its threshold for
        #    TRUST_DEGRADATION_PERSISTENCE_COUNT consecutive readings before it
        #    is allowed to contribute to `degradation_signals` (and thus to
        #    the DEGRADING state / degradation penalty).  This prevents single-
        #    reading derivative jitter from producing false DEGRADING on healthy
        #    baseline data.
        degradation_signals: List[Dict[str, Any]] = []
        derived = fv.derived_features

        # Ensure persistence dict exists for this device
        if device_id not in self._degradation_persistence:
            self._degradation_persistence[device_id] = {}
        dev_persistence = self._degradation_persistence[device_id]

        persistence_threshold = config.TRUST_DEGRADATION_PERSISTENCE_COUNT

        # Define the 4 temporal signal checks: (signal_name, rate_value, threshold, comparator, message_fmt)
        _signal_checks: List[Dict[str, Any]] = []

        # In fan_off context with nominal operation, small ambient thermal shifts are expected
        if not is_fan_off_context:
            if derived.temp_rate is not None:
                _signal_checks.append({
                    "signal": "TEMP_RISING",
                    "feature": "temp_rate",
                    "value": derived.temp_rate,
                    "threshold": config.TRUST_TEMP_RATE_THRESHOLD,
                    "active": derived.temp_rate > config.TRUST_TEMP_RATE_THRESHOLD,
                    "message": f"Temperature rising rapidly: +{derived.temp_rate:.4f} C/s",
                })
            if derived.rpm_rate is not None:
                _signal_checks.append({
                    "signal": "RPM_FALLING",
                    "feature": "rpm_rate",
                    "value": derived.rpm_rate,
                    "threshold": config.TRUST_RPM_RATE_THRESHOLD,
                    "active": derived.rpm_rate < config.TRUST_RPM_RATE_THRESHOLD,
                    "message": f"Fan speed dropping: {derived.rpm_rate:.2f} RPM/s",
                })
            if derived.current_rate is not None:
                _signal_checks.append({
                    "signal": "CURRENT_RISING",
                    "feature": "current_rate",
                    "value": derived.current_rate,
                    "threshold": config.TRUST_CURRENT_RATE_THRESHOLD,
                    "active": derived.current_rate > config.TRUST_CURRENT_RATE_THRESHOLD,
                    "message": f"Current consumption rising: +{derived.current_rate:.5f} A/s",
                })
            if derived.vibration_rate is not None:
                _signal_checks.append({
                    "signal": "VIBRATION_RISING",
                    "feature": "vibration_rate",
                    "value": derived.vibration_rate,
                    "threshold": config.TRUST_VIBRATION_RATE_THRESHOLD,
                    "active": derived.vibration_rate > config.TRUST_VIBRATION_RATE_THRESHOLD,
                    "message": f"Vibration increasing: +{derived.vibration_rate:.4f} m/s^2/s",
                })

        # Update persistence counters and collect signals that have persisted
        checked_signals = set()
        for check in _signal_checks:
            sig_name = check["signal"]
            checked_signals.add(sig_name)
            if check["active"]:
                dev_persistence[sig_name] = dev_persistence.get(sig_name, 0) + 1
            else:
                dev_persistence[sig_name] = 0

            if dev_persistence.get(sig_name, 0) >= persistence_threshold:
                degradation_signals.append({
                    "signal": sig_name,
                    "feature": check["feature"],
                    "value": check["value"],
                    "threshold": check["threshold"],
                    "message": check["message"],
                    "persistence_count": dev_persistence[sig_name],
                })

        # Reset counters for signals not evaluated this reading
        # (e.g. rate was None, or fan_off_context suppressed checks)
        for sig_name in list(dev_persistence.keys()):
            if sig_name not in checked_signals:
                dev_persistence[sig_name] = 0

        degradation_penalty = min(
            len(degradation_signals) * config.TRUST_DEGRADATION_PENALTY,
            config.TRUST_MAX_DEGRADATION_PENALTY,
        )
        score_breakdown["degradation_penalty"] = float(degradation_penalty)

        for sig in degradation_signals:
            reasons.append(sig["message"])
            structured_reasons.append(
                TrustReason(
                    reason_id=sig["signal"],
                    source="temporal",
                    message=sig["message"],
                    severity="WARNING",
                    evidence=sig,
                )
            )

        # 5. Final Score Calculation & Bounding
        total_deductions = (
            anomaly_penalty
            + warning_penalty
            + critical_penalty
            + degradation_penalty
        )
        raw_score = config.TRUST_BASE_SCORE - total_deductions
        trust_score = max(0.0, min(100.0, float(raw_score)))

        # 6. Machine State Determination
        # Precedence: OFFLINE -> FAULT -> DEGRADING -> CAUTION -> NORMAL
        effective_anomaly = anomaly_result.is_anomaly and not anomaly_suppressed

        if critical_count > 0 or trust_score <= config.TRUST_FAULT_THRESHOLD:
            state = MachineState.FAULT
        elif len(degradation_signals) > 0 and (warning_count > 0 or effective_anomaly or trust_score <= config.TRUST_CAUTION_THRESHOLD):
            state = MachineState.DEGRADING
        elif warning_count > 0 or effective_anomaly or trust_score <= config.TRUST_CAUTION_THRESHOLD:
            state = MachineState.CAUTION
        else:
            state = MachineState.NORMAL

        # 7. Operational Decision Determination & Consistency Enforcement
        if state == MachineState.FAULT:
            decision = TrustDecision.BLOCK
        elif state in (MachineState.DEGRADING, MachineState.CAUTION):
            decision = TrustDecision.WARN
        elif state == MachineState.OFFLINE:
            decision = TrustDecision.BLOCK
        else:
            decision = TrustDecision.ALLOW

        # Strict Consistency Enforcement:
        # Prevent any contradictory states (e.g. low trust score or critical rule resulting in ALLOW)
        if trust_score <= config.TRUST_WARN_THRESHOLD:
            decision = TrustDecision.BLOCK
            state = MachineState.FAULT
        elif trust_score <= config.TRUST_ALLOW_THRESHOLD and decision == TrustDecision.ALLOW:
            decision = TrustDecision.WARN
            if state == MachineState.NORMAL:
                state = MachineState.CAUTION

        if critical_count > 0:
            state = MachineState.FAULT
            decision = TrustDecision.BLOCK

        # 8. Data Quality Confidence Metric
        dq = fv.data_quality
        confidence = 1.0
        if dq.missing_fields:
            confidence -= 0.1 * len(dq.missing_fields)
        if not dq.rate_features_available:
            confidence -= 0.05
        if not dq.rolling_features_available:
            confidence -= 0.05
        confidence = max(0.0, min(1.0, confidence))

        # Summaries
        anomaly_summary = {
            "is_anomaly": bool(anomaly_result.is_anomaly),
            "raw_prediction": int(anomaly_result.raw_prediction),
            "anomaly_score": anomaly_result.anomaly_score,
            "penalty": float(anomaly_penalty),
            "suppressed": bool(anomaly_suppressed),
            "model_status": anomaly_result.model_status,
        }

        rule_summary = {
            "total_violations": len(rule_result.violations),
            "critical_count": critical_count,
            "warning_count": warning_count,
            "engine_status": rule_result.engine_status,
        }

        temporal_summary = {
            "signals_detected": len(degradation_signals),
            "signals": [s["signal"] for s in degradation_signals],
            "penalty": float(degradation_penalty),
        }

        combined_evidence = {
            "anomaly": anomaly_summary,
            "rules": [v.to_dict() for v in rule_result.violations],
            "temporal": degradation_signals,
            "key_sensors": {
                "temp_1": fv.raw_features.temp_1,
                "temp_2": fv.raw_features.temp_2,
                "rpm": fv.raw_features.rpm,
                "voltage": fv.raw_features.voltage,
                "current": fv.raw_features.current,
                "power": fv.raw_features.power,
                "fan_int": fv.raw_features.fan_int,
                "vibration": fv.raw_features.vibration,
            },
        }

        return TrustResult(
            trust_score=round(trust_score, 2),
            state=state,
            decision=decision,
            reasons=reasons,
            structured_reasons=structured_reasons,
            anomaly_summary=anomaly_summary,
            rule_summary=rule_summary,
            temporal_summary=temporal_summary,
            score_breakdown=score_breakdown,
            evidence=combined_evidence,
            device_id=device_id,
            timestamp=timestamp,
            confidence=round(confidence, 2),
            feature_vector=fv,
        )

    def evaluate_reading(self, reading: TelemetryReading) -> TrustResult:
        """Convenience method to evaluate a single TelemetryReading."""
        return self.evaluate(reading)

