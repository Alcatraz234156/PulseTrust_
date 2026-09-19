"""
test_rule_engine.py
===================
Stage 3: Rule Engine Dataset Evaluation & Scenario Detection Script.

Evaluates deterministic domain rules across all four telemetry datasets:
  1. normal_data.json
  2. degradation_data.json
  3. stall_data.json
  4. fan_off_data.json

Reports:
  - Total readings and evaluated results
  - Violation counts grouped by Severity (CRITICAL, WARNING, INFO)
  - Violation counts grouped by Rule ID
  - First occurrence details for each triggered rule
  - Scenario detection assessment

Usage
-----
    python -m trust_engine.scripts.test_rule_engine
"""

from __future__ import annotations

import json
import os
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List

# Add project root to sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from trust_engine.feature_extractor import FeatureExtractor
from trust_engine.models import TelemetryReading, RuleEvaluationResult, RuleViolation
from trust_engine.rules import RuleEngine


def evaluate_dataset_rules(filepath: Path) -> Dict[str, Any]:
    """Evaluate all readings in a dataset sequentially through FeatureExtractor and RuleEngine."""
    with open(filepath, "r", encoding="utf-8") as f:
        raw_data = json.load(f)
        if isinstance(raw_data, dict):
            raw_data = [raw_data]

    readings = [TelemetryReading(**item) for item in raw_data]
    fe = FeatureExtractor()
    engine = RuleEngine()

    total_readings = len(readings)
    severity_counts: Dict[str, int] = defaultdict(int)
    rule_counts: Dict[str, int] = defaultdict(int)
    first_occurrences: Dict[str, Dict[str, Any]] = {}
    readings_with_violations = 0
    readings_with_critical = 0

    for idx, r in enumerate(readings):
        fv = fe.process(r)
        result: RuleEvaluationResult = engine.evaluate(fv)

        if result.has_violations:
            readings_with_violations += 1
            has_crit = any(v.severity == "CRITICAL" for v in result.violations)
            if has_crit:
                readings_with_critical += 1

            for v in result.violations:
                severity_counts[v.severity] += 1
                rule_counts[v.rule_id] += 1

                if v.rule_id not in first_occurrences:
                    first_occurrences[v.rule_id] = {
                        "index": idx,
                        "timestamp": str(fv.metadata.timestamp),
                        "severity": v.severity,
                        "message": v.message,
                        "evidence": v.evidence,
                    }

    return {
        "dataset_name": filepath.name,
        "total_readings": total_readings,
        "readings_with_violations": readings_with_violations,
        "readings_with_critical": readings_with_critical,
        "severity_counts": dict(severity_counts),
        "rule_counts": dict(rule_counts),
        "first_occurrences": first_occurrences,
    }


def main():
    datasets = [
        Path("trust_engine/data/normal_data.json"),
        Path("trust_engine/data/degradation_data.json"),
        Path("trust_engine/data/stall_data.json"),
        Path("trust_engine/data/fan_off_data.json"),
    ]

    print("=" * 80)
    print("STAGE 3: DETERMINISTIC RULE ENGINE -- SCENARIO DETECTION & VALIDATION")
    print("Physical Rules, Operational Bounds & Cross-Sensor Consistency Checks")
    print("=" * 80)

    for ds_path in datasets:
        if not ds_path.exists():
            print(f"\nWarning: File {ds_path} not found.")
            continue

        res = evaluate_dataset_rules(ds_path)
        name = res["dataset_name"]
        total = res["total_readings"]
        v_readings = res["readings_with_violations"]
        crit_readings = res["readings_with_critical"]
        sev = res["severity_counts"]
        rules = res["rule_counts"]

        print(f"\n" + "-" * 80)
        print(f"Dataset: {name} ({total} readings)")
        print("-" * 80)
        print(f"  Readings with any violation : {v_readings} / {total} ({v_readings/total*100:.1f}%)")
        print(f"  Readings with CRITICAL rule : {crit_readings} / {total} ({crit_readings/total*100:.1f}%)")

        print("\n  Triggered Violations by Severity:")
        print(f"    CRITICAL : {sev.get('CRITICAL', 0)}")
        print(f"    WARNING  : {sev.get('WARNING', 0)}")
        print(f"    INFO     : {sev.get('INFO', 0)}")

        print("\n  Triggered Violations by Rule ID:")
        if rules:
            for rule_id, count in sorted(rules.items(), key=lambda x: -x[1]):
                print(f"    {rule_id:<30} : {count}")
        else:
            print("    (None - zero rule violations)")

        print("\n  First Occurrence Evidence per Triggered Rule:")
        if res["first_occurrences"]:
            for rule_id, occ in res["first_occurrences"].items():
                print(f"    [{occ['severity']}] {rule_id} at Reading #{occ['index']}:")
                print(f"      Message : {occ['message']}")
                print(f"      Evidence: {occ['evidence']}")
        else:
            print("    (None)")

        # Scenario detection assessment
        print("\n  Scenario Detection Assessment:")
        if name == "normal_data.json":
            if crit_readings == 0 and v_readings == 0:
                print("    PASS: Normal baseline clean. Zero false positive critical violations.")
            elif crit_readings == 0:
                print(f"    PASS: Zero critical violations. Minor non-critical warnings: {v_readings} readings.")
            else:
                print(f"    ATTENTION: Unexpected critical violation in normal baseline: {crit_readings} readings.")

        elif name == "stall_data.json":
            if "FAN_STALL" in rules:
                print(f"    PASS: Fan stall condition detected successfully ({rules['FAN_STALL']} readings confirmed).")
            else:
                print("    FAIL: Expected FAN_STALL violation was NOT triggered.")

        elif name == "degradation_data.json":
            detected = []
            if "HIGH_TEMPERATURE" in rules or "CRITICAL_TEMPERATURE" in rules:
                detected.append("Thermal drift")
            if "HIGH_CURRENT" in rules or "OVERCURRENT" in rules:
                detected.append("Current load elevation")
            if "LOW_RPM" in rules:
                detected.append("RPM speed loss")
            if detected:
                print(f"    PASS: Degradation detected via: {', '.join(detected)}.")
            else:
                print("    FAIL: Degradation trends did not trigger expected rules.")

        elif name == "fan_off_data.json":
            if "FAN_STALL" not in rules and crit_readings == 0:
                print("    PASS: Correctly recognized intentional OFF state. No false FAN_STALL.")
            else:
                print("    FAIL: False alarm on intentional fan OFF state.")

    print("\n" + "=" * 80)
    print("Rule Engine validation complete.")
    print("=" * 80)


if __name__ == "__main__":
    main()
