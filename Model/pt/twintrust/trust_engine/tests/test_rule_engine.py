"""
test_rule_engine.py
===================
Unit tests for Stage 3 Deterministic Rule Engine.

Covers:
 1. Normal telemetry produces no critical violations.
 2. High temperature triggers HIGH_TEMPERATURE (WARNING).
 3. Critical temperature triggers CRITICAL_TEMPERATURE (CRITICAL).
 4. High current triggers HIGH_CURRENT (WARNING).
 5. Critical current triggers OVERCURRENT (CRITICAL).
 6. Fan ON + RPM near zero does NOT immediately trigger FAN_STALL before persistence threshold.
 7. Fan ON + RPM near zero triggers FAN_STALL after N consecutive readings.
 8. Fan ON + moderately low RPM triggers LOW_RPM (WARNING).
 9. Fan OFF + RPM zero produces NO violation (healthy OFF state).
10. Fan OFF + unexpected high RPM triggers UNEXPECTED_RPM_WHEN_FAN_OFF (WARNING).
11. Temperature sensor gap triggers TEMP_SENSOR_DISAGREEMENT (WARNING).
12. Physically invalid sensor values trigger INVALID_TELEMETRY (WARNING).
13. Missing / None values are skipped gracefully and never converted to zero.
14. Rule evaluation is completely deterministic across identical inputs.
15. Evidence dictionary contains exact measured values and thresholds.
16. Centralized thresholds from config.py are respected.
17. Multiple independent violations coexist cleanly (e.g. overtemperature + overcurrent).
18. Duplicate physical conditions do not generate redundant rule IDs (e.g. CRITICAL_TEMP subsumes HIGH_TEMP).
19. Stateful consecutive stall counter resets correctly when RPM recovers.
20. Multi-device isolation: stall counts for device A do not leak into device B.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
import pytest

from trust_engine import config
from trust_engine.feature_extractor import FeatureExtractor
from trust_engine.models import (
    FeatureMetadata,
    FeatureVector,
    RawFeatures,
    DerivedFeatures,
    DataQuality,
    RuleEvaluationResult,
    RuleSeverity,
    TelemetryReading,
)
from trust_engine.rules import RuleEngine


# ---------------------------------------------------------------------------
# Fixture & Helper
# ---------------------------------------------------------------------------

def make_fv(
    temp_1=28.0,
    temp_2=28.0,
    rpm=1450.0,
    vibration=9.6,
    voltage=5.0,
    current=0.18,
    power=0.9,
    fan=True,
    device_id="test-device-01",
    timestamp=None,
) -> FeatureVector:
    """Helper to create a FeatureVector with explicit values."""
    ts = timestamp or datetime(2026, 9, 18, 12, 0, 0, tzinfo=timezone.utc)
    fan_int = 1.0 if fan is True else (0.0 if fan is False else None)

    temp_avg = None
    if temp_1 is not None and temp_2 is not None:
        temp_avg = (temp_1 + temp_2) / 2.0
    elif temp_1 is not None:
        temp_avg = temp_1
    elif temp_2 is not None:
        temp_avg = temp_2

    temp_delta = None
    if temp_1 is not None and temp_2 is not None:
        temp_delta = temp_1 - temp_2

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
        temp_delta=temp_delta,
        temp_avg=temp_avg,
    )
    metadata = FeatureMetadata(
        device_id=device_id,
        timestamp=ts,
        reading_index=0,
    )
    dq = DataQuality()
    return FeatureVector(
        metadata=metadata,
        raw_features=raw,
        derived_features=derived,
        data_quality=dq,
    )


# ---------------------------------------------------------------------------
# Test Cases
# ---------------------------------------------------------------------------

class TestRuleEngine:
    def setup_method(self):
        self.engine = RuleEngine()

    def test_1_normal_telemetry_no_critical_violations(self):
        fv = make_fv(temp_1=28.5, temp_2=28.5, rpm=1450.0, current=0.18, fan=True)
        res = self.engine.evaluate(fv)
        assert not res.has_violations
        assert res.triggered_rules == 0
        assert res.engine_status == "ok"
        critical_violations = [v for v in res.violations if v.severity == RuleSeverity.CRITICAL.value]
        assert len(critical_violations) == 0

    def test_2_high_temperature_warning(self):
        # RULE_TEMP_WARNING = 31.0, RULE_TEMP_CRITICAL = 33.5
        fv = make_fv(temp_1=32.0, temp_2=32.0)
        res = self.engine.evaluate(fv)
        assert res.has_violations
        rule_ids = [v.rule_id for v in res.violations]
        assert "HIGH_TEMPERATURE" in rule_ids
        assert "CRITICAL_TEMPERATURE" not in rule_ids

        v = next(v for v in res.violations if v.rule_id == "HIGH_TEMPERATURE")
        assert v.severity == RuleSeverity.WARNING.value
        assert v.value == pytest.approx(32.0)
        assert v.threshold == pytest.approx(config.RULE_TEMP_WARNING)

    def test_3_critical_temperature(self):
        fv = make_fv(temp_1=34.5, temp_2=34.5)
        res = self.engine.evaluate(fv)
        rule_ids = [v.rule_id for v in res.violations]
        assert "CRITICAL_TEMPERATURE" in rule_ids
        # Subsumption: HIGH_TEMPERATURE should NOT fire simultaneously
        assert "HIGH_TEMPERATURE" not in rule_ids

        v = next(v for v in res.violations if v.rule_id == "CRITICAL_TEMPERATURE")
        assert v.severity == RuleSeverity.CRITICAL.value
        assert res.engine_status == "critical"

    def test_4_high_current_warning(self):
        # RULE_CURRENT_WARNING = 0.28, RULE_CURRENT_CRITICAL = 0.40
        fv = make_fv(current=0.32)
        res = self.engine.evaluate(fv)
        rule_ids = [v.rule_id for v in res.violations]
        assert "HIGH_CURRENT" in rule_ids
        assert "OVERCURRENT" not in rule_ids

        v = next(v for v in res.violations if v.rule_id == "HIGH_CURRENT")
        assert v.severity == RuleSeverity.WARNING.value

    def test_5_critical_overcurrent(self):
        fv = make_fv(current=0.45)
        res = self.engine.evaluate(fv)
        rule_ids = [v.rule_id for v in res.violations]
        assert "OVERCURRENT" in rule_ids
        assert "HIGH_CURRENT" not in rule_ids
        assert res.engine_status == "critical"

    def test_6_fan_on_zero_rpm_transient_no_immediate_stall(self):
        # 1st reading below stall threshold should NOT immediately trigger FAN_STALL
        fv = make_fv(fan=True, rpm=10.0)
        res = self.engine.evaluate(fv)
        rule_ids = [v.rule_id for v in res.violations]
        assert "FAN_STALL" not in rule_ids
        assert self.engine.get_consecutive_stall_count("test-device-01") == 1

    def test_7_fan_on_low_rpm_persists_triggers_fan_stall(self):
        # Default RULE_FAN_STALL_CONFIRMATION_COUNT is 3
        fv = make_fv(fan=True, rpm=10.0)
        res1 = self.engine.evaluate(fv)
        assert "FAN_STALL" not in [v.rule_id for v in res1.violations]

        res2 = self.engine.evaluate(fv)
        assert "FAN_STALL" not in [v.rule_id for v in res2.violations]

        res3 = self.engine.evaluate(fv)
        assert "FAN_STALL" in [v.rule_id for v in res3.violations]
        v = next(v for v in res3.violations if v.rule_id == "FAN_STALL")
        assert v.severity == RuleSeverity.CRITICAL.value
        assert v.evidence["consecutive_readings"] == 3
        assert res3.engine_status == "critical"

    def test_8_fan_on_moderately_low_rpm_triggers_low_rpm(self):
        # RULE_RPM_STALL_THRESHOLD = 150, RULE_RPM_LOW_THRESHOLD = 1000
        fv = make_fv(fan=True, rpm=750.0)
        res = self.engine.evaluate(fv)
        rule_ids = [v.rule_id for v in res.violations]
        assert "LOW_RPM" in rule_ids
        assert "FAN_STALL" not in rule_ids
        v = next(v for v in res.violations if v.rule_id == "LOW_RPM")
        assert v.severity == RuleSeverity.WARNING.value

    def test_9_fan_off_zero_rpm_no_violation(self):
        # A machine intentionally turned off with 0 RPM is NOT a fault
        fv = make_fv(fan=False, rpm=0.0, current=0.001)
        res = self.engine.evaluate(fv)
        assert not res.has_violations
        assert res.triggered_rules == 0
        assert res.engine_status == "ok"

    def test_10_fan_off_unexpected_high_rpm(self):
        # RULE_UNEXPECTED_RPM_FAN_OFF_THRESHOLD = 50.0
        fv = make_fv(fan=False, rpm=250.0)
        res = self.engine.evaluate(fv)
        rule_ids = [v.rule_id for v in res.violations]
        assert "UNEXPECTED_RPM_WHEN_FAN_OFF" in rule_ids
        v = next(v for v in res.violations if v.rule_id == "UNEXPECTED_RPM_WHEN_FAN_OFF")
        assert v.severity == RuleSeverity.WARNING.value

    def test_11_temp_sensor_disagreement(self):
        # RULE_TEMP_DISAGREEMENT_THRESHOLD = 2.0
        fv = make_fv(temp_1=28.0, temp_2=31.5)
        res = self.engine.evaluate(fv)
        rule_ids = [v.rule_id for v in res.violations]
        assert "TEMP_SENSOR_DISAGREEMENT" in rule_ids
        v = next(v for v in res.violations if v.rule_id == "TEMP_SENSOR_DISAGREEMENT")
        assert v.severity == RuleSeverity.WARNING.value
        assert v.evidence["absolute_difference"] == pytest.approx(3.5)

    def test_12_invalid_telemetry_bounds(self):
        # Negative RPM and impossible temperature
        fv = make_fv(rpm=-50.0, temp_1=150.0)
        res = self.engine.evaluate(fv)
        rule_ids = [v.rule_id for v in res.violations]
        assert "INVALID_TELEMETRY" in rule_ids
        v = next(v for v in res.violations if v.rule_id == "INVALID_TELEMETRY")
        assert "rpm" in v.evidence
        assert "temp_1" in v.evidence

    def test_13_missing_none_values_do_not_crash(self):
        # All sensors None
        fv = make_fv(
            temp_1=None, temp_2=None, rpm=None,
            vibration=None, voltage=None, current=None, power=None, fan=None
        )
        res = self.engine.evaluate(fv)
        assert res.evaluated_rules == 9
        assert not res.has_violations

    def test_14_rule_evaluation_is_deterministic(self):
        fv = make_fv(temp_1=32.0, temp_2=32.0, current=0.30)
        res1 = self.engine.evaluate(fv)
        res2 = self.engine.evaluate(fv)
        assert res1.triggered_rules == res2.triggered_rules
        assert [v.rule_id for v in res1.violations] == [v.rule_id for v in res2.violations]

    def test_15_evidence_contains_actual_values(self):
        fv = make_fv(current=0.35)
        res = self.engine.evaluate(fv)
        v = next(v for v in res.violations if v.rule_id == "HIGH_CURRENT")
        assert v.evidence["current"] == pytest.approx(0.35)
        assert v.evidence["threshold"] == pytest.approx(config.RULE_CURRENT_WARNING)

    def test_16_custom_thresholds_configuration(self):
        custom_engine = RuleEngine(temp_warning=35.0, temp_critical=40.0)
        fv = make_fv(temp_1=32.0, temp_2=32.0)
        # Under default engine (31.0) this triggers, under custom (35.0) it should NOT
        res = custom_engine.evaluate(fv)
        assert "HIGH_TEMPERATURE" not in [v.rule_id for v in res.violations]

    def test_17_multiple_independent_violations_coexist(self):
        # High temperature + High current
        fv = make_fv(temp_1=32.0, temp_2=32.0, current=0.35)
        res = self.engine.evaluate(fv)
        rule_ids = {v.rule_id for v in res.violations}
        assert "HIGH_TEMPERATURE" in rule_ids
        assert "HIGH_CURRENT" in rule_ids
        assert res.triggered_rules >= 2

    def test_18_subsumption_prevents_duplicate_rules(self):
        # Critical temp should not also create HIGH_TEMPERATURE
        # Critical current should not also create HIGH_CURRENT
        fv = make_fv(temp_1=35.0, temp_2=35.0, current=0.45)
        res = self.engine.evaluate(fv)
        rule_ids = [v.rule_id for v in res.violations]
        assert "CRITICAL_TEMPERATURE" in rule_ids
        assert "HIGH_TEMPERATURE" not in rule_ids
        assert "OVERCURRENT" in rule_ids
        assert "HIGH_CURRENT" not in rule_ids

    def test_19_stateful_history_resets_on_recovery(self):
        # 2 low readings -> stall count = 2
        fv_low = make_fv(fan=True, rpm=20.0)
        self.engine.evaluate(fv_low)
        self.engine.evaluate(fv_low)
        assert self.engine.get_consecutive_stall_count("test-device-01") == 2

        # RPM recovers to normal -> counter resets to 0
        fv_norm = make_fv(fan=True, rpm=1450.0)
        self.engine.evaluate(fv_norm)
        assert self.engine.get_consecutive_stall_count("test-device-01") == 0

    def test_20_multi_device_isolation(self):
        dev_a = make_fv(device_id="device-A", fan=True, rpm=10.0)
        dev_b = make_fv(device_id="device-B", fan=True, rpm=1450.0)

        self.engine.evaluate(dev_a)
        self.engine.evaluate(dev_a)
        self.engine.evaluate(dev_b)

        assert self.engine.get_consecutive_stall_count("device-A") == 2
        assert self.engine.get_consecutive_stall_count("device-B") == 0
