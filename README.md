# PulseTrust_

**PulseTrust_** is an industrial sensor-trust and machine-monitoring prototype designed to prevent autonomous systems from making decisions based on unreliable sensor data.

The system collects real-world telemetry from an ESP32-based hardware platform, sends it to a FastAPI backend, and stores the readings in Supabase for further trust analysis, visualization, and decision-making.

## Architecture

```text
Physical Sensors
      ↓
     ESP32
      ↓
   FastAPI
      ↓
   Supabase
```

## Hardware & Sensors

The current prototype uses:

- ESP32 DevKit
- 2× DS18B20 temperature sensors
- MPU6050-family IMU for motion/vibration sensing
- 44E Hall-effect sensor for RPM measurement
- INA219 current, voltage, and power monitor
- 5V DC fan as the monitored/controlled actuator
- OLED display
- LED and buzzer for physical status indication

## Telemetry

PulseTrust_ currently records:

- Temperature Sensor 1
- Temperature Sensor 2
- RPM
- Raw Hall-effect sensor value
- Vibration / acceleration
- Voltage
- Current
- Power
- Fan state
- Device ID
- Server-generated timestamp

## Backend Setup

### 1. Enter the backend directory

```bash
cd backend
```

### 2. Create a virtual environment

```bash
python -m venv .venv
```

### 3. Activate the virtual environment

**Windows PowerShell**

```powershell
.\.venv\Scripts\Activate.ps1
```

**macOS/Linux**

```bash
source .venv/bin/activate
```

### 4. Install dependencies

```bash
python -m pip install -r requirements.txt
```

### 5. Configure environment variables

Copy `.env.example` to `.env` and add your Supabase credentials:

```env
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_KEY=your_backend_supabase_key
```

> Never commit `.env` or expose Supabase secrets in the ESP32 firmware or frontend.

### 6. Start the API

For local development:

```bash
python -m uvicorn app.main:app --reload
```

The API will be available at:

```text
http://127.0.0.1:8000
```

Swagger documentation:

```text
http://127.0.0.1:8000/docs
```

## ESP32 / LAN Setup

The ESP32 cannot access the FastAPI server using `127.0.0.1`, because that address refers to the ESP32 itself from its perspective.

Start FastAPI on all network interfaces:

```bash
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

Find the laptop's local IPv4 address on Windows:

```powershell
ipconfig
```

Then configure the ESP32 endpoint using the laptop's LAN address:

```text
http://192.168.1.100:8000/api/telemetry
```

Replace `192.168.1.100` with the actual IPv4 address of the machine running PulseTrust_.

The ESP32 and backend machine must be reachable over the same network.

> Your operating system firewall may need to allow incoming connections on port `8000`.

## API

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/` | API status and project metadata |
| `GET` | `/health` | Backend health and database configuration status |
| `POST` | `/api/telemetry` | Store a new telemetry reading |
| `GET` | `/api/telemetry` | Retrieve recent telemetry |
| `GET` | `/api/telemetry/latest` | Retrieve the latest telemetry reading |

`GET /api/telemetry` supports optional `device_id` and `limit` query parameters.

## Example Telemetry Payload

```json
{
  "device_id": "pulsetrust-plant-01",
  "temp_1": 28.5,
  "temp_2": 28.75,
  "rpm": 1500.0,
  "hall_raw": 320,
  "vibration": 9.61,
  "voltage": 4.85,
  "current": 0.143,
  "power": 0.694,
  "fan": true
}
```

The backend automatically generates the `recorded_at` timestamp when the telemetry is received.

The ESP32 should send the request with:

```text
Content-Type: application/json
```

## Database

Telemetry is stored in the Supabase `sensor_readings` table.

Each reading contains the sensor measurements, actuator state, device identifier, and timestamp required for later analysis and visualization.

## Current Status

The current PulseTrust_ prototype supports:

- Real physical sensor acquisition
- Redundant temperature sensing
- RPM measurement
- Vibration monitoring
- Electrical telemetry
- ESP32 Wi-Fi telemetry transmission
- FastAPI validation and ingestion
- Supabase telemetry storage
- Latest and historical telemetry retrieval
- Physical actuator and status hardware

## Project Direction

PulseTrust_ is being developed around the principle:

> **Trust Before Action.**

Rather than assuming every sensor measurement is reliable, PulseTrust_ is designed to provide an evidence layer between physical sensors and autonomous decisions.

The telemetry infrastructure established in the current prototype provides the foundation for sensor agreement analysis, anomaly detection, trust scoring, decision gating, visualization, AI-assisted explanations, and cloud integration.