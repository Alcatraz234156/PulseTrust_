from typing import Optional


# Temporary in-memory cache.
# Later this becomes Supabase + component API + Gemini.
_sensor_cache = {}


def get_sensor_profile(sensor_model: str) -> Optional[dict]:
    key = sensor_model.strip().lower()

    return _sensor_cache.get(key)


def save_sensor_profile(sensor_model: str, profile: dict) -> dict:
    key = sensor_model.strip().lower()

    _sensor_cache[key] = profile

    return profile


def profile_exists(sensor_model: str) -> bool:
    key = sensor_model.strip().lower()

    return key in _sensor_cache