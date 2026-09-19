"""
visualize_normal_scores.py
==========================
Stage 2: Diagnostic Visualization Script.

Generates a plot of Isolation Forest anomaly scores over time for the
NORMAL operating dataset (normal_data.json) to visually verify baseline stability.

Usage
-----
    python -m trust_engine.scripts.visualize_normal_scores \
        --file trust_engine/data/normal_data.json \
        --output models/normal_anomaly_scores.png
"""

from __future__ import annotations

import argparse
import sys
import os
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import matplotlib
matplotlib.use("Agg")  # headless backend for server/script execution
import matplotlib.pyplot as plt

from trust_engine import config
from trust_engine.anomaly_detector import AnomalyDetector
from trust_engine.feature_extractor import FeatureExtractor
from trust_engine.data.synthetic_generator import readings_from_json


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="visualize_normal_scores",
        description="Plot anomaly scores over time for normal telemetry.",
    )
    p.add_argument(
        "--file",
        type=str,
        default=config.TRAIN_DATA_PATH,
        help=f"Path to normal telemetry JSON (default: {config.TRAIN_DATA_PATH})",
    )
    p.add_argument(
        "--model-path",
        type=str,
        default=config.IFOREST_MODEL_PATH,
        help=f"Path to saved model (default: {config.IFOREST_MODEL_PATH})",
    )
    p.add_argument(
        "--output",
        type=str,
        default="models/normal_anomaly_scores.png",
        help="Path to save the generated PNG plot (default: models/normal_anomaly_scores.png)",
    )
    return p


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    model_path = Path(args.model_path)
    if not model_path.exists():
        print(f"Error: Model not found at {model_path}. Train it first.")
        sys.exit(1)

    detector = AnomalyDetector(model_path=str(model_path))
    detector.load()

    file_path = Path(args.file)
    if not file_path.exists():
        print(f"Error: Telemetry file not found: {file_path}")
        sys.exit(1)

    # Strictly enforce normal-only constraint
    name_lower = file_path.name.lower()
    if "degradation" in name_lower or "stall" in name_lower or "fan_off" in name_lower:
        print("ERROR: Visualization in Stage 2 is restricted to normal baseline telemetry.")
        sys.exit(1)

    with open(file_path, "r", encoding="utf-8") as f:
        readings = readings_from_json(f.read())

    print(f"Processing {len(readings)} normal readings through FeatureExtractor...")
    fe = FeatureExtractor()
    vectors = fe.process_batch(readings)

    scores = []
    indices = []
    anomaly_points_x = []
    anomaly_points_y = []

    for idx, fv in enumerate(vectors):
        res = detector.predict(fv, strict=False)
        if res.anomaly_score is not None:
            scores.append(res.anomaly_score)
            indices.append(idx)
            if res.is_anomaly:
                anomaly_points_x.append(idx)
                anomaly_points_y.append(res.anomaly_score)

    print(f"Scored {len(scores)} complete feature vectors.")

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    fig, ax = plt.subplots(figsize=(12, 5), dpi=120)
    ax.plot(indices, scores, label="Isolation Forest Decision Score", color="#1f77b4", linewidth=1.2)
    ax.axhline(0.0, color="#d62728", linestyle="--", linewidth=1.5, label="Decision Boundary (Score = 0.0)")

    if anomaly_points_x:
        ax.scatter(anomaly_points_x, anomaly_points_y, color="#d62728", s=25, zorder=5, label=f"Flagged Outlier ({len(anomaly_points_x)})")

    ax.set_title("Normal Telemetry: Isolation Forest Baseline Scores Over Time", fontsize=14, pad=12)
    ax.set_xlabel("Sequential Reading Index (~1 second intervals)", fontsize=11)
    ax.set_ylabel("Decision Score (>0 is Inlier/Normal)", fontsize=11)
    ax.grid(True, linestyle=":", alpha=0.6)
    ax.legend(loc="lower right", framealpha=0.9)
    plt.tight_layout()

    plt.savefig(out_path)
    plt.close()

    print(f"Plot saved successfully to: {out_path}")


if __name__ == "__main__":
    main()
