"""
validate_behavior.py
====================
Stage 2: Behavioral Validation Script.

Evaluates the saved Isolation Forest model (trained ONLY on normal_data.json)
against four separate telemetry datasets:
  1. normal_data.json      (healthy operating baseline)
  2. degradation_data.json (progressive motor/thermal degradation)
  3. stall_data.json       (fan commanded ON but RPM drops)
  4. fan_off_data.json     (fan commanded OFF, RPM near zero)

Computes:
  - Anomaly count & percentage
  - Mean, Min, Max decision scores
  - Temporal progression analysis for degradation
  - Comparison confirming normal anomaly rate is substantially lower than fault datasets.

IMPORTANT: Results are reported as anomaly rates and outlier distributions,
NOT accuracy, as this is an unsupervised model.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List

import numpy as np

# Add project root to sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from trust_engine import config
from trust_engine.anomaly_detector import AnomalyDetector
from trust_engine.feature_extractor import FeatureExtractor
from trust_engine.models import TelemetryReading


def evaluate_dataset(
    detector: AnomalyDetector,
    filepath: Path,
) -> Dict[str, Any]:
    """Evaluate a single dataset sequentially and collect statistics."""
    with open(filepath, "r", encoding="utf-8") as f:
        data = json.load(f)
        if isinstance(data, dict):
            data = [data]

    readings = [TelemetryReading(**item) for item in data]
    fe = FeatureExtractor()

    scores: List[float] = []
    predictions: List[int] = []
    readings_summary: List[Dict[str, Any]] = []
    warmup_skipped = 0

    for idx, r in enumerate(readings):
        fv = fe.process(r)
        res = detector.predict(fv, strict=False)

        if res.model_status == "insufficient_history":
            warmup_skipped += 1
            readings_summary.append({
                "index": idx,
                "timestamp": str(fv.metadata.timestamp),
                "rpm": fv.raw_features.rpm,
                "temp_1": fv.raw_features.temp_1,
                "current": fv.raw_features.current,
                "vibration": fv.raw_features.vibration,
                "score": None,
                "is_anomaly": False,
                "status": "warmup",
            })
        else:
            scores.append(res.anomaly_score)  # type: ignore
            predictions.append(res.raw_prediction)
            readings_summary.append({
                "index": idx,
                "timestamp": str(fv.metadata.timestamp),
                "rpm": fv.raw_features.rpm,
                "temp_1": fv.raw_features.temp_1,
                "current": fv.raw_features.current,
                "vibration": fv.raw_features.vibration,
                "score": res.anomaly_score,
                "is_anomaly": res.is_anomaly,
                "status": "anomaly" if res.is_anomaly else "normal",
            })

    total_readings = len(readings)
    evaluated_count = len(scores)
    anomaly_count = sum(1 for p in predictions if p == -1)
    normal_count = sum(1 for p in predictions if p == 1)
    anomaly_pct = (anomaly_count / evaluated_count * 100.0) if evaluated_count > 0 else 0.0

    mean_score = float(np.mean(scores)) if scores else 0.0
    min_score = float(np.min(scores)) if scores else 0.0
    max_score = float(np.max(scores)) if scores else 0.0

    return {
        "dataset_name": filepath.name,
        "total_readings": total_readings,
        "warmup_skipped": warmup_skipped,
        "evaluated_count": evaluated_count,
        "normal_count": normal_count,
        "anomaly_count": anomaly_count,
        "anomaly_pct": anomaly_pct,
        "mean_score": mean_score,
        "min_score": min_score,
        "max_score": max_score,
        "readings_summary": readings_summary,
    }


def main():
    model_path = Path(config.IFOREST_MODEL_PATH)
    if not model_path.exists():
        print(f"Error: Model not found at {model_path}. Train it first.")
        sys.exit(1)

    detector = AnomalyDetector(model_path=str(model_path))
    detector.load()

    datasets = [
        Path("trust_engine/data/normal_data.json"),
        Path("trust_engine/data/degradation_data.json"),
        Path("trust_engine/data/stall_data.json"),
        Path("trust_engine/data/fan_off_data.json"),
    ]

    results: Dict[str, Dict[str, Any]] = {}

    print("=" * 80)
    print("STAGE 2: BEHAVIORAL VALIDATION ACROSS DATASETS")
    print("Model: Isolation Forest (Trained EXCLUSIVELY on normal_data.json)")
    print("Features evaluated: 34")
    print("=" * 80)

    for ds_path in datasets:
        if not ds_path.exists():
            print(f"Warning: {ds_path} not found.")
            continue
        stats = evaluate_dataset(detector, ds_path)
        results[ds_path.name] = stats

    # Print Summary Comparison Table
    print(f"\n{'Dataset':<24} {'Total':<6} {'Warmup':<7} {'Eval':<6} {'Normal':<8} {'Anomaly':<8} {'Anom %':<8} {'Mean Score':<11} {'Min Score':<10} {'Max Score'}")
    print("-" * 96)
    for ds_name, s in results.items():
        print(
            f"{ds_name:<24} "
            f"{s['total_readings']:<6} "
            f"{s['warmup_skipped']:<7} "
            f"{s['evaluated_count']:<6} "
            f"{s['normal_count']:<8} "
            f"{s['anomaly_count']:<8} "
            f"{s['anomaly_pct']:>5.1f}%  "
            f"{s['mean_score']:>+9.4f}  "
            f"{s['min_score']:>+8.4f}  "
            f"{s['max_score']:>+8.4f}"
        )
    print("-" * 96)

    # Verification of Anomaly Rates
    normal_anom_pct = results.get("normal_data.json", {}).get("anomaly_pct", 0.0)
    print("\n--- Key Finding: Anomaly Rate Contrast ---")
    print(f"  Normal baseline anomaly rate     : {normal_anom_pct:.1f}%")
    for name in ["degradation_data.json", "stall_data.json", "fan_off_data.json"]:
        if name in results:
            anom_pct = results[name]["anomaly_pct"]
            delta = anom_pct - normal_anom_pct
            print(f"  {name:<24} anomaly rate: {anom_pct:.1f}% (Delta = {delta:+.1f}%)")

    # Detailed Temporal Progression for Degradation
    if "degradation_data.json" in results:
        deg_summary = results["degradation_data.json"]["readings_summary"]
        print("\n" + "=" * 80)
        print("TEMPORAL PROGRESSION ANALYSIS: degradation_data.json")
        print("Shows how anomaly status and decision scores evolve as degradation progresses")
        print("=" * 80)
        print(f"{'Index':<6} {'Temp1(C)':<10} {'RPM':<9} {'Current(A)':<12} {'Vib':<8} {'Score':<10} {'Prediction'}")
        print("-" * 72)

        # Print samples across the progression (every 5 readings)
        for row in deg_summary:
            idx = row["index"]
            if idx < 2 or idx % 5 == 0 or idx == len(deg_summary) - 1:
                score_str = f"{row['score']:+.4f}" if row['score'] is not None else "N/A (warmup)"
                pred_str = row['status'].upper()
                print(
                    f"{idx:<6} "
                    f"{row['temp_1']:<10.2f} "
                    f"{row['rpm']:<9.1f} "
                    f"{row['current']:<12.4f} "
                    f"{row['vibration']:<8.3f} "
                    f"{score_str:<10} "
                    f"{pred_str}"
                )

        # Progression phases breakdown
        valid_deg = [r for r in deg_summary if r["score"] is not None]
        n_eval = len(valid_deg)
        early_third = valid_deg[: n_eval // 3]
        mid_third = valid_deg[n_eval // 3 : 2 * n_eval // 3]
        late_third = valid_deg[2 * n_eval // 3 :]

        def phase_stats(p_list):
            anoms = sum(1 for x in p_list if x["is_anomaly"])
            pct = anoms / len(p_list) * 100
            mean_sc = np.mean([x["score"] for x in p_list])
            return pct, mean_sc

        e_pct, e_sc = phase_stats(early_third)
        m_pct, m_sc = phase_stats(mid_third)
        l_pct, l_sc = phase_stats(late_third)

        print("\n--- Degradation Progression by Phase ---")
        print(f"  Phase 1 (Early Readings  2..20) : Anomaly Rate = {e_pct:5.1f}%, Mean Decision Score = {e_sc:+.4f}")
        print(f"  Phase 2 (Middle Readings 21..39): Anomaly Rate = {m_pct:5.1f}%, Mean Decision Score = {m_sc:+.4f}")
        print(f"  Phase 3 (Late Readings   40..59): Anomaly Rate = {l_pct:5.1f}%, Mean Decision Score = {l_sc:+.4f}")

    print("\n" + "=" * 80)
    print("Validation completed.")


if __name__ == "__main__":
    main()
