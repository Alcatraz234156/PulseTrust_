"""Shared scenario inputs for FastAPI and the local Lambda adapter."""

def demo_histories(scenario: str):
    normal = [
        28.5,
        28.5625,
        28.5,
        28.625,
        28.5625,
        28.625,
        28.6875,
        28.625,
        28.6875,
        28.75,
        28.6875,
        28.75,
        28.6875,
        28.75,
        28.8125,
        28.75,
        28.8125,
        28.75,
        28.8125,
        28.875
    ]

    if scenario == "normal":
        temp_1 = normal
        temp_2 = normal

    elif scenario == "sensor-failure":
        temp_1 = normal[:-1] + [45.0]
        temp_2 = normal

    elif scenario == "real-event":
        temp_1 = [
            28.5 + i * 0.85
            for i in range(20)
        ]

        temp_2 = [
            28.6 + i * 0.84
            for i in range(20)
        ]

    else:
        raise ValueError("Unknown scenario. Use: normal, sensor-failure, real-event")

    return temp_1, temp_2
