from app.database import get_sensor_readings
from app.trust.feature_engine import extract_features


def get_live_features(
    sensor_field: str,
    device_id: str | None = None,
    limit: int = 100
) -> dict:

    rows = get_sensor_readings(
        device_id=device_id,
        limit=limit
    )

    if not rows:
        raise ValueError("No telemetry found")

    # Database returns newest → oldest.
    # ML needs chronological order.
    rows.reverse()

    values = [
        float(row[sensor_field])
        for row in rows
        if row.get(sensor_field) is not None
    ]

    if len(values) < 5:
        raise ValueError(
            f"Not enough readings for {sensor_field}"
        )

    return extract_features(values)