def compare_temperature_sensors(
    temp_1: float,
    temp_2: float,
    tolerance: float = 1.0
) -> dict:

    difference = abs(temp_1 - temp_2)

    if difference <= tolerance:
        agreement_score = 1.0
        agrees = True
    else:
        agreement_score = max(
            0.0,
            1.0 - ((difference - tolerance) / 5.0)
        )
        agrees = False

    return {
        "difference": difference,
        "agreement_score": agreement_score,
        "agrees": agrees
    }