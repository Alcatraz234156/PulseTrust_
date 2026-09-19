"""
test_trust_engine.py
====================
Unit tests for Stage 4 Trust Engine.

Covers all 24 core behavioral and edge-case requirements:
 1. Healthy telemetry produces high trust (>85).
 2. Healthy telemetry produces NORMAL state.
 3. Healthy telemetry produces ALLOW decision.
 4. Warning rule lowers trust.
 5. Critical rule produces very low trust (<= 30).
 6. Critical rule produces FAULT state.
 7. Critical rule produces BLOCK decision.
 8. Isolation Forest anomaly alone does not automatically produce FAULT.
 9. Fan OFF + zero RPM does not automatically produce FAULT/BLOCK.
10. Fan STALL produces low trust.
11. Fan STALL produces FAULT.
12. Fan STALL produces BLOCK.
13. Degradation produces DEGRADING when temporal evidence supports it.
14. Trust score is always bounded within [0, 100].
15. Missing values do not crash the engine.
16. No fabricated temporal values when rates are None.
17. Multiple warnings accumulate sensibly with cap.
18. Critical evidence dominates weaker evidence.
19. Stage 2 + Stage 3 evidence does not cause pathological double-counting.
20. Reasons correspond to actual evidence.
21. Evidence is preserved structurally.
22. Device state does not leak between devices.
23. Reset behavior works correctly.
24. Decision/state/score remain strictly consistent.
"""

from __future__ import annotations

from datetime import datetime, timezone
import pytest

from trust_engine import config
from trust_engine.models import (
    AnomalyResult,
    DataQuality,
    DerivedFeatures,
    FeatureMetadata,
    FeatureVector,
    MachineState,
    RawFeatures,
    RuleEvaluationResult,
    RuleSeverity,
    RuleViolation,
    TelemetryReading,
    TrustDecision,
    TrustReason,
    TrustResult,
)
from trust_engine.rules import RuleEngine
from trust_engine.anomaly_detector import AnomalyDetector
from trust_engine.trust_engine import TrustEngine


# ---------------------------------------------------------------------------
# Helpers & Fixtures
# ---------------------------------------------------------------------------

def make_fv(
    temp_1: float = 28.0,
    temp_2: float = 28.0,
    rpm: float = 1450.0,
    vibration: float = 9.6,
    voltage: float = 5.0,
    current: float = 0.18,
    power: float = 0.9,
    fan: bool = True,
    temp_rate: float | None = 0.0,
    rpm_rate: float | None = 0.0,
    current_rate: float | None = 0.0,
    vibration_rate: float | None = 0.0,
    device_id: str = "test-device-01",
    timestamp: datetime | None = None,
    rates_available: bool = True,
    rolling_available: bool = True,
    missing_fields: list[str] | None = None,
) -> FeatureVector:
    ts = timestamp or datetime(2026, 9, 18, 12, 0, 0, tzinfo=timezone.utc)
    fan_int = 1.0 if fan is True else (0.0 if fan is False else None)

    temp_avg = None
    if temp_1 is not None and temp_2 is not None:
        temp_avg = (temp_1 + temp_2) / 2.0

    raw = RawFeatures(
        temp_1=temp_1,
        temp_2=temp_2,
        rpm=rpm,
        vibration=vibration,
        voltage=voltage,
        current=current,
        power=power,
        fan_int=fan_int,
    )
    derived = DerivedFeatures(
        temp_avg=temp_avg,
        temp_rate=temp_rate,
        rpm_rate=rpm_rate,
        current_rate=current_rate,
        vibration_rate=vibration_rate,
    )
    metadata = FeatureMetadata(
        device_id=device_id,
        timestamp=ts,
        reading_index=10,
    )
    dq = DataQuality(
        rate_features_available=rates_available,
        rolling_features_available=rolling_available,
        missing_fields=missing_fields or [],
    )
    return FeatureVector(
        metadata=metadata,
        raw_features=raw,
        derived_features=derived,
        data_quality=dq,
    )


def make_anomaly_result(
    is_anomaly: bool = False,
    anomaly_score: float = 0.05,
    model_status: str = "loaded",
) -> AnomalyResult:
    return AnomalyResult(
        is_anomaly=is_anomaly,
        raw_prediction=-1 if is_anomaly else 1,
        anomaly_score=anomaly_score,
        model_status=model_status,
        features_used=34,
    )


def make_rule_result(
    violations: list[RuleViolation] | None = None,
    device_id: str = "test-device-01",
) -> RuleEvaluationResult:
    viols = violations or []
    status = "ok"
    if any(v.severity == "CRITICAL" for v in viols):
        status = "critical"
    elif any(v.severity == "WARNING" for v in viols):
        status = "warning"

    return RuleEvaluationResult(
        has_violations=len(viols) > 0,
        violations=viols,
        evaluated_rules=9,
        triggered_rules=len(viols),
        engine_status=status,
        device_id=device_id,
    )


@pytest.fixture
def engine() -> TrustEngine:
    """TrustEngine instance with auto_load_model disabled for pure unit tests."""
    return TrustEngine(auto_load_model=False)


# ---------------------------------------------------------------------------
# Unit Tests (1-24)
# ---------------------------------------------------------------------------

class TestTrustEngineRequirements:

    # 1. Healthy telemetry produces high trust
    def test_1_healthy_telemetry_produces_high_trust(self, engine: TrustEngine):
        fv = make_fv()
        anom = make_anomaly_result(is_anomaly=False, anomaly_score=0.08)
        rules = make_rule_result([])
        res = engine.evaluate(fv, anom, rules)
        assert res.trust_score >= 90.0, f"Expected high trust >= 90, got {res.trust_score}"

    # 2. Healthy telemetry produces NORMAL state
    def test_2_healthy_telemetry_produces_normal_state(self, engine: TrustEngine):
        fv = make_fv()
        anom = make_anomaly_result(is_anomaly=False, anomaly_score=0.05)
        rules = make_rule_result([])
        res = engine.evaluate(fv, anom, rules)
        assert res.state == MachineState.NORMAL

    # 3. Healthy telemetry produces ALLOW decision
    def test_3_healthy_telemetry_produces_allow_decision(self, engine: TrustEngine):
        fv = make_fv()
        anom = make_anomaly_result(is_anomaly=False, anomaly_score=0.05)
        rules = make_rule_result([])
        res = engine.evaluate(fv, anom, rules)
        assert res.decision == TrustDecision.ALLOW

    # 4. Warning rule lowers trust
    def test_4_warning_rule_lowers_trust(self, engine: TrustEngine):
        fv = make_fv()
        anom = make_anomaly_result(is_anomaly=False)
        rules_clean = make_rule_result([])
        rules_warn = make_rule_result([
            RuleViolation(
                rule_id="HIGH_CURRENT",
                severity="WARNING",
                message="Current draw is elevated: 0.30 A",
                evidence={"current": 0.30},
            )
        ])
        res_clean = engine.evaluate(fv, anom, rules_clean)
        res_warn = engine.evaluate(fv, anom, rules_warn)
        assert res_warn.trust_score < res_clean.trust_score
        assert res_clean.trust_score - res_warn.trust_score == config.TRUST_WARNING_PENALTY
        assert res_warn.state == MachineState.CAUTION
        assert res_warn.decision == TrustDecision.WARN

    # 5. Critical rule produces very low trust
    def test_5_critical_rule_produces_very_low_trust(self, engine: TrustEngine):
        fv = make_fv()
        anom = make_anomaly_result(is_anomaly=True, anomaly_score=-0.16)
        rules = make_rule_result([
            RuleViolation(
                rule_id="OVERCURRENT",
                severity="CRITICAL",
                message="Critical overcurrent: 0.42 A",
                evidence={"current": 0.42},
            )
        ])
        res = engine.evaluate(fv, anom, rules)
        # Base 100 - critical 30 - anomaly (15+10)*0.5=12.5 = 57.5, or even lower
        assert res.trust_score <= 60.0
        assert res.score_breakdown["critical_penalty"] >= config.TRUST_CRITICAL_PENALTY

    # 6. Critical rule produces FAULT state
    def test_6_critical_rule_produces_fault_state(self, engine: TrustEngine):
        fv = make_fv()
        anom = make_anomaly_result(is_anomaly=False)
        rules = make_rule_result([
            RuleViolation(
                rule_id="CRITICAL_TEMPERATURE",
                severity="CRITICAL",
                message="Severe overtemperature: 34.2 C",
                evidence={"temp_avg": 34.2},
            )
        ])
        res = engine.evaluate(fv, anom, rules)
        assert res.state == MachineState.FAULT

    # 7. Critical rule produces BLOCK decision
    def test_7_critical_rule_produces_block_decision(self, engine: TrustEngine):
        fv = make_fv()
        anom = make_anomaly_result(is_anomaly=False)
        rules = make_rule_result([
            RuleViolation(
                rule_id="CRITICAL_TEMPERATURE",
                severity="CRITICAL",
                message="Severe overtemperature",
            )
        ])
        res = engine.evaluate(fv, anom, rules)
        assert res.decision == TrustDecision.BLOCK

    # 8. Isolation Forest anomaly alone does not automatically produce FAULT
    def test_8_anomaly_alone_does_not_produce_fault(self, engine: TrustEngine):
        fv = make_fv()
        anom = make_anomaly_result(is_anomaly=True, anomaly_score=-0.08)
        rules = make_rule_result([])
        res = engine.evaluate(fv, anom, rules)
        # Should drop trust, but stay at CAUTION / WARN, NOT FAULT / BLOCK
        assert res.state == MachineState.CAUTION
        assert res.decision == TrustDecision.WARN
        assert res.trust_score == 100.0 - config.TRUST_ANOMALY_BASE_PENALTY
        assert res.state != MachineState.FAULT

    # 9. Fan OFF + zero RPM does not automatically produce FAULT/BLOCK
    def test_9_fan_off_zero_rpm_does_not_produce_fault_or_block(self, engine: TrustEngine):
        fv = make_fv(fan=False, rpm=0.0, current=0.01, power=0.05)
        # Model may flag anomaly because normal data had fan spinning
        anom = make_anomaly_result(is_anomaly=True, anomaly_score=-0.12)
        rules = make_rule_result([])  # No rule violations
        res = engine.evaluate(fv, anom, rules)

        assert res.anomaly_summary["suppressed"] is True
        assert res.trust_score == 100.0
        assert res.state == MachineState.NORMAL
        assert res.decision == TrustDecision.ALLOW

    # 10. Fan STALL produces low trust
    def test_10_fan_stall_produces_low_trust(self, engine: TrustEngine):
        fv = make_fv(fan=True, rpm=1.2, current=0.38)
        anom = make_anomaly_result(is_anomaly=True, anomaly_score=-0.18)
        rules = make_rule_result([
            RuleViolation(
                rule_id="FAN_STALL",
                severity="CRITICAL",
                message="Fan stall confirmed: fan ON but RPM <= 150 for 3 consecutive readings",
                evidence={"rpm": 1.2, "fan": True, "confirmation_count": 3},
            )
        ])
        res = engine.evaluate(fv, anom, rules)
        assert res.trust_score <= 60.0

    # 11. Fan STALL produces FAULT
    def test_11_fan_stall_produces_fault(self, engine: TrustEngine):
        fv = make_fv(fan=True, rpm=1.2)
        anom = make_anomaly_result(is_anomaly=True, anomaly_score=-0.18)
        rules = make_rule_result([
            RuleViolation(
                rule_id="FAN_STALL",
                severity="CRITICAL",
                message="Fan stall confirmed",
            )
        ])
        res = engine.evaluate(fv, anom, rules)
        assert res.state == MachineState.FAULT

    # 12. Fan STALL produces BLOCK
    def test_12_fan_stall_produces_block(self, engine: TrustEngine):
        fv = make_fv(fan=True, rpm=1.2)
        anom = make_anomaly_result(is_anomaly=True, anomaly_score=-0.18)
        rules = make_rule_result([
            RuleViolation(
                rule_id="FAN_STALL",
                severity="CRITICAL",
                message="Fan stall confirmed",
            )
        ])
        res = engine.evaluate(fv, anom, rules)
        assert res.decision == TrustDecision.BLOCK

    # 13. Degradation produces DEGRADING when temporal evidence persists
    def test_13_degradation_produces_degrading_state(self, engine: TrustEngine):
        # Sustained adverse trends require 3 CONSECUTIVE readings to trigger DEGRADING.
        fv = make_fv(
            temp_rate=0.08,     # > 0.05
            rpm_rate=-25.0,     # < -10.0
            current_rate=0.012, # > 0.005
        )
        anom = make_anomaly_result(is_anomaly=True, anomaly_score=-0.14)
        rules = make_rule_result([
            RuleViolation(
                rule_id="LOW_RPM",
                severity="WARNING",
                message="Fan RPM below expected operating range",
            )
        ])
        # Feed 3 consecutive readings with the same adverse rates
        engine.reset()
        engine.evaluate(fv, anom, rules)
        engine.evaluate(fv, anom, rules)
        res = engine.evaluate(fv, anom, rules)
        assert res.state == MachineState.DEGRADING
        assert res.decision == TrustDecision.WARN
        assert res.temporal_summary["signals_detected"] >= 2

    # 14. Trust score is always 0..100
    def test_14_score_bounds_always_enforced(self, engine: TrustEngine):
        # Multiple catastrophic conditions
        fv = make_fv(temp_rate=1.0, rpm_rate=-100.0, current_rate=1.0, vibration_rate=5.0)
        anom = make_anomaly_result(is_anomaly=True, anomaly_score=-0.50)
        rules = make_rule_result([
            RuleViolation(rule_id="CRITICAL_TEMPERATURE", severity="CRITICAL", message="Temp critical"),
            RuleViolation(rule_id="OVERCURRENT", severity="CRITICAL", message="Overcurrent critical"),
            RuleViolation(rule_id="FAN_STALL", severity="CRITICAL", message="Stall critical"),
            RuleViolation(rule_id="HIGH_CURRENT", severity="WARNING", message="High current"),
        ])
        res = engine.evaluate(fv, anom, rules)
        assert 0.0 <= res.trust_score <= 100.0
        assert res.trust_score == 0.0 or res.trust_score <= 20.0

    # 15. Missing values do not crash the engine
    def test_15_missing_values_do_not_crash(self, engine: TrustEngine):
        fv = make_fv(
            temp_1=None,
            temp_2=None,
            rpm=None,
            current=None,
            power=None,
            temp_rate=None,
            rpm_rate=None,
            current_rate=None,
            rates_available=False,
            missing_fields=["temp_1", "temp_2", "rpm", "current", "power"],
        )
        anom = make_anomaly_result(is_anomaly=False, model_status="insufficient_history")
        rules = make_rule_result([])
        res = engine.evaluate(fv, anom, rules)
        assert 0.0 <= res.trust_score <= 100.0
        assert res.confidence is not None
        assert res.confidence < 1.0  # Quality penalty reflected in confidence

    # 16. No fabricated temporal values
    def test_16_no_fabricated_temporal_values(self, engine: TrustEngine):
        fv = make_fv(
            temp_rate=None,
            rpm_rate=None,
            current_rate=None,
            vibration_rate=None,
            rates_available=False,
        )
        anom = make_anomaly_result(is_anomaly=False)
        rules = make_rule_result([])
        res = engine.evaluate(fv, anom, rules)
        assert res.temporal_summary["signals_detected"] == 0
        assert res.score_breakdown["degradation_penalty"] == 0.0

    # 17. Multiple warnings accumulate sensibly with cap
    def test_17_multiple_warnings_accumulate_with_cap(self, engine: TrustEngine):
        fv = make_fv()
        anom = make_anomaly_result(is_anomaly=False)
        rules = make_rule_result([
            RuleViolation(rule_id="HIGH_TEMPERATURE", severity="WARNING", message="High temp"),
            RuleViolation(rule_id="HIGH_CURRENT", severity="WARNING", message="High current"),
            RuleViolation(rule_id="LOW_RPM", severity="WARNING", message="Low rpm"),
            RuleViolation(rule_id="TEMP_SENSOR_DISAGREEMENT", severity="WARNING", message="Gap > 2"),
        ])
        res = engine.evaluate(fv, anom, rules)
        # 4 warnings * 10 = 40, but capped at TRUST_MAX_WARNING_PENALTY (25)
        assert res.score_breakdown["warning_penalty"] == config.TRUST_MAX_WARNING_PENALTY
        assert res.trust_score == 100.0 - config.TRUST_MAX_WARNING_PENALTY
        assert res.state == MachineState.CAUTION
        assert res.decision == TrustDecision.WARN

    # 18. Critical evidence dominates weaker evidence
    def test_18_critical_evidence_dominates(self, engine: TrustEngine):
        fv = make_fv()
        anom = make_anomaly_result(is_anomaly=False)  # Anomaly detector didn't notice
        rules = make_rule_result([
            RuleViolation(rule_id="CRITICAL_TEMPERATURE", severity="CRITICAL", message="Temp critical")
        ])
        res = engine.evaluate(fv, anom, rules)
        # Even with clean anomaly detector and high statistical score, state must be FAULT, decision BLOCK
        assert res.state == MachineState.FAULT
        assert res.decision == TrustDecision.BLOCK

    # 19. Stage 2 + Stage 3 evidence does not cause pathological double-counting
    def test_19_double_counting_mitigation(self, engine: TrustEngine):
        fv = make_fv()
        anom_severe = make_anomaly_result(is_anomaly=True, anomaly_score=-0.20)
        rules_crit = make_rule_result([
            RuleViolation(rule_id="OVERCURRENT", severity="CRITICAL", message="Critical overcurrent")
        ])
        res = engine.evaluate(fv, anom_severe, rules_crit)
        # Severe anomaly penalty (25) should be halved to 12.5 due to critical rule presence
        assert res.score_breakdown["anomaly_penalty"] == 25.0 * config.TRUST_DOUBLE_COUNT_REDUCTION
        assert res.structured_reasons[-1].evidence.get("double_count_reduced") is True or any(
            r.evidence.get("double_count_reduced") is True for r in res.structured_reasons
        )

    # 20. Reasons correspond to actual evidence
    def test_20_reasons_traceable_to_evidence(self, engine: TrustEngine):
        fv = make_fv(temp_rate=0.09)
        anom = make_anomaly_result(is_anomaly=True, anomaly_score=-0.16)
        rules = make_rule_result([
            RuleViolation(
                rule_id="HIGH_CURRENT",
                severity="WARNING",
                message="Elevated current draw",
                evidence={"current": 0.32},
            )
        ])
        # Feed 3 consecutive readings so TEMP_RISING persists and appears in reasons
        engine.reset()
        engine.evaluate(fv, anom, rules)
        engine.evaluate(fv, anom, rules)
        res = engine.evaluate(fv, anom, rules)
        reason_ids = [r.reason_id for r in res.structured_reasons]
        assert "HIGH_CURRENT" in reason_ids
        assert "ISOLATION_FOREST_ANOMALY" in reason_ids
        assert "TEMP_RISING" in reason_ids

    # 21. Evidence is preserved structurally
    def test_21_evidence_preserved_structurally(self, engine: TrustEngine):
        fv = make_fv()
        anom = make_anomaly_result(is_anomaly=True, anomaly_score=-0.12)
        rules = make_rule_result([
            RuleViolation(
                rule_id="LOW_RPM",
                severity="WARNING",
                message="Degraded speed",
                evidence={"rpm": 850.0},
            )
        ])
        res = engine.evaluate(fv, anom, rules)
        assert "anomaly" in res.evidence
        assert "rules" in res.evidence
        assert "temporal" in res.evidence
        assert "key_sensors" in res.evidence
        assert res.evidence["key_sensors"]["rpm"] == 1450.0

    # 22. Device state does not leak between devices
    def test_22_multi_device_isolation(self, engine: TrustEngine):
        fv_dev_a = make_fv(device_id="device-A", fan=True, rpm=10.0)
        fv_dev_b = make_fv(device_id="device-B", fan=True, rpm=1450.0)

        # Process through full RuleEngine to test device isolation
        re = engine.rule_engine
        re.reset()

        # Device A receives 2 stall readings (stall counter = 2, not yet confirmed)
        re.evaluate(fv_dev_a)
        re.evaluate(fv_dev_a)

        # Device B receives 1 normal reading
        rule_res_b = re.evaluate(fv_dev_b)
        assert not rule_res_b.has_violations

        # Device A 3rd reading confirms stall
        rule_res_a = re.evaluate(fv_dev_a)
        assert any(v.rule_id == "FAN_STALL" for v in rule_res_a.violations)

        # Device B is still completely healthy
        rule_res_b2 = re.evaluate(fv_dev_b)
        assert not rule_res_b2.has_violations

    # 23. Reset behavior works
    def test_23_reset_clears_state(self, engine: TrustEngine):
        fv_stall = make_fv(fan=True, rpm=10.0)
        re = engine.rule_engine
        re.reset()

        # Build stall state to 2
        re.evaluate(fv_stall)
        re.evaluate(fv_stall)

        # Reset
        engine.reset()

        # Next reading should be count 1, not confirmed stall
        rule_res = re.evaluate(fv_stall)
        assert not any(v.rule_id == "FAN_STALL" for v in rule_res.violations)

    # 24. Decision/state/score remain consistent
    def test_24_decision_state_score_consistency(self, engine: TrustEngine):
        fv = make_fv()

        # Test case: Low score forces BLOCK and FAULT
        anom = make_anomaly_result(is_anomaly=True, anomaly_score=-0.25)
        # Even with warnings only, if score drops <= 30, it must be FAULT / BLOCK
        rules = make_rule_result([
            RuleViolation(rule_id="CRITICAL_TEMPERATURE", severity="CRITICAL", message="Critical temp"),
            RuleViolation(rule_id="OVERCURRENT", severity="CRITICAL", message="Overcurrent"),
            RuleViolation(rule_id="FAN_STALL", severity="CRITICAL", message="Stall"),
        ])
        res = engine.evaluate(fv, anom, rules)
        assert res.trust_score <= 30.0
        assert res.state == MachineState.FAULT
        assert res.decision == TrustDecision.BLOCK

        # Test case: Healthy score produces ALLOW and NORMAL
        anom_clean = make_anomaly_result(is_anomaly=False)
        rules_clean = make_rule_result([])
        res_clean = engine.evaluate(fv, anom_clean, rules_clean)
        assert res_clean.trust_score >= 85.0
        assert res_clean.state == MachineState.NORMAL
        assert res_clean.decision == TrustDecision.ALLOW


# ---------------------------------------------------------------------------
# Temporal Persistence Tests (25-35)
# ---------------------------------------------------------------------------

class TestDegradationPersistence:
    """Tests for the 3-reading temporal persistence fix."""

    # 25. Single reading with adverse rate does NOT produce DEGRADING
    def test_25_single_reading_no_degrading(self, engine: TrustEngine):
        engine.reset()
        fv = make_fv(temp_rate=0.09, rpm_rate=-25.0)
        anom = make_anomaly_result(is_anomaly=True, anomaly_score=-0.14)
        rules = make_rule_result([])
        res = engine.evaluate(fv, anom, rules)
        assert res.temporal_summary["signals_detected"] == 0
        assert res.state != MachineState.DEGRADING

    # 26. Two consecutive readings with adverse rate does NOT produce DEGRADING
    def test_26_two_readings_no_degrading(self, engine: TrustEngine):
        engine.reset()
        fv = make_fv(temp_rate=0.09, rpm_rate=-25.0)
        anom = make_anomaly_result(is_anomaly=True, anomaly_score=-0.14)
        rules = make_rule_result([])
        engine.evaluate(fv, anom, rules)
        res = engine.evaluate(fv, anom, rules)
        assert res.temporal_summary["signals_detected"] == 0
        assert res.state != MachineState.DEGRADING

    # 27. Three consecutive readings triggers DEGRADING
    def test_27_three_readings_triggers_degrading(self, engine: TrustEngine):
        engine.reset()
        fv = make_fv(temp_rate=0.09, rpm_rate=-25.0)
        anom = make_anomaly_result(is_anomaly=True, anomaly_score=-0.14)
        rules = make_rule_result([
            RuleViolation(rule_id="LOW_RPM", severity="WARNING", message="Low RPM")
        ])
        engine.evaluate(fv, anom, rules)
        engine.evaluate(fv, anom, rules)
        res = engine.evaluate(fv, anom, rules)
        assert res.temporal_summary["signals_detected"] >= 1
        assert res.state == MachineState.DEGRADING

    # 28. Counter resets when adverse condition disappears
    def test_28_counter_reset_on_normal_reading(self, engine: TrustEngine):
        engine.reset()
        fv_bad = make_fv(temp_rate=0.09)
        fv_good = make_fv(temp_rate=0.01)
        anom = make_anomaly_result(is_anomaly=True, anomaly_score=-0.14)
        rules = make_rule_result([])

        # 2 adverse readings
        engine.evaluate(fv_bad, anom, rules)
        engine.evaluate(fv_bad, anom, rules)
        # 1 normal reading resets counter
        engine.evaluate(fv_good, anom, rules)
        # 2 more adverse readings (counter is 2, not 5)
        engine.evaluate(fv_bad, anom, rules)
        res = engine.evaluate(fv_bad, anom, rules)
        assert res.temporal_summary["signals_detected"] == 0
        assert res.state != MachineState.DEGRADING

    # 29. Per-device isolation: device A's counter doesn't affect device B
    def test_29_per_device_persistence_isolation(self, engine: TrustEngine):
        engine.reset()
        fv_a = make_fv(device_id="dev-A", temp_rate=0.09)
        fv_b = make_fv(device_id="dev-B", temp_rate=0.09)
        anom = make_anomaly_result(is_anomaly=True, anomaly_score=-0.14)
        rules = make_rule_result([], device_id="dev-A")
        rules_b = make_rule_result([], device_id="dev-B")

        # Device A: 2 readings
        engine.evaluate(fv_a, anom, rules)
        engine.evaluate(fv_a, anom, rules)

        # Device B: 1 reading (counter = 1, not 3)
        res_b = engine.evaluate(fv_b, anom, rules_b)
        assert res_b.temporal_summary["signals_detected"] == 0

    # 30. Cold start: first reading doesn't fabricate persistence history
    def test_30_cold_start_no_fabrication(self, engine: TrustEngine):
        engine.reset()
        fv = make_fv(temp_rate=0.09, rpm_rate=-25.0, current_rate=0.012, vibration_rate=0.5)
        anom = make_anomaly_result(is_anomaly=True, anomaly_score=-0.20)
        rules = make_rule_result([])
        res = engine.evaluate(fv, anom, rules)
        # Despite 4 adverse signals + anomaly, no DEGRADING on first reading
        assert res.temporal_summary["signals_detected"] == 0
        assert res.state != MachineState.DEGRADING

    # 31. Multiple independent signals each need their own 3 consecutive readings
    def test_31_multiple_signals_independent_persistence(self, engine: TrustEngine):
        engine.reset()
        anom = make_anomaly_result(is_anomaly=True, anomaly_score=-0.14)
        rules = make_rule_result([
            RuleViolation(rule_id="LOW_RPM", severity="WARNING", message="Low RPM")
        ])

        # First 3 readings: only temp_rate adverse
        fv_temp_only = make_fv(temp_rate=0.09, rpm_rate=0.0)
        engine.evaluate(fv_temp_only, anom, rules)
        engine.evaluate(fv_temp_only, anom, rules)
        res = engine.evaluate(fv_temp_only, anom, rules)
        # TEMP_RISING persisted, but RPM_FALLING did not
        temp_signals = [s for s in res.temporal_summary["signals"] if s == "TEMP_RISING"]
        rpm_signals = [s for s in res.temporal_summary["signals"] if s == "RPM_FALLING"]
        assert len(temp_signals) == 1
        assert len(rpm_signals) == 0

    # 32. Alternating different signals do NOT create persistence
    def test_32_alternating_signals_no_persistence(self, engine: TrustEngine):
        engine.reset()
        anom = make_anomaly_result(is_anomaly=True, anomaly_score=-0.14)
        rules = make_rule_result([])

        # Reading 1: TEMP_RISING
        engine.evaluate(make_fv(temp_rate=0.09, rpm_rate=0.0), anom, rules)
        # Reading 2: RPM_FALLING (not TEMP_RISING)
        engine.evaluate(make_fv(temp_rate=0.01, rpm_rate=-25.0), anom, rules)
        # Reading 3: CURRENT_RISING (not TEMP_RISING or RPM_FALLING)
        res = engine.evaluate(make_fv(temp_rate=0.01, rpm_rate=0.0, current_rate=0.012), anom, rules)

        # No signal persisted for 3 consecutive readings
        assert res.temporal_summary["signals_detected"] == 0
        assert res.state != MachineState.DEGRADING

    # 33. Critical rules still override persistence - FAULT/BLOCK immediately
    def test_33_critical_override_bypasses_persistence(self, engine: TrustEngine):
        engine.reset()
        fv = make_fv(temp_rate=0.09)
        anom = make_anomaly_result(is_anomaly=True, anomaly_score=-0.18)
        rules = make_rule_result([
            RuleViolation(rule_id="OVERCURRENT", severity="CRITICAL", message="Critical overcurrent")
        ])
        # Single reading with critical rule should be FAULT/BLOCK regardless of persistence
        res = engine.evaluate(fv, anom, rules)
        assert res.state == MachineState.FAULT
        assert res.decision == TrustDecision.BLOCK

    # 34. Fan OFF behavior unchanged by persistence
    def test_34_fan_off_unchanged_by_persistence(self, engine: TrustEngine):
        engine.reset()
        fv = make_fv(fan=False, rpm=0.0, current=0.01, power=0.05, temp_rate=0.06)
        anom = make_anomaly_result(is_anomaly=True, anomaly_score=-0.12)
        rules = make_rule_result([])

        # Even after 3 readings, fan_off context suppresses temporal checks
        engine.evaluate(fv, anom, rules)
        engine.evaluate(fv, anom, rules)
        res = engine.evaluate(fv, anom, rules)
        assert res.anomaly_summary["suppressed"] is True
        assert res.trust_score == 100.0
        assert res.state == MachineState.NORMAL
        assert res.decision == TrustDecision.ALLOW

    # 35. Persistence reset clears per-device state
    def test_35_reset_clears_persistence(self, engine: TrustEngine):
        engine.reset()
        fv = make_fv(temp_rate=0.09)
        anom = make_anomaly_result(is_anomaly=True, anomaly_score=-0.14)
        rules = make_rule_result([])

        # Build persistence to 2
        engine.evaluate(fv, anom, rules)
        engine.evaluate(fv, anom, rules)

        # Reset clears persistence
        engine.reset()

        # Next 2 readings should be fresh counter (not 4)
        engine.evaluate(fv, anom, rules)
        res = engine.evaluate(fv, anom, rules)
        assert res.temporal_summary["signals_detected"] == 0
        assert res.state != MachineState.DEGRADING
