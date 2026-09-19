import os
import json
import time

from dotenv import load_dotenv
from google import genai
from google.genai import errors

load_dotenv()

client = genai.Client(
    api_key=os.getenv("GEMINI_API_KEY")
)


def normalize_sensor_profile(component: dict) -> dict:

    prompt = f"""
You are the specification normalization component of PulseTrust_.

Convert the electronic component information below into a structured
sensor profile.

IMPORTANT RULES:

1. Use ONLY information present in the supplied component data.
2. Never invent missing specifications.
3. Unknown values must be null.
4. Preserve numerical units.
5. Return ONLY valid JSON.
6. Do not include Markdown.
7. Determine whether the component is actually a sensor.
8. Separate measurement limits from electrical/operating limits.

Return exactly this structure:

{{
  "manufacturer": null,
  "model": null,
  "is_sensor": null,
  "sensor_type": null,
  "measurement": {{
    "quantity": null,
    "unit": null,
    "minimum": null,
    "maximum": null,
    "accuracy": null,
    "resolution": null
  }},
  "electrical": {{
    "supply_voltage_min": null,
    "supply_voltage_max": null,
    "supply_current": null
  }},
  "operating_conditions": {{
    "temperature_min": null,
    "temperature_max": null
  }},
  "interface": null
}}

COMPONENT DATA:

{json.dumps(component, indent=2)}
"""

    models = [
        "gemini-3.6-flash",
        "gemini-3.6-flash-lite"
    ]

    response = None
    last_error = None

    for model in models:

        for attempt in range(2):

            try:
                response = client.models.generate_content(
                    model=model,
                    contents=prompt
                )

                print(f"Gemini model used: {model}")
                break

            except errors.ServerError as e:
                last_error = e
                print(
                    f"{model} unavailable "
                    f"(attempt {attempt + 1}/2)"
                )

                time.sleep(2)

        if response is not None:
            break

    if response is None:
        raise RuntimeError(
            f"All Gemini models unavailable: {last_error}"
        )

    text = response.text.strip()

    if text.startswith("```"):
        text = text.replace("```json", "")
        text = text.replace("```", "")
        text = text.strip()

    return json.loads(text)