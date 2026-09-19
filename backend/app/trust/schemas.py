from pydantic import BaseModel
from typing import Optional


class SensorReading(BaseModel):
    sensor_id: str
    sensor_model: str
    measurement_type: str
    value: float
    supply_voltage: Optional[float] = None
    timestamp: Optional[str] = None


class TrustResult(BaseModel):
    sensor_id: str
    sensor_model: str

    trust_score: float
    anomaly_score: float
    spec_score: float

    state: str
    reasons: list[str]