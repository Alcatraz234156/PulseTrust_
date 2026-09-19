"""
config.py
=========
All configurable parameters for the Trust Engine.

Keep every tunable number HERE so nothing is buried inside logic files.
For a hackathon demo, treat these as reasonable starting values -- not
scientifically validated safety thresholds.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Rolling / history window
# ---------------------------------------------------------------------------

# Number of past TelemetryReadings kept in the feature extractor history
# buffer. Used for rolling mean/std calculations.
ROLLING_WINDOW_SIZE: int = 10

# ---------------------------------------------------------------------------
# Rate calculation guards
# ---------------------------------------------------------------------------

# If elapsed time between two readings is below this value (seconds), rate
# features (temp_rate, rpm_rate, etc.) are set to None instead of producing
# a very large or infinite number. Handles duplicate timestamps and
# readings that arrive faster than the sensor sampling rate.
MIN_ELAPSED_SECONDS: float = 0.01

# ---------------------------------------------------------------------------
# Division-by-zero guards
# ---------------------------------------------------------------------------

# When computing power_per_rpm or current_per_rpm, if rpm is below this
# value the result is set to None to avoid infinity / numerical garbage.
MIN_RPM_FOR_RATIO: float = 1.0

# ---------------------------------------------------------------------------
# Fan / RPM consistency
# ---------------------------------------------------------------------------

# Expected RPM when the fan is commanded ON and running normally.
# fan_rpm_consistency = 0  -> no inconsistency (fan off, or fan on + good RPM)
# fan_rpm_consistency = 1  -> fan is ON but RPM is completely zero
# Values 0-1 represent partial inconsistency.
EXPECTED_FAN_RPM: float = 1200.0

# ---------------------------------------------------------------------------
# Vibration
# ---------------------------------------------------------------------------

# Document the type of vibration measurement the ESP32 currently sends.
# sqrt(ax^2 + ay^2 + az^2) includes gravity (~9.8 m/s^2 at rest).
# Future options: "gravity_compensated", "rms_variance"
VIBRATION_MEASUREMENT_TYPE: str = "gravity_inclusive_magnitude"

# ---------------------------------------------------------------------------
# Missing value policy
# ---------------------------------------------------------------------------

# How to handle missing/None raw sensor values:
#   "skip"  -> feature is set to None (safe default; no fabrication)
#   "zero"  -> missing values are replaced with 0.0 (may distort physics)
#   "last"  -> missing values are replaced with the last known value
MISSING_VALUE_POLICY: str = "skip"

# ---------------------------------------------------------------------------
# ML feature list
# ---------------------------------------------------------------------------
# Explicit ordered list of feature names that will be fed to Isolation Forest.
# Defined here so the AnomalyDetector always uses the same feature set as
# the FeatureExtractor -- no silent mismatches.
#
# Rules:
#   - hall_raw is NOT included (raw ADC reading, not a machine-state variable)
#   - device_id and timestamps are NOT included (metadata)
#   - current_vs_rpm_ratio and power_vs_rpm_ratio are redundant duplicates of
#     current_per_rpm and power_per_rpm and are omitted from ML_FEATURE_NAMES.

ML_FEATURE_NAMES: list[str] = [
    # raw physical state
    "temp_1",
    "temp_2",
    "rpm",
    "vibration",
    "voltage",
    "current",
    "power",
    "fan_int",
    # temperature derived
    "temp_delta",
    "temp_avg",
    "temp_rate",
    # rpm derived
    "rpm_delta",
    "rpm_rate",
    # electrical derived
    "current_delta",
    "current_rate",
    "power_delta",
    "power_rate",
    "power_per_rpm",
    "current_per_rpm",
    # vibration derived
    "vibration_delta",
    "vibration_rate",
    # rolling statistics (window = ROLLING_WINDOW_SIZE)
    "temp_1_mean",
    "temp_1_std",
    "temp_2_mean",
    "temp_2_std",
    "rpm_mean",
    "rpm_std",
    "current_mean",
    "current_std",
    "vibration_mean",
    "vibration_std",
    "power_mean",
    "power_std",
    # cross-sensor consistency
    "fan_rpm_consistency",
]

# ---------------------------------------------------------------------------
# Isolation Forest Configuration (Stage 2)
# ---------------------------------------------------------------------------

# Number of trees in the Isolation Forest ensemble.
IFOREST_N_ESTIMATORS: int = 150

# Expected contamination in training data. Set to "auto" initially as we train
# exclusively on verified clean normal telemetry (normal_data.json) and should
# not arbitrarily force 2% or 5% of healthy normal data to be labeled anomalous.
IFOREST_CONTAMINATION: str | float = "auto"

# Random seed for reproducible training and holdout splitting.
IFOREST_RANDOM_STATE: int = 42

# Fraction of normal dataset to hold out as a false-alarm/sanity check.
# Note: This is strictly a sanity check on normal data, NOT an accuracy metric.
IFOREST_HOLDOUT_SPLIT: float = 0.20

# Number of initial readings to skip as warm-up during training pipeline.
# FeatureExtractor requires at least 2 readings for rates/deltas and rolling stats.
# Default is 2 (minimal incomplete rows dropped), or up to ROLLING_WINDOW_SIZE.
IFOREST_WARMUP_DROP_COUNT: int = 2

# Path where trained model and metadata are saved.
IFOREST_MODEL_DIR: str = "models"
IFOREST_MODEL_PATH: str = "models/isolation_forest.joblib"
IFOREST_METADATA_PATH: str = "models/isolation_forest_metadata.json"

# Default training data path.
TRAIN_DATA_PATH: str = "trust_engine/data/normal_data.json"

# ---------------------------------------------------------------------------
# Rule Engine Configuration (Stage 3)
# ---------------------------------------------------------------------------
# All thresholds below are initial engineering/demo calibration values for the
# TrustTwin plant simulator. They are NOT certified safety limits and should
# be calibrated against specific hardware before production or critical use.

# Temperature limits (°C)
RULE_TEMP_WARNING: float = 31.0       # Elevated operating temperature
RULE_TEMP_CRITICAL: float = 33.5      # Severe overtemperature limit
RULE_TEMP_DISAGREEMENT_THRESHOLD: float = 2.0  # Max acceptable gap between temp_1 and temp_2

# Electrical current limits (Amperes)
RULE_CURRENT_WARNING: float = 0.28    # Abnormally elevated current draw
RULE_CURRENT_CRITICAL: float = 0.40   # Severe overcurrent / mechanical stall draw

# RPM operational limits
RULE_RPM_STALL_THRESHOLD: float = 150.0   # RPM - below this with fan=ON indicates stall
RULE_RPM_LOW_THRESHOLD: float = 1000.0    # RPM - below this with fan=ON indicates degraded speed
RULE_UNEXPECTED_RPM_FAN_OFF_THRESHOLD: float = 50.0  # RPM - rotation while fan commanded OFF

# Stateful confirmation
RULE_FAN_STALL_CONFIRMATION_COUNT: int = 3  # Consecutive readings below stall threshold to confirm FAN_STALL

# Sensor physical plausibility bounds (Data quality sanity)
RULE_VALID_TEMP_MIN: float = -40.0
RULE_VALID_TEMP_MAX: float = 125.0
RULE_VALID_VOLTAGE_MIN: float = 0.0
RULE_VALID_VOLTAGE_MAX: float = 24.0
RULE_VALID_CURRENT_MIN: float = 0.0
RULE_VALID_CURRENT_MAX: float = 5.0
RULE_VALID_RPM_MIN: float = 0.0
RULE_VALID_POWER_MIN: float = 0.0

# ---------------------------------------------------------------------------
# Trust Engine Configuration (Stage 4)
# ---------------------------------------------------------------------------
# All thresholds and penalties below are initial engineering/demo calibration
# parameters. They are NOT certified safety thresholds and should be tuned
# and validated against specific hardware before critical operational use.

# Base trust score from which penalties are subtracted
TRUST_BASE_SCORE: float = 100.0

# Stage 2 Anomaly penalties
TRUST_ANOMALY_BASE_PENALTY: float = 15.0       # Deducted when Isolation Forest flags is_anomaly=True
TRUST_ANOMALY_SEVERE_THRESHOLD: float = -0.15   # Anomaly score threshold for severe anomaly bonus
TRUST_ANOMALY_SEVERE_BONUS: float = 10.0        # Additional penalty when anomaly_score < TRUST_ANOMALY_SEVERE_THRESHOLD
TRUST_MAX_ANOMALY_PENALTY: float = 25.0         # Upper bound on anomaly-sourced penalty

# Stage 3 Rule penalties
TRUST_WARNING_PENALTY: float = 10.0             # Deducted per WARNING rule violation
TRUST_CRITICAL_PENALTY: float = 30.0            # Deducted per CRITICAL rule violation
TRUST_MAX_WARNING_PENALTY: float = 25.0         # Upper bound on accumulated warning penalties

# Double-counting mitigation factor
# When critical physical rules trigger, the event is already physically explained.
# The statistical anomaly penalty is scaled by this factor (e.g. 0.5) to prevent double counting.
TRUST_DOUBLE_COUNT_REDUCTION: float = 0.5

# Temporal / Degradation penalties
TRUST_DEGRADATION_PENALTY: float = 8.0          # Deducted per persistent adverse trend signal
TRUST_MAX_DEGRADATION_PENALTY: float = 15.0     # Upper bound on temporal degradation penalties

# Physical rate thresholds for degradation detection (from DerivedFeatures)
TRUST_TEMP_RATE_THRESHOLD: float = 0.05         # °C/s - sustained temperature rise
TRUST_RPM_RATE_THRESHOLD: float = -10.0         # RPM/s - sustained RPM drop (negative)
TRUST_CURRENT_RATE_THRESHOLD: float = 0.005     # A/s - sustained current rise
TRUST_VIBRATION_RATE_THRESHOLD: float = 0.1     # m/s^2/s - sustained vibration rise

# Temporal persistence: adverse temporal signal must persist for N consecutive
# readings before it is allowed to contribute to DEGRADING state classification.
# This prevents single-reading derivative jitter from causing false DEGRADING on
# healthy baseline data. Set to 1 to disable persistence (original behavior).
TRUST_DEGRADATION_PERSISTENCE_COUNT: int = 3

# Machine state determination thresholds
TRUST_FAULT_THRESHOLD: float = 30.0             # Trust score <= this triggers FAULT state
TRUST_CAUTION_THRESHOLD: float = 75.0           # Trust score <= this triggers CAUTION (if no fault/degrading)

# Operational decision thresholds
TRUST_ALLOW_THRESHOLD: float = 75.0             # Minimum trust score for ALLOW (without active warnings/faults)
TRUST_WARN_THRESHOLD: float = 30.0              # Minimum trust score for WARN (below this is BLOCK)

