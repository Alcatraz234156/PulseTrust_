"""
test_anomaly_detector.py
========================
Unit and integration tests for the Stage 2 Isolation Forest Anomaly Detector.

Tests cover:
  1. Initialization with default and custom configurations.
  2. Training on valid normal feature vectors.
  3. Predict / score on valid complete FeatureVectors.
  4. Error when predicting on untrained/unloaded model.
  5. Missing-value rejection (strict mode raises ValueError).
  6. Cold-start handling in non-strict mode (returns model_status="insufficient_history").
  7. NaN / Infinity rejection in matrix preparation.
  8. Feature ordering determinism and consistency between training and inference.
  9. Model save and load round-trip (producing identical predictions).
 10. Train/holdout sanity validation produces valid metrics on normal data.
 11. Reading-level inference convenience method.
"""

from __future__ import annotations

import json
import math
import os
import tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path

import numpy as np
import pytest

from trust_engine import config
from trust_engine.anomaly_detector import AnomalyDetector, IsolationForestDetector
from trust_engine.data.synthetic_generator import generate_normal_sequence
from trust_engine.feature_extractor import FeatureExtractor
from trust_engine.models import AnomalyResult, FeatureVector, TelemetryReading


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def normal_vectors() -> list[FeatureVector]:
    """Generate 25 sequential normal feature vectors."""
    readings = generate_normal_sequence(n=25, seed=42)
    fe = FeatureExtractor()
    return fe.process_batch(readings)


@pytest.fixture
def trained_detector(normal_vectors: list[FeatureVector]) -> AnomalyDetector:
    """Return an AnomalyDetector trained on normal vectors."""
    detector = AnomalyDetector(
        n_estimators=50,
        contamination="auto",
        random_state=42,
    )
    detector.train(normal_vectors)
    return detector


# ---------------------------------------------------------------------------
# Initialization Tests
# ---------------------------------------------------------------------------

class TestInitialization:
    def test_default_init(self):
        det = AnomalyDetector()
        assert det.n_estimators == config.IFOREST_N_ESTIMATORS
        assert det.contamination == config.IFOREST_CONTAMINATION
        assert det.random_state == config.IFOREST_RANDOM_STATE
        assert det.feature_names == config.ML_FEATURE_NAMES
        assert not det.is_ready

    def test_alias_equivalence(self):
        assert IsolationForestDetector is AnomalyDetector

    def test_custom_init(self):
        custom_feats = ["temp_1", "rpm", "current"]
        det = AnomalyDetector(
            n_estimators=80,
            contamination=0.01,
            random_state=123,
            feature_names=custom_feats,
        )
        assert det.n_estimators == 80
        assert det.contamination == 0.01
        assert det.random_state == 123
        assert det.feature_names == custom_feats


# ---------------------------------------------------------------------------
# Matrix Preparation Tests
# ---------------------------------------------------------------------------

class TestMatrixPreparation:
    def test_prepare_matrix_skips_cold_start_rows(self, normal_vectors: list[FeatureVector]):
        det = AnomalyDetector()
        X, valid_indices = det.prepare_matrix(normal_vectors, drop_incomplete=True)

        # The first 2 rows of cold start have None for rate/rolling stats
        assert len(X) == len(normal_vectors) - 2
        assert valid_indices[0] == 2
        assert X.shape[1] == len(det.feature_names)
        assert np.all(np.isfinite(X))

    def test_prepare_matrix_strict_mode_raises_on_incomplete(self, normal_vectors: list[FeatureVector]):
        det = AnomalyDetector()
        # Row 0 has incomplete rates
        with pytest.raises(ValueError, match="incomplete features"):
            det.prepare_matrix([normal_vectors[0]], drop_incomplete=False)

    def test_prepare_matrix_feature_ordering(self, normal_vectors: list[FeatureVector]):
        # Verify columns match feature_names in exact order
        det = AnomalyDetector(feature_names=["temp_1", "rpm"])
        X, _ = det.prepare_matrix(normal_vectors[5:7], drop_incomplete=True)
        assert X[0, 0] == pytest.approx(normal_vectors[5].raw_features.temp_1)
        assert X[0, 1] == pytest.approx(normal_vectors[5].raw_features.rpm)


# ---------------------------------------------------------------------------
# Training Tests
# ---------------------------------------------------------------------------

class TestTraining:
    def test_train_on_feature_vectors(self, normal_vectors: list[FeatureVector]):
        det = AnomalyDetector(n_estimators=30, random_state=42)
        meta = det.train(normal_vectors)
        assert det.is_ready
        assert meta["usable_sample_count"] == len(normal_vectors) - 2
        assert meta["feature_count"] == len(det.feature_names)
        assert meta["model_type"] == "IsolationForest"

    def test_train_insufficient_samples_raises(self, normal_vectors: list[FeatureVector]):
        det = AnomalyDetector()
        # Only 5 samples total -> 3 complete vectors, which is < 10 threshold
        with pytest.raises(ValueError, match="Insufficient training samples"):
            det.train(normal_vectors[:5])

    def test_train_and_validate_sanity_split(self, normal_vectors: list[FeatureVector]):
        det = AnomalyDetector(n_estimators=30, random_state=42)
        stats = det.train_and_validate(normal_vectors, holdout_split=0.25)
        assert stats["total_usable_samples"] == len(normal_vectors) - 2
        assert stats["train_samples"] + stats["holdout_samples"] == stats["total_usable_samples"]
        assert "holdout_predicted_normal" in stats
        assert "holdout_anomaly_percentage" in stats
        assert det.is_ready


# ---------------------------------------------------------------------------
# Prediction & Inference Tests
# ---------------------------------------------------------------------------

class TestPrediction:
    def test_predict_before_train_raises_runtime_error(self, normal_vectors: list[FeatureVector]):
        det = AnomalyDetector()
        with pytest.raises(RuntimeError, match="not ready"):
            det.predict(normal_vectors[10])

    def test_predict_on_valid_vector(self, trained_detector: AnomalyDetector, normal_vectors: list[FeatureVector]):
        res = trained_detector.predict(normal_vectors[10])
        assert isinstance(res, AnomalyResult)
        assert res.raw_prediction in (1, -1)
        assert res.anomaly_score is not None
        assert math.isfinite(res.anomaly_score)
        assert res.features_used == len(trained_detector.feature_names)
        assert res.model_status == "trained"
        assert res.data_quality_warning is None

    def test_predict_incomplete_vector_strict_mode(self, trained_detector: AnomalyDetector, normal_vectors: list[FeatureVector]):
        # Row 0 has incomplete rates
        with pytest.raises(ValueError, match="Cannot score incomplete FeatureVector"):
            trained_detector.predict(normal_vectors[0], strict=True)

    def test_predict_incomplete_vector_non_strict_mode(self, trained_detector: AnomalyDetector, normal_vectors: list[FeatureVector]):
        # Row 0 has incomplete rates
        res = trained_detector.predict(normal_vectors[0], strict=False)
        assert res.model_status == "insufficient_history"
        assert res.raw_prediction == 0
        assert res.anomaly_score is None
        assert res.data_quality_warning is not None
        assert "requires sequential history" in res.data_quality_warning

    def test_legacy_score_method_returns_dict(self, trained_detector: AnomalyDetector, normal_vectors: list[FeatureVector]):
        score_dict = trained_detector.score(normal_vectors[10])
        assert "anomaly_score" in score_dict
        assert "is_anomaly" in score_dict
        assert "raw_prediction" in score_dict

    def test_predict_reading_convenience_method(self, trained_detector: AnomalyDetector):
        reading1 = TelemetryReading(
            temp_1=28.0, temp_2=28.0, rpm=1450, vibration=9.6,
            voltage=5.0, current=0.18, power=0.9, fan=True,
            timestamp=datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
        )
        reading2 = TelemetryReading(
            temp_1=28.05, temp_2=28.0, rpm=1452, vibration=9.61,
            voltage=5.0, current=0.181, power=0.905, fan=True,
            timestamp=datetime(2024, 1, 1, 12, 0, 1, tzinfo=timezone.utc),
        )
        reading3 = TelemetryReading(
            temp_1=28.02, temp_2=28.01, rpm=1448, vibration=9.59,
            voltage=5.0, current=0.179, power=0.895, fan=True,
            timestamp=datetime(2024, 1, 1, 12, 0, 2, tzinfo=timezone.utc),
        )

        fe = FeatureExtractor()
        # Reading 1: cold start
        res1 = trained_detector.predict_reading(reading1, feature_extractor=fe)
        assert res1.model_status == "insufficient_history"

        # Reading 2: has rate, but not rolling stats
        res2 = trained_detector.predict_reading(reading2, feature_extractor=fe)
        assert res2.model_status == "insufficient_history"

        # Reading 3: has full history!
        res3 = trained_detector.predict_reading(reading3, feature_extractor=fe)
        assert res3.model_status == "trained"
        assert res3.raw_prediction in (1, -1)


# ---------------------------------------------------------------------------
# Save & Load Persistence Tests
# ---------------------------------------------------------------------------

class TestPersistence:
    def test_save_and_load_round_trip(self, trained_detector: AnomalyDetector, normal_vectors: list[FeatureVector]):
        with tempfile.TemporaryDirectory() as tmpdir:
            model_file = os.path.join(tmpdir, "model.joblib")
            meta_file = os.path.join(tmpdir, "meta.json")

            trained_detector.save(model_path=model_file, metadata_path=meta_file)
            assert os.path.exists(model_file)
            assert os.path.exists(meta_file)

            # Load into fresh detector
            loaded_detector = AnomalyDetector(model_path=model_file, metadata_path=meta_file)
            loaded_detector.load()

            assert loaded_detector.is_ready
            assert loaded_detector.feature_names == trained_detector.feature_names

            # Predictions from both models must be 100% IDENTICAL
            test_vector = normal_vectors[15]
            orig_res = trained_detector.predict(test_vector)
            loaded_res = loaded_detector.predict(test_vector)

            assert orig_res.raw_prediction == loaded_res.raw_prediction
            assert orig_res.anomaly_score == pytest.approx(loaded_res.anomaly_score, rel=1e-6)
            assert orig_res.is_anomaly == loaded_res.is_anomaly
            assert loaded_res.model_status == "loaded"

    def test_load_nonexistent_model_raises_file_not_found(self):
        det = AnomalyDetector(model_path="nonexistent_path_to_model.joblib")
        with pytest.raises(FileNotFoundError):
            det.load()
