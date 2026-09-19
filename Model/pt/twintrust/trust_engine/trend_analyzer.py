"""
trend_analyzer.py
=================
STUB -- Temporal degradation and trend analysis stage.

NOT IMPLEMENTED YET.

The TrendAnalyzer examines FeatureVectors over a longer time window to detect
gradual degradation that might not look anomalous in any single reading.

Planned analyses (future):
    - Linear trend in temperature over the last N minutes
    - Monotonically increasing current over time (motor wearing out)
    - RPM variance increasing (mechanical looseness)
    - CUSUM / EWMA control charts for drift detection
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from .models import FeatureVector


@dataclass
class TrendSignal:
    """One detected trend or degradation signal."""
    signal_id: str
    feature_name: str
    trend_direction: str     # "increasing" | "decreasing" | "stable"
    slope: Optional[float]   # units per second
    confidence: float        # 0-1
    message: str


class TrendAnalyzer:
    """
    Interface for temporal trend and degradation analysis.

    NOT IMPLEMENTED YET.
    """

    def update(self, feature_vector: FeatureVector) -> List[TrendSignal]:
        """
        Update the trend analyzer with a new reading and return any signals.

        Raises
        ------
        NotImplementedError
            Always (not yet implemented).
        """
        raise NotImplementedError(
            "TrendAnalyzer.update() is not implemented yet. "
            "Implement after AnomalyDetector is validated."
        )
