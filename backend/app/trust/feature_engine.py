import numpy as np


def extract_features(values: list[float]) -> dict:
    if len(values) < 5:
        raise ValueError("At least 5 readings are required")

    x = np.array(values, dtype=float)

    current = x[-1]
    mean = np.mean(x)
    std = np.std(x)

    # Prevent division by zero
    safe_std = max(std, 1e-6)

    normalized_value = (current - mean) / safe_std
    rate_of_change = current - x[-2]
    deviation_from_baseline = abs(current - mean) / safe_std

    recent = x[-5:]

    rolling_mean = np.mean(recent)
    rolling_std = np.std(recent)

    # Ratio of consecutive readings that did not change
    changes = np.abs(np.diff(x))
    unchanged_ratio = np.mean(changes < 1e-6)
    stuck_score = float(unchanged_ratio)

    return {
        "normalized_value": float(normalized_value),
        "rate_of_change": float(rate_of_change),
        "rolling_mean": float(rolling_mean),
        "rolling_std": float(rolling_std),
        "deviation_from_baseline": float(deviation_from_baseline),
        "stuck_score": stuck_score
    }