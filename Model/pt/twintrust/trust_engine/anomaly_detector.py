"""
anomaly_detector.py
===================
Stage 2: Isolation Forest Anomaly Detector.

Trains an unsupervised Isolation Forest on clean, normal telemetry to learn
the multivariate baseline distribution of healthy machine behavior.

Key Design Principles:
  1. TRAIN EXCLUSIVELY ON NORMAL DATA:
     Never mix degradation, stall, or fault scenarios into training.
     The model learns what "normal" looks like and flags deviations.
  2. STRICT FEATURE ORDERING:
     Feature vectors are always extracted in the exact order specified in
     config.ML_FEATURE_NAMES (and persisted in model metadata).
  3. NO SILENT FABRICATION:
     Cold-start readings with missing rate/rolling features are rejected
     or flagged explicitly rather than filled with arbitrary numbers.
  4. INTERPRETATION OF SCORES:
     - raw_prediction: 1 = normal (inlier), -1 = anomaly (outlier)
     - anomaly_score: sklearn decision_function value.
         > 0: Inlier (typical normal behavior).
         < 0: Outlier (anomalous relative to learned normal baseline).
     - It is NOT a percentage or probability of failure.
"""

from __future__ import annotations

import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import joblib
import numpy as np
from sklearn.ensemble import IsolationForest

from . import config
from .feature_extractor import FeatureExtractor
from .models import AnomalyResult, FeatureVector, TelemetryReading


class AnomalyDetector:
    """
    Unsupervised Isolation Forest detector for machine telemetry.

    Parameters
    ----------
    n_estimators : int
        Number of trees in the forest (default from config.IFOREST_N_ESTIMATORS).
    contamination : str or float
        Expected proportion of outliers in training data (default "auto").
    random_state : int
        Seed for reproducibility (default from config.IFOREST_RANDOM_STATE).
    model_path : str
        Default path to serialize/load the model.
    metadata_path : str
        Default path to serialize/load the metadata JSON.
    feature_names : list of str
        Explicit list and ordering of feature columns (default config.ML_FEATURE_NAMES).
    """

    def __init__(
        self,
        n_estimators: int = config.IFOREST_N_ESTIMATORS,
        contamination: Union[str, float] = config.IFOREST_CONTAMINATION,
        random_state: int = config.IFOREST_RANDOM_STATE,
        model_path: str = config.IFOREST_MODEL_PATH,
        metadata_path: str = config.IFOREST_METADATA_PATH,
        feature_names: Optional[List[str]] = None,
    ) -> None:
        self.n_estimators = n_estimators
        self.contamination = contamination
        self.random_state = random_state
        self.model_path = model_path
        self.metadata_path = metadata_path
        self.feature_names = list(feature_names or config.ML_FEATURE_NAMES)

        self._model: Optional[IsolationForest] = None
        self._is_trained: bool = False
        self._is_loaded: bool = False
        self._metadata: Dict[str, Any] = {}
        self._persistent_fe: FeatureExtractor = FeatureExtractor()

    # ----------------------------------------------------------------------
    # Properties & Status
    # ----------------------------------------------------------------------

    @property
    def is_ready(self) -> bool:
        """True if model is trained or loaded and ready for prediction."""
        return self._model is not None and (self._is_trained or self._is_loaded)

    @property
    def metadata(self) -> Dict[str, Any]:
        """Model metadata dict."""
        return dict(self._metadata)

    # ----------------------------------------------------------------------
    # Matrix Preparation
    # ----------------------------------------------------------------------

    def prepare_matrix(
        self,
        feature_vectors: List[FeatureVector],
        drop_incomplete: bool = True,
    ) -> Tuple[np.ndarray, List[int]]:
        """
        Convert a list of FeatureVector objects into a 2D numpy array.

        Features are extracted in the exact order of `self.feature_names`.

        Parameters
        ----------
        feature_vectors : list of FeatureVector
        drop_incomplete : bool
            If True, rows containing any None or non-finite values (such as cold-start
            history warmup rows) are skipped. If False and incomplete rows are found,
            raises ValueError.

        Returns
        -------
        X : np.ndarray of shape (n_samples, n_features)
            Clean, finite float64 array.
        valid_indices : list of int
            Original indices of the included vectors.
        """
        rows: List[List[float]] = []
        valid_indices: List[int] = []

        for idx, fv in enumerate(feature_vectors):
            vals = fv.to_ml_list(self.feature_names)
            has_none_or_inf = any(
                v is None or not math.isfinite(v) for v in vals
            )

            if has_none_or_inf:
                if not drop_incomplete:
                    missing = [
                        self.feature_names[i]
                        for i, v in enumerate(vals)
                        if v is None or not math.isfinite(v)
                    ]
                    raise ValueError(
                        f"Vector at index {idx} has incomplete features: {missing}. "
                        "Cold-start readings require sequential history."
                    )
                continue

            rows.append([float(v) for v in vals])  # type: ignore
            valid_indices.append(idx)

        if not rows:
            return np.empty((0, len(self.feature_names)), dtype=np.float64), []

        return np.array(rows, dtype=np.float64), valid_indices

    # ----------------------------------------------------------------------
    # Training
    # ----------------------------------------------------------------------

    def train(
        self,
        data: Union[List[FeatureVector], List[TelemetryReading], str, Path],
        drop_warmup: int = config.IFOREST_WARMUP_DROP_COUNT,
    ) -> Dict[str, Any]:
        """
        Train the Isolation Forest on NORMAL telemetry.

        Parameters
        ----------
        data : list of FeatureVector, list of TelemetryReading, or file path (JSON)
            Must represent ONLY clean, healthy machine behavior.
        drop_warmup : int
            Number of initial cold-start vectors to drop (default 2).

        Returns
        -------
        dict with training summary statistics.
        """
        feature_vectors = self._resolve_feature_vectors(data)

        # Build feature matrix
        X, valid_indices = self.prepare_matrix(feature_vectors, drop_incomplete=True)

        if len(X) < 10:
            raise ValueError(
                f"Insufficient training samples: only {len(X)} complete vectors extracted. "
                "Ensure sufficient telemetry is provided."
            )

        # Fit Isolation Forest
        model = IsolationForest(
            n_estimators=self.n_estimators,
            contamination=self.contamination,
            random_state=self.random_state,
        )
        model.fit(X)

        self._model = model
        self._is_trained = True
        self._is_loaded = False

        total_input_count = len(feature_vectors)
        usable_sample_count = len(X)
        warmup_dropped_count = total_input_count - usable_sample_count

        self._metadata = {
            "model_type": "IsolationForest",
            "trained_at": datetime.now(timezone.utc).isoformat(),
            "n_estimators": self.n_estimators,
            "contamination": self.contamination,
            "random_state": self.random_state,
            "feature_names": self.feature_names,
            "feature_count": len(self.feature_names),
            "total_input_count": total_input_count,
            "usable_sample_count": usable_sample_count,
            "warmup_dropped_count": warmup_dropped_count,
            "training_dataset_note": "Trained EXCLUSIVELY on normal operating baseline data.",
        }

        return self._metadata

    def train_and_validate(
        self,
        data: Union[List[FeatureVector], List[TelemetryReading], str, Path],
        holdout_split: float = config.IFOREST_HOLDOUT_SPLIT,
        random_state: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Train on (1 - holdout_split) of normal data, and validate on holdout.

        IMPORTANT SANITY-CHECK PRINCIPLE:
        Both the training and holdout partitions come EXCLUSIVELY from normal_data.json.
        The holdout validation is strictly an initial false-alarm / sanity check to
        inspect whether normal data is flagged as anomalous. It is NOT an accuracy
        score and does NOT measure fault detection.

        Returns
        -------
        dict with training and holdout validation metrics.
        """
        feature_vectors = self._resolve_feature_vectors(data)
        X, _ = self.prepare_matrix(feature_vectors, drop_incomplete=True)

        seed = random_state if random_state is not None else self.random_state
        rng = np.random.RandomState(seed)

        n_samples = len(X)
        indices = np.arange(n_samples)
        rng.shuffle(indices)

        split_idx = int(n_samples * (1.0 - holdout_split))
        train_idx = indices[:split_idx]
        holdout_idx = indices[split_idx:]

        X_train = X[train_idx]
        X_holdout = X[holdout_idx]

        # Train on train split
        model = IsolationForest(
            n_estimators=self.n_estimators,
            contamination=self.contamination,
            random_state=seed,
        )
        model.fit(X_train)

        self._model = model
        self._is_trained = True
        self._is_loaded = False

        # Evaluate on holdout normal partition
        holdout_preds = model.predict(X_holdout)
        holdout_scores = model.decision_function(X_holdout)

        holdout_normal_count = int(np.sum(holdout_preds == 1))
        holdout_anomaly_count = int(np.sum(holdout_preds == -1))
        holdout_anomaly_pct = (holdout_anomaly_count / len(X_holdout)) * 100.0

        stats = {
            "total_usable_samples": n_samples,
            "train_samples": len(X_train),
            "holdout_samples": len(X_holdout),
            "holdout_predicted_normal": holdout_normal_count,
            "holdout_predicted_anomaly": holdout_anomaly_count,
            "holdout_anomaly_percentage": round(holdout_anomaly_pct, 2),
            "holdout_mean_decision_score": round(float(np.mean(holdout_scores)), 4),
            "holdout_min_decision_score": round(float(np.min(holdout_scores)), 4),
            "holdout_max_decision_score": round(float(np.max(holdout_scores)), 4),
            "validation_note": (
                "Holdout partition contains ONLY normal baseline data. "
                "Low anomaly percentage indicates low false-alarm rate on normal operations. "
                "This is a sanity check, not a fault detection accuracy measure."
            ),
        }

        self._metadata = {
            "model_type": "IsolationForest",
            "trained_at": datetime.now(timezone.utc).isoformat(),
            "n_estimators": self.n_estimators,
            "contamination": self.contamination,
            "random_state": seed,
            "feature_names": self.feature_names,
            "feature_count": len(self.feature_names),
            "validation_stats": stats,
            "training_dataset_note": "Trained EXCLUSIVELY on normal operating baseline data.",
        }

        return stats

    # ----------------------------------------------------------------------
    # Persistence
    # ----------------------------------------------------------------------

    def save(
        self,
        model_path: Optional[str] = None,
        metadata_path: Optional[str] = None,
    ) -> Tuple[str, str]:
        """Save the trained model and metadata JSON to disk."""
        if self._model is None:
            raise RuntimeError("Cannot save: model has not been trained or loaded.")

        m_path = Path(model_path or self.model_path)
        meta_path = Path(metadata_path or self.metadata_path)

        m_path.parent.mkdir(parents=True, exist_ok=True)
        meta_path.parent.mkdir(parents=True, exist_ok=True)

        joblib.dump(self._model, m_path)

        metadata_to_save = dict(self._metadata)
        metadata_to_save["saved_at"] = datetime.now(timezone.utc).isoformat()
        metadata_to_save["model_file"] = str(m_path)
        metadata_to_save["feature_names"] = self.feature_names

        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(metadata_to_save, f, indent=2)

        return str(m_path), str(meta_path)

    def load(
        self,
        model_path: Optional[str] = None,
        metadata_path: Optional[str] = None,
    ) -> None:
        """Load a saved model and its metadata from disk."""
        m_path = Path(model_path or self.model_path)
        meta_path = Path(metadata_path or self.metadata_path)

        if not m_path.exists():
            raise FileNotFoundError(f"Model file not found at: {m_path}")

        self._model = joblib.load(m_path)
        self._is_loaded = True
        self._is_trained = False

        if meta_path.exists():
            with open(meta_path, "r", encoding="utf-8") as f:
                self._metadata = json.load(f)
            if "feature_names" in self._metadata:
                self.feature_names = self._metadata["feature_names"]
            if "n_estimators" in self._metadata:
                self.n_estimators = self._metadata["n_estimators"]
        else:
            self._metadata = {
                "model_type": "IsolationForest",
                "loaded_from": str(m_path),
                "feature_names": self.feature_names,
            }

    # ----------------------------------------------------------------------
    # Prediction / Scoring
    # ----------------------------------------------------------------------

    def predict(
        self,
        feature_vector: FeatureVector,
        strict: bool = True,
    ) -> AnomalyResult:
        """
        Evaluate a single FeatureVector.

        Parameters
        ----------
        feature_vector : FeatureVector
            Derived feature vector from FeatureExtractor.
        strict : bool
            If True (default), raises ValueError if any configured ML feature is None.
            If False, returns AnomalyResult with status 'insufficient_history'.

        Returns
        -------
        AnomalyResult
        """
        if not self.is_ready:
            raise RuntimeError(
                "AnomalyDetector is not ready. Call train() or load() before predict()."
            )

        vals = feature_vector.to_ml_list(self.feature_names)
        missing = [
            self.feature_names[i]
            for i, v in enumerate(vals)
            if v is None or not math.isfinite(v)
        ]

        if missing:
            warning_msg = (
                f"Missing {len(missing)} features ({missing[:3]}...). "
                "FeatureExtractor requires sequential history (>= 2 readings) "
                "to calculate rate, delta, and rolling features."
            )
            if strict:
                raise ValueError(
                    f"Cannot score incomplete FeatureVector: {warning_msg} "
                    "Feed readings sequentially through FeatureExtractor or pass strict=False."
                )
            return AnomalyResult(
                is_anomaly=False,
                raw_prediction=0,
                anomaly_score=None,
                normalized_score=None,
                model_status="insufficient_history",
                features_used=0,
                data_quality_warning=warning_msg,
                feature_vector=feature_vector,
            )

        row = np.array([[float(v) for v in vals]], dtype=np.float64)  # type: ignore

        pred = int(self._model.predict(row)[0])  # type: ignore
        score = float(self._model.decision_function(row)[0])  # type: ignore

        status = "trained" if self._is_trained else "loaded"
        is_anom = (pred == -1)

        return AnomalyResult(
            is_anomaly=is_anom,
            raw_prediction=pred,
            anomaly_score=score,
            normalized_score=score,
            model_status=status,
            features_used=len(self.feature_names),
            data_quality_warning=None,
            feature_vector=feature_vector,
        )

    def score(self, feature_vector: FeatureVector) -> Dict[str, Optional[float]]:
        """
        Legacy stub interface for compatibility with future TrustEngine.

        Returns
        -------
        dict with keys:
            "anomaly_score": float or None
            "is_anomaly": bool
            "raw_prediction": int
        """
        res = self.predict(feature_vector, strict=False)
        return {
            "anomaly_score": res.anomaly_score,
            "is_anomaly": res.is_anomaly,
            "raw_prediction": res.raw_prediction,
        }

    def predict_reading(
        self,
        reading: TelemetryReading,
        feature_extractor: Optional[FeatureExtractor] = None,
        strict: bool = False,
    ) -> AnomalyResult:
        """
        Convenience method to process a TelemetryReading through a stateful
        FeatureExtractor and score the resulting FeatureVector.

        Parameters
        ----------
        reading : TelemetryReading
            Raw incoming reading.
        feature_extractor : Optional[FeatureExtractor]
            Stateful extractor to use. If None, uses internal persistent extractor.
        strict : bool
            If False (default), cold-start readings gracefully return an
            AnomalyResult with model_status='insufficient_history'.

        Returns
        -------
        AnomalyResult
        """
        fe = feature_extractor or self._persistent_fe
        fv = fe.process(reading)
        return self.predict(fv, strict=strict)

    def predict_batch(
        self,
        feature_vectors: List[FeatureVector],
        strict: bool = False,
    ) -> List[AnomalyResult]:
        """Score a list of FeatureVectors in order."""
        return [self.predict(fv, strict=strict) for fv in feature_vectors]

    def reset_history(self) -> None:
        """Reset internal persistent feature extractor history."""
        self._persistent_fe.reset()

    # ----------------------------------------------------------------------
    # Internal Helpers
    # ----------------------------------------------------------------------

    def _resolve_feature_vectors(
        self,
        data: Union[List[FeatureVector], List[TelemetryReading], str, Path],
    ) -> List[FeatureVector]:
        """Convert various input formats into a list of FeatureVectors."""
        if isinstance(data, (str, Path)):
            path = Path(data)
            if not path.exists():
                raise FileNotFoundError(f"Data file not found: {path}")
            with open(path, "r", encoding="utf-8") as f:
                raw_json = json.load(f)
            if isinstance(raw_json, dict):
                raw_json = [raw_json]
            readings = [TelemetryReading(**item) for item in raw_json]
            fe = FeatureExtractor()
            return fe.process_batch(readings)

        if not data:
            return []

        if isinstance(data[0], FeatureVector):
            return data  # type: ignore

        if isinstance(data[0], TelemetryReading):
            fe = FeatureExtractor()
            return fe.process_batch(data)  # type: ignore

        raise TypeError(f"Unsupported data type: {type(data)}")


# Convenient alias
IsolationForestDetector = AnomalyDetector
