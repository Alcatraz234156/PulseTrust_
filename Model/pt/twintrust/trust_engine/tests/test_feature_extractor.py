"""
test_feature_extractor.py
=========================
Unit tests for the FeatureExtractor.

Tests cover:
  - Single reading (no history)
  - Two sequential readings (rates computed)
  - Temperature features (temp_delta, temp_avg, temp_rate)
  - RPM features (rpm_delta, rpm_rate)
  - Electrical features (current_rate, power_rate, power_per_rpm)
  - Vibration features
  - Rolling window statistics
  - Cross-sensor consistency (fan_rpm_consistency)
  - to_ml_dict() correctness
  - reset() clears history
"""

from __future__ import annotations

import math
import pytest
from datetime import datetime, timezone, timedelta

from trust_engine.feature_extractor import FeatureExtractor, _safe_sub, _safe_avg, _safe_rate, _safe_div
from trust_engine.models import TelemetryReading


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def make_reading(
    temp_1=28.0, temp_2=28.0, rpm=1450.0,
    vibration=9.6, voltage=5.0, current=0.18, power=0.9,
    fan=True, hall_raw=5.0, device_id="test-device",
    timestamp=None,
) -> TelemetryReading:
    """Create a TelemetryReading with sensible defaults."""
    if timestamp is None:
        timestamp = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    return TelemetryReading(
        device_id=device_id,
        timestamp=timestamp,
        temp_1=temp_1, temp_2=temp_2,
        rpm=rpm, hall_raw=hall_raw,
        vibration=vibration,
        voltage=voltage, current=current, power=power,
        fan=fan,
    )


def t(offset_seconds: float) -> datetime:
    """Return a timestamp offset_seconds after 2024-01-01 12:00:00 UTC."""
    return datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc) + timedelta(seconds=offset_seconds)


# ---------------------------------------------------------------------------
# Pure utility function tests
# ---------------------------------------------------------------------------

class TestUtilityFunctions:
    def test_safe_sub_both_present(self):
        assert _safe_sub(5.0, 3.0) == pytest.approx(2.0)

    def test_safe_sub_first_none(self):
        assert _safe_sub(None, 3.0) is None

    def test_safe_sub_second_none(self):
        assert _safe_sub(5.0, None) is None

    def test_safe_sub_both_none(self):
        assert _safe_sub(None, None) is None

    def test_safe_avg_both_present(self):
        assert _safe_avg(10.0, 20.0) == pytest.approx(15.0)

    def test_safe_avg_first_only(self):
        assert _safe_avg(10.0, None) == pytest.approx(10.0)

    def test_safe_avg_second_only(self):
        assert _safe_avg(None, 20.0) == pytest.approx(20.0)

    def test_safe_avg_both_none(self):
        assert _safe_avg(None, None) is None

    def test_safe_rate_normal(self):
        # (10 - 5) / 2 = 2.5
        assert _safe_rate(10.0, 5.0, 2.0) == pytest.approx(2.5)

    def test_safe_rate_negative_delta(self):
        # (5 - 10) / 2 = -2.5
        assert _safe_rate(5.0, 10.0, 2.0) == pytest.approx(-2.5)

    def test_safe_rate_zero_elapsed(self):
        assert _safe_rate(10.0, 5.0, 0.0) is None

    def test_safe_rate_none_current(self):
        assert _safe_rate(None, 5.0, 1.0) is None

    def test_safe_rate_none_previous(self):
        assert _safe_rate(10.0, None, 1.0) is None

    def test_safe_div_normal(self):
        assert _safe_div(10.0, 4.0) == pytest.approx(2.5)

    def test_safe_div_zero_denominator(self):
        assert _safe_div(10.0, 0.0) is None

    def test_safe_div_none_numerator(self):
        assert _safe_div(None, 4.0) is None

    def test_safe_div_none_denominator(self):
        assert _safe_div(10.0, None) is None


# ---------------------------------------------------------------------------
# Single reading (first observation -- no history)
# ---------------------------------------------------------------------------

class TestSingleReading:
    def setup_method(self):
        self.fe = FeatureExtractor()

    def test_reading_index_is_zero(self):
        fv = self.fe.process(make_reading())
        assert fv.metadata.reading_index == 0

    def test_raw_temp1_preserved(self):
        fv = self.fe.process(make_reading(temp_1=32.5))
        assert fv.raw_features.temp_1 == pytest.approx(32.5)

    def test_raw_temp2_preserved(self):
        fv = self.fe.process(make_reading(temp_2=31.0))
        assert fv.raw_features.temp_2 == pytest.approx(31.0)

    def test_raw_rpm_preserved(self):
        fv = self.fe.process(make_reading(rpm=1200.0))
        assert fv.raw_features.rpm == pytest.approx(1200.0)

    def test_fan_true_gives_fan_int_one(self):
        fv = self.fe.process(make_reading(fan=True))
        assert fv.raw_features.fan_int == pytest.approx(1.0)

    def test_fan_false_gives_fan_int_zero(self):
        fv = self.fe.process(make_reading(fan=False))
        assert fv.raw_features.fan_int == pytest.approx(0.0)

    def test_hall_raw_in_metadata_not_raw_features(self):
        fv = self.fe.process(make_reading(hall_raw=7.5))
        assert fv.metadata.hall_raw == pytest.approx(7.5)
        # hall_raw must NOT appear in raw_features
        raw_dict = fv.raw_features.model_dump()
        assert "hall_raw" not in raw_dict

    def test_temp_delta_equal_temps(self):
        fv = self.fe.process(make_reading(temp_1=28.0, temp_2=28.0))
        assert fv.derived_features.temp_delta == pytest.approx(0.0)

    def test_temp_delta_different_temps(self):
        fv = self.fe.process(make_reading(temp_1=30.0, temp_2=28.0))
        assert fv.derived_features.temp_delta == pytest.approx(2.0)

    def test_temp_avg(self):
        fv = self.fe.process(make_reading(temp_1=30.0, temp_2=28.0))
        assert fv.derived_features.temp_avg == pytest.approx(29.0)

    def test_temp_rate_none_on_first_reading(self):
        fv = self.fe.process(make_reading())
        assert fv.derived_features.temp_rate is None

    def test_rpm_rate_none_on_first_reading(self):
        fv = self.fe.process(make_reading())
        assert fv.derived_features.rpm_rate is None

    def test_current_rate_none_on_first_reading(self):
        fv = self.fe.process(make_reading())
        assert fv.derived_features.current_rate is None

    def test_vibration_rate_none_on_first_reading(self):
        fv = self.fe.process(make_reading())
        assert fv.derived_features.vibration_rate is None

    def test_no_rolling_stats_on_first_reading(self):
        fv = self.fe.process(make_reading())
        d = fv.derived_features
        # All rolling stats should be None with no history
        assert d.temp_1_mean is None
        assert d.rpm_mean is None
        assert d.current_std is None

    def test_power_per_rpm_computed(self):
        # power_per_rpm = 0.9 / 1450 ~ 0.000621
        fv = self.fe.process(make_reading(power=0.9, rpm=1450.0))
        assert fv.derived_features.power_per_rpm == pytest.approx(0.9 / 1450.0, rel=1e-4)

    def test_current_per_rpm_computed(self):
        fv = self.fe.process(make_reading(current=0.18, rpm=1450.0))
        assert fv.derived_features.current_per_rpm == pytest.approx(0.18 / 1450.0, rel=1e-4)

    def test_power_per_rpm_none_when_rpm_zero(self):
        fv = self.fe.process(make_reading(rpm=0.0, power=0.9))
        assert fv.derived_features.power_per_rpm is None

    def test_data_quality_rate_not_available_first_reading(self):
        fv = self.fe.process(make_reading())
        assert fv.data_quality.rate_features_available is False

    def test_data_quality_history_size_zero_first_reading(self):
        fv = self.fe.process(make_reading())
        assert fv.data_quality.history_size == 0


# ---------------------------------------------------------------------------
# Two sequential readings
# ---------------------------------------------------------------------------

class TestTwoReadings:
    def setup_method(self):
        self.fe = FeatureExtractor()

    def test_second_reading_index_is_one(self):
        self.fe.process(make_reading(timestamp=t(0)))
        fv2 = self.fe.process(make_reading(timestamp=t(1)))
        assert fv2.metadata.reading_index == 1

    def test_history_size_after_two_readings(self):
        self.fe.process(make_reading(timestamp=t(0)))
        fv2 = self.fe.process(make_reading(timestamp=t(1)))
        assert fv2.data_quality.history_size == 1  # history has 1 reading (the first)

    def test_elapsed_seconds_computed(self):
        self.fe.process(make_reading(timestamp=t(0)))
        fv2 = self.fe.process(make_reading(timestamp=t(2.5)))
        assert fv2.data_quality.elapsed_seconds == pytest.approx(2.5)

    def test_temp_rate_computed_correctly(self):
        # temp_avg_1 = (28 + 28) / 2 = 28
        # temp_avg_2 = (30 + 30) / 2 = 30
        # elapsed = 1 second
        # temp_rate = (30 - 28) / 1 = 2.0 C/s
        self.fe.process(make_reading(temp_1=28.0, temp_2=28.0, timestamp=t(0)))
        fv2 = self.fe.process(make_reading(temp_1=30.0, temp_2=30.0, timestamp=t(1)))
        assert fv2.derived_features.temp_rate == pytest.approx(2.0)

    def test_rpm_rate_computed_correctly(self):
        # rpm_delta = 1200 - 1450 = -250
        # rpm_rate  = -250 / 1.0 = -250 rpm/s
        self.fe.process(make_reading(rpm=1450.0, timestamp=t(0)))
        fv2 = self.fe.process(make_reading(rpm=1200.0, timestamp=t(1)))
        assert fv2.derived_features.rpm_rate == pytest.approx(-250.0)

    def test_rpm_delta_computed_correctly(self):
        self.fe.process(make_reading(rpm=1450.0, timestamp=t(0)))
        fv2 = self.fe.process(make_reading(rpm=1200.0, timestamp=t(1)))
        assert fv2.derived_features.rpm_delta == pytest.approx(-250.0)

    def test_current_rate_computed_correctly(self):
        # (0.40 - 0.18) / 2.0 = 0.11 A/s
        self.fe.process(make_reading(current=0.18, timestamp=t(0)))
        fv2 = self.fe.process(make_reading(current=0.40, timestamp=t(2)))
        assert fv2.derived_features.current_rate == pytest.approx(0.11)

    def test_vibration_rate_computed_correctly(self):
        # (12.0 - 9.6) / 1.0 = 2.4 m/s^3
        self.fe.process(make_reading(vibration=9.6, timestamp=t(0)))
        fv2 = self.fe.process(make_reading(vibration=12.0, timestamp=t(1)))
        assert fv2.derived_features.vibration_rate == pytest.approx(2.4)

    def test_power_delta(self):
        self.fe.process(make_reading(power=0.9, timestamp=t(0)))
        fv2 = self.fe.process(make_reading(power=2.0, timestamp=t(1)))
        assert fv2.derived_features.power_delta == pytest.approx(1.1)

    def test_rate_available_flag(self):
        self.fe.process(make_reading(timestamp=t(0)))
        fv2 = self.fe.process(make_reading(timestamp=t(1)))
        assert fv2.data_quality.rate_features_available is True

    def test_rolling_not_available_with_one_history_item(self):
        # Rolling requires >= 2 history items -- after 2nd reading, history has 1
        self.fe.process(make_reading(timestamp=t(0)))
        fv2 = self.fe.process(make_reading(timestamp=t(1)))
        assert fv2.data_quality.rolling_features_available is False

    def test_rolling_available_with_three_readings(self):
        self.fe.process(make_reading(timestamp=t(0)))
        self.fe.process(make_reading(timestamp=t(1)))
        fv3 = self.fe.process(make_reading(timestamp=t(2)))
        assert fv3.data_quality.rolling_features_available is True


# ---------------------------------------------------------------------------
# Fan RPM consistency
# ---------------------------------------------------------------------------

class TestFanRpmConsistency:
    def setup_method(self):
        self.fe = FeatureExtractor(expected_fan_rpm=1200.0)

    def test_fan_off_consistency_zero(self):
        # Fan OFF: no inconsistency regardless of RPM
        fv = self.fe.process(make_reading(fan=False, rpm=0.0))
        assert fv.derived_features.fan_rpm_consistency == pytest.approx(0.0)

    def test_fan_on_good_rpm_consistency_zero(self):
        # Fan ON + RPM >= expected -> 0 inconsistency
        fv = self.fe.process(make_reading(fan=True, rpm=1200.0))
        assert fv.derived_features.fan_rpm_consistency == pytest.approx(0.0)

    def test_fan_on_rpm_zero_consistency_one(self):
        # Fan ON + RPM = 0 -> maximum inconsistency = 1.0
        fv = self.fe.process(make_reading(fan=True, rpm=0.0))
        assert fv.derived_features.fan_rpm_consistency == pytest.approx(1.0)

    def test_fan_on_half_rpm_consistency_half(self):
        # Fan ON + RPM = 600 (half of 1200) -> consistency = 0.5
        fv = self.fe.process(make_reading(fan=True, rpm=600.0))
        assert fv.derived_features.fan_rpm_consistency == pytest.approx(0.5)

    def test_fan_on_rpm_exceeds_expected_no_negative(self):
        # RPM above expected -> clamp to 0, not negative
        fv = self.fe.process(make_reading(fan=True, rpm=2000.0))
        assert fv.derived_features.fan_rpm_consistency == pytest.approx(0.0)

    def test_fan_none_consistency_none(self):
        fv = self.fe.process(make_reading(fan=None, rpm=0.0))
        assert fv.derived_features.fan_rpm_consistency is None


# ---------------------------------------------------------------------------
# Rolling window statistics
# ---------------------------------------------------------------------------

class TestRollingStatistics:
    def test_rolling_mean_correct(self):
        fe = FeatureExtractor(window_size=10)
        # Process 5 readings with known temps, then check rolling mean
        temps = [28.0, 29.0, 30.0, 31.0, 32.0]
        for i, temp in enumerate(temps):
            fv = fe.process(make_reading(temp_1=temp, timestamp=t(i)))

        # After 5 readings, history has 4 items (1st through 4th)
        # Rolling mean of temp_1 in history = (28 + 29 + 30 + 31) / 4 = 29.5
        assert fv.derived_features.temp_1_mean == pytest.approx(29.5)

    def test_rolling_std_correct(self):
        fe = FeatureExtractor(window_size=10)
        # Use readings with known temp to compute expected std
        for i, temp in enumerate([28.0, 30.0, 32.0]):
            fv = fe.process(make_reading(temp_1=temp, timestamp=t(i)))
        # After 3 readings, history has 2 items: [28.0, 30.0]
        # mean = 29.0, variance = ((28-29)^2 + (30-29)^2) / 2 = 1.0, std = 1.0
        assert fv.derived_features.temp_1_std == pytest.approx(1.0)

    def test_rolling_window_respects_maxlen(self):
        fe = FeatureExtractor(window_size=3)
        temps = [20.0, 22.0, 24.0, 26.0, 28.0]
        for i, temp in enumerate(temps):
            fv = fe.process(make_reading(temp_1=temp, timestamp=t(i)))
        # Window size is 3 so history keeps at most 3 items: [24, 26, 28]
        # After 5th reading, history = [22, 24, 26] (5th not yet added)
        # mean = (22 + 24 + 26) / 3 = 24.0
        assert fv.derived_features.temp_1_mean == pytest.approx(24.0)


# ---------------------------------------------------------------------------
# Reset
# ---------------------------------------------------------------------------

class TestReset:
    def test_reset_clears_history(self):
        fe = FeatureExtractor()
        fe.process(make_reading(timestamp=t(0)))
        fe.process(make_reading(timestamp=t(1)))
        fe.reset()
        assert fe.history_size == 0

    def test_reset_clears_index(self):
        fe = FeatureExtractor()
        fe.process(make_reading(timestamp=t(0)))
        fe.reset()
        fv = fe.process(make_reading(timestamp=t(0)))
        assert fv.metadata.reading_index == 0

    def test_after_reset_first_reading_has_no_rates(self):
        fe = FeatureExtractor()
        fe.process(make_reading(timestamp=t(0)))
        fe.process(make_reading(timestamp=t(1)))
        fe.reset()
        fv = fe.process(make_reading(timestamp=t(0)))
        assert fv.derived_features.temp_rate is None
        assert fv.derived_features.rpm_rate is None


# ---------------------------------------------------------------------------
# to_ml_dict correctness
# ---------------------------------------------------------------------------

class TestToMlDict:
    def test_no_none_in_ml_dict(self):
        fe = FeatureExtractor()
        fv = fe.process(make_reading())
        ml = fv.to_ml_dict()
        for k, v in ml.items():
            assert v is not None, f"None found for key {k}"
            assert math.isfinite(v), f"Non-finite value {v} found for key {k}"

    def test_no_nan_in_ml_dict(self):
        fe = FeatureExtractor()
        fv = fe.process(make_reading())
        ml = fv.to_ml_dict()
        for k, v in ml.items():
            assert not math.isnan(v), f"NaN found for key {k}"

    def test_ml_dict_excludes_metadata(self):
        fe = FeatureExtractor()
        fv = fe.process(make_reading())
        ml = fv.to_ml_dict()
        assert "device_id" not in ml
        assert "timestamp" not in ml
        assert "hall_raw" not in ml

    def test_ml_dict_contains_expected_keys(self):
        fe = FeatureExtractor()
        fv = fe.process(make_reading(rpm=1450.0, power=0.9, current=0.18))
        ml = fv.to_ml_dict()
        # These should always be present for a full single reading
        for key in ["temp_1", "temp_2", "rpm", "vibration", "fan_int",
                    "temp_delta", "temp_avg", "power_per_rpm"]:
            assert key in ml, f"Expected key '{key}' missing from ml_dict"
