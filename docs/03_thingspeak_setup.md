# 03 · ThingSpeak Setup and Data Transmission

## 1. Create the channel

1. Sign up at `thingspeak.com` (a free MathWorks account; the student licence works).
2. **Channels → My Channels → New Channel.**
3. Name: `Smart Agriculture Field Node 01`.
4. Enable **fields 1–6** and name them exactly as below — the field numbers are hard-coded
   in both the firmware and `thingspeak_io.py`.

| Field | Name | Unit | Source |
|---|---|---|---|
| field1 | Temperature | °C | DHT11 |
| field2 | Humidity | % RH | DHT11 |
| field3 | Soil Moisture | % | capacitive probe |
| field4 | Light Intensity | % | LDR |
| field5 | Water Level | % | HC-SR04 |
| field6 | Pump Status | 0/1 | relay state |

5. Tick **Show Channel Location** and **Show Status** (the status string carries the
   human-readable alert text).
6. Save. Note the **Channel ID**, and from the **API Keys** tab the **Write API Key** and
   **Read API Key**.

A free account gives you 4 channels and roughly 3 million messages per year. Budget them —
see §4.

---

## 2. Publishing from the node

`smart_agri_esp32_thingspeak.ino` already does this. The relevant lines:

```cpp
ThingSpeak.setField(1, t);      // temperature
ThingSpeak.setField(2, h);      // humidity
ThingSpeak.setField(3, s);      // soil moisture
ThingSpeak.setField(4, l);      // light
ThingSpeak.setField(5, w);      // water level
ThingSpeak.setField(6, (int)(duty > 0.5 ? 1 : 0));
ThingSpeak.setStatus(alertText());
int code = ThingSpeak.writeFields(THINGSPEAK_CHANNEL_ID, THINGSPEAK_WRITE_KEY);
```

Fill in `THINGSPEAK_CHANNEL_ID` and `THINGSPEAK_WRITE_KEY` at the top of the sketch.

### Return codes you will actually see

| Code | Meaning | Fix |
|---|---|---|
| `200` | accepted | — |
| `0` | posting faster than the rate limit, **or** malformed payload | increase `PUBLISH_MS` |
| `401` | wrong write API key | copy it again from the API Keys tab |
| `-301` | connection failed | WiFi not associated / DNS failure |
| `-304` | timeout | gateway congestion, retry next cycle |

### The rate limit is the thing that breaks student projects

**A free channel accepts one update every 15 seconds.** Not "roughly"; the server drops
anything faster and returns `0`. The firmware therefore samples at **2 s** and publishes a
**20 s mean** of ten samples. This is not a workaround — averaging ten samples also reduces
the ADC noise by √10, so the published series is cleaner than the raw one.

If you need finer resolution, use several channels (each has its own 15 s budget) or move
to the bulk-update endpoint described below.

---

## 3. Running it in Wokwi

1. Go to `wokwi.com`, **New Project → ESP32**.
2. Paste `smart_agri_esp32_thingspeak.ino` into `sketch.ino`.
3. Create `libraries.txt` with:

```
DHT sensor library
Adafruit Unified Sensor
ThingSpeak
```

4. Add components in `diagram.json` (or via the **+** button): DHT22, two potentiometers
   (standing in for the soil probe and LDR, or use a real photoresistor part), HC-SR04,
   three LEDs with resistors, a buzzer, and a relay module.
5. Leave the credentials as `Wokwi-GUEST` / empty string, channel 6. Wokwi provides a
   virtual access point and an IoT gateway to the real internet.
6. Start the simulation. Within a few seconds the serial monitor prints `[ts] 200 OK` and
   your ThingSpeak channel begins plotting.

You can download a `.pcap` of the simulated traffic from the WiFi icon and open it in
Wireshark — an HTTP POST to `api.thingspeak.com` in a packet capture is very strong
evidence for the report that the cloud path is genuinely working.

---

## 4. Loading the 21-day history

You cannot run a Tinkercad or Wokwi simulation for three weeks, and a ten-minute live demo
produces plots with nothing in them. Load the generated campaign into the channel instead,
using the **bulk-update** endpoint:

```
POST https://api.thingspeak.com/channels/<CHANNEL_ID>/bulk_update.json
Content-Type: application/json

{ "write_api_key": "...",
  "updates": [ {"created_at": "2026-03-01 00:00:00 +0530",
                "field1": 22.4, "field2": 65.6, "field3": 48.17,
                "field4": 0.39, "field5": 91.6, "field6": 0}, ... ] }
```

`thingspeak_io.py` does all of this:

```bash
export TS_CHANNEL_ID=1234567
export TS_WRITE_KEY=XXXXXXXXXXXXXXXX

python python/thingspeak_io.py upload --resample 5min --dry-run   # inspect first
python python/thingspeak_io.py upload --resample 5min             # 7 calls, ~2 min
python python/thingspeak_io.py download --results 8000            # round trip back
```

Constraints the script enforces, all of which are real and will reject your data if
violated:

| Constraint | Value | Consequence if ignored |
|---|---|---|
| messages per bulk call (free) | **960** | request rejected |
| interval between bulk calls | **≥ 15 s** | returns `0`, nothing inserted |
| timestamps within a channel | **must be unique** | duplicates → *all* updates in the call rejected |
| time format | consistent across all objects in a call | mixed `created_at` / `delta_t` → rejected |

**Message budget.** The full campaign at 1-minute resolution is 30,240 messages — about
1 % of the annual free allowance, delivered in 32 calls over ~8 minutes. The default
5-minute resample is 6,048 messages in 7 calls, which is plenty for readable plots. Use the
1-minute upload only if you specifically need it.

Also note: **MQTT subscribers are not notified of bulk writes**, and a React with
"On Data Insertion" fires only once per bulk request. Neither affects this project, but
they are the kind of detail an examiner who knows ThingSpeak may probe.

---

## 5. Visualisations to configure on the channel

The default field charts give you six of the required plots for free. Set each one's
**Results** to 8000 and **Type** to `line`.

Add these MATLAB visualisations (**Channel → Visualizations → MATLAB Visualization**) to
turn the channel from a set of strip charts into an analysis surface:

**(a) Soil moisture with the control band**

```matlab
data = thingSpeakRead(channelID, 'Fields', 3, 'NumPoints', 8000, ...
                      'OutputFormat', 'timetable', 'ReadKey', readKey);
plot(data.Timestamps, data.SoilMoisture, 'LineWidth', 1.2); hold on
yline(35, 'r--', 'Start 35%'); yline(60, 'g--', 'Stop 60%');
ylabel('Soil moisture (%)'); title('Root-zone moisture vs control set-points'); grid on
```

**(b) Pump duty cycle by hour of day**

```matlab
d = thingSpeakRead(channelID, 'Fields', 6, 'NumPoints', 8000, ...
                   'OutputFormat', 'timetable', 'ReadKey', readKey);
h = hour(d.Timestamps);
duty = accumarray(h+1, d.PumpStatus, [24 1], @mean) * 100;
bar(0:23, duty); xlabel('Hour of day'); ylabel('% of time pump ON'); grid on
```

**(c) Temperature–humidity coupling**

```matlab
d = thingSpeakRead(channelID, 'Fields', [1 2], 'NumPoints', 8000, ...
                   'OutputFormat', 'timetable', 'ReadKey', readKey);
scatter(d.Temperature, d.Humidity, 4, 'filled'); lsline
xlabel('Temperature (°C)'); ylabel('Humidity (% RH)');
title(sprintf('r = %.3f', corr(d.Temperature, d.Humidity, 'rows', 'complete')));
```

Screenshot all of these; they populate the "Cloud analytics" chapter of the report.

---

## 6. React alerts (optional, one slide's worth of value)

**Apps → React → New React**: condition `field5 < 20`, action **ThingHTTP** or **Email**.
This demonstrates that the alerting is not only local to the buzzer but also propagates
through the cloud — a genuinely useful point when the examiner asks "what happens if nobody
is standing next to the node?"

---

## 7. Alternatives, if ThingSpeak is unavailable

| Platform | Free tier | Why you might switch |
|---|---|---|
| **Blynk** | 5 devices, 10 datastreams | better mobile dashboard |
| **Adafruit IO** | 30 data points/min, 30-day retention | simpler MQTT |
| **InfluxDB + Grafana (local)** | unlimited | no rate limit, full control, but you host it |

The pipeline downstream of the channel reads a CSV, so swapping platforms only means
changing `thingspeak_io.py`. State this in the report as a design property: the analytics
layer is decoupled from the broker.
