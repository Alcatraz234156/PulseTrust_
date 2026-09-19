"""
run_feature_extraction.py
=========================
CLI script for the FeatureExtractor.

Usage
-----
Single JSON reading from the command line:

    python -m trust_engine.scripts.run_feature_extraction \
        --json "{\"temp_1\": 28, \"temp_2\": 28, \"rpm\": 1450, \"vibration\": 9.6, \"voltage\": 5.0, \"current\": 0.18, \"power\": 0.9, \"fan\": true}"

From a JSON file:

    python -m trust_engine.scripts.run_feature_extraction --file my_data.json

From a CSV file:

    python -m trust_engine.scripts.run_feature_extraction --file my_data.csv

Run a named synthetic scenario:

    python -m trust_engine.scripts.run_feature_extraction --scenario normal
    python -m trust_engine.scripts.run_feature_extraction --scenario stall
    python -m trust_engine.scripts.run_feature_extraction --scenario degradation

Additional flags:

    --window 15        Override ROLLING_WINDOW_SIZE (default: 10)
    --verbose          Print the full FeatureVector for every reading
    --ml-dict          Print the ML-ready flat dict for every reading
"""

from __future__ import annotations

import argparse
import json
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from trust_engine.feature_extractor import FeatureExtractor
from trust_engine.models import TelemetryReading
from trust_engine.data.synthetic_generator import (
    generate_normal_sequence,
    generate_fan_stall_sequence,
    generate_degradation_sequence,
    readings_from_json,
    readings_from_csv,
)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="run_feature_extraction",
        description="TrustTwin FeatureExtractor CLI",
    )
    source = p.add_mutually_exclusive_group(required=True)
    source.add_argument("--json", metavar="JSON_STRING",
                        help="Single telemetry reading as a JSON string.")
    source.add_argument("--file", metavar="PATH",
                        help="Path to a .json or .csv file of telemetry readings.")
    source.add_argument("--scenario", choices=["normal", "stall", "degradation"],
                        help="Run a built-in synthetic scenario.")
    p.add_argument("--window", type=int, default=None,
                   help="Rolling window size (default: from config.py).")
    p.add_argument("--verbose", action="store_true",
                   help="Print the full FeatureVector for every reading.")
    p.add_argument("--ml-dict", action="store_true", dest="ml_dict",
                   help="Print the ML-ready flat feature dict for every reading.")
    p.add_argument("--n", type=int, default=20,
                   help="Number of readings for synthetic scenarios (default: 20).")
    return p


def load_readings(args: argparse.Namespace):
    if args.json:
        data = json.loads(args.json)
        if isinstance(data, dict):
            data = [data]
        return [TelemetryReading(**d) for d in data]

    if args.file:
        path = args.file
        if path.endswith(".csv"):
            return readings_from_csv(path)
        else:
            with open(path, encoding="utf-8") as f:
                return readings_from_json(f.read())

    if args.scenario == "normal":
        return generate_normal_sequence(n=args.n)
    elif args.scenario == "stall":
        return generate_fan_stall_sequence(n=args.n)
    elif args.scenario == "degradation":
        return generate_degradation_sequence(n=args.n)


def main():
    parser = build_parser()
    args = parser.parse_args()

    kwargs = {}
    if args.window is not None:
        kwargs["window_size"] = args.window

    fe = FeatureExtractor(**kwargs)
    readings = load_readings(args)

    print(f"\nTrustTwin FeatureExtractor")
    print(f"  Readings loaded : {len(readings)}")
    print(f"  Rolling window  : {fe.window_size}")
    print()

    for i, reading in enumerate(readings):
        fv = fe.process(reading)

        if args.verbose:
            print(fv.pretty_print())
        elif args.ml_dict:
            ml = fv.to_ml_dict()
            print(f"Reading #{i:03d} [{fv.metadata.timestamp.isoformat()}]")
            for k, v in sorted(ml.items()):
                print(f"  {k:<30} = {v:.6f}")
            print()
        else:
            # Compact summary
            d = fv.derived_features
            r = fv.raw_features
            q = fv.data_quality
            print(
                f"#{i:03d} "
                f"T={_f(r.temp_1)}/{_f(r.temp_2)}C "
                f"RPM={_f(r.rpm)} "
                f"I={_f(r.current)}A "
                f"P={_f(r.power)}W "
                f"fan={r.fan_int} | "
                f"t_rate={_f(d.temp_rate)} "
                f"rpm_rate={_f(d.rpm_rate)} "
                f"fan_consist={_f(d.fan_rpm_consistency)} "
                f"[hist={q.history_size}]"
            )

    print(f"\nDone. {len(readings)} reading(s) processed.")
    print("Use --verbose to see every feature, or --ml-dict for the ML feature vector.")


def _f(v):
    if v is None:
        return "  None"
    return f"{v:7.3f}"


if __name__ == "__main__":
    main()
