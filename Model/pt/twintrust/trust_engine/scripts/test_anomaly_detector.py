"""
test_anomaly_detector.py
========================
Stage 2: Inference & Evaluation CLI Script.

Loads the trained Isolation Forest model and evaluates telemetry readings.

Usage Examples
--------------
Evaluate normal data file (e.g. first 20 readings):
    python -m trust_engine.scripts.test_anomaly_detector \
        --file trust_engine/data/normal_data.json --limit 20

Evaluate manual readings in JSON format:
    python -m trust_engine.scripts.test_anomaly_detector \
        --json "[{\"temp_1\": 28.0, \"temp_2\": 28.0, \"rpm\": 1450, \"vibration\": 9.6, \"voltage\": 5.0, \"current\": 0.18, \"power\": 0.9, \"fan\": true}, {\"temp_1\": 28.1, \"temp_2\": 28.0, \"rpm\": 1455, \"vibration\": 9.6, \"voltage\": 5.0, \"current\": 0.18, \"power\": 0.9, \"fan\": true}]"
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
import os
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from trust_engine import config
from trust_engine.anomaly_detector import AnomalyDetector
from trust_engine.feature_extractor import FeatureExtractor
from trust_engine.models import TelemetryReading


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="test_anomaly_detector",
        description="Run inference using the trained Isolation Forest model.",
    )
    source = p.add_mutually_exclusive_group(required=True)
    source.add_argument(
        "--file",
        type=str,
        help="Path to JSON file containing telemetry readings.",
    )
    source.add_argument(
        "--json",
        type=str,
        help="Inline JSON string (single reading dict or array of reading dicts).",
    )
    p.add_argument(
        "--model-path",
        type=str,
        default=config.IFOREST_MODEL_PATH,
        help=f"Path to saved model (default: {config.IFOREST_MODEL_PATH})",
    )
    p.add_argument(
        "--metadata-path",
        type=str,
        default=config.IFOREST_METADATA_PATH,
        help=f"Path to saved metadata (default: {config.IFOREST_METADATA_PATH})",
    )
    p.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Max number of readings to evaluate.",
    )
    p.add_argument(
        "--verbose",
        action="store_true",
        help="Print detailed evaluation per reading.",
    )
    return p


def parse_json_safely(raw_str: str):
    """Parse JSON with fallback for PowerShell quote stripping."""
    try:
        return json.loads(raw_str)
    except Exception:
        pass

    # Try literal_eval if PowerShell unquoted keys
    try:
        # Convert true/false/null to Python equivalents
        py_str = raw_str.replace("true", "True").replace("false", "False").replace("null", "None")
        return ast.literal_eval(py_str)
    except Exception:
        pass

    # Try regex fix for unquoted JSON keys and timestamps
    try:
        fixed = raw_str
        # Quote keys
        fixed = re.sub(r'([{,])\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*:', r'\1"\2":', fixed)
        # Quote unquoted ISO timestamps
        fixed = re.sub(r':\s*([0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9:+-]+)', r': "\1"', fixed)
        return json.loads(fixed)
    except Exception as e:
        raise ValueError(f"Could not parse JSON input: {raw_str} (error: {e})")


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    # Load model
    model_path = Path(args.model_path)
    if not model_path.exists():
        print(f"Error: Model not found at {model_path}.")
        print("Please train the model first by running:")
        print("  python -m trust_engine.scripts.train_anomaly_detector")
        sys.exit(1)

    detector = AnomalyDetector(
        model_path=str(model_path),
        metadata_path=args.metadata_path,
    )
    detector.load()

    # Parse telemetry input
    raw_items = []
    if args.file:
        file_path = Path(args.file)
        if not file_path.exists():
            print(f"Error: File not found: {file_path}")
            sys.exit(1)
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            raw_items = data if isinstance(data, list) else [data]
    elif args.json:
        parsed = parse_json_safely(args.json)
        raw_items = parsed if isinstance(parsed, list) else [parsed]

    if args.limit:
        raw_items = raw_items[: args.limit]

    readings = [TelemetryReading(**item) for item in raw_items]

    print("=" * 65)
    print("TrustTwin / PulseTrust -- Stage 2: Anomaly Detector Inference")
    print("=" * 65)
    print(f"  Model Loaded          : {model_path}")
    print(f"  Features Evaluated    : {len(detector.feature_names)}")
    print(f"  Readings to Process   : {len(readings)}")
    print("=" * 65)

    fe = FeatureExtractor()

    # If only 1 reading was passed, explain history requirement clearly
    if len(readings) == 1:
        fv = fe.process(readings[0])
        res = detector.predict(fv, strict=False)

        print("\nSingle Standalone Reading Evaluation:")
        if res.model_status == "insufficient_history":
            print("  Status : INSUFFICIENT HISTORY (Expected for 1st standalone reading)")
            print("  Note   : Rate, delta, and rolling features require sequential history")
            print("           from prior readings. A single isolated reading cannot produce")
            print("           these values without fabricating history.")
            print(f"  Warning: {res.data_quality_warning}")
            print("\nTip: Pass a sequence of at least 2 readings in a JSON array to evaluate")
            print("     temporal features and generate model anomaly scores.")
        else:
            print(res.pretty_print())
        return

    # Multiple readings: stream through FeatureExtractor
    normal_count = 0
    anomaly_count = 0
    skipped_count = 0

    print(f"\n{'#':<4} {'RPM':<7} {'Temp1':<7} {'Vib':<7} {'Status':<16} {'Score':<10} {'Prediction'}")
    print("-" * 65)

    for idx, reading in enumerate(readings):
        fv = fe.process(reading)
        res = detector.predict(fv, strict=False)

        rpm_str = f"{fv.raw_features.rpm:.1f}" if fv.raw_features.rpm is not None else "N/A"
        t1_str = f"{fv.raw_features.temp_1:.1f}" if fv.raw_features.temp_1 is not None else "N/A"
        vib_str = f"{fv.raw_features.vibration:.2f}" if fv.raw_features.vibration is not None else "N/A"

        if res.model_status == "insufficient_history":
            skipped_count += 1
            status_str = "WARMUP (no rate)"
            score_str = "N/A"
            pred_str = "warmup"
        elif res.is_anomaly:
            anomaly_count += 1
            status_str = "ANOMALY"
            score_str = f"{res.anomaly_score:+.4f}" if res.anomaly_score is not None else "N/A"
            pred_str = "-1 (outlier)"
        else:
            normal_count += 1
            status_str = "NORMAL"
            score_str = f"{res.anomaly_score:+.4f}" if res.anomaly_score is not None else "N/A"
            pred_str = "+1 (inlier)"

        print(f"{idx:<4} {rpm_str:<7} {t1_str:<7} {vib_str:<7} {status_str:<16} {score_str:<10} {pred_str}")

        if args.verbose and res.model_status != "insufficient_history":
            print(f"     -> Score: {score_str} | Features: {res.features_used}")

    print("-" * 65)
    print("Summary:")
    print(f"  Evaluated Complete Vectors : {normal_count + anomaly_count}")
    print(f"  Flagged as Normal (+1)     : {normal_count}")
    print(f"  Flagged as Anomaly (-1)    : {anomaly_count}")
    print(f"  Cold-start Warmup (skipped): {skipped_count}")
    print("=" * 65)


if __name__ == "__main__":
    main()
