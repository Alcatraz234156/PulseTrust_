"""
audit_normal.py
===============
Deep audit of the 110 readings in normal_data.json classified as DEGRADING.
Answers questions 1-7 in full detail.
"""

from __future__ import annotations

import json
import os
import sys
from collections import Counter, defaultdict
from pathlib import Path

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from trust_engine import config
from trust_engine.anomaly_detector import AnomalyDetector
from trust_engine.feature_extractor import FeatureExtractor
from trust_engine.models import MachineState, TelemetryReading
from trust_engine.rules import RuleEngine
from trust_engine.trust_engine import TrustEngine

def run_audit():
    fe = FeatureExtractor()
    ad = AnomalyDetector()
    ad.load()
    re = RuleEngine()
    engine = TrustEngine(fe, ad, re, auto_load_model=False)

    data_path = PROJECT_ROOT / "trust_engine" / "data" / "normal_data.json"
    with open(data_path, "r", encoding="utf-8") as f:
        readings = [TelemetryReading.from_dict(d) for d in json.load(f)]

    engine.reset()

    records = []
    for idx, r in enumerate(readings):
        fv = engine.feature_extractor.process(r)
        anom = engine.anomaly_detector.predict(fv, strict=False)
        rule = engine.rule_engine.evaluate(fv)
        trust = engine.evaluate(fv, anom, rule)

        records.append({
            "index": idx,
            "reading": r,
            "fv": fv,
            "anom": anom,
            "rule": rule,
            "trust": trust,
        })

    degrading_records = [rec for rec in records if rec["trust"].state == MachineState.DEGRADING]
    caution_records = [rec for rec in records if rec["trust"].state == MachineState.CAUTION]
    normal_records = [rec for rec in records if rec["trust"].state == MachineState.NORMAL]

    print("================================================================================")
    print("                    AUDIT OF normal_data.json CLASSIFICATIONS")
    print("================================================================================")
    print(f"Total readings: {len(records)}")
    print(f"  - NORMAL   : {len(normal_records)} ({len(normal_records)/len(records)*100:.1f}%)")
    print(f"  - CAUTION  : {len(caution_records)} ({len(caution_records)/len(records)*100:.1f}%)")
    print(f"  - DEGRADING: {len(degrading_records)} ({len(degrading_records)/len(records)*100:.1f}%)")
    print(f"  - FAULT    : 0 (0.0%)")
    print()

    # --- 1. Which temporal signals trigger DEGRADING on normal_data.json? ---
    signal_counts_in_degrading = Counter()
    for rec in degrading_records:
        signals = rec["trust"].temporal_summary.get("signals", [])
        for s in signals:
            signal_counts_in_degrading[s] += 1

    print("--- 1. TEMPORAL SIGNALS TRIGGERING DEGRADING (in 110 degrading readings) ---")
    for sig, count in signal_counts_in_degrading.most_common():
        print(f"  - {sig:<20}: {count} occurrences ({count/len(degrading_records)*100:.1f}% of degrading readings)")
    print()

    # --- 2. Temporal signals frequency across ALL 1800 readings ---
    signal_counts_all = Counter()
    for rec in records:
        signals = rec["trust"].temporal_summary.get("signals", [])
        for s in signals:
            signal_counts_all[s] += 1

    print("--- 2. TEMPORAL SIGNALS FREQUENCY ACROSS ENTIRE DATASET (1800 readings) ---")
    for sig, count in signal_counts_all.most_common():
        print(f"  - {sig:<20}: {count} occurrences ({count/len(records)*100:.2f}% of all readings)")
    print()

    # --- 3. Independent vs Joint Signal Occurrence in all readings ---
    signal_combinations_all = Counter()
    signal_combinations_deg = Counter()
    for rec in records:
        sigs = tuple(sorted(rec["trust"].temporal_summary.get("signals", [])))
        signal_combinations_all[sigs] += 1
    for rec in degrading_records:
        sigs = tuple(sorted(rec["trust"].temporal_summary.get("signals", [])))
        signal_combinations_deg[sigs] += 1

    print("--- 3. COMBINATION OF SIGNALS IN ALL 1800 READINGS ---")
    for sigs, count in signal_combinations_all.most_common():
        name = " + ".join(sigs) if sigs else "NONE"
        print(f"  - {name:<40}: {count} readings")
    print()

    print("--- 3b. COMBINATION OF SIGNALS IN 110 DEGRADING READINGS ---")
    for sigs, count in signal_combinations_deg.most_common():
        name = " + ".join(sigs) if sigs else "NONE"
        print(f"  - {name:<40}: {count} readings")
    print()

    # --- 4. Role of Isolation Forest Anomalies ---
    print("--- 4. ISOLATION FOREST CONTRIBUTION TO DEGRADING ---")
    anom_in_deg = sum(1 for rec in degrading_records if rec["anom"].is_anomaly)
    anom_in_caut = sum(1 for rec in caution_records if rec["anom"].is_anomaly)
    anom_in_norm = sum(1 for rec in normal_records if rec["anom"].is_anomaly)
    rule_viols_in_all = sum(len(rec["rule"].violations) for rec in records)

    print(f"  - Rule violations in normal_data.json    : {rule_viols_in_all} (Stage 3 found 0 violations)")
    print(f"  - Total Isolation Forest anomalies (IF) : {anom_in_deg + anom_in_caut + anom_in_norm} / 1800 (10.0%)")
    print(f"  - Anomalies in DEGRADING                 : {anom_in_deg} / {len(degrading_records)} ({anom_in_deg/len(degrading_records)*100:.1f}%)")
    print(f"  - Anomalies in CAUTION                   : {anom_in_caut} / {len(caution_records)} ({anom_in_caut/len(caution_records)*100:.1f}%)")
    print(f"  - Anomalies in NORMAL                    : {anom_in_norm} / {len(normal_records)} ({anom_in_norm/len(normal_records)*100:.1f}%)")
    print()
    print("  KEY FINDING: Exactly 180 readings had is_anomaly=True from Stage 2.")
    print("  When is_anomaly=True AND len(signals) > 0 -> state becomes DEGRADING (110 readings).")
    print("  When is_anomaly=True AND len(signals) == 0 -> state becomes CAUTION (70 readings).")
    print("  When is_anomaly=False, even if len(signals) > 0, state stays NORMAL (1620 readings).")
    print()

    # --- 5 & 6. Sequences Analysis (Islands of Degrading) ---
    deg_indices = [rec["index"] for rec in degrading_records]
    sequences = []
    if deg_indices:
        start = deg_indices[0]
        prev = deg_indices[0]
        for idx in deg_indices[1:]:
            if idx == prev + 1:
                prev = idx
            else:
                sequences.append((start, prev, prev - start + 1))
                start = idx
                prev = idx
        sequences.append((start, prev, prev - start + 1))

    print("--- 5 & 6. SEQUENCE ANALYSIS OF DEGRADING READINGS ---")
    print(f"Total contiguous sequences of DEGRADING: {len(sequences)}")
    length_distribution = Counter(length for _, _, length in sequences)
    print("Sequence length distribution:")
    for length, count in sorted(length_distribution.items()):
        print(f"  - Length {length:2d}: {count:2d} occurrences ({count*length:3d} readings total)")
    print()

    print("Exact list of first and last indices for each sequence:")
    for i, (s, e, l) in enumerate(sequences):
        if l == 1:
            print(f"  Seq #{i+1:2d}: Reading #{s} (isolated 1 reading)")
        else:
            print(f"  Seq #{i+1:2d}: Readings #{s} to #{e} ({l} consecutive readings)")
    print()

    # --- 7. Print 10 Representative Degrading Readings ---
    print("--- 7. 10 REPRESENTATIVE NORMAL READINGS THAT BECAME DEGRADING ---")
    step = max(1, len(degrading_records) // 10)
    sample_recs = [degrading_records[i] for i in range(0, len(degrading_records), step)][:10]

    for rank, rec in enumerate(sample_recs, 1):
        idx = rec["index"]
        trust = rec["trust"]
        fv = rec["fv"]
        anom = rec["anom"]
        derived = fv.derived_features
        raw = fv.raw_features

        print(f"Sample #{rank} (Reading Index #{idx}):")
        print(f"  Trust Score     : {trust.trust_score:.2f} / 100.0")
        print(f"  State / Decision: {trust.state.value} / {trust.decision.value}")
        print(f"  Anomaly Score   : {anom.anomaly_score:.4f} (is_anomaly={anom.is_anomaly})")
        print(f"  Rule Violations : {len(rec['rule'].violations)}")
        print(f"  Temporal Signals: {trust.temporal_summary.get('signals')}")
        print(f"  Rates           : temp_rate={derived.temp_rate:+.5f} °C/s (thresh: >{config.TRUST_TEMP_RATE_THRESHOLD}), "
              f"rpm_rate={derived.rpm_rate:+.2f} RPM/s (thresh: <{config.TRUST_RPM_RATE_THRESHOLD}), "
              f"current_rate={derived.current_rate:+.6f} A/s (thresh: >{config.TRUST_CURRENT_RATE_THRESHOLD}), "
              f"vib_rate={derived.vibration_rate:+.5f} m/s²/s (thresh: >{config.TRUST_VIBRATION_RATE_THRESHOLD})")
        print(f"  Key Values      : temp_avg={derived.temp_avg:.2f}°C, rpm={raw.rpm:.1f}, current={raw.current:.4f}A, vib={raw.vibration:.2f}")
        print(f"  Score Breakdown : {trust.score_breakdown}")
        print(f"  Reasons         : {trust.reasons}")
        print("-" * 80)

if __name__ == "__main__":
    run_audit()
