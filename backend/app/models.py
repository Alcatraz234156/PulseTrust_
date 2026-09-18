from pydantic import BaseModel

class Telemetry(BaseModel):
    device_id: str
    temp_1: float
    temp_2: float
    rpm: float
    hall_raw: int
    vibration: float
    voltage: float
    current: float
    power: float
    fan: bool


