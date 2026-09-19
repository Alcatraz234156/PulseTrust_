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


def explain_trust(
    telemetry: dict,
    trust_result: dict
) -> dict:

    prompt = f"""
You are the reasoning layer of PulseTrust_.

PulseTrust_ evaluates whether industrial sensor readings can be trusted.

You are NOT responsible for calculating the trust score.
The deterministic Trust Engine has already calculated it.

Your job is to explain the supplied evidence and identify plausible
cross-sensor inconsistencies.

Rules:

1. Do not modify the trust score.
2. Do not invent sensor readings.
3. Use only the supplied evidence.
4. An abnormal machine condition does NOT automatically mean the sensor is faulty.
5. Distinguish sensor reliability from machine/process health.
6. Be concise.
7. Return ONLY valid JSON.

Return:

{{
  "summary": "",
  "sensor_assessment": "",
  "process_assessment": "",
  "recommended_action": ""
}}

TELEMETRY:
{json.dumps(telemetry, indent=2)}

TRUST ENGINE RESULT:
{json.dumps(trust_result, indent=2)}
"""

    response = None

    for attempt in range(2):
        try:
            response = client.models.generate_content(
                model="gemini-3.6-flash",
                contents=prompt
            )
            break

        except errors.ServerError:
            time.sleep(2)

    if response is None:
        return {
            "summary": "AI explanation temporarily unavailable.",
            "sensor_assessment": None,
            "process_assessment": None,
            "recommended_action": None
        }

    text = response.text.strip()

    if text.startswith("```"):
        text = text.replace("```json", "")
        text = text.replace("```", "")
        text = text.strip()

    return json.loads(text)