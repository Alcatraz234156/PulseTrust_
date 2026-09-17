from fastapi import FastAPI, HTTPException, Query, status
from fastapi.responses import JSONResponse
from app.models import Telemetry
from app.config import settings
import app.database as db
from typing import Optional
from datetime import datetime, timezone

app = FastAPI(
    title="PulseTrust_ API",
    description="Sensor telemetry ingestion and storage backend for PulseTrust_.",
    version="0.1.0"
)

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
    db_configured = bool(settings.supabase_url and settings.supabase_key)
    return {
        "status": "healthy",
        "database_configured": db_configured
    }

@app.post("/api/telemetry", status_code=status.HTTP_201_CREATED, tags=["Telemetry"])
def create_reading(data: Telemetry):
    try:
        # Convert model to dict and inject server-side timestamp
        reading_dict = data.model_dump()
        reading_dict['recorded_at'] = datetime.now(timezone.utc).isoformat()
        
        inserted_data = db.insert_sensor_reading(reading_dict)
        return {
            "success": True,
            "message": "Sensor reading stored",
            "reading": inserted_data
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail="Database insertion failed")

@app.get("/api/telemetry/latest", tags=["Telemetry"])
def get_latest_reading(device_id: Optional[str] = Query(None, description="Filter by device ID")):
    try:
        reading = db.get_latest_sensor_reading(device_id=device_id)
        if not reading:
            raise HTTPException(status_code=404, detail="No readings found")
        return reading
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail="Database retrieval failed")

@app.get("/api/telemetry", tags=["Telemetry"])
def get_readings(
    device_id: Optional[str] = Query(None, description="Filter by device ID"),
    limit: int = Query(50, le=500, description="Number of recent readings to fetch")
):
    try:
        readings = db.get_sensor_readings(device_id=device_id, limit=limit)
        return readings
    except Exception as e:
        raise HTTPException(status_code=500, detail="Database retrieval failed")

