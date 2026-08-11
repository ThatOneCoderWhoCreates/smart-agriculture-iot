/* ==========================================================================
 * smart_agri_tinkercad.ino
 * IoT-Based Smart Agriculture System - edge node firmware (Tinkercad build)
 * --------------------------------------------------------------------------
 * TARGET : Arduino Uno R3, Tinkercad Circuits simulator
 *
 * WHY THE SENSORS ARE SUBSTITUTED
 * Tinkercad Circuits ships a deliberately limited component drawer. It has no
 * DHT11 model and no DHT library, and no capacitive soil-moisture probe. The
 * accepted workaround (documented by Autodesk in "Choose Sensor Substitutes in
 * Tinkercad Circuits") is to replace a 3-pin analogue sensor with a TMP36 or a
 * potentiometer, and a 2-pin analogue sensor with a photoresistor.
 *
 *   REAL HARDWARE            TINKERCAD STAND-IN         SIGNAL PATH
 *   DHT11 temperature        TMP36                      A0, 10 mV/degC, 500 mV @ 0 C
 *   DHT11 humidity           10 k potentiometer         A1, 0-1023 -> 0-100 %RH
 *   Capacitive soil probe    10 k potentiometer         A2, 0-1023 -> 0-100 %
 *   LDR + 10 k divider       photoresistor + 10 k       A3, 0-1023 -> 0-100 %
 *   HC-SR04                  HC-SR04 (native)           D7 trig / D8 echo
 *   Relay + DC pump          relay module + DC motor    D9
 *
 * The control law, the alert logic, the debouncing and the telemetry frame are
 * IDENTICAL to the ESP32 build, so behaviour demonstrated here is the behaviour
 * that runs on real hardware. Only the four acquisition functions differ.
 *
 * TELEMETRY FRAME (Serial, 9600 baud, CSV - paste into a .csv for analysis):
 *   millis,temp_c,hum_pct,soil_pct,light_pct,water_pct,pump,alert_code
 * ========================================================================== */

#include <LiquidCrystal.h>

/* ---------------------------- PIN MAP ---------------------------------- */
const uint8_t PIN_TMP36      = A0;   // temperature
const uint8_t PIN_HUM_POT    = A1;   // humidity stand-in
const uint8_t PIN_SOIL       = A2;   // soil moisture stand-in
const uint8_t PIN_LDR        = A3;   // light intensity
const uint8_t PIN_LED_YELLOW = A4;   // pump running          (analog pin as digital)
const uint8_t PIN_LED_RED    = A5;   // alert active

const uint8_t PIN_TRIG       = 7;    // HC-SR04 trigger
const uint8_t PIN_ECHO       = 8;    // HC-SR04 echo
const uint8_t PIN_RELAY      = 9;    // relay IN -> DC motor (pump)
const uint8_t PIN_BUZZER     = 10;   // piezo
const uint8_t PIN_LED_GREEN  = 11;   // system healthy / idle

// LCD 16x2 in 4-bit mode : RS, E, D4, D5, D6, D7
LiquidCrystal lcd(13, 12, 5, 4, 3, 2);

/* ------------------------ CONTROL SET-POINTS ---------------------------- */
const float SM_LOW      = 35.0;   // %  start irrigation below this
const float SM_HIGH     = 60.0;   // %  stop irrigation above this
const float TANK_MIN    = 20.0;   // %  inhibit pump below this
const float TEMP_ALERT  = 35.0;   // degC high-temperature warning

/* --------------------------- TANK GEOMETRY ------------------------------ */
const float TANK_HEIGHT_CM  = 40.0;  // full-scale water column
const float SENSOR_GAP_CM   =  4.0;  // sensor face to the 100 % water line

/* ---------------------------- TIMING ------------------------------------ */
const unsigned long SAMPLE_MS    = 2000UL;   // acquisition period
const unsigned long PUBLISH_MS   = 20000UL;  // telemetry period (>=15 s: ThingSpeak)
const unsigned long MIN_PUMP_MS  = 10000UL;  // anti-short-cycle dwell time

/* --------------------------- ALERT CODES -------------------------------- */
const uint8_t ALERT_NONE      = 0;
const uint8_t ALERT_LOW_WATER = 1;
const uint8_t ALERT_HIGH_TEMP = 2;
const uint8_t ALERT_BOTH      = 3;
const uint8_t ALERT_SENSOR    = 4;

/* ----------------------------- STATE ------------------------------------ */
bool  pumpOn            = false;
unsigned long pumpSince = 0;
unsigned long lastSample = 0, lastPublish = 0;
uint8_t alertCode = ALERT_NONE;
uint8_t lcdPage   = 0;

// Accumulators so that the published sample is a mean, not one noisy instant.
float accT = 0, accH = 0, accS = 0, accL = 0, accW = 0;
uint16_t accN = 0, accPumpOn = 0;

float lastT = 0, lastH = 0, lastS = 0, lastL = 0, lastW = 0;

/* ======================================================================== */
/*  ACQUISITION                                                             */
/* ======================================================================== */

// Median-of-5 on the raw ADC: kills the single-sample spikes that a long
// unshielded field cable picks up. Cheap, deterministic, no floating point.
int readAnalogMedian(uint8_t pin) {
  int v[5];
  for (uint8_t i = 0; i < 5; i++) { v[i] = analogRead(pin); delay(2); }
  for (uint8_t i = 1; i < 5; i++) {          // insertion sort, n = 5
    int key = v[i]; int j = i - 1;
    while (j >= 0 && v[j] > key) { v[j + 1] = v[j]; j--; }
    v[j + 1] = key;
  }
  return v[2];
}

float readTemperatureC() {
  // TMP36: Vout = 0.5 V + 10 mV/degC
  float volts = readAnalogMedian(PIN_TMP36) * (5.0 / 1023.0);
  return (volts - 0.5) * 100.0;
}

float readHumidityPct() {
  return readAnalogMedian(PIN_HUM_POT) * (100.0 / 1023.0);
}

float readSoilMoisturePct() {
  // A real resistive/capacitive probe reads LOW counts when wet, so the map is
  // inverted on hardware. The Tinkercad potentiometer is wired non-inverted to
  // keep the demo readable; flip the next line for the physical sensor.
  return readAnalogMedian(PIN_SOIL) * (100.0 / 1023.0);
  // hardware: return (1023 - readAnalogMedian(PIN_SOIL)) * (100.0 / 1023.0);
}

float readLightPct() {
  return readAnalogMedian(PIN_LDR) * (100.0 / 1023.0);
}

float readWaterLevelPct() {
  // HC-SR04 measures the AIR GAP above the water, so level is the complement.
  digitalWrite(PIN_TRIG, LOW);  delayMicroseconds(4);
  digitalWrite(PIN_TRIG, HIGH); delayMicroseconds(10);
  digitalWrite(PIN_TRIG, LOW);

  unsigned long us = pulseIn(PIN_ECHO, HIGH, 30000UL);   // 30 ms ~= 5 m ceiling
  if (us == 0) return -1.0;                              // no echo -> fault
  float distanceCm = us * 0.0343 / 2.0;
  float level = (1.0 - (distanceCm - SENSOR_GAP_CM) / TANK_HEIGHT_CM) * 100.0;
  return constrain(level, 0.0, 100.0);
}

/* ======================================================================== */
/*  CONTROL LAW                                                             */
/* ======================================================================== */
/*
 *  Hysteresis (Schmitt) controller, NOT a single threshold.
 *
 *      pump ON      if soil < 35 %  AND tank > 20 %
 *      pump OFF     if soil > 60 %
 *      pump OFF     if tank <= 20 %                (hard interlock, overrides)
 *      hold state   if 35 % <= soil <= 60 %
 *
 *  A single set-point would chatter the relay every few seconds while the soil
 *  hovers at the threshold. The dead band plus MIN_PUMP_MS bounds the relay to
 *  a few operations per day instead of thousands.
 */
void updateControl(float soil, float tank, float temp) {
  bool prev = pumpOn;
  bool lowWater = (tank <= TANK_MIN) || (tank < 0);
  bool dwellOk  = (millis() - pumpSince) >= MIN_PUMP_MS;

  if (lowWater) {
    pumpOn = false;                                   // interlock: dry-run guard
  } else if (!pumpOn && soil < SM_LOW && dwellOk) {
    pumpOn = true;
  } else if (pumpOn && soil > SM_HIGH && dwellOk) {
    pumpOn = false;
  }
  if (pumpOn != prev) pumpSince = millis();

  digitalWrite(PIN_RELAY, pumpOn ? HIGH : LOW);
  digitalWrite(PIN_LED_YELLOW, pumpOn ? HIGH : LOW);

  bool hot = (temp >= TEMP_ALERT);
  bool bad = (tank < 0) || (temp < -20) || (temp > 70);

  if (bad)                    alertCode = ALERT_SENSOR;
  else if (lowWater && hot)   alertCode = ALERT_BOTH;
  else if (lowWater)          alertCode = ALERT_LOW_WATER;
  else if (hot)               alertCode = ALERT_HIGH_TEMP;
  else                        alertCode = ALERT_NONE;

  digitalWrite(PIN_LED_RED,   alertCode != ALERT_NONE);
  digitalWrite(PIN_LED_GREEN, alertCode == ALERT_NONE);

  // Distinct tones so the fault is identifiable without looking at the LCD.
  if      (alertCode == ALERT_LOW_WATER) tone(PIN_BUZZER, 900, 120);
  else if (alertCode == ALERT_HIGH_TEMP) tone(PIN_BUZZER, 1500, 60);
  else if (alertCode == ALERT_BOTH)      tone(PIN_BUZZER, 2000, 250);
  else if (alertCode == ALERT_SENSOR)    tone(PIN_BUZZER, 400, 400);
  else                                   noTone(PIN_BUZZER);
}

/* ======================================================================== */
/*  PRESENTATION                                                            */
/* ======================================================================== */
void updateLcd(float t, float h, float s, float l, float w) {
  lcd.clear();
  if (lcdPage == 0) {
    lcd.setCursor(0, 0); lcd.print("T:"); lcd.print(t, 1);
    lcd.print((char)223);  lcd.print("C H:"); lcd.print(h, 0); lcd.print("%");
    lcd.setCursor(0, 1); lcd.print("Soil:"); lcd.print(s, 0);
    lcd.print("% "); lcd.print(pumpOn ? "PUMP:ON" : "PUMP:OF");
  } else {
    lcd.setCursor(0, 0); lcd.print("Light:"); lcd.print(l, 0);
    lcd.print("% Tank:"); lcd.print(w, 0);
    lcd.setCursor(0, 1);
    switch (alertCode) {
      case ALERT_LOW_WATER: lcd.print("! LOW WATER LVL"); break;
      case ALERT_HIGH_TEMP: lcd.print("! HIGH TEMP    "); break;
      case ALERT_BOTH:      lcd.print("! LOW H2O+HEAT "); break;
      case ALERT_SENSOR:    lcd.print("! SENSOR FAULT "); break;
      default:              lcd.print("Status: NORMAL "); break;
    }
  }
  lcdPage ^= 1;
}

void publish(float t, float h, float s, float l, float w, float duty) {
  Serial.print(millis());      Serial.print(',');
  Serial.print(t, 2);          Serial.print(',');
  Serial.print(h, 2);          Serial.print(',');
  Serial.print(s, 2);          Serial.print(',');
  Serial.print(l, 2);          Serial.print(',');
  Serial.print(w, 2);          Serial.print(',');
  Serial.print(duty > 0.5 ? 1 : 0);  Serial.print(',');
  Serial.println(alertCode);
}

/* ======================================================================== */
/*  SETUP / LOOP                                                            */
/* ======================================================================== */
void setup() {
  Serial.begin(9600);
  pinMode(PIN_TRIG, OUTPUT);
  pinMode(PIN_ECHO, INPUT);
  pinMode(PIN_RELAY, OUTPUT);
  pinMode(PIN_BUZZER, OUTPUT);
  pinMode(PIN_LED_GREEN, OUTPUT);
  pinMode(PIN_LED_YELLOW, OUTPUT);
  pinMode(PIN_LED_RED, OUTPUT);
  digitalWrite(PIN_RELAY, LOW);

  lcd.begin(16, 2);
  lcd.print("Smart Agri Node");
  lcd.setCursor(0, 1); lcd.print("booting...");
  delay(1500);

  // CSV header - copy the Serial Monitor contents straight into a .csv file
  Serial.println(F("millis,temp_c,hum_pct,soil_pct,light_pct,water_pct,pump,alert"));
  pumpSince = millis();
}

void loop() {
  unsigned long now = millis();

  if (now - lastSample >= SAMPLE_MS) {
    lastSample = now;

    lastT = readTemperatureC();
    lastH = readHumidityPct();
    lastS = readSoilMoisturePct();
    lastL = readLightPct();
    lastW = readWaterLevelPct();

    updateControl(lastS, lastW, lastT);
    updateLcd(lastT, lastH, lastS, lastL, lastW);

    accT += lastT; accH += lastH; accS += lastS;
    accL += lastL; accW += (lastW < 0 ? 0 : lastW);
    accPumpOn += pumpOn ? 1 : 0;
    accN++;
  }

  if (now - lastPublish >= PUBLISH_MS && accN > 0) {
    lastPublish = now;
    publish(accT / accN, accH / accN, accS / accN,
            accL / accN, accW / accN, (float)accPumpOn / accN);
    accT = accH = accS = accL = accW = 0;
    accN = accPumpOn = 0;
  }
}
