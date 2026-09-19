"""
test_trust_engine.py
====================
End-to-End Trust Validation across all 4 operational datasets:
  1. normal_data.json      (1800 readings -- nominal healthy operation)
  2. degradation_data.json (60 readings -- gradual multi-sensor deterioration)
  3. stall_data.json       (45 readings -- fan stall event)
  4. fan_off_data.json     (20 readings -- intentional fan OFF state)

Pipeline:
  Raw TelemetryReading
         |
  Stage 1: FeatureExtractor (stateful rolling stats, derived physical rates)
         |
  Stage 2: Isolation Forest AnomalyDetector (unsupervised statistical novelty)
         +
  Stage 3: Deterministic RuleEngine (physical bounds, stall confirmation)
         |
  Stage 4: TrustEngine (evidence synthesis, double-counting mitigation, context)
         |
  TrustResult (score: 0-100, state: NORMAL/CAUTION/DEGRADING/FAULT, decision: ALLOW/WARN/BLOCK)

Usage
-----
    python -m trust_engine.scripts.test_trust_engine
"""

from __future__ import annotations

import json
import os
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from trust_engine import config
from trust_engine.anomaly_detector import AnomalyDetector
from trust_engine.feature_extractor import FeatureExtractor
from trust_engine.models import (
    MachineState,
    TelemetryReading,
    TrustDecision,
    TrustResult,
)
from trust_engine.rules import RuleEngine
from trust_engine.trust_engine import TrustEngine


DATA_DIR = PROJECT_ROOT / "trust_engine" / "data"

DATASETS = [
    ("normal_data.json", "Healthy Baseline Operation"),
    ("degradation_data.json", "Gradual Multi-Sensor Degradation"),
    ("stall_data.json", "Mechanical Fan Stall"),
    ("fan_off_data.json", "Intentional Fan OFF Context"),
]


def load_dataset(filename: str) -> List[TelemetryReading]:
    path = DATA_DIR / filename
    if not path.exists():
        raise FileNotFoundError(f"Dataset not found: {path}")
    with open(path, "r", encoding="utf-8") as f:
        raw_list = json.load(f)
    return [TelemetryReading.from_dict(d) for d in raw_list]


def run_validation() -> Dict[str, Any]:
    print("=" * 80)
    print("  STAGE 4 END-TO-END TRUST ENGINE VALIDATION")
    print("=" * 80)
    print("Pipeline: Raw Telemetry -> FeatureExtractor -> AnomalyDetector + RuleEngine -> TrustEngine")
    print("Note: Results reflect behavioral engineering validation, NOT statistical accuracy.\n")

    # Initialize components
    fe = FeatureExtractor()
    ad = AnomalyDetector()
    ad.load()  # Load pre-trained Isolation Forest
    re = RuleEngine()
    engine = TrustEngine(
        feature_extractor=fe,
        anomaly_detector=ad,
        rule_engine=re,
        auto_load_model=False,
    )

    all_dataset_reports: Dict[str, Any] = {}

    for filename, description in DATASETS:
        print("-" * 80)
        print(f"Dataset: {filename} ({description})")
        print("-" * 80)

        readings = load_dataset(filename)
        total_readings = len(readings)

        # Reset pipeline state between datasets to guarantee strict isolation
        engine.reset()

        trust_results: List[TrustResult] = []
        scores: List[float] = []
        state_dist: Dict[str, int] = defaultdict(int)
        decision_dist: Dict[str, int] = defaultdict(int)

        first_caution: int | None = None
        first_degrading: int | None = None
        first_fault: int | None = None
        first_block: int | None = None

        t0 = time.perf_counter()

        for idx, reading in enumerate(readings):
            # Evaluate reading through full unified TrustEngine
            res = engine.evaluate(reading)
            trust_results.append(res)
            scores.append(res.trust_score)
            state_dist[res.state.value] += 1
            decision_dist[res.decision.value] += 1

            if first_caution is None and res.state == MachineState.CAUTION:
                first_caution = idx
            if first_degrading is None and res.state == MachineState.DEGRADING:
                first_degrading = idx
            if first_fault is None and res.state == MachineState.FAULT:
                first_fault = idx
            if first_block is None and res.decision == TrustDecision.BLOCK:
                first_block = idx

        elapsed = time.perf_counter() - t0
        evaluated_count = len(trust_results)

        mean_score = sum(scores) / len(scores) if scores else 0.0
        min_score = min(scores) if scores else 0.0
        max_score = max(scores) if scores else 0.0

        # Print Dataset Summary
        print(f"  Total readings processed : {total_readings}")
        print(f"  Evaluated readings       : {evaluated_count} (100.0%)")
        print(f"  Processing time          : {elapsed * 1000:.2f} ms ({elapsed / evaluated_count * 1000:.3f} ms/reading)")
        print(f"  Trust Score Statistics   : Mean = {mean_score:.2f}, Min = {min_score:.2f}, Max = {max_score:.2f}")
        print(f"  State Distribution       : {dict(state_dist)}")
        print(f"  Decision Distribution    : {dict(decision_dist)}")
        print(f"  Transition Chronology    :")
        print(f"    - First CAUTION        : Reading #{first_caution if first_caution is not None else 'Never'}")
        print(f"    - First DEGRADING      : Reading #{first_degrading if first_degrading is not None else 'Never'}")
        print(f"    - First FAULT          : Reading #{first_fault if first_fault is not None else 'Never'}")
        print(f"    - First BLOCK          : Reading #{first_block if first_block is not None else 'Never'}")

        # Representative Sample
        sample_idx = 0
        if first_fault is not None:
            sample_idx = first_fault
        elif first_degrading is not None:
            sample_idx = first_degrading
        elif first_caution is not None:
            sample_idx = first_caution

        sample_res = trust_results[sample_idx]
        print(f"\n  Representative Result (Reading #{sample_idx}):")
        print(f"    Trust Score : {sample_res.trust_score:.2f}")
        print(f"    State       : {sample_res.state.value}")
        print(f"    Decision    : {sample_res.decision.value}")
        print(f"    Score Deductions: {sample_res.score_breakdown}")
        print(f"    Reasons     : {sample_res.reasons[:3]}")
        print()

        all_dataset_reports[filename] = {
            "description": description,
            "total_readings": total_readings,
            "evaluated_readings": evaluated_count,
            "mean_trust_score": round(mean_score, 2),
            "min_trust_score": round(min_score, 2),
            "max_trust_score": round(max_score, 2),
            "state_distribution": dict(state_dist),
            "decision_distribution": dict(decision_dist),
            "first_caution": first_caution,
            "first_degrading": first_degrading,
            "first_fault": first_fault,
            "first_block": first_block,
            "sample_reading_index": sample_idx,
            "sample_trust_result": sample_res.to_dict(),
        }

    return all_dataset_reports


if __name__ == "__main__":
    report = run_validation()
    print("=" * 80)
    print("  END-TO-END VALIDATION COMPLETE")
    print("=" * 80)
