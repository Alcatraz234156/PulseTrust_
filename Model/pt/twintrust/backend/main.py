from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI()


# The Pydantic model describes what a valid sensor reading looks like.
# FastAPI uses it to automatically check (validate) incoming POST data.
class SensorData(BaseModel):
    temperature: float
    current: float
    vibration: float


# Root endpoint - a simple health check to confirm the backend is alive.
@app.get("/")
def home():
    return {"message": "TrustTwin backend is running!"}


# GET endpoint that returns one fake sensor reading.
# The values are fixed for now; realistic/random data comes in a later phase.
@app.get("/sensor-data")
def get_sensor_data():
    return {
        "temperature": 42.3,
        "current": 1.72,
        "vibration": 0.31
    }


# POST endpoint that receives sensor data as JSON.
# The SensorData model makes FastAPI reject the request with a clear
# error if any field is missing or has the wrong type.
@app.post("/sensor-data")
def receive_sensor_data(data: SensorData):
    return {
        "message": "Sensor data received",
        "data": data
    }
