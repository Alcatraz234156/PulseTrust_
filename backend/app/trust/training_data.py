from app.database import get_sensor_readings
from app.trust.feature_engine import extract_features


FEATURE_NAMES = [
    "normalized_value",
    "rate_of_change",
    "rolling_mean",
    "rolling_std",
    "deviation_from_baseline",
    "stuck_score"
]


def build_training_data(
    sensor_field: str,
    device_id: str | None = None,
    limit: int = 500,
    window_size: int = 20
) -> list[list[float]]:

    rows = get_sensor_readings(
        device_id=device_id,
        limit=limit
    )

    rows.reverse()

    values = [
        float(row[sensor_field])
        for row in rows
        if row.get(sensor_field) is not None
    ]

    if len(values) < window_size:
        raise ValueError(
            f"Need at least {window_size} readings, got {len(values)}"
        )

    samples = []

    for end in range(window_size, len(values) + 1):
        window = values[end - window_size:end]

        features = extract_features(window)

        samples.append([
            features[name]
            for name in FEATURE_NAMES
        ])

    return samples