import joblib

from app.trust.feature_engine import extract_features
from app.trust.training_data import FEATURE_NAMES


MODEL_PATH = "models/temperature_isolation_forest.joblib"


def detect_anomaly(values: list[float]) -> dict:
    model = joblib.load(MODEL_PATH)

    features = extract_features(values)

    X = [[
        features[name]
        for name in FEATURE_NAMES
    ]]

    prediction = int(model.predict(X)[0])
    decision_score = float(model.decision_function(X)[0])

    return {
        "is_anomaly": prediction == -1,
        "decision_score": decision_score,
        "features": features
    }
