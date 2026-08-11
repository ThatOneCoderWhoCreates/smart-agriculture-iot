/* ==========================================================================
 * smart_agri_esp32_thingspeak.ino
 * IoT-Based Smart Agriculture System - connected node (Wokwi / real hardware)
 * --------------------------------------------------------------------------
 * TARGET : ESP32 DevKit v1  (runs unmodified in the Wokwi simulator, which
 *          provides a full simulated 802.11 stack + an internet gateway, so the
 *          data really does land in your ThingSpeak channel).
 *
 * WHY ESP32 AND NOT ESP8266
 *   The ESP8266 exposes exactly ONE ADC pin (A0). This design needs three
 *   simultaneous analogue channels (soil, LDR, spare), so on an ESP8266 you
 *   would have to add a CD4051 multiplexer or an ADS1115 I2C ADC. The ESP32 has
 *   two SAR ADCs with 15 usable channels, so the wiring stays honest. An
 *   ESP8266 variant is described in docs/hardware_wiring.md.
 *
 * LIBRARIES (Arduino Library Manager / Wokwi libraries.txt)
 *   DHT sensor library            (Adafruit)      - DHT11/DHT22
 *   Adafruit Unified Sensor       (dependency)
 *   ThingSpeak                    (MathWorks)
 *   LiquidCrystal I2C             (optional local display)
 *
 * THINGSPEAK CHANNEL FIELD MAP
 *   field1 temperature (degC)   field4 light intensity (%)
 *   field2 humidity (%)         field5 water level (%)
 *   field3 soil moisture (%)    field6 pump status (0/1)
 *   status string carries the human-readable alert
 *
 * RATE LIMIT: a free ThingSpeak channel accepts one update per 15 s. The node
 * therefore samples at 2 s and publishes a 20 s mean. Publishing faster does
 * not give you more data, it gives you HTTP 0 responses and dropped points.
 * ========================================================================== */

#include <WiFi.h>
#include <HTTPClient.h>
#include <DHT.h>
#include <ThingSpeak.h>

/* ------------------------- CREDENTIALS ---------------------------------- */
const char* WIFI_SSID = "Wokwi-GUEST";   // real deployment: your field AP
const char* WIFI_PASS = "";
const int   WIFI_CHAN = 6;               // Wokwi: skips the scan, saves ~4 s

unsigned long THINGSPEAK_CHANNEL_ID = 0000000;      // <-- your channel ID
const char*   THINGSPEAK_WRITE_KEY  = "XXXXXXXXXXXXXXXX";  // <-- write API key

/* ---------------------------- PIN MAP ----------------------------------- */
#define PIN_DHT        4      // DHT11/DHT22 data
#define DHTTYPE        DHT22  // Wokwi ships DHT22; use DHT11 on the real board
#define PIN_SOIL       34     // ADC1_CH6  (input only)
#define PIN_LDR        35     // ADC1_CH7  (input only)
#define PIN_TRIG       12
#define PIN_ECHO       14
#define PIN_RELAY      26
#define PIN_BUZZER     25
#define PIN_LED_GREEN  27
#define PIN_LED_YELLOW 33
#define PIN_LED_RED    32

DHT dht(PIN_DHT, DHTTYPE);
WiFiClient wifiClient;

/* ------------------------ CONTROL SET-POINTS ---------------------------- */
const float SM_LOW     = 35.0;
const float SM_HIGH    = 60.0;
const float TANK_MIN   = 20.0;
const float TEMP_ALERT = 35.0;

const float TANK_HEIGHT_CM = 40.0;
const float SENSOR_GAP_CM  =  4.0;

const unsigned long SAMPLE_MS   = 2000UL;
const unsigned long PUBLISH_MS  = 20000UL;   // >= 15 s, ThingSpeak free tier
const unsigned long MIN_PUMP_MS = 10000UL;

/* ---------------------- CALIBRATION CONSTANTS --------------------------- */
// ESP32 ADC is 12-bit (0-4095) and NOT linear near the rails. These two points
// come from a two-point calibration: probe in air and probe in saturated soil.
const int SOIL_ADC_DRY = 3200;   // reading in air
const int SOIL_ADC_WET = 1250;   // reading fully submerged
const int LDR_ADC_DARK =   80;
const int LDR_ADC_SUN  = 3900;

/* ----------------------------- STATE ------------------------------------ */
bool pumpOn = false;
unsigned long pumpSince = 0, lastSample = 0, lastPublish = 0;
uint8_t alertCode = 0;
float accT = 0, accH = 0, accS = 0, accL = 0, accW = 0;
uint16_t accN = 0, accPump = 0;
uint32_t publishOk = 0, publishFail = 0;

/* ======================================================================== */
int readAnalogMedian(uint8_t pin) {
  int v[5];
  for (int i = 0; i < 5; i++) { v[i] = analogRead(pin); delay(2); }
  for (int i = 1; i < 5; i++) {
    int k = v[i], j = i - 1;
    while (j >= 0 && v[j] > k) { v[j + 1] = v[j]; j--; }
    v[j + 1] = k;
  }
  return v[2];
}

float readSoilMoisturePct() {
  int raw = readAnalogMedian(PIN_SOIL);
  float pct = 100.0 * (float)(SOIL_ADC_DRY - raw) / (float)(SOIL_ADC_DRY - SOIL_ADC_WET);
  return constrain(pct, 0.0, 100.0);
}

float readLightPct() {
  int raw = readAnalogMedian(PIN_LDR);
  float pct = 100.0 * (float)(raw - LDR_ADC_DARK) / (float)(LDR_ADC_SUN - LDR_ADC_DARK);
  return constrain(pct, 0.0, 100.0);
}

float readWaterLevelPct() {
  digitalWrite(PIN_TRIG, LOW);  delayMicroseconds(4);
  digitalWrite(PIN_TRIG, HIGH); delayMicroseconds(10);
  digitalWrite(PIN_TRIG, LOW);
  unsigned long us = pulseIn(PIN_ECHO, HIGH, 30000UL);
  if (us == 0) return -1.0;
  float d = us * 0.0343 / 2.0;
  return constrain((1.0 - (d - SENSOR_GAP_CM) / TANK_HEIGHT_CM) * 100.0, 0.0, 100.0);
}

/* ---------------- identical control law to the Tinkercad build ---------- */
void updateControl(float soil, float tank, float temp) {
  bool prev = pumpOn;
  bool lowWater = (tank <= TANK_MIN) || (tank < 0);
  bool dwellOk = (millis() - pumpSince) >= MIN_PUMP_MS;

  if (lowWater)                                    pumpOn = false;
  else if (!pumpOn && soil < SM_LOW  && dwellOk)   pumpOn = true;
  else if ( pumpOn && soil > SM_HIGH && dwellOk)   pumpOn = false;

  if (pumpOn != prev) pumpSince = millis();

  digitalWrite(PIN_RELAY,      pumpOn ? HIGH : LOW);
  digitalWrite(PIN_LED_YELLOW, pumpOn ? HIGH : LOW);

  bool hot = temp >= TEMP_ALERT;
  bool bad = (tank < 0) || isnan(temp) || temp < -20 || temp > 70;

  if (bad)                  alertCode = 4;
  else if (lowWater && hot) alertCode = 3;
  else if (lowWater)        alertCode = 1;
  else if (hot)             alertCode = 2;
  else                      alertCode = 0;

  digitalWrite(PIN_LED_RED,   alertCode != 0);
  digitalWrite(PIN_LED_GREEN, alertCode == 0);
  if (alertCode == 1)      tone(PIN_BUZZER,  900, 120);
  else if (alertCode == 2) tone(PIN_BUZZER, 1500,  60);
  else if (alertCode == 3) tone(PIN_BUZZER, 2000, 250);
  else if (alertCode == 4) tone(PIN_BUZZER,  400, 400);
  else                     noTone(PIN_BUZZER);
}

const char* alertText() {
  switch (alertCode) {
    case 1: return "LOW_WATER: pump inhibited";
    case 2: return "HIGH_TEMP: heat stress warning";
    case 3: return "LOW_WATER + HIGH_TEMP";
    case 4: return "SENSOR_FAULT: reading out of range";
    default: return "NORMAL";
  }
}

/* --------------------------- CONNECTIVITY -------------------------------- */
void ensureWifi() {
  if (WiFi.status() == WL_CONNECTED) return;
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASS, WIFI_CHAN);
  Serial.print("[wifi] connecting");
  unsigned long t0 = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - t0 < 20000UL) {
    delay(200); Serial.print('.');
  }
  Serial.println(WiFi.status() == WL_CONNECTED ? " ok" : " FAILED");
  if (WiFi.status() == WL_CONNECTED) { Serial.print("[wifi] ip "); Serial.println(WiFi.localIP()); }
}

void publishThingSpeak(float t, float h, float s, float l, float w, float duty) {
  ensureWifi();
  if (WiFi.status() != WL_CONNECTED) { publishFail++; return; }

  ThingSpeak.setField(1, t);
  ThingSpeak.setField(2, h);
  ThingSpeak.setField(3, s);
  ThingSpeak.setField(4, l);
  ThingSpeak.setField(5, w);
  ThingSpeak.setField(6, (int)(duty > 0.5 ? 1 : 0));
  ThingSpeak.setStatus(alertText());

  int code = ThingSpeak.writeFields(THINGSPEAK_CHANNEL_ID, THINGSPEAK_WRITE_KEY);
  if (code == 200) { publishOk++; Serial.println("[ts] 200 OK"); }
  else {
    publishFail++;
    // 0 = posting faster than the 15 s rate limit, or a malformed payload
    // 401 = bad write API key, -301 = connection failed
    Serial.print("[ts] error "); Serial.println(code);
  }
}

/* ------------------------------- SETUP ---------------------------------- */
void setup() {
  Serial.begin(115200);
  pinMode(PIN_TRIG, OUTPUT);   pinMode(PIN_ECHO, INPUT);
  pinMode(PIN_RELAY, OUTPUT);  pinMode(PIN_BUZZER, OUTPUT);
  pinMode(PIN_LED_GREEN, OUTPUT);
  pinMode(PIN_LED_YELLOW, OUTPUT);
  pinMode(PIN_LED_RED, OUTPUT);
  digitalWrite(PIN_RELAY, LOW);

  analogReadResolution(12);
  analogSetAttenuation(ADC_11db);   // full 0-3.3 V input span

  dht.begin();
  ensureWifi();
  ThingSpeak.begin(wifiClient);

  Serial.println(F("millis,temp_c,hum_pct,soil_pct,light_pct,water_pct,pump,alert"));
  pumpSince = millis();
}

/* -------------------------------- LOOP ---------------------------------- */
void loop() {
  unsigned long now = millis();

  if (now - lastSample >= SAMPLE_MS) {
    lastSample = now;

    float t = dht.readTemperature();
    float h = dht.readHumidity();
    if (isnan(t) || isnan(h)) {          // DHT11 fails ~1 read in 50; hold last
      t = accN ? accT / accN : 25.0;
      h = accN ? accH / accN : 50.0;
    }
    float s = readSoilMoisturePct();
    float l = readLightPct();
    float w = readWaterLevelPct();

    updateControl(s, w, t);

    Serial.print(now);   Serial.print(',');
    Serial.print(t, 2);  Serial.print(',');
    Serial.print(h, 2);  Serial.print(',');
    Serial.print(s, 2);  Serial.print(',');
    Serial.print(l, 2);  Serial.print(',');
    Serial.print(w, 2);  Serial.print(',');
    Serial.print(pumpOn ? 1 : 0); Serial.print(',');
    Serial.println(alertCode);

    accT += t; accH += h; accS += s; accL += l; accW += (w < 0 ? 0 : w);
    accPump += pumpOn ? 1 : 0; accN++;
  }

  if (now - lastPublish >= PUBLISH_MS && accN > 0) {
    lastPublish = now;
    publishThingSpeak(accT / accN, accH / accN, accS / accN,
                      accL / accN, accW / accN, (float)accPump / accN);
    accT = accH = accS = accL = accW = 0;
    accN = accPump = 0;
  }
}
