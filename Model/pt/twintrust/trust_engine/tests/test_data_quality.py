"""
test_data_quality.py
====================
Tests for edge cases in data quality handling:

  - Missing sensor values (None)
  - Different missing-value policies (skip, zero, last)
  - Backward / duplicate timestamps
  - Timestamps too close together (elapsed < MIN_ELAPSED_SECONDS)
  - Invalid sensor values caught by validators
  - to_ml_dict never returns NaN or infinity
"""

from __future__ import annotations

import math
import pytest
from datetime import datetime, timezone, timedelta

from trust_engine.feature_extractor import FeatureExtractor
from trust_engine.models import TelemetryReading


def t(offset: float) -> datetime:
    return datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc) + timedelta(seconds=offset)


def base_reading(**overrides) -> TelemetryReading:
    defaults = dict(
        device_id="test", timestamp=t(0),
        temp_1=28.0, temp_2=28.0, rpm=1450.0, hall_raw=5.0,
        vibration=9.6, voltage=5.0, current=0.18, power=0.9, fan=True,
    )
    defaults.update(overrides)
    return TelemetryReading(**defaults)


# ---------------------------------------------------------------------------
# Missing values -- "skip" policy (default)
# ---------------------------------------------------------------------------

class TestMissingValuesSkipPolicy:
    def setup_method(self):
        self.fe = FeatureExtractor(missing_value_policy="skip")

    def test_missing_temp1_recorded(self):
        fv = self.fe.process(base_reading(temp_1=None))
        assert fv.raw_features.temp_1 is None
        assert "temp_1" in fv.data_quality.missing_fields

    def test_missing_temp1_temp_delta_none(self):
        fv = self.fe.process(base_reading(temp_1=None))
        # temp_delta = temp_1 - temp_2 -> None if temp_1 is None
        assert fv.derived_features.temp_delta is None

    def test_missing_temp1_temp_avg_uses_temp2(self):
        # temp_avg falls back to the non-None value
        fv = self.fe.process(base_reading(temp_1=None, temp_2=30.0))
        assert fv.derived_features.temp_avg == pytest.approx(30.0)

    def test_missing_rpm_power_per_rpm_none(self):
        fv = self.fe.process(base_reading(rpm=None))
        assert fv.derived_features.power_per_rpm is None
        assert fv.derived_features.current_per_rpm is None

    def test_missing_fan_consistency_none(self):
        fv = self.fe.process(base_reading(fan=None))
        assert fv.derived_features.fan_rpm_consistency is None

    def test_missing_current_not_in_ml_dict(self):
        fv = self.fe.process(base_reading(current=None))
        ml = fv.to_ml_dict()
        assert "current" not in ml

    def test_all_missing_ml_dict_has_no_nans(self):
        fv = self.fe.process(TelemetryReading(device_id="test", timestamp=t(0)))
        ml = fv.to_ml_dict()
        for k, v in ml.items():
            assert math.isfinite(v), f"Non-finite value {v} for key {k}"


# ---------------------------------------------------------------------------
# Missing values -- "zero" policy
# ---------------------------------------------------------------------------

class TestMissingValuesZeroPolicy:
    def setup_method(self):
        self.fe = FeatureExtractor(missing_value_policy="zero")

    def test_missing_temp1_imputed_zero(self):
        fv = self.fe.process(base_reading(temp_1=None))
        assert fv.raw_features.temp_1 == pytest.approx(0.0)
        assert "temp_1" in fv.data_quality.imputed_fields

    def test_missing_rpm_imputed_zero(self):
        fv = self.fe.process(base_reading(rpm=None))
        assert fv.raw_features.rpm == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# Missing values -- "last" policy
# ---------------------------------------------------------------------------

class TestMissingValuesLastPolicy:
    def setup_method(self):
        self.fe = FeatureExtractor(missing_value_policy="last")

    def test_missing_temp1_uses_last_known(self):
        self.fe.process(base_reading(temp_1=30.0, timestamp=t(0)))
        fv2 = self.fe.process(base_reading(temp_1=None, timestamp=t(1)))
        assert fv2.raw_features.temp_1 == pytest.approx(30.0)
        assert "temp_1" in fv2.data_quality.imputed_fields

    def test_missing_on_first_reading_no_last_stays_none(self):
        # No history yet; "last" policy has nothing to fall back to
        fv = self.fe.process(base_reading(temp_1=None))
        assert fv.raw_features.temp_1 is None


# ---------------------------------------------------------------------------
# Timestamp edge cases
# ---------------------------------------------------------------------------

class TestTimestampEdgeCases:
    def test_backward_timestamp_rates_none(self):
        fe = FeatureExtractor()
        fe.process(base_reading(timestamp=t(5)))
        fv2 = fe.process(base_reading(timestamp=t(3)))  # earlier!
        assert fv2.derived_features.temp_rate is None
        assert fv2.derived_features.rpm_rate is None
        assert any("backwards" in w.lower() for w in fv2.data_quality.warnings)

    def test_duplicate_timestamp_rates_none(self):
        fe = FeatureExtractor(min_elapsed_seconds=0.01)
        fe.process(base_reading(timestamp=t(0)))
        fv2 = fe.process(base_reading(timestamp=t(0)))  # identical!
        assert fv2.derived_features.temp_rate is None

    def test_very_short_elapsed_rates_none(self):
        fe = FeatureExtractor(min_elapsed_seconds=1.0)
        fe.process(base_reading(timestamp=t(0)))
        fv2 = fe.process(base_reading(timestamp=t(0.001)))  # 1ms apart
        assert fv2.derived_features.temp_rate is None

    def test_normal_elapsed_rates_computed(self):
        fe = FeatureExtractor(min_elapsed_seconds=0.01)
        fe.process(base_reading(temp_1=28.0, temp_2=28.0, timestamp=t(0)))
        fv2 = fe.process(base_reading(temp_1=30.0, temp_2=30.0, timestamp=t(1)))
        assert fv2.derived_features.temp_rate == pytest.approx(2.0)


# ---------------------------------------------------------------------------
# Model validators (TelemetryReading)
# ---------------------------------------------------------------------------

class TestModelValidators:
    def test_negative_rpm_rejected(self):
        with pytest.raises(Exception):
            TelemetryReading(rpm=-100.0)

    def test_extreme_temperature_rejected(self):
        with pytest.raises(Exception):
            TelemetryReading(temp_1=200.0)  # above +130 C limit

    def test_zero_rpm_accepted(self):
        r = TelemetryReading(rpm=0.0)
        assert r.rpm == 0.0

    def test_normal_temperature_accepted(self):
        r = TelemetryReading(temp_1=85.0)
        assert r.temp_1 == pytest.approx(85.0)

    def test_missing_timestamp_uses_now(self):
        r = TelemetryReading()
        ts = r.effective_timestamp()
        assert ts is not None


# ---------------------------------------------------------------------------
# Infinity / NaN cannot reach to_ml_dict
# ---------------------------------------------------------------------------

class TestNoInfinityNaN:
    def test_zero_rpm_no_infinity(self):
        fe = FeatureExtractor()
        fv = fe.process(base_reading(rpm=0.0, power=0.9, current=0.18))
        ml = fv.to_ml_dict()
        for k, v in ml.items():
            assert math.isfinite(v), f"Non-finite {v} for key {k}"

    def test_zero_elapsed_no_infinity(self):
        fe = FeatureExtractor(min_elapsed_seconds=0.01)
        fe.process(base_reading(timestamp=t(0)))
        fv2 = fe.process(base_reading(timestamp=t(0)))  # zero elapsed
        ml = fv2.to_ml_dict()
        for k, v in ml.items():
            assert math.isfinite(v), f"Non-finite {v} for key {k}"

    def test_all_sensors_present_no_nan(self):
        fe = FeatureExtractor()
        readings = [base_reading(timestamp=t(i)) for i in range(15)]
        for r in readings:
            fv = fe.process(r)
            ml = fv.to_ml_dict()
            for k, v in ml.items():
                assert not math.isnan(v), f"NaN for key {k}"
                assert math.isfinite(v), f"Inf for key {k}"
