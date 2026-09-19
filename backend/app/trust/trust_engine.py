from app.trust.anomaly_detector import detect_anomaly
from app.trust.cross_sensor import compare_temperature_sensors


def calculate_temperature_trust(
    temp_1_history: list[float],
    temp_2_history: list[float]
) -> dict:

    if len(temp_1_history) < 5 or len(temp_2_history) < 5:
        raise ValueError("At least 5 readings per sensor are required")

    anomaly_1 = detect_anomaly(temp_1_history)
    anomaly_2 = detect_anomaly(temp_2_history)

    current_1 = temp_1_history[-1]
    current_2 = temp_2_history[-1]

    agreement = compare_temperature_sensors(
        current_1,
        current_2
    )

    reasons = []

    # Start fully trusted
    trust_1 = 100.0
    trust_2 = 100.0

    # Individual behavioural anomaly
    if anomaly_1["is_anomaly"]:
        trust_1 -= 20
        reasons.append("Sensor 1 behavior is anomalous")

    if anomaly_2["is_anomaly"]:
        trust_2 -= 20
        reasons.append("Sensor 2 behavior is anomalous")

    # Attribute disagreement using behavioral evidence
    if not agreement["agrees"]:
        disagreement_penalty = 40 * (
            1.0 - agreement["agreement_score"]
        )

        if anomaly_1["is_anomaly"] and not anomaly_2["is_anomaly"]:
            # Sensor 1 is the stronger fault candidate
            trust_1 -= disagreement_penalty

            reasons.append(
                "Sensor 1 is anomalous while Sensor 2 remains behaviorally normal"
            )

        elif anomaly_2["is_anomaly"] and not anomaly_1["is_anomaly"]:
            # Sensor 2 is the stronger fault candidate
            trust_2 -= disagreement_penalty

            reasons.append(
                "Sensor 2 is anomalous while Sensor 1 remains behaviorally normal"
            )

        else:
            # Cannot confidently determine which sensor is responsible
            shared_penalty = disagreement_penalty / 2

            trust_1 -= shared_penalty
            trust_2 -= shared_penalty

            reasons.append(
                "Sensors disagree, but the unreliable sensor cannot be isolated"
            )

        reasons.append(
            f"Temperature sensors disagree by "
            f"{agreement['difference']:.2f} °C"
        )

    # Both sensors anomalous but mutually corroborating:
    # likely a real process event rather than sensor failure
    corroborated_event = (
        anomaly_1["is_anomaly"]
        and anomaly_2["is_anomaly"]
        and agreement["agrees"]
    )

    if corroborated_event:
        trust_1 += 15
        trust_2 += 15

        reasons.append(
            "Both sensors show abnormal behavior but mutually corroborate"
        )

    trust_1 = max(0.0, min(100.0, trust_1))
    trust_2 = max(0.0, min(100.0, trust_2))

    overall_trust = (trust_1 + trust_2) / 2

    if overall_trust >= 80:
        state = "TRUSTED"
    elif overall_trust >= 50:
        state = "DEGRADED"
    else:
        state = "UNTRUSTED"

    return {
        "trust_score": round(overall_trust, 2),
        "state": state,

        "sensor_1": {
            "value": current_1,
            "trust_score": round(trust_1, 2),
            "anomaly": anomaly_1["is_anomaly"],
            "anomaly_score": round(
                anomaly_1["decision_score"], 4
            )
        },

        "sensor_2": {
            "value": current_2,
            "trust_score": round(trust_2, 2),
            "anomaly": anomaly_2["is_anomaly"],
            "anomaly_score": round(
                anomaly_2["decision_score"], 4
            )
        },

        "agreement": agreement,
        "corroborated_event": corroborated_event,
        "reasons": reasons
    }