from fastapi import FastAPI, HTTPException, Query, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pathlib import Path
from app.models import Telemetry
from app.config import settings
import app.database as db
from typing import Optional
from datetime import datetime, timezone
from app.trust.ai_reasoner import explain_trust

from app.database import get_sensor_readings
from app.trust.trust_engine import calculate_temperature_trust


app = FastAPI(
    title="PulseTrust_ API",
    description="Sensor telemetry ingestion and storage backend for PulseTrust_.",
    version="0.1.0"
)

# Initial hackathon deployment: allow Amplify origins without browser credentials.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

frontend_dir = Path(__file__).resolve().parents[2] / "frontend"
if frontend_dir.is_dir():
    app.mount("/dashboard", StaticFiles(directory=frontend_dir, html=True), name="dashboard")


@app.get("/", tags=["System"])
def read_root():
    return {
        "project": "PulseTrust_",
        "status": "online",
        "service": "sensor telemetry backend",
        "version": "0.1.0"
    }


@app.get("/health", tags=["System"])
def health_check():
    db_configured = bool(
        settings.supabase_url and settings.supabase_key
    )

    return {
        "status": "healthy",
        "database_configured": db_configured
    }


@app.get("/api/aws/status", tags=["System"])
def aws_local_status():
    from app.aws_local import integration_status
    return integration_status()


@app.post(
    "/api/telemetry",
    status_code=status.HTTP_201_CREATED,
    tags=["Telemetry"]
)
def create_reading(data: Telemetry):
    try:
        reading_dict = data.model_dump()
        reading_dict["recorded_at"] = datetime.now(
            timezone.utc
        ).isoformat()

        inserted_data = db.insert_telemetry(reading_dict)

        return {
            "success": True,
            "message": "Sensor reading stored",
            "reading": inserted_data
        }

    except Exception as e:
        print("SUPABASE ERROR:", repr(e))

        raise HTTPException(
            status_code=500,
            detail=f"Supabase error: {str(e)}"
        )


@app.get("/api/telemetry/latest", tags=["Telemetry"])
def get_latest_reading(
    device_id: Optional[str] = Query(
        None,
        description="Filter by device ID"
    )
):
    try:
        reading = db.get_latest_sensor_reading(
            device_id=device_id
        )

        if not reading:
            raise HTTPException(
                status_code=404,
                detail="No readings found"
            )

        return reading

    except HTTPException:
        raise

    except Exception:
        raise HTTPException(
            status_code=500,
            detail="Database retrieval failed"
        )


@app.get("/api/telemetry", tags=["Telemetry"])
def get_readings(
    device_id: Optional[str] = Query(
        None,
        description="Filter by device ID"
    ),
    limit: int = Query(
        50,
        le=500,
        description="Number of recent readings to fetch"
    )
):
    try:
        return db.get_sensor_readings(
            device_id=device_id,
            limit=limit
        )

    except Exception:
        raise HTTPException(
            status_code=500,
            detail="Database retrieval failed"
        )


@app.get("/api/trust/latest", tags=["Trust"])
def get_latest_trust(
    device_id: Optional[str] = None
):
    rows = get_sensor_readings(
        device_id=device_id,
        limit=100
    )

    if not rows:
        raise HTTPException(
            status_code=404,
            detail="No telemetry available"
        )

    # Supabase returns newest -> oldest
    rows.reverse()

    temp_1_history = [
        float(row["temp_1"])
        for row in rows
        if row.get("temp_1") is not None
    ]

    temp_2_history = [
        float(row["temp_2"])
        for row in rows
        if row.get("temp_2") is not None
    ]

    if (
        len(temp_1_history) < 5
        or len(temp_2_history) < 5
    ):
        raise HTTPException(
            status_code=400,
            detail=(
                "Not enough temperature history "
                "for trust analysis"
            )
        )

    try:
        result = calculate_temperature_trust(
            temp_1_history,
            temp_2_history
        )

        return {
            "mode": "LIVE",
            "device_id": (
                device_id
                or rows[-1]["device_id"]
            ),
            **result
        }

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=str(e)
        )


@app.get(
    "/api/trust/demo/{scenario}",
    tags=["Trust"]
)
def get_trust_demo(scenario: str):

    from app.trust.demo_inputs import demo_histories

    try:
        temp_1, temp_2 = demo_histories(scenario)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    result = calculate_temperature_trust(
        temp_1,
        temp_2
    )

    return {
        "mode": "SIMULATION",
        "scenario": scenario,
        **result
    }

@app.get("/api/trust/explain", tags=["Trust"])
def explain_latest_trust(
    device_id: Optional[str] = None
):
    rows = get_sensor_readings(
        device_id=device_id,
        limit=100
    )

    if not rows:
        raise HTTPException(
            status_code=404,
            detail="No telemetry available"
        )

    latest_telemetry = rows[0]

    rows.reverse()

    temp_1_history = [
        float(row["temp_1"])
        for row in rows
        if row.get("temp_1") is not None
    ]

    temp_2_history = [
        float(row["temp_2"])
        for row in rows
        if row.get("temp_2") is not None
    ]

    if len(temp_1_history) < 5 or len(temp_2_history) < 5:
        raise HTTPException(
            status_code=400,
            detail="Not enough telemetry history"
        )

    trust_result = calculate_temperature_trust(
        temp_1_history,
        temp_2_history
    )

    try:
        explanation = explain_trust(
            telemetry=latest_telemetry,
            trust_result=trust_result
        )
    except Exception as e:
        explanation = {
            "summary": "AI explanation temporarily unavailable.",
            "sensor_assessment": None,
            "process_assessment": None,
            "recommended_action": None,
            "error": str(e)
        }

    return {
        "mode": "LIVE",
        "device_id": (
            device_id
            or latest_telemetry["device_id"]
        ),
        "trust": trust_result,
        "ai_reasoning": explanation
    }
