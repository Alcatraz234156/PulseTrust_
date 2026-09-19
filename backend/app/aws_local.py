"""Account-free local AWS adapter. Never selects a public AWS endpoint."""

import json
import math
import os
from datetime import datetime, timezone
from urllib.request import Request, ProxyHandler, build_opener

from app.trust.demo_inputs import demo_histories
from app.trust.trust_engine import calculate_temperature_trust

BUCKET = "pulsetrust-local-results"
KEY = "latest.json"
LOCALSTACK_HOST = "http://127.0.0.1:4566"
LOCALSTACK_CONTAINER = "http://localstack:4566"


def local_request(url, *, data=None, method="GET"):
    # Explicit local endpoints and no inherited HTTP proxy / AWS credential chain.
    request = Request(url, data=data, method=method, headers={"Content-Type": "application/json"})
    with build_opener(ProxyHandler({})).open(request, timeout=3) as response:
        return response.read()


def analyze_input(payload):
    if not isinstance(payload, dict):
        raise ValueError("Input must be a JSON object")
    if "scenario" in payload and "telemetry" in payload:
        raise ValueError("Provide scenario or telemetry, not both")
    if "telemetry" in payload:
        rows = payload["telemetry"]
        if not isinstance(rows, list) or not 5 <= len(rows) <= 100:
            raise ValueError("telemetry must contain 5 to 100 ordered readings")
        histories = [[], []]
        devices = set()
        for row in rows:
            if not isinstance(row, dict):
                raise ValueError("Each reading must be an object")
            if row.get("device_id") is not None:
                if not isinstance(row["device_id"], str):
                    raise ValueError("device_id must be a string")
                devices.add(row["device_id"])
            for index, field in enumerate(("temp_1", "temp_2")):
                value = row.get(field)
                if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                    raise ValueError(f"{field} must be a finite number")
                histories[index].append(value)
        if len(devices) > 1:
            raise ValueError("Telemetry must belong to one device")
        metadata = {"mode": "LOCAL_INPUT"}
    else:
        scenario = payload.get("scenario", "normal")
        histories = demo_histories(scenario)
        metadata = {"mode": "SIMULATION", "scenario": scenario}
    return {**metadata, **calculate_temperature_trust(*histories)}


def lambda_handler(event, context):
    """Accept a direct Lambda event or SAM's HTTP proxy event."""
    try:
        payload = event
        if isinstance(event, dict) and "body" in event:
            if event.get("isBase64Encoded"):
                raise ValueError("Send plain JSON, not base64")
            payload = json.loads(event["body"] or "{}")
        result = analyze_input(payload)
    except (ValueError, TypeError) as exc:
        return {"statusCode": 400, "body": json.dumps({"error": str(exc)})}

    result["execution"] = {
        "provider": "AWS SAM local",
        "request_id": getattr(context, "aws_request_id", None),
        "recorded_at": datetime.now(timezone.utc).isoformat(),
    }
    if os.environ.get("PULSETRUST_LOCAL_ARCHIVE") == "1":
        try:
            local_request(
                f"{LOCALSTACK_CONTAINER}/{BUCKET}/{KEY}",
                data=json.dumps(result).encode(), method="PUT",
            )
        except Exception:
            return {"statusCode": 503, "body": json.dumps({
                "error": "Trust analysis succeeded but LocalStack S3 archive is unavailable",
                "trust_result": result,
            })}
        result["archive"] = {"provider": "LocalStack S3", "bucket": BUCKET, "key": KEY}
    return {"statusCode": 200, "headers": {"Content-Type": "application/json"}, "body": json.dumps(result)}


def integration_status():
    """Report live local probes and saved evidence; never fabricate readiness."""
    status = {"mode": "LOCAL_ONLY", "localstack_reachable": False,
              "sam_reachable": False, "last_invocation": None}
    try:
        local_request(f"{LOCALSTACK_HOST}/_localstack/health")
        status["localstack_reachable"] = True
        try:
            status["last_invocation"] = json.loads(local_request(f"{LOCALSTACK_HOST}/{BUCKET}/{KEY}"))
        except Exception:
            pass
    except Exception:
        pass
    # A GET to the POST-only SAM route should return an HTTP error if SAM is alive.
    from urllib.error import HTTPError
    try:
        local_request("http://127.0.0.1:3001/trust")
        status["sam_reachable"] = True
    except HTTPError as exc:
        status["sam_reachable"] = exc.code in (403, 404, 405)
    except Exception:
        pass
    status["active"] = status["localstack_reachable"] and status["sam_reachable"]
    status["invocation_verified"] = status["active"] and status["last_invocation"] is not None
    return status
