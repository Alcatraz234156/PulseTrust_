# PulseTrust_

PulseTrust_ is an industrial machine-monitoring and sensor-trust prototype that ingests telemetry from physical DC motors to track their health and operation.

## Current Architecture

Sensors -> ESP32 -> FastAPI -> Supabase

## Sensors

* MPU6500-family IMU
* Temperature sensor
* Hall-effect sensor
* INA219 current/power monitor

## Backend Setup

1. Enter the backend directory:
   ```bash
   cd PulseTrust_/backend
   ```

2. Create a virtual environment:
   ```bash
   python -m venv venv
   ```

3. Activate the virtual environment:
   * Windows: `.\venv\Scripts\Activate.ps1`
   * macOS/Linux: `source venv/bin/activate`

4. Install requirements:
   ```bash
   pip install -r requirements.txt
   ```

5. Configure `.env`:
   Copy `.env.example` to `.env` and fill in your Supabase credentials:
   ```
   SUPABASE_URL=https://your-project.supabase.co
   SUPABASE_KEY=your_backend_supabase_key
   ```

6. Start the server:
   ```bash
   uvicorn app.main:app --reload
   ```

## Running

Run this from the `backend` directory:
```bash
uvicorn app.main:app --reload
```

The API will be available at: http://127.0.0.1:8000
Swagger documentation: http://127.0.0.1:8000/docs

To expose the server on your local network (so the ESP32 can connect), use:
```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```
*Note: You may need to allow port 8000 through your local OS firewall for the ESP32 to reach the laptop.*

## API

* **GET /** : Returns basic API status and metadata.
* **GET /health** : Returns health status and whether the database is configured.
* **POST /api/telemetry** : Ingests a new sensor reading based on the hardware contract.
* **GET /api/telemetry** : Retrieves recent readings (supports `device_id` and `limit` query parameters).
* **GET /api/telemetry/latest** : Retrieves the single most recent reading.

### Example POST Body
```json
{
  "device_id": "pulsetrust-motor-01",
  "temp_1": 42.3,
  "temp_2": 45.1,
  "rpm": 1500.0,
  "vibration": 1.01,
  "voltage": 11.94,
  "current": 1.72,
  "power": 20.54,
  "fan": true
}
```

## ESP32 Contract

The ESP32 must connect to Wi-Fi and send HTTP POST requests containing JSON payloads (like the example above) to the FastAPI server. Note that the server generates the `recorded_at` timestamp upon receipt.

**Important:** The ESP32 cannot use `127.0.0.1`. It must use the laptop's Local Area Network (LAN) IP address. 
To find this IP on Windows, open a terminal and run `ipconfig`. Look for the "IPv4 Address" under your Wi-Fi adapter (e.g., `192.168.1.100`).

The target URL for the ESP32 will look like:
`http://192.168.1.100:8000/api/telemetry`

Remember to set the header: `Content-Type: application/json`

## Current Scope

Current version handles sensor ingestion, validation, storage, and retrieval.
Signal processing, NumPy/Pandas analysis, trust scoring, ML, frontend visualization, AI explanations, and AWS integration are intentionally future stages.

