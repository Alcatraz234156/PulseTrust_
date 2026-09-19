"""
test_full_pipeline.py
=====================
End-to-End Integration Tests for Stage 1, Stage 2, and Stage 3.

Validates the full integrated sequential pipeline:
    raw telemetry -> FeatureExtractor -> Isolation Forest + Rule Engine -> independent evidence

Verifies:
 1. Normal baseline pipeline (warmup handling, ~10% Stage 2 anomaly rate, zero Stage 3 violations, 34-feature ordering).
 2. Degradation pipeline (Stage 1 rates evolve, Stage 2 scores drop, Stage 3 rules trigger chronologically).
 3. Stall pipeline (normal operation initially, degraded speed, 3-consecutive-reading stall confirmation, no premature trigger).
 4. Stall recovery (stateful stall counter resets when RPM recovers).
 5. Fan OFF pipeline (intentional OFF state produces zero Rule Engine violations, division guards active).
 6. Cross-stage evidence separation (Stage 2 and Stage 3 outputs are stored as distinct evidence; no Stage 4 score).
 7. Feature matrix integrity (exact 34-feature ordering, all finite floats, no strings or booleans).
 8. State isolation between datasets and across multiple devices.
 9. Ordering and temporal integrity (sequential processing, monotonically increasing timestamps).
10. No model mutation or retraining during validation.
11. Strict Stage 4 boundary (no TrustResult, no ALLOW/WARN/BLOCK decision synthesis).
"""

from __future__ import annotations

import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import List

import numpy as np
import pytest

from trust_engine import config
from trust_engine.anomaly_detector import AnomalyDetector
from trust_engine.feature_extractor import FeatureExtractor
from trust_engine.models import (
    AnomalyResult,
    FeatureVector,
    RuleEvaluationResult,
    TelemetryReading,
)
from trust_engine.rules import RuleEngine


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def load_dataset(filename: str) -> List[TelemetryReading]:
    path = Path("trust_engine/data") / filename
    assert path.exists(), f"Dataset file not found: {path}"
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, dict):
        data = [data]
    return [TelemetryReading(**item) for item in data]


@pytest.fixture(scope="module")
def trained_detector() -> AnomalyDetector:
    """Load the pre-trained Isolation Forest model."""
    detector = AnomalyDetector(model_path=config.IFOREST_MODEL_PATH)
    assert Path(config.IFOREST_MODEL_PATH).exists(), "Trained model joblib file missing"
    detector.load()
    assert detector.is_ready, "AnomalyDetector failed to load"
    return detector


# ---------------------------------------------------------------------------
# Test 1: Normal Baseline
# ---------------------------------------------------------------------------

class TestNormalBaselinePipeline:
    def test_normal_baseline_execution(self, trained_detector: AnomalyDetector):
        readings = load_dataset("normal_data.json")
        assert len(readings) == 1800

        fe = FeatureExtractor()
        re = RuleEngine()

        stage1_vectors: List[FeatureVector] = []
        stage2_results: List[AnomalyResult] = []
        stage3_results: List[RuleEvaluationResult] = []

        for r in readings:
            fv = fe.process(r)
            stage1_vectors.append(fv)

            anom_res = trained_detector.predict(fv, strict=False)
            stage2_results.append(anom_res)

            rule_res = re.evaluate(fv)
            stage3_results.append(rule_res)

        # Stage 1 assertions
        assert len(stage1_vectors) == 1800
        # Warmup rows 0 and 1 have incomplete rate/rolling features
        assert stage2_results[0].model_status == "insufficient_history"
        assert stage2_results[1].model_status == "insufficient_history"

        # Stage 2 evaluated readings: 1798
        eval_s2 = [res for res in stage2_results if res.model_status != "insufficient_history"]
        assert len(eval_s2) == 1798

        anom_count = sum(1 for res in eval_s2 if res.is_anomaly)
        anom_pct = anom_count / len(eval_s2) * 100.0
        # Validate baseline anomaly rate is around 10%
        assert 8.0 <= anom_pct <= 12.0
        assert anom_count == 180

        # Mean decision score should be positive (inlier zone)
        scores = [res.anomaly_score for res in eval_s2]
        assert np.mean(scores) > 0.03

        # Stage 3 assertions: Zero violations on normal baseline
        violations_count = sum(1 for res in stage3_results if res.has_violations)
        assert violations_count == 0
        crit_count = sum(1 for res in stage3_results if res.engine_status == "critical")
        assert crit_count == 0


# ---------------------------------------------------------------------------
# Test 2: Degradation Pipeline
# ---------------------------------------------------------------------------

class TestDegradationPipeline:
    def test_degradation_chronology_and_evidence(self, trained_detector: AnomalyDetector):
        readings = load_dataset("degradation_data.json")
        assert len(readings) == 60

        fe = FeatureExtractor()
        re = RuleEngine()

        first_violations = {}

        for idx, r in enumerate(readings):
            fv = fe.process(r)
            anom_res = trained_detector.predict(fv, strict=False)
            rule_res = re.evaluate(fv)

            for v in rule_res.violations:
                if v.rule_id not in first_violations:
                    first_violations[v.rule_id] = {
                        "index": idx,
                        "anomaly_score": anom_res.anomaly_score,
                    }

        # Verify chronological emergence of degradation rules
        assert "HIGH_CURRENT" in first_violations
        assert "LOW_RPM" in first_violations
        assert "HIGH_TEMPERATURE" in first_violations
        assert "CRITICAL_TEMPERATURE" in first_violations
        assert "OVERCURRENT" in first_violations

        # HIGH_CURRENT triggers before CRITICAL_TEMPERATURE
        assert first_violations["HIGH_CURRENT"]["index"] == 25
        assert first_violations["LOW_RPM"]["index"] == 26
        assert first_violations["HIGH_TEMPERATURE"]["index"] == 32
        assert first_violations["CRITICAL_TEMPERATURE"]["index"] == 54
        assert first_violations["OVERCURRENT"]["index"] == 54

        # Verify Stage 2 anomaly scores were negative during degradation phase
        assert first_violations["HIGH_CURRENT"]["anomaly_score"] < 0.0
        assert first_violations["CRITICAL_TEMPERATURE"]["anomaly_score"] < -0.10


# ---------------------------------------------------------------------------
# Test 3 & 4: Stall & Recovery Pipeline
# ---------------------------------------------------------------------------

class TestStallPipeline:
    def test_stall_progression_and_confirmation(self, trained_detector: AnomalyDetector):
        readings = load_dataset("stall_data.json")
        assert len(readings) == 45

        fe = FeatureExtractor()
        re = RuleEngine()

        first_stall_idx = None
        stall_evidence = None

        for idx, r in enumerate(readings):
            fv = fe.process(r)
            anom_res = trained_detector.predict(fv, strict=False)
            rule_res = re.evaluate(fv)

            # Check readings 0..24: normal operation, zero violations
            if idx < 25:
                assert not rule_res.has_violations, f"Unexpected violation at pre-stall reading #{idx}"

            for v in rule_res.violations:
                if v.rule_id == "FAN_STALL" and first_stall_idx is None:
                    first_stall_idx = idx
                    stall_evidence = v.evidence

        # FAN_STALL must be confirmed at reading #44 (after 3 consecutive low-RPM readings)
        assert first_stall_idx == 44
        assert stall_evidence is not None
        assert stall_evidence["fan"] is True
        assert stall_evidence["consecutive_readings"] == 3
        assert stall_evidence["rpm"] <= 150.0

    def test_stall_counter_resets_on_recovery(self):
        re = RuleEngine()
        fe = FeatureExtractor()

        # 2 readings below stall threshold
        r_low1 = TelemetryReading(fan=True, rpm=10.0, current=0.35, voltage=5.0, temp_1=28.0, temp_2=28.0)
        r_low2 = TelemetryReading(fan=True, rpm=12.0, current=0.36, voltage=5.0, temp_1=28.0, temp_2=28.0)
        re.evaluate(fe.process(r_low1))
        res2 = re.evaluate(fe.process(r_low2))
        assert "FAN_STALL" not in [v.rule_id for v in res2.violations]
        assert re.get_consecutive_stall_count("unknown") == 2

        # RPM recovers to normal speed -> counter resets
        r_rec = TelemetryReading(fan=True, rpm=1450.0, current=0.18, voltage=5.0, temp_1=28.0, temp_2=28.0)
        res_rec = re.evaluate(fe.process(r_rec))
        assert "FAN_STALL" not in [v.rule_id for v in res_rec.violations]
        assert re.get_consecutive_stall_count("unknown") == 0


# ---------------------------------------------------------------------------
# Test 5: Fan OFF Pipeline (Intentional Shutdown)
# ---------------------------------------------------------------------------

class TestFanOffPipeline:
    def test_fan_off_no_false_stall(self, trained_detector: AnomalyDetector):
        readings = load_dataset("fan_off_data.json")
        assert len(readings) == 20

        fe = FeatureExtractor()
        re = RuleEngine()

        for idx, r in enumerate(readings):
            fv = fe.process(r)
            anom_res = trained_detector.predict(fv, strict=False)
            rule_res = re.evaluate(fv)

            # Must NOT produce FAN_STALL or LOW_RPM when fan is commanded OFF
            violations = [v.rule_id for v in rule_res.violations]
            assert "FAN_STALL" not in violations, f"False stall alarm at index {idx}"
            assert "LOW_RPM" not in violations
            assert not rule_res.has_violations, f"Unexpected violation on fan off: {violations}"


# ---------------------------------------------------------------------------
# Test 6: Cross-Stage Evidence Separation & No Stage 4 Leakage
# ---------------------------------------------------------------------------

class TestCrossStageSeparation:
    def test_evidence_separation(self, trained_detector: AnomalyDetector):
        readings = load_dataset("degradation_data.json")[:5]
        fe = FeatureExtractor()
        re = RuleEngine()

        for r in readings:
            fv = fe.process(r)
            anom_res = trained_detector.predict(fv, strict=False)
            rule_res = re.evaluate(fv)

            # Assert Stage 2 and Stage 3 outputs are completely separate objects
            assert isinstance(anom_res, AnomalyResult)
            assert isinstance(rule_res, RuleEvaluationResult)

            # Assert NO TrustResult or trust score attribute exists
            assert not hasattr(anom_res, "trust_score")
            assert not hasattr(rule_res, "trust_score")
            assert not hasattr(anom_res, "decision")
            assert not hasattr(rule_res, "decision")


# ---------------------------------------------------------------------------
# Test 7: Feature Integrity & Matrix Ordering
# ---------------------------------------------------------------------------

class TestFeatureIntegrity:
    def test_all_34_features_deterministic(self, trained_detector: AnomalyDetector):
        readings = load_dataset("normal_data.json")[:20]
        fe = FeatureExtractor()

        for idx, r in enumerate(readings):
            fv = fe.process(r)
            if idx >= 2:  # after warmup
                vals = fv.to_ml_list(config.ML_FEATURE_NAMES)
                assert len(vals) == 34
                assert len(config.ML_FEATURE_NAMES) == 34

                for feat_idx, val in enumerate(vals):
                    feat_name = config.ML_FEATURE_NAMES[feat_idx]
                    assert val is not None, f"Feature {feat_name} is None at index {idx}"
                    assert isinstance(val, (float, int)), f"Feature {feat_name} is not numeric"
                    assert math.isfinite(val), f"Feature {feat_name} is not finite: {val}"


# ---------------------------------------------------------------------------
# Test 8: State Isolation Across Datasets & Devices
# ---------------------------------------------------------------------------

class TestStateIsolation:
    def test_pipeline_reset_isolates_datasets(self, trained_detector: AnomalyDetector):
        fe = FeatureExtractor()
        re = RuleEngine()

        # Run stall dataset (stalls device)
        stall_readings = load_dataset("stall_data.json")
        for r in stall_readings:
            fv = fe.process(r)
            re.evaluate(fv)

        assert re.get_consecutive_stall_count("trusttwin-plant-01") > 0

        # Reset both stateful components
        fe.reset()
        re.reset()

        assert re.get_consecutive_stall_count("trusttwin-plant-01") == 0
        assert fe.history_size == 0

        # Run fan_off dataset; must be 100% clean with zero inherited stall state
        fan_off_readings = load_dataset("fan_off_data.json")
        for r in fan_off_readings:
            fv = fe.process(r)
            res = re.evaluate(fv)
            assert not res.has_violations

    def test_multi_device_isolation(self):
        re = RuleEngine()
        fe1 = FeatureExtractor()
        fe2 = FeatureExtractor()

        r_stall = TelemetryReading(device_id="plant-A", fan=True, rpm=10.0)
        r_healthy = TelemetryReading(device_id="plant-B", fan=True, rpm=1450.0)

        # 3 low readings on plant-A
        for _ in range(3):
            re.evaluate(fe1.process(r_stall))

        # 1 reading on plant-B
        res_b = re.evaluate(fe2.process(r_healthy))

        assert re.get_consecutive_stall_count("plant-A") == 3
        assert re.get_consecutive_stall_count("plant-B") == 0
        assert not res_b.has_violations


# ---------------------------------------------------------------------------
# Test 9: Ordering & Temporal Integrity
# ---------------------------------------------------------------------------

class TestTemporalIntegrity:
    def test_timestamps_monotonically_increasing(self):
        for fname in ["normal_data.json", "degradation_data.json", "stall_data.json", "fan_off_data.json"]:
            readings = load_dataset(fname)
            for i in range(1, len(readings)):
                t_prev = readings[i - 1].effective_timestamp()
                t_curr = readings[i].effective_timestamp()
                assert t_curr >= t_prev, f"Timestamp regression in {fname} at row {i}"


# ---------------------------------------------------------------------------
# Test 10: No Model Mutation During Validation
# ---------------------------------------------------------------------------

class TestNoModelMutation:
    def test_model_artifact_unchanged(self, trained_detector: AnomalyDetector):
        meta_path = Path(config.IFOREST_METADATA_PATH)
        assert meta_path.exists()
        with open(meta_path, "r", encoding="utf-8") as f:
            meta = json.load(f)

        assert meta["n_estimators"] == config.IFOREST_N_ESTIMATORS
        assert meta["contamination"] == config.IFOREST_CONTAMINATION
        assert meta["random_state"] == config.IFOREST_RANDOM_STATE
        assert meta["feature_count"] == 34
        assert "EXCLUSIVELY on normal" in meta["training_dataset_note"]
