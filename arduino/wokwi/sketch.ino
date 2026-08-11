/* ==========================================================================
 * sketch.ino — Smart Agriculture field node, WOKWI build
 * --------------------------------------------------------------------------
 * Paste this into a new Wokwi ESP32 project alongside the supplied
 * diagram.json and libraries.txt. It runs unmodified and posts to ThingSpeak.
 *
 * THREE DIFFERENCES FROM THE GENERIC ESP32 SKETCH — read these, they are the
 * things that silently break a Wokwi build:
 *
 * 1. THE RELAY MODULE IS ACTIVE LOW. Wokwi's wokwi-relay-module connects
 *    COM to NO when IN is driven LOW, and COM to NC when IN is HIGH or
 *    floating. Writing HIGH to "turn the pump on" therefore turns it off.
 *    RELAY_ACTIVE_LOW below handles it; on a bare SRD-05VDC relay driven
 *    through an NPN transistor, set it to 0.
 *
 * 2. DHT LIBRARY. Wokwi's own documentation says to use "DHT sensor library
 *    for ESPx" (DHTesp) on the ESP32 — the Adafruit DHT library is timing
 *    sensitive and misreads under simulation.
 *
 * 3. SOIL CALIBRATION. The soil probe is stood in by a potentiometer, which
 *    sweeps the full 0–4095 ADC range. A real capacitive probe only covers
 *    roughly 1250–3200, so the two calibration constants differ. Both sets are
 *    below; swap them when you move to hardware.
 *
 * CHANNEL MAP (ThingSpeak)
 *   field1 temperature °C   field4 light %
 *   field2 humidity %       field5 water level %
 *   field3 soil moisture %  field6 pump 0/1
 * ========================================================================== */

#include <WiFi.h>
#include <Wire.h>
#include <LiquidCrystal_I2C.h>
#include <DHTesp.h>
#include <ThingSpeak.h>

/* ------------------------- CREDENTIALS ---------------------------------- */
const char* WIFI_SSID = "Wokwi-GUEST";
const char* WIFI_PASS = "";
const int   WIFI_CHAN = 6;          // skips the scan, saves ~4 s in Wokwi

unsigned long THINGSPEAK_CHANNEL_ID = 0000000;              // <-- your channel
const char*   THINGSPEAK_WRITE_KEY  = "XXXXXXXXXXXXXXXX";   // <-- your write key

/* ---------------------------- PIN MAP ----------------------------------- */
#define PIN_DHT        4
#define PIN_SOIL       34     // ADC1_CH6, input only
#define PIN_LDR        35     // ADC1_CH7, input only
#define PIN_TRIG       12
#define PIN_ECHO       14
#define PIN_RELAY      26
#define PIN_BUZZER     25
#define PIN_LED_GREEN  27
#define PIN_LED_YELLOW 33
#define PIN_LED_RED    32

#define RELAY_ACTIVE_LOW 1    // 1 for the Wokwi relay module, 0 for a bare relay

DHTesp dht;
LiquidCrystal_I2C lcd(0x27, 16, 2);
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
// Wokwi: the potentiometer sweeps the whole ADC range.
const int SOIL_ADC_DRY = 4095;
const int SOIL_ADC_WET = 0;
// Real capacitive probe, two-point calibration (air / submerged):
// const int SOIL_ADC_DRY = 3200;
// const int SOIL_ADC_WET = 1250;
const int LDR_ADC_DARK = 0;
const int LDR_ADC_SUN  = 4095;

/* ----------------------------- STATE ------------------------------------ */
bool pumpOn = false;
unsigned long pumpSince = 0, lastSample = 0, lastPublish = 0;
uint8_t alertCode = 0, lcdPage = 0;
float accT = 0, accH = 0, accS = 0, accL = 0, accW = 0;
uint16_t accN = 0, accPump = 0;
float lastT = 25, lastH = 50;

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
  if (us == 0) return -1.0;                       // no echo -> fault, fail closed
  float d = us * 0.0343 / 2.0;
  return constrain((1.0 - (d - SENSOR_GAP_CM) / TANK_HEIGHT_CM) * 100.0, 0.0, 100.0);
}

void driveRelay(bool on) {
#if RELAY_ACTIVE_LOW
  digitalWrite(PIN_RELAY, on ? LOW : HIGH);
#else
  digitalWrite(PIN_RELAY, on ? HIGH : LOW);
#endif
}

/* ---------------- hysteresis control law, identical to the Uno build ---- */
void updateControl(float soil, float tank, float temp) {
  bool prev = pumpOn;
  bool lowWater = (tank <= TANK_MIN) || (tank < 0);
  bool dwellOk = (millis() - pumpSince) >= MIN_PUMP_MS;

  if (lowWater)                                    pumpOn = false;
  else if (!pumpOn && soil < SM_LOW  && dwellOk)   pumpOn = true;
  else if ( pumpOn && soil > SM_HIGH && dwellOk)   pumpOn = false;

  if (pumpOn != prev) pumpSince = millis();

  driveRelay(pumpOn);
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

void updateLcd(float t, float h, float s, float l, float w) {
  lcd.clear();
  if (lcdPage == 0) {
    lcd.setCursor(0, 0);
    lcd.print("T:"); lcd.print(t, 1); lcd.print("C H:"); lcd.print(h, 0); lcd.print("%");
    lcd.setCursor(0, 1);
    lcd.print("Soil:"); lcd.print(s, 0); lcd.print("% ");
    lcd.print(pumpOn ? "PMP:ON" : "PMP:OF");
  } else {
    lcd.setCursor(0, 0);
    lcd.print("Lgt:"); lcd.print(l, 0); lcd.print("% Tnk:"); lcd.print(w, 0);
    lcd.setCursor(0, 1);
    switch (alertCode) {
      case 1: lcd.print("! LOW WATER LVL"); break;
      case 2: lcd.print("! HIGH TEMP    "); break;
      case 3: lcd.print("! LOW H2O+HEAT "); break;
      case 4: lcd.print("! SENSOR FAULT "); break;
      default: lcd.print("Status: NORMAL "); break;
    }
  }
  lcdPage ^= 1;
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
  if (WiFi.status() == WL_CONNECTED) {
    Serial.print("[wifi] ip "); Serial.println(WiFi.localIP());
  }
}

void publishThingSpeak(float t, float h, float s, float l, float w, float duty) {
  ensureWifi();
  if (WiFi.status() != WL_CONNECTED) return;

  ThingSpeak.setField(1, t);
  ThingSpeak.setField(2, h);
  ThingSpeak.setField(3, s);
  ThingSpeak.setField(4, l);
  ThingSpeak.setField(5, w);
  ThingSpeak.setField(6, (int)(duty > 0.5 ? 1 : 0));
  ThingSpeak.setStatus(alertText());

  int code = ThingSpeak.writeFields(THINGSPEAK_CHANNEL_ID, THINGSPEAK_WRITE_KEY);
  if (code == 200) Serial.println("[ts] 200 OK");
  else {
    // 0 = faster than the 15 s rate limit or malformed payload
    // 401 = bad write key | -301 = connection failed | -304 = timeout
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
  driveRelay(false);

  analogReadResolution(12);
  analogSetAttenuation(ADC_11db);       // full 0–3.3 V input span

  dht.setup(PIN_DHT, DHTesp::DHT22);

  Wire.begin(21, 22);
  lcd.init();
  lcd.backlight();
  lcd.setCursor(0, 0); lcd.print("Smart Agri Node");
  lcd.setCursor(0, 1); lcd.print("booting...");

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

    TempAndHumidity d = dht.getTempAndHumidity();
    float t = d.temperature, h = d.humidity;
    if (isnan(t) || isnan(h)) { t = lastT; h = lastH; }   // hold last valid
    lastT = t; lastH = h;

    float s = readSoilMoisturePct();
    float l = readLightPct();
    float w = readWaterLevelPct();

    updateControl(s, w, t);
    updateLcd(t, h, s, l, w);

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
