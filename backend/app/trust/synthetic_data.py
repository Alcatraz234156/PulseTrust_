import numpy as np


def generate_temperature_baseline(
    samples: int = 1000,
    start_temp: float = 28.5,
    seed: int = 42
) -> list[float]:

    rng = np.random.default_rng(seed)

    temperature = start_temp
    values = []

    for _ in range(samples):
        # Slow environmental drift
        temperature += rng.normal(0, 0.025)

        # Small sensor quantization/noise
        measured = temperature + rng.normal(0, 0.04)

        # Approximate digital sensor quantization
        measured = round(measured * 16) / 16

        values.append(float(measured))

    return values