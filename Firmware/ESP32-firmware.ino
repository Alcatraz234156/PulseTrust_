#include <WiFi.h>
#include <HTTPClient.h>
#include <Wire.h>
#include <OneWire.h>
#include <DallasTemperature.h>
#include <Adafruit_MPU6050.h>
#include <Adafruit_Sensor.h>
#include <Adafruit_INA219.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>

// =====================================================
// TRUSTTWIN CONFIGURATION
// =====================================================

const char* WIFI_SSID = "";
const char* WIFI_PASSWORD = "";

const char* API_URL =
  "http://YOUR_FASTAPI_ADDRESS:8000/api/telemetry";

const char* DEVICE_ID = "trusttwin-plant-01";

// =====================================================
// PIN DEFINITIONS
// =====================================================

#define TEMP1_PIN 32
#define TEMP2_PIN 33

#define HALL_PIN 34
#define FAN_PIN 25
#define LED_PIN 26
#define BUZZER_PIN 14

#define SDA_PIN 21
#define SCL_PIN 22

// =====================================================
// OLED
// =====================================================

#define SCREEN_WIDTH 128
#define SCREEN_HEIGHT 64
#define OLED_ADDRESS 0x3C

Adafruit_SSD1306 display(
  SCREEN_WIDTH,
  SCREEN_HEIGHT,
  &Wire,
  -1
);

// =====================================================
// TEMPERATURE SENSORS
// =====================================================

OneWire oneWire1(TEMP1_PIN);
OneWire oneWire2(TEMP2_PIN);

DallasTemperature tempSensor1(&oneWire1);
DallasTemperature tempSensor2(&oneWire2);

// =====================================================
// OTHER SENSORS
// =====================================================

Adafruit_MPU6050 mpu;
Adafruit_INA219 ina219;

// =====================================================
// STATUS
// =====================================================

bool inaAvailable = false;
bool oledAvailable = false;
bool fanOn = false;

// =====================================================
// HALL SENSOR / RPM
// 44E ANALOG HALL SENSOR
// =====================================================

float rpm = 0;

unsigned long revolutionCount = 0;
unsigned long lastRPMTime = 0;
unsigned long lastTelemetryTime = 0;

bool magnetDetected = false;

// Calibrated from your sensor:
// No magnet ~= 0
// Magnet close ~= 680
const int HALL_ON_THRESHOLD = 250;
const int HALL_OFF_THRESHOLD = 100;

const unsigned long TELEMETRY_INTERVAL = 1000;

// =====================================================
// WIFI
// =====================================================

void connectWiFi() {

  Serial.print("Connecting to WiFi");

  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

  unsigned long start = millis();

  while (
    WiFi.status() != WL_CONNECTED &&
    millis() - start < 15000
  ) {
    delay(500);
    Serial.print(".");
  }

  if (WiFi.status() == WL_CONNECTED) {

    Serial.println();
    Serial.println("WiFi connected");

    Serial.print("ESP32 IP: ");
    Serial.println(WiFi.localIP());

  } else {

    Serial.println();
    Serial.println("WiFi connection failed");
  }
}

// =====================================================
// RPM CALCULATION - 44E ANALOG HALL SENSOR
// =====================================================

void calculateRPM() {

  int hallValue = analogRead(HALL_PIN);

  // Magnet approaches sensor
  if (
    !magnetDetected &&
    hallValue > HALL_ON_THRESHOLD
  ) {

    revolutionCount++;
    magnetDetected = true;
  }

  // Magnet leaves sensor
  if (
    magnetDetected &&
    hallValue < HALL_OFF_THRESHOLD
  ) {

    magnetDetected = false;
  }

  unsigned long now = millis();

  if (now - lastRPMTime >= 1000) {

    unsigned long elapsed =
      now - lastRPMTime;

    rpm =
      revolutionCount *
      (60000.0 / elapsed);

    revolutionCount = 0;

    lastRPMTime = now;
  }
}

// =====================================================
// FAN CONTROL
// =====================================================

void setFan(bool state) {

  fanOn = state;

  digitalWrite(
    FAN_PIN,
    state ? HIGH : LOW
  );
}

// =====================================================
// ALARM CONTROL
// =====================================================

void setAlarm(bool state) {

  digitalWrite(
    LED_PIN,
    state ? HIGH : LOW
  );

  digitalWrite(
    BUZZER_PIN,
    state ? HIGH : LOW
  );
}

// =====================================================
// SEND TELEMETRY TO FASTAPI
// =====================================================

void sendTelemetry(
  float temp1,
  float temp2,
  float vibration,
  float voltage,
  float current,
  float power,
  int hallRaw
) {

  if (WiFi.status() != WL_CONNECTED) {

    Serial.println("WiFi disconnected");

    connectWiFi();

    return;
  }

  HTTPClient http;

  http.setTimeout(3000);

  http.begin(API_URL);

  http.addHeader(
    "Content-Type",
    "application/json"
  );

  String json = "{";

  json += "\"device_id\":\"";
  json += DEVICE_ID;
  json += "\",";

  json += "\"temp_1\":";
  json += String(temp1, 2);
  json += ",";

  json += "\"temp_2\":";
  json += String(temp2, 2);
  json += ",";

  json += "\"rpm\":";
  json += String(rpm, 0);
  json += ",";

  json += "\"hall_raw\":";
  json += String(hallRaw);
  json += ",";

  json += "\"vibration\":";
  json += String(vibration, 3);
  json += ",";

  json += "\"voltage\":";
  json += String(voltage, 3);
  json += ",";

  json += "\"current\":";
  json += String(current, 3);
  json += ",";

  json += "\"power\":";
  json += String(power, 3);
  json += ",";

  json += "\"fan\":";
  json += fanOn ? "true" : "false";

  json += "}";

  Serial.println();
  Serial.println("Sending:");
  Serial.println(json);

  int responseCode =
    http.POST(json);

  Serial.print(
    "FastAPI response: "
  );

  Serial.println(
    responseCode
  );

  if (responseCode > 0) {

    String response =
      http.getString();

    Serial.println(
      response
    );
  }

  http.end();
}

// =====================================================
// OLED
// =====================================================

void updateDisplay(
  float temp1,
  float temp2,
  float vibration,
  float current
) {

  if (!oledAvailable)
    return;

  display.clearDisplay();

  display.setTextColor(
    SSD1306_WHITE
  );

  display.setTextSize(1);

  display.setCursor(0, 0);

  display.println("TRUSTTWIN");

  display.print("T1: ");
  display.print(temp1, 1);
  display.println(" C");

  display.print("T2: ");
  display.print(temp2, 1);
  display.println(" C");

  display.print("RPM: ");
  display.println(rpm, 0);

  display.print("Current: ");
  display.print(current, 2);
  display.println(" A");

  display.print("Vib: ");
  display.println(vibration, 2);

  display.print("Fan: ");
  display.println(
    fanOn ? "ON" : "OFF"
  );

  display.display();
}

// =====================================================
// SETUP
// =====================================================

void setup() {

  Serial.begin(115200);

  delay(1000);

  Serial.println();
  Serial.println("======================");
  Serial.println("      PULSETRUST_");
  Serial.println("    Trust Before Action");
  Serial.println("======================");

  // ===================================================
  // GPIO
  // ===================================================

  pinMode(
    HALL_PIN,
    INPUT
  );

  pinMode(
    FAN_PIN,
    OUTPUT
  );

  pinMode(
    LED_PIN,
    OUTPUT
  );

  pinMode(
    BUZZER_PIN,
    OUTPUT
  );

  setFan(true);
  setAlarm(true);

  // ESP32 ADC
  analogReadResolution(12);

  // ===================================================
  // I2C
  // ===================================================

  Wire.begin(
    SDA_PIN,
    SCL_PIN
  );

  // ===================================================
  // DS18B20
  // ===================================================

  tempSensor1.begin();
  tempSensor2.begin();

  tempSensor1.setResolution(10);
  tempSensor2.setResolution(10);

  Serial.println(
    "DS18B20 initialized"
  );

  // ===================================================
  // MPU6050
  // ===================================================
  //
  // Your MPU responds correctly at 0x68 even though
  // the Adafruit begin() check reports failure.
  // We therefore initialize it and continue using it.
  // ===================================================

  mpu.begin(
    0x68,
    &Wire
  );

  mpu.setAccelerometerRange(
    MPU6050_RANGE_8_G
  );

  mpu.setGyroRange(
    MPU6050_RANGE_500_DEG
  );

  mpu.setFilterBandwidth(
    MPU6050_BAND_21_HZ
  );

  Serial.println(
    "MPU6050 initialized at 0x68"
  );

  // ===================================================
  // INA219
  // ===================================================

  if (ina219.begin()) {

    inaAvailable = true;

    Serial.println(
      "INA219 connected"
    );

  } else {

    Serial.println(
      "WARNING: INA219 not found"
    );
  }

  // ===================================================
  // OLED
  // ===================================================

  if (
    display.begin(
      SSD1306_SWITCHCAPVCC,
      OLED_ADDRESS
    )
  ) {

    oledAvailable = true;

    display.clearDisplay();

    display.setTextColor(
      SSD1306_WHITE
    );

    display.setTextSize(1);

    display.setCursor(
      0,
      0
    );

    display.println(
      "PULSETRUST_"
    );

    display.println();

    display.println(
      "Trust Before Action"
    );

    display.println();

    display.println(
      "Booting..."
    );

    display.display();

    Serial.println(
      "OLED connected"
    );

  } else {

    Serial.println(
      "WARNING: OLED not found"
    );
  }

  // ===================================================
  // HALL SENSOR
  // ===================================================

  Serial.println(
    "44E Hall sensor initialized on GPIO34"
  );

  Serial.print(
    "Hall baseline: "
  );

  Serial.println(
    analogRead(HALL_PIN)
  );

  // ===================================================
  // WIFI
  // ===================================================

  connectWiFi();

  delay(1000);

  lastRPMTime = millis();

  Serial.println();
  Serial.println(
    "TrustTwin ready."
  );
}

// =====================================================
// LOOP
// =====================================================

void loop() {

  // ===================================================
  // HALL / RPM
  // ===================================================

  calculateRPM();

  unsigned long now =
    millis();

  if (
    now - lastTelemetryTime <
    TELEMETRY_INTERVAL
  ) {

    delay(5);
    return;
  }

  lastTelemetryTime = now;

  // ===================================================
  // TEMPERATURE
  // ===================================================

  tempSensor1.requestTemperatures();
  tempSensor2.requestTemperatures();

  float temp1 =
    tempSensor1.getTempCByIndex(0);

  float temp2 =
    tempSensor2.getTempCByIndex(0);

  // ===================================================
  // MPU6050
  // ===================================================

  sensors_event_t accel;
  sensors_event_t gyro;
  sensors_event_t internalTemp;

  mpu.getEvent(
    &accel,
    &gyro,
    &internalTemp
  );

  float ax =
    accel.acceleration.x;

  float ay =
    accel.acceleration.y;

  float az =
    accel.acceleration.z;

  float vibration =
    sqrt(
      ax * ax +
      ay * ay +
      az * az
    );

  // ===================================================
  // INA219
  // ===================================================

  float voltage = 0;
  float current = 0;
  float power = 0;

  if (inaAvailable) {

    voltage =
      ina219.getBusVoltage_V();

    current =
      ina219.getCurrent_mA()
      / 1000.0;

    power =
      ina219.getPower_mW()
      / 1000.0;
  }

  // ===================================================
  // HALL RAW VALUE
  // ===================================================

  int hallRaw =
    analogRead(HALL_PIN);

  // ===================================================
  // OLED
  // ===================================================

  updateDisplay(
    temp1,
    temp2,
    vibration,
    current
  );

  // ===================================================
  // FASTAPI
  // ===================================================

  sendTelemetry(
    temp1,
    temp2,
    vibration,
    voltage,
    current,
    power,
    hallRaw
  );

}
