# PulseTrust_

> **Trust Before Action.**

**PulseTrust_** is an industrial sensor-trust and machine-monitoring prototype designed to prevent autonomous systems from making decisions based on unreliable sensor data.

Instead of assuming that every sensor reading is trustworthy, PulseTrust_ introduces an **evidence and trust layer** between physical sensors and downstream autonomous decisions.

The system combines real-world ESP32 telemetry, behavioral anomaly detection, redundant sensor corroboration, deterministic trust scoring, component metadata, and AI-assisted reasoning to distinguish between:

- normal sensor behavior,
- potentially faulty or inconsistent sensors,
- and genuine abnormal process conditions reported by trustworthy sensors.

A key principle of PulseTrust_ is:

> **An abnormal measurement does not necessarily mean the sensor is faulty.**

A sensor may be accurately reporting a dangerous or unusual physical condition. PulseTrust_ therefore evaluates **sensor trust separately from process health**.

---

## Architecture

```text
                    PulseTrust_ Architecture

Physical Sensors
      │
      ▼
    ESP32
      │
      ▼
   FastAPI
      │
      ├──────────────► Supabase
      │                    │
      │              Telemetry History
      │                    │
      ▼                    ▼
Feature Engineering ◄──────┘
      │
      ▼
Isolation Forest
Behavioral Anomaly Detection
      │
      ├──────────────────────┐
      │                      │
      ▼                      ▼
Sensor Agreement       Cross-Sensor Evidence
      │                      │
      └──────────┬───────────┘
                 ▼
            Trust Engine
                 │
        ┌────────┴─────────┐
        ▼                  ▼
 Trust Score / State    Gemini Reasoner
        │                  │
        │                  ├─ Sensor Assessment
        │                  ├─ Process Assessment
        │                  ├─ Explanation
        │                  └─ Recommended Action
        │
        ▼
      Web Dashboard
        │
   ┌────┼─────────┐
   ▼    ▼         ▼
Telemetry  Digital   Trust / AI
 Charts     Twin     Explanation
```

The deterministic trust engine remains operational independently of the AI reasoning layer.

Gemini is used to **interpret and explain evidence**, not to directly calculate the core trust score.

---

## Hardware & Sensors

The current physical prototype uses:

- ESP32 DevKit
- 2× DS18B20 temperature sensors
- MPU6050-family IMU for motion/acceleration monitoring
- 44E Hall-effect sensor for RPM measurement
- INA219 current, voltage, and power monitor
- 5V DC fan as the monitored/controlled actuator
- OLED display
- LED and buzzer for physical status indication

---

## Telemetry

PulseTrust_ currently records:

- Temperature Sensor 1
- Temperature Sensor 2
- RPM
- Raw Hall-effect sensor value
- Vibration / acceleration measurement
- Voltage
- Current
- Power
- Fan state
- Device ID
- Server-generated timestamp

Example telemetry:

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

---

# Sensor Trust Intelligence

## 1. Feature Engineering

Historical telemetry is converted into behavioral features such as:

- normalized value
- rate of change
- rolling mean
- rolling standard deviation
- deviation from baseline
- stuck-sensor score

These features allow PulseTrust_ to reason about sensor behavior rather than relying only on absolute thresholds.

---

## 2. Behavioral Anomaly Detection

PulseTrust_ currently uses an **Isolation Forest** model to identify unusual sensor behavior.

The current prototype demonstrates this primarily using the redundant temperature sensors.

The model can identify behaviors such as:

```text
Sudden spike
     ↓
Behavioral anomaly

Sensor remains frozen
     ↓
Potential stuck-sensor anomaly

Unexpected continuous drift
     ↓
Behavioral anomaly
```

For the current hackathon prototype, the temperature anomaly model is bootstrapped using synthetic baseline telemetry representing normal temperature behavior.

The resulting anomaly evidence is then combined with other evidence rather than being treated as proof that a sensor has failed.

> Anomaly detection and sensor trust are intentionally separate concepts.

---

## 3. Cross-Sensor Corroboration

PulseTrust_ compares redundant sensor measurements to determine whether independent sensors support the same physical observation.

For example:

```text
Sensor 1: 45.0 °C
Sensor 2: 28.5 °C

Behavior:
Sensor 1 anomalous
Sensor 2 normal
Sensors disagree

Result:
Sensor 1 becomes significantly less trustworthy.
```

But:

```text
Sensor 1: 44.7 °C
Sensor 2: 44.6 °C

Behavior:
Both sensors show abnormal behavior
Sensors strongly agree

Result:
The process may be abnormal,
while the measurements remain trustworthy.
```

This allows PulseTrust_ to distinguish **sensor failure from a genuine physical event**.

---

## 4. Trust Engine

The trust engine combines:

```text
Behavioral anomaly evidence
            +
Sensor agreement
            +
Cross-sensor corroboration
            ↓
        Trust Score
```

Current trust states are:

```text
80–100   TRUSTED
50–79    DEGRADED
0–49     UNTRUSTED
```

The current scores are prototype evidence scores and should not be interpreted as calibrated probabilities of sensor correctness.

Example output:

```json
{
  "trust_score": 95.0,
  "state": "TRUSTED",
  "sensor_1": {
    "value": 44.65,
    "trust_score": 95.0,
    "anomaly": true
  },
  "sensor_2": {
    "value": 44.56,
    "trust_score": 95.0,
    "anomaly": true
  },
  "corroborated_event": true
}
```

Here, both sensors are behaving unusually but corroborate each other.

PulseTrust_ therefore preserves high **sensor trust** while allowing the downstream system to recognize that the **physical process itself may be abnormal**.

---

## 5. AI-Assisted Reasoning

PulseTrust_ includes a Gemini-based reasoning layer.

Gemini receives:

```text
Current telemetry
        +
Trust Engine result
        +
Anomaly evidence
        +
Sensor agreement evidence
        ↓
AI Explanation
```

It generates:

- a concise trust summary
- sensor assessment
- process assessment
- recommended action

The AI layer does **not** calculate or override the deterministic trust score.

If AI reasoning becomes unavailable, the core trust engine continues functioning.

---

## Component Intelligence

PulseTrust_ also contains an experimental component-identification and profiling layer.

Given a sensor part number, the backend can retrieve component metadata through the Mouser Search API and normalize the information into a sensor profile.

The architecture is designed to support future automatic ingestion of manufacturer datasheets and sensor specifications.

Detailed datasheet extraction is currently experimental and is not required by the runtime trust pipeline.

---

# Backend Setup

## 1. Enter the backend directory

```bash
cd backend
```

## 2. Create a virtual environment

```bash
python -m venv .venv
```

## 3. Activate the virtual environment

### Windows PowerShell

```powershell
.\.venv\Scripts\Activate.ps1
```

### macOS/Linux

```bash
source .venv/bin/activate
```

## 4. Install dependencies

```bash
python -m pip install -r requirements.txt
```

## 5. Configure environment variables

Copy `.env.example` to `.env`.

Configure the required services:

```env
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_KEY=your_backend_supabase_key

GEMINI_API_KEY=your_gemini_api_key

MOUSER_API_KEY=your_mouser_api_key
```

> Never commit `.env` or expose backend credentials in ESP32 firmware or frontend code.

## 6. Start the API

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

---

# ESP32 / LAN Setup

The ESP32 cannot access the FastAPI server using `127.0.0.1`, because that address refers to the ESP32 itself from its perspective.

Start FastAPI on all network interfaces:

```bash
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

Find the backend machine's local IPv4 address on Windows:

```powershell
ipconfig
```

Configure the ESP32 telemetry endpoint using that address:

```text
http://192.168.1.100:8000/api/telemetry
```

Replace `192.168.1.100` with the actual IPv4 address of the machine running PulseTrust_.

The ESP32 and backend machine must be reachable over the same network.

> Your operating system firewall may need to allow incoming connections on port `8000`.

---

# API

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/` | API status and project metadata |
| `GET` | `/health` | Backend/database health |
| `POST` | `/api/telemetry` | Store a telemetry reading |
| `GET` | `/api/telemetry` | Retrieve telemetry history |
| `GET` | `/api/telemetry/latest` | Retrieve latest telemetry |
| `GET` | `/api/trust/latest` | Calculate trust from live stored telemetry |
| `GET` | `/api/trust/explain` | Trust result with Gemini-assisted explanation |
| `GET` | `/api/trust/demo/normal` | Simulate normal operation |
| `GET` | `/api/trust/demo/sensor-failure` | Simulate a faulty/inconsistent sensor |
| `GET` | `/api/trust/demo/real-event` | Simulate a genuine corroborated process event |

`GET /api/telemetry` supports optional `device_id` and `limit` query parameters.

---

# Web Dashboard

PulseTrust_ includes an interactive web dashboard for visualizing live telemetry, sensor trust, anomaly evidence, and machine state.

The dashboard provides:

- Overall trust score and trust state
- Digital twin visualization of the monitored fan
- Live temperature, RPM, electrical, and vibration telemetry
- Isolation Forest anomaly evidence
- Sensor-validation and trust evidence
- Trust-score breakdown
- Human-readable decision explanations
- Historical telemetry charts
- Machine-state timeline
- Expandable technical diagnostics
- Live and simulation operating modes

The frontend communicates with the FastAPI backend and presents trust-engine output separately from raw sensor telemetry.

## Frontend Structure

```text
frontend/
├── index.html
├── styles.css
└── script.js
```

The dashboard uses vanilla HTML, CSS, and JavaScript, keeping the visualization layer lightweight and independent of a frontend framework.

## Running the Dashboard

The backend also serves the dashboard directly at **http://127.0.0.1:8000/dashboard/**.
Start it from the repository root with:

```powershell
cd backend
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

This uses the same origin for dashboard assets and API requests. Live readings
are polled every five seconds and connection failures are retried automatically.
If trust analysis is unavailable, raw telemetry remains visible. When using a
separate local frontend server, the dashboard connects to port 8000 on the same
hostname; local development origins on ports 5500, 5501, 3000, and 5173 are allowed.

Start the backend:

```bash
cd backend
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

Then serve the frontend from its directory:

```bash
cd frontend
python -m http.server 5500
```

Open:

```text
http://127.0.0.1:5500
```

The frontend API base URL can be configured in `script.js`.

---

# Simulation Mode

PulseTrust_ includes explicitly labelled simulation endpoints for demonstrating trust behavior without requiring the physical hardware to be connected.

### Normal Operation

```text
/api/trust/demo/normal
```

Expected behavior:

```text
Sensors behave normally
Sensors agree
        ↓
TRUSTED
```

### Sensor Failure

```text
/api/trust/demo/sensor-failure
```

Expected behavior:

```text
One sensor becomes anomalous
Sensors disagree
        ↓
DEGRADED
```

### Genuine Process Event

```text
/api/trust/demo/real-event
```

Expected behavior:

```text
Both sensors become anomalous
Both report the same physical change
        ↓
Corroborated Event
        ↓
Sensors remain highly trusted
```

Simulation responses contain:

```json
{
  "mode": "SIMULATION"
}
```

Live trust responses contain:

```json
{
  "mode": "LIVE"
}
```

This keeps simulated demonstration data clearly separated from real telemetry.

---

# Database

Telemetry is stored in the Supabase `sensor_readings` table.

Each reading contains the sensor measurements, actuator state, device identifier, and server timestamp required for historical analysis and visualization.

---

# Current Status

The PulseTrust_ prototype currently supports:

- Real physical sensor acquisition
- ESP32 Wi-Fi telemetry transmission
- Redundant temperature sensing
- RPM sensing
- Electrical telemetry
- Motion/acceleration monitoring
- FastAPI telemetry ingestion
- Supabase historical telemetry storage
- Feature extraction from sensor history
- Isolation Forest anomaly detection
- Stuck-sensor detection evidence
- Redundant sensor agreement analysis
- Cross-sensor corroboration
- Per-sensor trust scoring
- Overall trust states
- Live trust analysis
- Simulation scenarios
- Gemini-assisted trust explanations
- Component metadata lookup
- Interactive web dashboard
- Digital twin visualization
- Live telemetry visualization
- Historical telemetry charts
- Trust evidence visualization
- Trust-score breakdown
- Machine-state timeline
- Expandable technical diagnostics
- Physical fan, OLED, LED, and buzzer hardware

---

# Prototype Scope

The current implementation is a **hackathon prototype**, not a certified industrial safety system.

The Isolation Forest model currently demonstrates behavioral trust analysis primarily on temperature telemetry and is bootstrapped using synthetic baseline data.

Trust scores are heuristic evidence scores rather than calibrated failure probabilities.

The architecture is designed so that additional sensor types, historical datasets, specification validation, cloud infrastructure, and more advanced cross-sensor reasoning can be incorporated without changing the core **Trust Before Action** principle.

---

# Project Direction

Modern autonomous systems increasingly depend on physical sensors to decide when to start, stop, cool, accelerate, alert, isolate, or otherwise interact with the real world.

PulseTrust_ asks a question that should come first:

> **Can the system trust the measurement it is about to act on?**

The long-term goal is to provide a reusable sensor-trust layer between physical telemetry and autonomous decision systems:

```text
Physical World
      ↓
   Sensors
      ↓
  PulseTrust_
      ↓
Trusted Evidence
      ↓
Autonomous System
```

**Trust Before Action.**
