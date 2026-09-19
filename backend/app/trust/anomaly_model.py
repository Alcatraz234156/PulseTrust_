import os
from pathlib import Path
import joblib
import numpy as np

from sklearn.ensemble import IsolationForest

from app.trust.feature_engine import extract_features
from app.trust.training_data import FEATURE_NAMES
from app.trust.synthetic_data import generate_temperature_baseline


MODEL_DIR = Path(__file__).resolve().parents[2] / "models"


def build_feature_windows(
    values: list[float],
    window_size: int = 20
) -> np.ndarray:

    samples = []

    for end in range(window_size, len(values) + 1):
        window = values[end - window_size:end]

        features = extract_features(window)

        samples.append([
            features[name]
            for name in FEATURE_NAMES
        ])

    return np.array(samples, dtype=float)


def train_temperature_model():
    values = generate_temperature_baseline(
        samples=1000
    )

    X = build_feature_windows(values)

    model = IsolationForest(
        n_estimators=200,
        contamination=0.03,
        random_state=42
    )

    model.fit(X)

    os.makedirs(MODEL_DIR, exist_ok=True)

    path = os.path.join(
        MODEL_DIR,
        "temperature_isolation_forest.joblib"
    )

    joblib.dump(model, path)

    return model, X, path
