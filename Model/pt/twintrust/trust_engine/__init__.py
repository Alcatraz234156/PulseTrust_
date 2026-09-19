"""
trust_engine
============
The Trust Engine for TrustTwin / PulseTrust.

Determines how trustworthy a machine's current state is based on
sensor telemetry from an ESP32-based industrial plant monitor.

Stages:
    1. FeatureExtractor  (Stage 1 -- feature extraction, rolling stats)
    2. AnomalyDetector   (Stage 2 -- Isolation Forest multivariate detector)
    3. RuleEngine        (Stage 3 -- deterministic physical & stall rules)
    4. TrustEngine       (Stage 4 -- operational decision & trust synthesizer)
"""

from .anomaly_detector import AnomalyDetector
from .feature_extractor import FeatureExtractor
from .models import (
    AnomalyResult,
    FeatureVector,
    MachineState,
    RuleEvaluationResult,
    RuleSeverity,
    RuleViolation,
    TelemetryReading,
    TrustDecision,
    TrustReason,
    TrustResult,
)
from .rules import RuleEngine
from .trust_engine import TrustEngine

__version__ = "0.4.0"
__author__ = "TrustTwin Team"
