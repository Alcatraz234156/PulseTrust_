"""
train_anomaly_detector.py
=========================
Stage 2: Model Training Script.

Trains an Isolation Forest anomaly detector EXCLUSIVELY on normal baseline
telemetry (normal_data.json).

Usage
-----
Train with default normal dataset:
    python -m trust_engine.scripts.train_anomaly_detector

Train with custom path or settings:
    python -m trust_engine.scripts.train_anomaly_detector \
        --file trust_engine/data/normal_data.json \
        --holdout 0.20 \
        --estimators 150
"""

from __future__ import annotations

import argparse
import sys
import os
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from trust_engine import config
from trust_engine.anomaly_detector import AnomalyDetector


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="train_anomaly_detector",
        description="Train Isolation Forest detector on clean normal telemetry.",
    )
    p.add_argument(
        "--file",
        type=str,
        default=config.TRAIN_DATA_PATH,
        help=f"Path to normal telemetry JSON (default: {config.TRAIN_DATA_PATH})",
    )
    p.add_argument(
        "--holdout",
        type=float,
        default=config.IFOREST_HOLDOUT_SPLIT,
        help="Fraction of normal data to hold out for sanity check (default: 0.20)",
    )
    p.add_argument(
        "--estimators",
        type=int,
        default=config.IFOREST_N_ESTIMATORS,
        help="Number of trees in Isolation Forest (default: 150)",
    )
    p.add_argument(
        "--contamination",
        type=str,
        default=str(config.IFOREST_CONTAMINATION),
        help="Expected contamination parameter (default: auto)",
    )
    p.add_argument(
        "--model-path",
        type=str,
        default=config.IFOREST_MODEL_PATH,
        help=f"Path to save trained model (default: {config.IFOREST_MODEL_PATH})",
    )
    p.add_argument(
        "--metadata-path",
        type=str,
        default=config.IFOREST_METADATA_PATH,
        help=f"Path to save metadata JSON (default: {config.IFOREST_METADATA_PATH})",
    )
    return p


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    data_path = Path(args.file)
    if not data_path.exists():
        print(f"Error: Training file not found: {data_path}")
        sys.exit(1)

    # Enforce normal-only constraint
    filename_lower = data_path.name.lower()
    if "degradation" in filename_lower or "stall" in filename_lower or "fan_off" in filename_lower:
        print("=" * 60)
        print("ERROR: CRITICAL DATA RESTRICTION VIOLATION!")
        print("Isolation Forest must be trained EXCLUSIVELY on normal data.")
        print(f"Attempted to train on prohibited abnormal dataset: {data_path.name}")
        print("=" * 60)
        sys.exit(1)

    contamination_val: str | float = args.contamination
    try:
        contamination_val = float(args.contamination)
    except ValueError:
        pass  # keep as "auto"

    print("=" * 60)
    print("TrustTwin / PulseTrust -- Stage 2: Isolation Forest Training")
    print("=" * 60)
    print(f"  Dataset               : {data_path}")
    print(f"  Estimators            : {args.estimators}")
    print(f"  Contamination         : {contamination_val}")
    print(f"  Holdout Split         : {args.holdout * 100:.1f}% (normal-data sanity check)")
    print()

    detector = AnomalyDetector(
        n_estimators=args.estimators,
        contamination=contamination_val,
        random_state=config.IFOREST_RANDOM_STATE,
        model_path=args.model_path,
        metadata_path=args.metadata_path,
    )

    print("Step 1: Extracting features from telemetry...")
    if args.holdout and args.holdout > 0:
        print("Step 2: Performing 80/20 train/holdout sanity validation on normal data...")
        val_stats = detector.train_and_validate(data_path, holdout_split=args.holdout)

        print("\n--- Normal-Data Holdout Sanity Results ---")
        print(f"  Total Usable Vectors  : {val_stats['total_usable_samples']}")
        print(f"  Training Split        : {val_stats['train_samples']} samples")
        print(f"  Holdout Split         : {val_stats['holdout_samples']} samples")
        print(f"  Holdout Flagged Normal: {val_stats['holdout_predicted_normal']}")
        print(f"  Holdout Flagged Anom  : {val_stats['holdout_predicted_anomaly']}")
        print(f"  Holdout Anomaly Rate  : {val_stats['holdout_anomaly_percentage']}%")
        print(f"  Mean Decision Score   : {val_stats['holdout_mean_decision_score']}")
        print("  Note: Low anomaly % on holdout confirms low false alarm rate on normal behavior.")
        print("        (This is a baseline sanity check, not a fault detection accuracy metric)")

    print("\nStep 3: Fitting final Isolation Forest model on all normal data...")
    train_meta = detector.train(data_path)

    print(f"  Total Raw Readings    : {train_meta['total_input_count']}")
    print(f"  Usable Feature Vectors: {train_meta['usable_sample_count']}")
    print(f"  Warmup Rows Dropped   : {train_meta['warmup_dropped_count']} (rows 0..1 for feature initialization)")
    print(f"  Feature Dimensions    : {train_meta['feature_count']} features")

    print("\nStep 4: Persisting model and metadata...")
    m_path, meta_path = detector.save()
    print(f"  Saved Model           : {m_path}")
    print(f"  Saved Metadata        : {meta_path}")

    print("\nTraining complete successfully!")
    print("=" * 60)


if __name__ == "__main__":
    main()
