"""
synthetic_generator.py
======================
Generates synthetic telemetry datasets for testing the Trust Engine
WITHOUT needing a real ESP32, Supabase connection, or FastAPI backend.

Three scenarios are built in:

  generate_normal_sequence()     -- healthy fan running at steady state
  generate_fan_stall_sequence()  -- fan commanded ON but RPM drops to near zero
  generate_degradation_sequence()-- gradual: temp UP, current UP, RPM DOWN

Usage
-----
    from trust_engine.data.synthetic_generator import (
        generate_normal_sequence,
        generate_fan_stall_sequence,
        generate_degradation_sequence,
        sequence_to_json,
    )

    readings = generate_normal_sequence(n=20)
    print(sequence_to_json(readings))

All readings include plausible timestamps spaced ~1 second apart with small
jitter, mimicking real-world irregular ESP32 sampling.
"""

from __future__ import annotations

import json
import math
import random
from datetime import datetime, timedelta, timezone
from typing import List

from ..models import TelemetryReading


def _base_time() -> datetime:
    """Return a fixed base timestamp (2024-01-01 00:00:00 UTC) for reproducibility."""
    return datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc)


def _jitter(base: float, pct: float = 0.02, rng: random.Random = None) -> float:
    """Add small multiplicative noise to a value.  pct=0.02 means +/-2%."""
    r = rng or random
    return base * (1.0 + r.uniform(-pct, pct))


# ---------------------------------------------------------------------------
# Scenario 1: Normal healthy operation
# ---------------------------------------------------------------------------

def generate_normal_sequence(
    n: int = 20,
    interval_seconds: float = 1.0,
    seed: int = 42,
    device_id: str = "trusttwin-plant-01",
) -> List[TelemetryReading]:
    """
    Generate n telemetry readings representing normal, healthy fan operation.

    Physical model
    --------------
    - Fan is ON throughout
    - RPM steady at ~1450 (with small noise)
    - Temperatures stable at ~28 C (with small noise)
    - Current ~0.18 A, Power ~0.9 W (with small noise)
    - Vibration ~9.6 m/s^2 (gravity-inclusive magnitude, slightly noisy)

    Parameters
    ----------
    n : int
        Number of readings.
    interval_seconds : float
        Approximate time between readings. Small random jitter is added.
    seed : int
        Random seed for reproducibility.

    Returns
    -------
    List[TelemetryReading]
    """
    rng = random.Random(seed)
    readings = []
    t = _base_time()

    for i in range(n):
        readings.append(TelemetryReading(
            device_id=device_id,
            timestamp=t,
            temp_1=round(_jitter(28.0, 0.01, rng), 2),
            temp_2=round(_jitter(27.8, 0.01, rng), 2),
            rpm=round(_jitter(1450.0, 0.02, rng)),
            hall_raw=round(rng.uniform(0, 10), 1),
            vibration=round(_jitter(9.6, 0.02, rng), 3),
            voltage=round(_jitter(5.0, 0.005, rng), 3),
            current=round(_jitter(0.18, 0.03, rng), 4),
            power=round(_jitter(0.9, 0.03, rng), 4),
            fan=True,
        ))
        # Irregular interval: base +/- 10%
        jitter_s = interval_seconds * rng.uniform(0.9, 1.1)
        t = t + timedelta(seconds=jitter_s)

    return readings


# ---------------------------------------------------------------------------
# Scenario 2: Fan ON but RPM unexpectedly low (stall scenario)
# ---------------------------------------------------------------------------

def generate_fan_stall_sequence(
    n: int = 20,
    interval_seconds: float = 1.0,
    seed: int = 7,
    device_id: str = "trusttwin-plant-01",
) -> List[TelemetryReading]:
    """
    Generate readings where the fan is commanded ON but RPM drops sharply.

    Physical model
    --------------
    - Fan is ON throughout (fan=True)
    - RPM starts at 1450, then drops to ~100-400 from reading 5 onward
      (simulating a stall / blockage / mechanical failure)
    - Current spikes slightly when the motor stalls (more current draw)
    - Temperature rises due to reduced airflow
    - Vibration increases (irregular mechanical motion during stall)

    Key feature to watch
    --------------------
    fan_rpm_consistency should rise sharply around reading 5.
    """
    rng = random.Random(seed)
    readings = []
    t = _base_time()

    for i in range(n):
        # Normal until reading 5, then stall
        if i < 5:
            rpm = round(_jitter(1450.0, 0.02, rng))
            current = round(_jitter(0.18, 0.03, rng), 4)
            temp = round(_jitter(28.0, 0.01, rng), 2)
            vibration = round(_jitter(9.6, 0.02, rng), 3)
            power = round(_jitter(0.9, 0.03, rng), 4)
        else:
            # Stall: RPM low, current higher, temp rising, vibration higher
            rpm = round(_jitter(250.0, 0.15, rng))           # stalled
            current = round(_jitter(0.40, 0.05, rng), 4)     # higher draw
            temp = round(28.0 + (i - 5) * 0.3 + rng.uniform(-0.1, 0.1), 2)  # rising
            vibration = round(_jitter(12.0, 0.05, rng), 3)   # rougher
            power = round(current * 5.0, 4)

        readings.append(TelemetryReading(
            device_id=device_id,
            timestamp=t,
            temp_1=temp,
            temp_2=round(temp - 0.2 + rng.uniform(-0.05, 0.05), 2),
            rpm=rpm,
            hall_raw=round(rng.uniform(0, 10), 1),
            vibration=vibration,
            voltage=round(_jitter(5.0, 0.005, rng), 3),
            current=current,
            power=power,
            fan=True,   # fan is commanded ON the whole time
        ))
        jitter_s = interval_seconds * rng.uniform(0.9, 1.1)
        t = t + timedelta(seconds=jitter_s)

    return readings


# ---------------------------------------------------------------------------
# Scenario 3: Gradual degradation (temp UP, current UP, RPM DOWN)
# ---------------------------------------------------------------------------

def generate_degradation_sequence(
    n: int = 30,
    interval_seconds: float = 1.0,
    seed: int = 99,
    device_id: str = "trusttwin-plant-01",
) -> List[TelemetryReading]:
    """
    Generate a sequence showing gradual machine degradation.

    Physical model
    --------------
    Over n readings:
      - temp_1 and temp_2 increase linearly from 28 to 42 C
      - current increases from 0.18 A to 0.55 A (motor drawing more)
      - rpm decreases from 1450 to 800 (motor slowing down)
      - vibration increases from 9.6 to 14.0 (increasing instability)
      - power = voltage * current (physically consistent)
      - fan stays ON

    Key features to watch
    ---------------------
    temp_rate > 0
    rpm_rate < 0
    current_rate > 0
    vibration_rate > 0
    Rolling means drift from initial values.
    """
    rng = random.Random(seed)
    readings = []
    t = _base_time()

    for i in range(n):
        progress = i / max(n - 1, 1)  # 0.0 at start, 1.0 at end

        temp_base = 28.0 + progress * 14.0        # 28 -> 42
        rpm_base = 1450.0 - progress * 650.0      # 1450 -> 800
        current_base = 0.18 + progress * 0.37     # 0.18 -> 0.55
        vibration_base = 9.6 + progress * 4.4     # 9.6 -> 14.0
        voltage_val = round(_jitter(5.0, 0.005, rng), 3)
        power_val = round(voltage_val * current_base * _jitter(1.0, 0.02, rng), 4)

        readings.append(TelemetryReading(
            device_id=device_id,
            timestamp=t,
            temp_1=round(_jitter(temp_base, 0.01, rng), 2),
            temp_2=round(_jitter(temp_base - 0.5, 0.01, rng), 2),
            rpm=max(0, round(_jitter(rpm_base, 0.02, rng))),
            hall_raw=round(rng.uniform(0, 10), 1),
            vibration=round(_jitter(vibration_base, 0.02, rng), 3),
            voltage=voltage_val,
            current=round(_jitter(current_base, 0.03, rng), 4),
            power=power_val,
            fan=True,
        ))
        jitter_s = interval_seconds * rng.uniform(0.9, 1.1)
        t = t + timedelta(seconds=jitter_s)

    return readings


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def sequence_to_json(readings: List[TelemetryReading], indent: int = 2) -> str:
    """Serialize a list of TelemetryReadings to a JSON string."""
    data = []
    for r in readings:
        d = r.model_dump()
        # datetime -> ISO string
        if d.get("timestamp"):
            d["timestamp"] = d["timestamp"].isoformat()
        data.append(d)
    return json.dumps(data, indent=indent)


def readings_from_json(json_str: str) -> List[TelemetryReading]:
    """
    Deserialize a JSON string (array of telemetry objects) into TelemetryReadings.

    This is also the entry point for loading from a .json file:

        with open("my_data.json") as f:
            readings = readings_from_json(f.read())
    """
    data = json.loads(json_str)
    if isinstance(data, dict):
        data = [data]  # single reading wrapped in a list
    return [TelemetryReading(**item) for item in data]


def readings_from_csv(csv_path: str) -> List[TelemetryReading]:
    """
    Load telemetry readings from a CSV file.

    The CSV must have a header row matching TelemetryReading field names.
    Boolean columns (fan) accept: true/false, 1/0, yes/no (case-insensitive).
    Numeric columns accept empty string as None.

    Parameters
    ----------
    csv_path : str
        Path to the CSV file.

    Returns
    -------
    List[TelemetryReading]
    """
    import csv

    readings = []
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            cleaned: dict = {}
            for k, v in row.items():
                k = k.strip()
                v = v.strip() if v else ""
                if v == "":
                    cleaned[k] = None
                elif k == "fan":
                    cleaned[k] = v.lower() in ("true", "1", "yes")
                else:
                    try:
                        cleaned[k] = float(v)
                    except ValueError:
                        cleaned[k] = v  # keep as string (device_id, timestamp, etc.)
            readings.append(TelemetryReading(**cleaned))
    return readings
