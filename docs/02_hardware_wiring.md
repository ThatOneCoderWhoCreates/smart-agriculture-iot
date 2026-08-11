# 02 · Hardware, Tinkercad Components and Wiring

## 1. Read this first: what Tinkercad can and cannot do

Tinkercad Circuits ships a deliberately small component drawer. Two facts will shape your
build, and it is better to state them in the report than to be caught by them in the viva:

1. **There is no DHT11 model and no DHT library in Tinkercad.** Autodesk's own guidance
   ("Choose Sensor Substitutes in Tinkercad Circuits") is to substitute a 3-pin analogue
   sensor with a TMP36 or a potentiometer, and a 2-pin analogue sensor with a photoresistor.
2. **Tinkercad has no network stack.** No WiFi board, no HTTP, no internet. A Tinkercad
   circuit physically cannot reach ThingSpeak.

This is why the project has **two firmware builds**:

| Build | Platform | Purpose | What it proves |
|---|---|---|---|
| `smart_agri_tinkercad.ino` | Arduino Uno in Tinkercad | circuit, wiring, control law, LCD, alerts | the electronics and the logic |
| `smart_agri_esp32_thingspeak.ino` | ESP32 in Wokwi (or real hardware) | WiFi + ThingSpeak publishing | the cloud path |

The control law, alert state machine, filtering and telemetry frame are byte-for-byte
equivalent between the two. Only the four acquisition functions differ. Say exactly this if
asked why there are two sketches.

Wokwi simulates a complete network stack for the ESP32 — 802.11 MAC through DNS/HTTP — and
routes it through an IoT gateway to the real internet via the `Wokwi-GUEST` access point.
Your ThingSpeak channel really does receive the data.

---

## 2. Bill of materials

### 2.1 Tinkercad build (Arduino Uno)

| # | Component in Tinkercad drawer | Qty | Represents |
|---|---|---|---|
| 1 | Arduino Uno R3 | 1 | edge controller |
| 2 | Breadboard (full+) | 1 | — |
| 3 | Temperature Sensor (TMP36) | 1 | DHT11 temperature channel |
| 4 | Potentiometer 10 kΩ | 1 | DHT11 humidity channel |
| 5 | Potentiometer 10 kΩ | 1 | capacitive soil-moisture probe |
| 6 | Photoresistor (LDR) | 1 | light intensity |
| 7 | Resistor 10 kΩ | 1 | LDR divider bottom leg |
| 8 | Ultrasonic Distance Sensor (HC-SR04, 4-pin) | 1 | tank level |
| 9 | Relay SPDT (5 V) | 1 | pump switching |
| 10 | DC Motor | 1 | irrigation pump |
| 11 | Power supply / battery 9 V | 1 | pump rail (kept off the Arduino 5 V) |
| 12 | Diode 1N4001 | 1 | flyback across the motor |
| 13 | LED green / yellow / red | 3 | status, pump ON, alert |
| 14 | Resistor 220 Ω | 3 | LED series |
| 15 | Piezo buzzer | 1 | audible alert |
| 16 | LCD 16×2 | 1 | local readout |
| 17 | Potentiometer 10 kΩ | 1 | LCD contrast (V0) |
| 18 | Resistor 220 Ω | 1 | LCD backlight (pin 15) |

### 2.2 Real / Wokwi build (ESP32)

Replace items 3–5 with a **DHT22** (Wokwi) or **DHT11** (real), a **capacitive soil moisture
sensor v1.2**, and keep the LDR divider. Add a **relay module with opto-isolation** rather
than a bare relay, and power the pump from a separate supply sharing only ground.

---

## 3. Pin map

### 3.1 Arduino Uno (Tinkercad)

| Signal | Uno pin | Direction | Notes |
|---|---|---|---|
| TMP36 Vout | **A0** | analog in | 10 mV/°C, 500 mV at 0 °C |
| Humidity potentiometer wiper | **A1** | analog in | 0–1023 → 0–100 % RH |
| Soil potentiometer wiper | **A2** | analog in | 0–1023 → 0–100 % |
| LDR divider midpoint | **A3** | analog in | LDR to 5 V, 10 kΩ to GND |
| Yellow LED (pump running) | **A4** | digital out | analog pins used as digital |
| Red LED (alert) | **A5** | digital out | |
| LCD D7 | **D2** | digital out | 4-bit mode |
| LCD D6 | **D3** | digital out | |
| LCD D5 | **D4** | digital out | |
| LCD D4 | **D5** | digital out | |
| HC-SR04 TRIG | **D7** | digital out | 10 µs pulse |
| HC-SR04 ECHO | **D8** | digital in | `pulseIn`, 30 ms timeout |
| Relay IN | **D9** | digital out | HIGH = energised |
| Piezo buzzer | **D10** | digital out | `tone()` |
| Green LED (healthy) | **D11** | digital out | |
| LCD E | **D12** | digital out | |
| LCD RS | **D13** | digital out | |

`LiquidCrystal lcd(13, 12, 5, 4, 3, 2);` — the constructor order is
`(RS, E, D4, D5, D6, D7)`, which is why the pin numbers descend.

### 3.2 ESP32 DevKit v1

| Signal | GPIO | Notes |
|---|---|---|
| DHT data | 4 | 10 kΩ pull-up to 3V3 on real hardware |
| Soil analog | 34 | ADC1_CH6, **input only** |
| LDR analog | 35 | ADC1_CH7, **input only** |
| HC-SR04 TRIG | 12 | |
| HC-SR04 ECHO | 14 | **5 V → 3.3 V divider required on real hardware** |
| Relay IN | 26 | |
| Buzzer | 25 | |
| LED green / yellow / red | 27 / 33 / 32 | |

Two constraints you should be able to justify:

- Only **ADC1** (GPIO 32–39) is usable while WiFi is active; ADC2 is claimed by the radio.
  This is why both analogue sensors sit on GPIO 34/35.
- **The ESP8266 has exactly one ADC pin.** This design needs two simultaneous analogue
  channels, so an ESP8266 build requires a CD4051 analogue multiplexer or an ADS1115 I²C
  ADC. That is the reason the connected build targets ESP32 rather than ESP8266, and it is
  a legitimate engineering answer, not an avoidance.

---

## 4. Wiring detail

### 4.1 LDR divider

```
 5V ──[ LDR ]──┬── A3
               │
             [10kΩ]
               │
              GND
```

Bright light lowers LDR resistance, pulling A3 **up**. The map is therefore
`light% = analogRead(A3) × 100/1023`, non-inverted. If you wire the LDR to ground instead,
invert the map — and say which you did in the report.

### 4.2 TMP36

Three pins, left to right with the flat face toward you: **+5 V, Vout, GND**. Reversing
+5 V and GND destroys a real TMP36 (and gets you a nonsense reading in Tinkercad).

```
Vout = 0.5 + 0.01 × T(°C)      →      T = (analogRead × 5/1023 − 0.5) × 100
```

### 4.3 HC-SR04 and the tank geometry

The sensor sits on the tank lid pointing down, so it measures the **air gap**, not the
water. Level is the complement:

```
distance_cm = pulse_µs × 0.0343 / 2
level%      = (1 − (distance_cm − SENSOR_GAP_CM) / TANK_HEIGHT_CM) × 100
```

With `SENSOR_GAP_CM = 4` (sensor face to the 100 % line) and `TANK_HEIGHT_CM = 40`:
a 4 cm reading is a full tank, 44 cm is empty. Calibrate these two constants by measuring
your actual tank; do not copy the numbers.

The `0.0343` is the speed of sound in cm/µs at 20 °C. It varies about **0.6 % per 10 °C**,
so across a 15–40 °C field day the level reading drifts by roughly 0.3 pp. Acceptable here;
mention it as a known error source.

### 4.4 Relay and motor — the part that is usually wrong

```
D9 ──► relay IN
5V ──► relay VCC          (module)   |   coil + ──► 5V     (bare relay)
GND ─► relay GND                     |   coil − ──► D9 via NPN + 1kΩ base resistor

                    ┌──────────────┐
   9V (+) ──────────┤ relay COM    │
                    │      NO ─────┼──► motor (+)
                    └──────────────┘
   motor (−) ───────────────────────► 9V (−) ──── common GND with Arduino
                    1N4001 across the motor, cathode to (+)
```

Three rules:

1. **Never power a motor from the Arduino 5 V rail.** Stall current on even a small DC
   motor exceeds the regulator's limit and browns out the MCU mid-decision.
2. **Grounds must be common**, or the relay input sees an undefined level.
3. **Flyback diode across the motor**, cathode to the positive terminal. Without it, the
   inductive kick on switch-off injects a spike into the supply that corrupts ADC readings
   — which then looks exactly like the "spike" anomaly class your Isolation Forest is
   trained to catch. A nice detail to raise unprompted.

A bare SPDT relay driven straight from a GPIO also needs an NPN transistor (BC547/2N2222)
plus base resistor, because the coil draws ~70 mA and a pin sources 20 mA. In Tinkercad
you can drive the relay directly and it will simulate; on real hardware use a relay
*module*, which has the transistor, diode and opto-isolator built in.

### 4.5 LCD 16×2

| LCD pin | Connects to |
|---|---|
| 1 VSS | GND |
| 2 VDD | 5 V |
| 3 V0 | 10 kΩ pot wiper (contrast) |
| 4 RS | D13 |
| 5 RW | GND |
| 6 E | D12 |
| 11–14 D4–D7 | D5, D4, D3, D2 |
| 15 A | 5 V via 220 Ω |
| 16 K | GND |

If the LCD shows a row of solid blocks, the contrast pot is at the wrong end — that is the
single most common Tinkercad LCD complaint.

---

## 5. Build and test order

Do not wire everything and then power up. Build in stages, verifying each on the Serial
Monitor before adding the next:

1. Uno + TMP36 → print temperature. Verify ~25 °C at room setting.
2. Add both potentiometers → print humidity and soil. Sweep each, confirm 0–100 %.
3. Add LDR divider → cover and uncover the photoresistor, confirm the value moves.
4. Add HC-SR04 → move the ruler slider, confirm distance tracks and level inverts.
5. Add relay + motor + diode → force `pumpOn = true` and confirm the motor spins.
6. Add LEDs and buzzer → drive the alert codes manually.
7. Add the LCD last (it uses six pins and complicates debugging).
8. Enable the real control law and run the six test scenarios in `docs/05_test_cases.md`.

---

## 6. Driving the demonstration in Tinkercad

Tinkercad has no environment simulation, so *you* are the environment. During the demo:

- turn the **soil potentiometer down** to cross 35 % → pump starts, yellow LED on
- turn it **up** past 60 % → pump stops
- drag the **HC-SR04 distance slider** out past 36 cm → level < 20 % → pump inhibited, red
  LED, low-water tone
- raise the **TMP36 slider** past 35 °C → high-temperature tone
- cover the **LDR** → light drops, visible on the LCD second page

Record this as a screen capture. It is the evidence that the control law works; the ML
evidence comes from the Python pipeline, and the two should not be conflated in the report.
