# 10 · Building the Circuit — Wokwi, step by step

## 1. Which platform, and why

**Use Wokwi.** Build the Tinkercad version only if your department explicitly requires it.

| | Tinkercad Circuits | Wokwi |
|---|---|---|
| Internet / WiFi | **none at all** | full simulated 802.11 + IoT gateway to the real internet |
| ThingSpeak | impossible | genuinely posts to your channel |
| DHT11 / DHT22 | **not in the parts drawer, no DHT library** | native `wokwi-dht22` |
| HC-SR04 | yes | yes |
| Soil probe | substitute a potentiometer | substitute a potentiometer |
| LDR | photoresistor | photoresistor sensor module with analogue output |
| Relay | yes | yes (`wokwi-relay-module`) |
| DC motor | **yes, spins visibly** | no DC motor part — use an LED on the relay output |
| LCD 16×2 | yes, 6-wire parallel | yes, 2-wire I²C (much less wiring) |
| Circuit definition | drag and drop only | **`diagram.json`, a text file you can paste** |
| Board | Arduino Uno only | ESP32, ESP8266, Uno, Pico, and more |

The decision comes down to one thing. **Your project's entire cloud half — ThingSpeak,
the six field charts, the bulk upload, the React alert — depends on the node reaching the
internet, and Tinkercad cannot do it.** Everything else is a preference; that is a hard
blocker.

Two secondary advantages matter in practice:

- `diagram.json` is text, so the circuit in this repository can be pasted in and is wired
  correctly on the first attempt. No mis-dragged wires, no hunting for a bad connection.
- I²C on the LCD replaces six data wires with two, which removes the single most common
  source of Tinkercad wiring errors.

The one thing Tinkercad does better is the visibly spinning DC motor. If you want that
shot for your report, build the Tinkercad circuit too and use it purely for the pump
demonstration — `arduino/smart_agri_tinkercad/` is ready for that, and the control law is
identical, so nothing you claim about behaviour changes between them.

---

## 2. The fast route: paste the circuit in

Everything you need is in `arduino/wokwi/`.

1. Go to **wokwi.com** and sign in (free account; you need it to save projects).
2. **New Project → ESP32**. You get `sketch.ino` and `diagram.json`.
3. Click the **`diagram.json`** tab. Select all, delete, and paste the contents of
   `arduino/wokwi/diagram.json`. The canvas redraws with every part wired.
4. Click the **`sketch.ino`** tab. Select all, delete, paste `arduino/wokwi/sketch.ino`.
5. Create a third file: **`+` → `libraries.txt`**, and paste:

   ```
   DHT sensor library for ESPx
   LiquidCrystal I2C
   ThingSpeak
   ```

6. In `sketch.ino`, fill in your two ThingSpeak values near the top:

   ```cpp
   unsigned long THINGSPEAK_CHANNEL_ID = 1234567;
   const char*   THINGSPEAK_WRITE_KEY  = "YOURWRITEKEYHERE";
   ```

7. Press the green **play** button.

Within a few seconds the serial monitor shows `[wifi] connecting.... ok`, then a CSV line
every two seconds, then `[ts] 200 OK` every twenty. Your ThingSpeak channel starts plotting.

---

## 3. The manual route: build it part by part

Do this if you need to show the construction process, or if you want to understand the
wiring rather than inherit it. Add parts with the **`+`** button on the canvas.

### 3.1 Parts to add

| Wokwi part name | Quantity | Stands in for |
|---|---|---|
| ESP32 DevKit V4 (`board-esp32-devkit-c-v4`) | 1 | edge controller |
| DHT22 Temperature & Humidity Sensor | 1 | DHT11 (temperature + humidity) |
| Potentiometer | 1 | capacitive soil moisture probe |
| Photoresistor (LDR) Sensor | 1 | light intensity |
| HC-SR04 Ultrasonic Distance Sensor | 1 | tank level |
| Relay Module | 1 | pump switching |
| Buzzer | 1 | audible alert |
| LED | 3 | green OK, yellow pump, red alert |
| Resistor (220 Ω) | 3 | LED series resistors |
| LCD1602, `pins: i2c` | 1 | local readout |

### 3.2 Wiring

Click a pin, then click its destination — Wokwi draws the wire.

**Power rails**

| From | To |
|---|---|
| DHT22 VCC, potentiometer VCC, LDR VCC | ESP32 **3V3** |
| HC-SR04 VCC, relay VCC, LCD VCC | ESP32 **VIN** (5 V) |
| every GND pin | any ESP32 **GND** |

**Signals**

| Component | Pin | ESP32 GPIO |
|---|---|---|
| DHT22 | SDA | **D4** |
| Potentiometer (soil) | SIG | **D34** |
| LDR sensor | AO | **D35** |
| HC-SR04 | TRIG | **D12** |
| HC-SR04 | ECHO | **D14** |
| Relay module | IN | **D26** |
| Buzzer | pin 2 (+) | **D25** |
| Green LED | anode → 220 Ω → | **D27** |
| Yellow LED | anode → 220 Ω → | **D33** |
| Red LED | anode → 220 Ω → | **D32** |
| LCD1602 (I²C) | SDA | **D21** |
| LCD1602 (I²C) | SCL | **D22** |

All three LED cathodes go to GND. Buzzer pin 1 goes to GND.

### 3.3 Two constraints you should be able to justify

**Only ADC1 works while WiFi is on.** GPIO 32–39 belong to ADC1; ADC2 is claimed by the
radio, so an `analogRead` on an ADC2 pin returns garbage once WiFi associates. That is why
both analogue sensors sit on GPIO 34 and 35 — and both are input-only pins, which is fine
because sensors only ever drive them.

**The ESP8266 has exactly one ADC pin.** This design needs two analogue channels, so an
ESP8266 build would need a CD4051 multiplexer or an ADS1115 I²C ADC. That is the reason
the connected build targets ESP32, and it is a legitimate engineering answer rather than
an avoidance.

---

## 4. The three things that silently break a Wokwi build

These are worth knowing before you spend an hour debugging.

**1. The relay module is active LOW.** Wokwi's relay connects COM to NO when IN is driven
**LOW**, and COM to NC when IN is HIGH or floating. Writing HIGH to "turn the pump on"
turns it off. The sketch handles this with:

```cpp
#define RELAY_ACTIVE_LOW 1     // 1 for the Wokwi module, 0 for a bare relay + NPN
```

Set it to `0` when you move to a bare SRD-05VDC relay driven through a transistor.

**2. Use DHTesp, not the Adafruit DHT library.** Wokwi's own documentation says other DHT
libraries may not read reliably on the ESP32 — the protocol is timing-sensitive and the
simulator's timing is not identical to silicon. The sketch uses `DHTesp`.

**3. The soil calibration constants differ.** A potentiometer sweeps the full 0–4095 ADC
range; a real capacitive probe only covers roughly 1250–3200. Both sets are in the sketch;
swap them when you move to hardware, and say in the report that you did.

---

## 5. Driving the demonstration

Wokwi has no environment model, so you are the environment. Click a part during the
simulation to get its control.

| To show | Do this | Expected |
|---|---|---|
| **Irrigation starts** | drag the potentiometer down below 35 % | relay clicks, yellow LED on, LCD shows `PMP:ON` |
| **Hysteresis** | drag it slowly back up | pump stays on through 40, 50, 55 % and releases only above 60 % |
| **Low-water interlock** | drag the HC-SR04 distance slider past 36 cm with soil still dry | pump forced off, red LED, 900 Hz tone, `! LOW WATER LVL` |
| **Heat alert** | click the DHT22, raise temperature past 35 °C | red LED, 1500 Hz chirp, pump behaviour unchanged |
| **Both alerts** | low tank and high temperature together | 2000 Hz, `! LOW H2O+HEAT` |
| **Light channel** | drag the LDR light slider | light % changes on LCD page 2 |
| **Sensor fault** | delete the HC-SR04 ECHO wire mid-run | `pulseIn` times out → −1 → pump inhibited, 400 Hz, alert 4 |

That last one is worth doing deliberately. It demonstrates that the system **fails closed**
— an unreadable tank sensor stops the pump rather than starting it. A missed irrigation
cycle costs a day of growth; a dry-run pump costs the pump.

---

## 6. Evidence to capture for the report

1. **Screenshot of the wired canvas** — Figure 4.1.
2. **Serial monitor** showing the CSV stream and `[ts] 200 OK` — proves the cloud path.
3. **ThingSpeak channel** with all six fields plotting — Figures 5.1–5.6.
4. **Packet capture.** Click the WiFi icon in Wokwi to download a `.pcap`, then open it in
   Wireshark and filter on `http`. An HTTP POST to `api.thingspeak.com` in a real packet
   capture is unusually strong evidence that the telemetry path genuinely works, and almost
   no student project includes it.
5. **Short screen recording** of the six demonstrations in §5.

---

## 7. If you also build the Tinkercad version

Use `arduino/smart_agri_tinkercad/smart_agri_tinkercad.ino` and the pin map in
`docs/02_hardware_wiring.md` §3.1. Remember the substitutions — TMP36 for temperature, a
potentiometer for humidity — and state them in the report as a documented platform
constraint rather than leaving the examiner to notice.

Build in stages and verify each on the serial monitor before adding the next: board and
TMP36 first, then the potentiometers, then the LDR divider, then HC-SR04, then relay and
motor with the flyback diode, then LEDs and buzzer, and the LCD last because it occupies
six pins and complicates debugging.
