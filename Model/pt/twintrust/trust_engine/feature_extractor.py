"""
feature_extractor.py
====================
The first computational stage of the Trust Engine.

FeatureExtractor converts a raw TelemetryReading into a rich FeatureVector
containing:
  - cleaned raw physical values
  - derived / computed features (deltas, rates, ratios)
  - rolling window statistics
  - cross-sensor consistency features
  - data quality flags

Usage
-----
Single reading::

    from trust_engine.feature_extractor import FeatureExtractor
    from trust_engine.models import TelemetryReading

    fe = FeatureExtractor()
    reading = TelemetryReading(temp_1=28.0, temp_2=27.5, rpm=1200, ...)
    fv = fe.process(reading)
    print(fv.pretty_print())

Multiple readings (stateful -- history is kept)::

    fe = FeatureExtractor()
    for reading in readings:
        fv = fe.process(reading)

Reset history::

    fe.reset()
"""

from __future__ import annotations

import math
from collections import deque
from datetime import datetime, timezone
from typing import Deque, Dict, List, Optional, Tuple

from . import config
from .models import (
    DataQuality,
    DerivedFeatures,
    FeatureMetadata,
    FeatureVector,
    RawFeatures,
    TelemetryReading,
)


# ---------------------------------------------------------------------------
# Internal history record
# ---------------------------------------------------------------------------

class _HistoryRecord:
    """Compact snapshot of one reading stored in the rolling buffer."""

    __slots__ = (
        "timestamp",
        "temp_1", "temp_2", "temp_avg",
        "rpm", "vibration",
        "voltage", "current", "power",
        "fan_int",
    )

    def __init__(
        self,
        timestamp: datetime,
        temp_1: Optional[float],
        temp_2: Optional[float],
        rpm: Optional[float],
        vibration: Optional[float],
        voltage: Optional[float],
        current: Optional[float],
        power: Optional[float],
        fan_int: Optional[float],
    ) -> None:
        self.timestamp = timestamp
        self.temp_1 = temp_1
        self.temp_2 = temp_2
        self.temp_avg = _safe_avg(temp_1, temp_2)
        self.rpm = rpm
        self.vibration = vibration
        self.voltage = voltage
        self.current = current
        self.power = power
        self.fan_int = fan_int


# ---------------------------------------------------------------------------
# FeatureExtractor
# ---------------------------------------------------------------------------

class FeatureExtractor:
    """
    Converts raw TelemetryReading objects into FeatureVector objects.

    Stateful: maintains a rolling history buffer so that delta, rate, and
    rolling-window features can be computed across sequential readings.

    Parameters
    ----------
    window_size : int
        Number of past readings to keep for rolling statistics.
        Defaults to config.ROLLING_WINDOW_SIZE.
    min_elapsed_seconds : float
        Minimum elapsed time (seconds) between readings to compute rate features.
        Prevents division by near-zero when timestamps are very close.
    min_rpm_for_ratio : float
        Minimum RPM to compute per-RPM ratios (power_per_rpm, current_per_rpm).
    expected_fan_rpm : float
        Expected RPM when the fan is ON and healthy. Used for fan_rpm_consistency.
    missing_value_policy : str
        How to handle None sensor values: "skip" | "zero" | "last".
    """

    def __init__(
        self,
        window_size: int = config.ROLLING_WINDOW_SIZE,
        min_elapsed_seconds: float = config.MIN_ELAPSED_SECONDS,
        min_rpm_for_ratio: float = config.MIN_RPM_FOR_RATIO,
        expected_fan_rpm: float = config.EXPECTED_FAN_RPM,
        missing_value_policy: str = config.MISSING_VALUE_POLICY,
    ) -> None:
        self.window_size = window_size
        self.min_elapsed_seconds = min_elapsed_seconds
        self.min_rpm_for_ratio = min_rpm_for_ratio
        self.expected_fan_rpm = expected_fan_rpm
        self.missing_value_policy = missing_value_policy

        # Rolling history buffer (most-recent reading is at the right)
        self._history: Deque[_HistoryRecord] = deque(maxlen=window_size)
        self._reading_index: int = 0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def process(self, reading: TelemetryReading) -> FeatureVector:
        """
        Process one TelemetryReading and return a FeatureVector.

        The internal history buffer is updated after features are extracted,
        so the current reading contributes to future rolling stats but does
        not count itself in the current window.

        Parameters
        ----------
        reading : TelemetryReading
            Raw sensor packet from the ESP32.

        Returns
        -------
        FeatureVector
            All features, metadata, and data quality flags.
        """
        ts = reading.effective_timestamp()
        warnings: List[str] = []
        missing_fields: List[str] = []
        imputed_fields: List[str] = []

        # ---- Step 1: resolve raw values (apply missing-value policy) --------
        raw = self._resolve_raw(reading, missing_fields, imputed_fields, warnings)

        # ---- Step 2: determine previous reading (if any) --------------------
        prev: Optional[_HistoryRecord] = self._history[-1] if self._history else None
        elapsed: Optional[float] = None
        rate_ok = False

        if prev is not None:
            elapsed = (ts - prev.timestamp).total_seconds()
            if elapsed < 0:
                warnings.append(
                    f"Timestamp went backwards by {-elapsed:.3f}s. "
                    "Rate features set to None."
                )
                elapsed = None
            elif elapsed < self.min_elapsed_seconds:
                warnings.append(
                    f"Elapsed time {elapsed:.4f}s < MIN_ELAPSED_SECONDS "
                    f"({self.min_elapsed_seconds}s). Rate features set to None."
                )
                elapsed = None
            else:
                rate_ok = True

        # ---- Step 3: compute derived features --------------------------------
        derived = self._compute_derived(raw, prev, elapsed, rate_ok)

        # ---- Step 4: compute rolling stats -----------------------------------
        rolling_ok = len(self._history) >= 2
        self._fill_rolling(derived, rolling_ok)

        # ---- Step 5: cross-sensor consistency --------------------------------
        self._fill_cross_sensor(derived, raw)

        # ---- Step 6: assemble output ----------------------------------------
        dq = DataQuality(
            missing_fields=missing_fields,
            imputed_fields=imputed_fields,
            rate_features_available=rate_ok,
            rolling_features_available=rolling_ok,
            elapsed_seconds=elapsed,
            history_size=len(self._history),
            warnings=warnings,
        )

        metadata = FeatureMetadata(
            device_id=reading.device_id,
            timestamp=ts,
            reading_index=self._reading_index,
            hall_raw=reading.hall_raw,
        )

        fv = FeatureVector(
            metadata=metadata,
            raw_features=raw,
            derived_features=derived,
            data_quality=dq,
        )

        # ---- Step 7: update history (AFTER output, so window excludes self) -
        self._history.append(
            _HistoryRecord(
                timestamp=ts,
                temp_1=raw.temp_1,
                temp_2=raw.temp_2,
                rpm=raw.rpm,
                vibration=raw.vibration,
                voltage=raw.voltage,
                current=raw.current,
                power=raw.power,
                fan_int=raw.fan_int,
            )
        )
        self._reading_index += 1
        return fv

    def process_batch(self, readings: List[TelemetryReading]) -> List[FeatureVector]:
        """
        Process a list of readings in order.

        The history buffer accumulates across the batch, so later readings
        benefit from the history of earlier ones.
        """
        return [self.process(r) for r in readings]

    def reset(self) -> None:
        """Clear the history buffer and reset the reading index."""
        self._history.clear()
        self._reading_index = 0

    @property
    def history_size(self) -> int:
        """Current number of readings in the history buffer."""
        return len(self._history)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _resolve_raw(
        self,
        reading: TelemetryReading,
        missing_fields: List[str],
        imputed_fields: List[str],
        warnings: List[str],
    ) -> RawFeatures:
        """
        Apply the missing-value policy and return clean RawFeatures.

        The policy controls what happens when a sensor field is None:
          "skip" -> leave it as None (safest, no fabrication)
          "zero" -> replace with 0.0
          "last" -> replace with the most recent value in history
        """
        prev = self._history[-1] if self._history else None

        def resolve(field_name: str, value: Optional[float]) -> Optional[float]:
            if value is not None and math.isfinite(value):
                return value
            missing_fields.append(field_name)
            policy = self.missing_value_policy
            if policy == "zero":
                imputed_fields.append(field_name)
                return 0.0
            elif policy == "last" and prev is not None:
                last = getattr(prev, field_name, None)
                if last is not None:
                    imputed_fields.append(field_name)
                    warnings.append(
                        f"Field '{field_name}' missing -- using last known value {last}."
                    )
                    return last
            return None

        fan_int: Optional[float] = None
        if reading.fan is not None:
            fan_int = 1.0 if reading.fan else 0.0
        else:
            missing_fields.append("fan")
            if self.missing_value_policy == "last" and prev is not None:
                fan_int = prev.fan_int
                if fan_int is not None:
                    imputed_fields.append("fan_int")

        return RawFeatures(
            temp_1=resolve("temp_1", reading.temp_1),
            temp_2=resolve("temp_2", reading.temp_2),
            rpm=resolve("rpm", reading.rpm),
            vibration=resolve("vibration", reading.vibration),
            voltage=resolve("voltage", reading.voltage),
            current=resolve("current", reading.current),
            power=resolve("power", reading.power),
            fan_int=fan_int,
        )

    def _compute_derived(
        self,
        raw: RawFeatures,
        prev: Optional[_HistoryRecord],
        elapsed: Optional[float],
        rate_ok: bool,
    ) -> DerivedFeatures:
        """Compute all delta, rate, and ratio features for one reading."""
        d = DerivedFeatures()

        # ---- Temperature ------------------------------------------------
        d.temp_delta = _safe_sub(raw.temp_1, raw.temp_2)
        d.temp_avg = _safe_avg(raw.temp_1, raw.temp_2)

        if rate_ok and prev is not None and elapsed is not None:
            prev_avg = prev.temp_avg
            d.temp_rate = _safe_rate(d.temp_avg, prev_avg, elapsed)
        # else: None (first reading or bad timestamp)

        # ---- RPM --------------------------------------------------------
        if rate_ok and prev is not None and elapsed is not None:
            d.rpm_delta = _safe_sub(raw.rpm, prev.rpm)
            d.rpm_rate = _safe_rate(raw.rpm, prev.rpm, elapsed)

        # ---- Electrical -------------------------------------------------
        if rate_ok and prev is not None and elapsed is not None:
            d.current_delta = _safe_sub(raw.current, prev.current)
            d.current_rate = _safe_rate(raw.current, prev.current, elapsed)
            d.power_delta = _safe_sub(raw.power, prev.power)
            d.power_rate = _safe_rate(raw.power, prev.power, elapsed)

        # Power/current per RPM -- only when RPM is meaningful
        rpm = raw.rpm
        if rpm is not None and rpm >= self.min_rpm_for_ratio:
            d.power_per_rpm = _safe_div(raw.power, rpm)
            d.current_per_rpm = _safe_div(raw.current, rpm)
        # else: None (fan off or RPM too low -- ratio is physically meaningless)

        # ---- Vibration --------------------------------------------------
        if rate_ok and prev is not None and elapsed is not None:
            d.vibration_delta = _safe_sub(raw.vibration, prev.vibration)
            d.vibration_rate = _safe_rate(raw.vibration, prev.vibration, elapsed)

        return d

    def _fill_rolling(self, d: DerivedFeatures, rolling_ok: bool) -> None:
        """
        Compute rolling mean and std from the history buffer.

        The history at this point contains PREVIOUS readings only (the current
        reading has not been appended yet).  This means with N readings in
        history, we have N data points for rolling stats.
        """
        if not rolling_ok:
            return  # Not enough history yet

        def _stats(field: str) -> Tuple[Optional[float], Optional[float]]:
            vals = [
                getattr(h, field)
                for h in self._history
                if getattr(h, field) is not None
            ]
            if len(vals) < 2:
                return None, None
            mean = sum(vals) / len(vals)
            variance = sum((v - mean) ** 2 for v in vals) / len(vals)
            std = math.sqrt(variance)
            return mean, std

        d.temp_1_mean, d.temp_1_std = _stats("temp_1")
        d.temp_2_mean, d.temp_2_std = _stats("temp_2")
        d.rpm_mean, d.rpm_std = _stats("rpm")
        d.current_mean, d.current_std = _stats("current")
        d.vibration_mean, d.vibration_std = _stats("vibration")
        d.power_mean, d.power_std = _stats("power")

    def _fill_cross_sensor(self, d: DerivedFeatures, raw: RawFeatures) -> None:
        """
        Compute cross-sensor consistency features.

        fan_rpm_consistency
        -------------------
        Formula: fan_int * max(0, 1 - rpm / expected_fan_rpm)

        Interpretation:
          0   -> consistent  (fan off: no rotation expected;
                              OR fan on + rpm >= expected_fan_rpm)
          >0  -> inconsistency detected (fan commanded ON but RPM is lower
                 than expected, suggesting a stall, blockage, or sensor fault)
          1   -> maximally inconsistent (fan on, RPM = 0)

        current_vs_rpm_ratio / power_vs_rpm_ratio
        ------------------------------------------
        Same as current_per_rpm / power_per_rpm -- kept as separate fields
        for semantic clarity in cross-sensor analysis.
        """
        fan = raw.fan_int
        rpm = raw.rpm

        if fan is not None and rpm is not None:
            # Continuous inconsistency score -- clamp to [0, 1]
            ratio = rpm / self.expected_fan_rpm if self.expected_fan_rpm > 0 else 0.0
            d.fan_rpm_consistency = fan * max(0.0, 1.0 - ratio)
        # else None -- cannot compute without both signals

        d.current_vs_rpm_ratio = d.current_per_rpm  # alias for cross-sensor clarity
        d.power_vs_rpm_ratio = d.power_per_rpm       # alias for cross-sensor clarity


# ---------------------------------------------------------------------------
# Pure utility functions (no state, easy to unit-test)
# ---------------------------------------------------------------------------

def _safe_sub(a: Optional[float], b: Optional[float]) -> Optional[float]:
    """Return a - b, or None if either operand is None."""
    if a is None or b is None:
        return None
    return a - b


def _safe_avg(a: Optional[float], b: Optional[float]) -> Optional[float]:
    """Return (a + b) / 2, or the non-None value if only one is present."""
    if a is not None and b is not None:
        return (a + b) / 2.0
    if a is not None:
        return a
    if b is not None:
        return b
    return None


def _safe_div(numerator: Optional[float], denominator: Optional[float]) -> Optional[float]:
    """Return numerator / denominator, or None if either is None or denominator is 0."""
    if numerator is None or denominator is None:
        return None
    if denominator == 0.0:
        return None
    result = numerator / denominator
    if not math.isfinite(result):
        return None
    return result


def _safe_rate(
    current: Optional[float],
    previous: Optional[float],
    elapsed_seconds: float,
) -> Optional[float]:
    """
    Compute rate of change: (current - previous) / elapsed_seconds.

    Returns None if either value is None or if elapsed_seconds <= 0.
    """
    if current is None or previous is None:
        return None
    if elapsed_seconds <= 0:
        return None
    delta = current - previous
    rate = delta / elapsed_seconds
    if not math.isfinite(rate):
        return None
    return rate
