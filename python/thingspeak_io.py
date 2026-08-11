r"""
thingspeak_io.py
================
Two-way bridge between the local dataset and a ThingSpeak channel.

  upload   push the generated 21-day campaign into your channel so that the
           ThingSpeak time-series plots show the real history, not 10 minutes
           of live demo. Uses the bulk-update endpoint.
  download pull the channel feed back down as a CSV, which is what you should
           actually analyse in the report (it proves the round trip works).

Constraints that this script respects (they will bite you otherwise):
  * one normal update per channel per 15 s on a free account;
  * bulk-update calls must also be >= 15 s apart;
  * a free account accepts at most 960 messages per bulk-update call;
  * every created_at timestamp in a channel must be unique.

At 1-minute resolution the 21-day campaign is 30,240 messages = 32 bulk calls
= ~8 minutes of wall clock. That is a large slice of the free annual message
allowance, so the default is to upload a 5-minute resample (6,048 messages).

Usage
-----
  export TS_CHANNEL_ID=1234567
  export TS_WRITE_KEY=XXXXXXXXXXXXXXXX
  export TS_READ_KEY=YYYYYYYYYYYYYYYY        # only if the channel is private

  python thingspeak_io.py upload   --resample 5min
  python thingspeak_io.py upload   --resample 5min --dry-run
  python thingspeak_io.py download --results 8000
"""

import os
import sys
import time
import json
import argparse
import urllib.request
import urllib.error
import pandas as pd

BASE = "https://api.thingspeak.com"
HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.abspath(os.path.join(HERE, "..", "data"))

FIELD_MAP = {                       # channel field <- dataframe column
    "field1": "temperature_c",
    "field2": "humidity_pct",
    "field3": "soil_moisture_pct",
    "field4": "light_pct",
    "field5": "water_level_pct",
    "field6": "pump_status",
}
MAX_PER_CALL = 960                  # free-account limit
MIN_INTERVAL = 15.0                 # seconds between bulk calls


def _update_obj(row):
    """One ThingSpeak update object. IST offset - change for your locale."""
    obj = {"created_at": row.timestamp.strftime("%Y-%m-%d %H:%M:%S +0530")}
    for f, c in FIELD_MAP.items():
        v = getattr(row, c)
        obj[f] = int(round(v)) if c == "pump_status" else round(float(v), 3)
    return obj


def _post(url, payload):
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.status, r.read().decode()


def upload(csv_path, channel_id, write_key, resample=None, limit=None, dry_run=False):
    df = pd.read_csv(csv_path, parse_dates=["timestamp"])
    keep = ["timestamp"] + list(FIELD_MAP.values())
    df = df[keep]

    if resample:
        agg = {c: "mean" for c in FIELD_MAP.values()}
        agg["pump_status"] = "max"          # keep the ON state visible
        df = df.set_index("timestamp").resample(resample).agg(agg).dropna().reset_index()
    if limit:
        df = df.head(limit)

    n_calls = (len(df) + MAX_PER_CALL - 1) // MAX_PER_CALL
    print(f"rows to send : {len(df):,}")
    print(f"bulk calls   : {n_calls}  (~{n_calls * MIN_INTERVAL / 60:.1f} min at the rate limit)")
    if dry_run:
        print("\n--- dry run, first update object ---")
        r0 = df.iloc[0]
        print(json.dumps(_update_obj(r0), indent=2))
        return

    url = f"{BASE}/channels/{channel_id}/bulk_update.json"
    sent = 0
    for i in range(n_calls):
        chunk = df.iloc[i * MAX_PER_CALL:(i + 1) * MAX_PER_CALL]
        updates = [_update_obj(r) for r in chunk.itertuples(index=False)]

        payload = {"write_api_key": write_key, "updates": updates}
        t0 = time.time()
        try:
            status, body = _post(url, payload)
            sent += len(updates)
            print(f"  [{i+1}/{n_calls}] HTTP {status}  {body.strip()[:90]}  (total {sent:,})")
        except urllib.error.HTTPError as e:
            print(f"  [{i+1}/{n_calls}] HTTP ERROR {e.code}: {e.read().decode()[:200]}")
            print("    401 -> wrong write key | 400 -> duplicate timestamps or bad JSON")
            break
        except Exception as e:                                  # noqa: BLE001
            print(f"  [{i+1}/{n_calls}] {type(e).__name__}: {e}")
            break

        wait = MIN_INTERVAL - (time.time() - t0)
        if wait > 0 and i < n_calls - 1:
            time.sleep(wait)
    print(f"done, {sent:,} messages accepted")


def download(channel_id, read_key=None, results=8000, out=None):
    """Pull the feed back. ThingSpeak caps `results` at 8000 per request."""
    url = f"{BASE}/channels/{channel_id}/feeds.csv?results={min(results, 8000)}"
    if read_key:
        url += f"&api_key={read_key}"
    print(f"GET {url.split('&api_key')[0]}")
    with urllib.request.urlopen(url, timeout=60) as r:
        raw = r.read().decode()

    out = out or os.path.join(DATA, "thingspeak_feed.csv")
    with open(out, "w") as f:
        f.write(raw)

    df = pd.read_csv(out, parse_dates=["created_at"])
    df = df.rename(columns={"created_at": "timestamp", **{k: v for k, v in FIELD_MAP.items()}})
    df.to_csv(out, index=False)
    print(f"{len(df):,} rows -> {out}")
    print(df.head(3).to_string())
    return df


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("action", choices=["upload", "download"])
    ap.add_argument("--csv", default=os.path.join(DATA, "sensor_data_raw.csv"))
    ap.add_argument("--resample", default="5min",
                    help="pandas offset alias, or 'none' to send every minute")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--results", type=int, default=8000)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    cid = os.environ.get("TS_CHANNEL_ID")
    wkey = os.environ.get("TS_WRITE_KEY")
    rkey = os.environ.get("TS_READ_KEY")

    if a.action == "upload":
        if not a.dry_run and (not cid or not wkey):
            sys.exit("set TS_CHANNEL_ID and TS_WRITE_KEY, or pass --dry-run")
        upload(a.csv, cid, wkey,
               resample=None if a.resample == "none" else a.resample,
               limit=a.limit, dry_run=a.dry_run)
    else:
        if not cid:
            sys.exit("set TS_CHANNEL_ID")
        download(cid, rkey, a.results)
