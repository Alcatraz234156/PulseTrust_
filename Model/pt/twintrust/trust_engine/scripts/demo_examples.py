"""
demo_examples.py
================
Runs three concrete demo scenarios and prints the full feature output.

Usage
-----
    python -m trust_engine.scripts.demo_examples

or from the project root:

    python trust_engine/scripts/demo_examples.py

No arguments required.  Each example prints the raw input and every
derived feature so you can inspect the calculations.
"""

from __future__ import annotations

import sys
import os

# Allow running directly as a script from any directory
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from datetime import datetime, timezone, timedelta

from trust_engine.feature_extractor import FeatureExtractor
from trust_engine.models import TelemetryReading


# ============================================================
# EXAMPLE 1: Normal fan operation
# ============================================================
# Fan is ON, RPM healthy at 1450, temperatures stable,
# current and power nominal.
#
# Expected key features:
#   fan_int              = 1.0
#   rpm                  = 1450
#   fan_rpm_consistency  = 0.0 (rpm >= EXPECTED_FAN_RPM -- consistent)
#   temp_delta           = 0.0 (temp_1 == temp_2)
#   power_per_rpm        = 0.9 / 1450 ~= 0.000621
#   current_per_rpm      = 0.18 / 1450 ~= 0.000124
# ============================================================

def run_example_1():
    print("\n" + "=" * 60)
    print("  EXAMPLE 1: Normal fan operation")
    print("=" * 60)
    print("""
Physical situation:
  Fan is ON and spinning at healthy 1450 RPM.
  Both temperature sensors read 28 C (no thermal gradient).
  Current and power are nominal.
  No anomalies expected.

Key features to observe:
  fan_rpm_consistency  -> 0.0 (fan ON + good RPM = consistent)
  temp_delta           -> 0.0
  power_per_rpm        -> ~0.00062  W/RPM
  current_per_rpm      -> ~0.00012  A/RPM
  All rate features    -> None (only one reading, no history)
""")

    fe = FeatureExtractor()
    reading = TelemetryReading(
        device_id="trusttwin-plant-01",
        timestamp=datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
        temp_1=28.0,
        temp_2=28.0,
        rpm=1450.0,
        hall_raw=5.0,
        vibration=9.6,
        voltage=5.0,
        current=0.18,
        power=0.9,
        fan=True,
    )
    fv = fe.process(reading)
    print(fv.pretty_print())


# ============================================================
# EXAMPLE 2: Fan ON but RPM unexpectedly low
# ============================================================
# Fan is commanded ON, but RPM is only 400 (well below the
# expected 1200 for a healthy fan).
# This simulates a blockage, stall, or mechanical fault.
#
# Expected key features:
#   fan_int              = 1.0
#   rpm                  = 400
#   fan_rpm_consistency  = fan_int * max(0, 1 - 400/1200)
#                        = 1.0 * (1 - 0.333) = 0.667  <-- elevated!
#   current              = 0.40 (higher than normal -- stalled motor draws more)
#   power_per_rpm        = 2.0 / 400 = 0.005  (much higher than normal)
# ============================================================

def run_example_2():
    print("\n" + "=" * 60)
    print("  EXAMPLE 2: Fan ON but RPM unexpectedly low (stall)")
    print("=" * 60)
    print("""
Physical situation:
  Fan is commanded ON (fan=True).
  But RPM is only 400 -- well below healthy 1450.
  Current is elevated (stalled motor draws more current).
  This is the key fault scenario the Trust Engine must detect.

Key features to observe:
  fan_rpm_consistency  -> ~0.667  (fan on + low RPM = INCONSISTENT!)
  rpm                  -> 400     (vs expected ~1200-1450)
  current              -> 0.40    (higher than healthy 0.18)
  power_per_rpm        -> 0.005   (much higher than healthy ~0.00062)
  current_per_rpm      -> 0.001   (much higher than healthy ~0.00012)
""")

    fe = FeatureExtractor()
    reading = TelemetryReading(
        device_id="trusttwin-plant-01",
        timestamp=datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
        temp_1=30.0,
        temp_2=30.0,
        rpm=400.0,
        hall_raw=2.0,
        vibration=12.0,
        voltage=5.0,
        current=0.40,
        power=2.0,
        fan=True,
    )
    fv = fe.process(reading)
    print(fv.pretty_print())


# ============================================================
# EXAMPLE 3: Degrading behavior (sequence of 5 readings)
# ============================================================
# Temperature rises, current rises, RPM falls, vibration rises.
# Rate features and rolling stats should capture this trend.
#
# Expected key features across readings:
#   temp_rate    > 0 (temperature rising)
#   rpm_rate     < 0 (RPM falling)
#   current_rate > 0 (current climbing)
#   vibration_rate > 0 (vibration increasing)
#   Rolling temp_mean should increase over the sequence.
# ============================================================

def run_example_3():
    print("\n" + "=" * 60)
    print("  EXAMPLE 3: Degrading behavior (5-reading sequence)")
    print("=" * 60)
    print("""
Physical situation:
  The machine degrades over 5 readings:
    temp_1:    28 -> 30 -> 33 -> 36 -> 40  C  (rising)
    current:   0.18 -> 0.25 -> 0.32 -> 0.40 -> 0.50  A  (rising)
    rpm:       1450 -> 1300 -> 1100 -> 900 -> 700  (falling)
    vibration: 9.6 -> 10.2 -> 11.0 -> 12.0 -> 13.5  m/s^2  (rising)
  Fan stays ON throughout.

Key features to observe across readings:
  temp_rate     -> positive and increasing
  rpm_rate      -> negative (RPM declining)
  current_rate  -> positive
  vibration_rate-> positive
  Rolling means shift as more readings arrive.
  fan_rpm_consistency -> rising as RPM drops below expected.
""")

    fe = FeatureExtractor()

    # Define the degradation sequence
    scenario = [
        (28.0,  0.18, 1450, 9.6),
        (30.0,  0.25, 1300, 10.2),
        (33.0,  0.32, 1100, 11.0),
        (36.0,  0.40,  900, 12.0),
        (40.0,  0.50,  700, 13.5),
    ]

    base_time = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)

    for i, (temp, current, rpm, vibration) in enumerate(scenario):
        t = base_time + timedelta(seconds=i * 1.05)  # ~1.05s apart
        reading = TelemetryReading(
            device_id="trusttwin-plant-01",
            timestamp=t,
            temp_1=temp,
            temp_2=temp - 0.5,
            rpm=float(rpm),
            hall_raw=4.0,
            vibration=vibration,
            voltage=5.0,
            current=current,
            power=round(5.0 * current, 4),
            fan=True,
        )
        fv = fe.process(reading)
        print(f"\n--- Reading #{i} (t + {i * 1.05:.2f}s) ---")
        print(f"  INPUT:  temp={temp}C  current={current}A  rpm={rpm}  vib={vibration}")
        print(f"  temp_rate        = {_fmt(fv.derived_features.temp_rate)}")
        print(f"  rpm_rate         = {_fmt(fv.derived_features.rpm_rate)}")
        print(f"  current_rate     = {_fmt(fv.derived_features.current_rate)}")
        print(f"  vibration_rate   = {_fmt(fv.derived_features.vibration_rate)}")
        print(f"  fan_rpm_consist. = {_fmt(fv.derived_features.fan_rpm_consistency)}")
        print(f"  power_per_rpm    = {_fmt(fv.derived_features.power_per_rpm)}")
        print(f"  temp_1_mean(roll)= {_fmt(fv.derived_features.temp_1_mean)}")
        print(f"  rpm_mean(roll)   = {_fmt(fv.derived_features.rpm_mean)}")
        print(f"  history_size     = {fv.data_quality.history_size}")

    print()


def _fmt(v):
    if v is None:
        return "None (no history yet)"
    return f"{v:.6f}"


# ============================================================
# Main
# ============================================================

if __name__ == "__main__":
    print("\nTrustTwin / PulseTrust -- Feature Extraction Demo")
    print("=" * 60)
    print("Running 3 example scenarios...\n")

    run_example_1()
    run_example_2()
    run_example_3()

    print("\nDemo complete.  All feature formulas are documented in:")
    print("  trust_engine/models.py  (DerivedFeatures docstring)")
    print("  trust_engine/feature_extractor.py  (method docstrings)")
    print("  trust_engine/config.py  (all configurable parameters)")
