"""
test_synthetic.py
=================
End-to-end tests using the synthetic data generator.

Validates that the three built-in scenarios produce feature vectors
that match the expected physical behavior.
"""

from __future__ import annotations

import pytest
from trust_engine.feature_extractor import FeatureExtractor
from trust_engine.data.synthetic_generator import (
    generate_normal_sequence,
    generate_fan_stall_sequence,
    generate_degradation_sequence,
    sequence_to_json,
    readings_from_json,
)


# ---------------------------------------------------------------------------
# Normal scenario
# ---------------------------------------------------------------------------

class TestNormalScenario:
    def setup_method(self):
        self.readings = generate_normal_sequence(n=20, seed=42)
        self.fe = FeatureExtractor()
        self.vectors = self.fe.process_batch(self.readings)

    def test_correct_number_of_vectors(self):
        assert len(self.vectors) == 20

    def test_all_fans_on(self):
        for fv in self.vectors:
            assert fv.raw_features.fan_int == pytest.approx(1.0)

    def test_rpm_in_healthy_range(self):
        for fv in self.vectors:
            assert 1300 <= fv.raw_features.rpm <= 1600

    def test_fan_rpm_consistency_near_zero_normal(self):
        # All readings have RPM near 1450, well above expected 1200
        # So fan_rpm_consistency should be 0 throughout
        for fv in self.vectors[1:]:  # skip first (no history)
            assert fv.derived_features.fan_rpm_consistency == pytest.approx(0.0, abs=0.01)

    def test_rolling_stats_available_after_window(self):
        # After 3+ readings, rolling stats should be available
        for fv in self.vectors[3:]:
            assert fv.data_quality.rolling_features_available is True

    def test_temp_rates_small_for_stable_machine(self):
        # In normal operation, temperature barely changes, so rate should be tiny
        for fv in self.vectors[1:]:
            if fv.derived_features.temp_rate is not None:
                assert abs(fv.derived_features.temp_rate) < 1.0  # < 1 C/s

    def test_json_roundtrip(self):
        json_str = sequence_to_json(self.readings)
        reloaded = readings_from_json(json_str)
        assert len(reloaded) == len(self.readings)
        assert reloaded[0].rpm == pytest.approx(self.readings[0].rpm, rel=1e-3)


# ---------------------------------------------------------------------------
# Fan stall scenario
# ---------------------------------------------------------------------------

class TestFanStallScenario:
    def setup_method(self):
        self.readings = generate_fan_stall_sequence(n=20, seed=7)
        self.fe = FeatureExtractor()
        self.vectors = self.fe.process_batch(self.readings)

    def test_fan_always_on(self):
        for fv in self.vectors:
            assert fv.raw_features.fan_int == pytest.approx(1.0)

    def test_rpm_drops_after_reading_5(self):
        # Readings 0-4: healthy RPM. Readings 5+: stalled (low RPM)
        for fv in self.vectors[5:]:
            assert fv.raw_features.rpm < 500

    def test_fan_rpm_consistency_elevated_after_stall(self):
        # After the stall begins (reading 5+), fan_rpm_consistency should be high
        for fv in self.vectors[6:]:  # need at least reading index 6 for history
            assert fv.derived_features.fan_rpm_consistency is not None
            assert fv.derived_features.fan_rpm_consistency > 0.5

    def test_rpm_rate_negative_at_stall(self):
        # Reading at index 5 should show a sharp negative RPM rate
        fv5 = self.vectors[5]
        assert fv5.derived_features.rpm_rate is not None
        assert fv5.derived_features.rpm_rate < -500  # sharp drop


# ---------------------------------------------------------------------------
# Degradation scenario
# ---------------------------------------------------------------------------

class TestDegradationScenario:
    def setup_method(self):
        self.readings = generate_degradation_sequence(n=30, seed=99)
        self.fe = FeatureExtractor()
        self.vectors = self.fe.process_batch(self.readings)

    def test_temperature_rises_over_sequence(self):
        first_temp = self.vectors[0].raw_features.temp_1
        last_temp = self.vectors[-1].raw_features.temp_1
        assert last_temp > first_temp + 5.0  # at least 5 C hotter

    def test_rpm_falls_over_sequence(self):
        first_rpm = self.vectors[0].raw_features.rpm
        last_rpm = self.vectors[-1].raw_features.rpm
        assert last_rpm < first_rpm - 200  # at least 200 RPM drop

    def test_current_rises_over_sequence(self):
        first_current = self.vectors[0].raw_features.current
        last_current = self.vectors[-1].raw_features.current
        assert last_current > first_current + 0.1  # at least 0.1 A increase

    def test_temp_rate_generally_positive(self):
        # Most readings should show positive temp_rate
        positive_rates = [
            fv for fv in self.vectors[1:]
            if fv.derived_features.temp_rate is not None
            and fv.derived_features.temp_rate > 0
        ]
        assert len(positive_rates) > len(self.vectors) * 0.7  # > 70% positive

    def test_rpm_rate_generally_negative(self):
        negative_rates = [
            fv for fv in self.vectors[1:]
            if fv.derived_features.rpm_rate is not None
            and fv.derived_features.rpm_rate < 0
        ]
        assert len(negative_rates) > len(self.vectors) * 0.7

    def test_fan_rpm_consistency_increases_over_time(self):
        # As RPM falls, fan_rpm_consistency should grow
        early_vals = [
            fv.derived_features.fan_rpm_consistency
            for fv in self.vectors[1:6]
            if fv.derived_features.fan_rpm_consistency is not None
        ]
        late_vals = [
            fv.derived_features.fan_rpm_consistency
            for fv in self.vectors[-5:]
            if fv.derived_features.fan_rpm_consistency is not None
        ]
        if early_vals and late_vals:
            assert sum(late_vals) / len(late_vals) > sum(early_vals) / len(early_vals)

    def test_rolling_temp_mean_rises(self):
        # Rolling temp mean should be higher later in the sequence
        early_mean = self.vectors[5].derived_features.temp_1_mean
        late_mean = self.vectors[-1].derived_features.temp_1_mean
        if early_mean is not None and late_mean is not None:
            assert late_mean > early_mean
