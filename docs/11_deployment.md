# 11 · Deploying the Dashboard for Free

Recommended: **Streamlit Community Cloud**. It is built for exactly this, takes about ten
minutes, and your app ends up at `https://<name>.streamlit.app` — a link you can put in the
report, the slides and your CV.

---

## 1. Will it fit? Yes, with room

The free tier gives you roughly **1 GB of RAM**. Measured on this project:

| What loads | Memory |
|---|---|
| pandas + joblib imported | 104 MB |
| `processed_dataset.csv` (30,180 × 97) | 44 MB |
| `test_predictions.csv` | <1 MB |
| the three models | 189 MB |
| **total before Streamlit's own overhead** | **337 MB** |

Add Streamlit's runtime and you land near 500 MB. That fits, but it is not unlimited — most
of the 189 MB is the soil-moisture regressor, and each extra concurrent visitor costs a
little more. If you ever hit the ceiling, §6 has the fallback.

Repository size matters too. Run this once before you push:

```bash
python python/05_pack_for_deploy.py
```

It gzips the two runtime CSVs — **26.3 MB → 6.5 MB** and **1.1 MB → 0.3 MB**. The dashboard
already prefers the `.csv.gz` copies (`data_path()` in `app.py`), pandas reads them natively,
and the uncompressed originals are gitignored. Total repo lands around 38 MB.

---

## 2. Deploy in ten minutes

### Step 1 · Put the project on GitHub

Free deployment requires a **public** repository. The free tier allows unlimited public apps
but only one private app, so public is the path of least resistance for a college project.

```bash
cd ~/Downloads/smart_agri
python python/05_pack_for_deploy.py

git init
git add .
git commit -m "IoT smart agriculture system with ML irrigation prediction"
git branch -M main
git remote add origin https://github.com/ThatOneCoderWhoCreates/smart-agriculture-iot.git
git push -u origin main
```

Create the empty repository on github.com first, without a README, so the push is clean.

Check what you actually committed before pushing:

```bash
git ls-files | xargs du -ch | tail -1      # should be roughly 38 MB
git ls-files data/                          # should show the .gz files, not the raw CSVs
```

### Step 2 · Connect Streamlit

1. Go to **share.streamlit.io** and sign in with GitHub.
2. Authorise access. For a public repo the default OAuth scopes are enough; a private repo
   additionally needs the broader `repo` scope, which is another reason to go public.
3. Click **Create app → Deploy a public app from GitHub**.

### Step 3 · Configure

| Field | Value |
|---|---|
| Repository | `ThatOneCoderWhoCreates/smart-agriculture-iot` |
| Branch | `main` |
| Main file path | **`dashboard/app.py`** |
| App URL | e.g. `smart-agriculture-iot` |

Under **Advanced settings**, set **Python version 3.12** to match your local environment.

### Step 4 · Deploy

Press **Deploy**. The first build takes three to five minutes while scikit-learn, pandas and
plotly install. Watch the log pane; the app opens automatically when it is ready.

---

## 3. Things that will bite you

**Nothing here is hypothetical — each one is a real failure mode for this specific app.**

| Symptom | Cause | Fix |
|---|---|---|
| `FileNotFoundError: processed_dataset.csv` | data files gitignored or never committed | run `05_pack_for_deploy.py`, then `git add -f data/*.csv.gz` |
| `ModuleNotFoundError: theme` | `sys.path` not picking up `dashboard/` | already handled in `app.py`; make sure you set the main file path to `dashboard/app.py`, not a copy at the root |
| App crashes with no traceback | out of memory | see §6 |
| Fonts look wrong | Google Fonts blocked by the visitor's network | harmless; the CSS falls back to system sans and monospace |
| Models fail to unpickle | scikit-learn version mismatch | `requirements.txt` pins `scikit-learn>=1.4`; the models were built on 1.8.0, so pin `scikit-learn==1.8.0` exactly if you see a version warning |
| Push rejected, file too large | you committed the raw CSVs | GitHub's hard limit is 100 MB per file; you are well under it, but keep the `.gz` discipline anyway |

**Do not commit your ThingSpeak write key.** It is only in the Arduino sketches, which are
not executed by the deployed app, but a write key in a public repository lets anyone push
junk into your channel. Replace it with `XXXXXXXXXXXXXXXX` before pushing and keep the real
one in a local note. If you have already pushed it, regenerate the key from the ThingSpeak
**API Keys** tab — rewriting git history is not worth the effort for a key you can rotate in
one click.

---

## 4. After it is live

- **Apps sleep after about 12 quiet hours.** The next visitor sees a "waking up" page for
  roughly 30 seconds. Open your own app the morning of the viva so it is warm — this is the
  single most common demo embarrassment on the free tier.
- **Updates are automatic.** Push to `main` and the app rebuilds. Community Cloud rate-limits
  this to five updates per minute.
- **Logs** are under **Manage app** in the bottom-right corner of your deployed app.

---

## 5. Worth putting in the report

A deployed link is unusually good evidence for a student project. Add it to:

- the title slide and the last slide of the deck
- Chapter 9 of the report, beside the dashboard screenshots
- the README, as a badge:

```markdown
[![Open in Streamlit](https://static.streamlit.io/badges/streamlit_badge_black_white.svg)](https://smart-agriculture-iot.streamlit.app)
```

Give the examiner the URL at the start of the viva so they can click through your six
scenarios themselves while you talk.

---

## 6. If you outgrow the free tier

**Hugging Face Spaces** is the strongest free fallback: **16 GB RAM and 8 CPU cores** on the
free CPU tier, versus roughly 1 GB on Streamlit Cloud. Worth switching to if the app is
killed for memory, or if you want several people clicking through it at once.

1. huggingface.co → **New Space** → SDK **Streamlit**, hardware **CPU basic (free)**.
2. Push the same repository to the Space's git remote.
3. Rename `dashboard/app.py` to `app.py` at the repository root, or add a one-line root
   `app.py` containing `exec(open("dashboard/app.py").read())` — Spaces expects the entry
   point at the root.
4. Keep the same `requirements.txt`.

Other options, in descending order of usefulness here: **Render** free tier (works, but
spins down aggressively and cold starts are slower than Streamlit's), **Railway** (trial
credit rather than a true free tier), and **Docker on a VPS** (full control, not free).

For this project, Streamlit Community Cloud is the right answer and Hugging Face Spaces is
the one to move to if memory becomes the problem.

---

## 7. Trimming memory, if you need to

In order of how much they buy you against how much they cost:

1. **Shrink the regressor.** It is 189 MB of the 337 MB. Retraining with
   `n_estimators=150, max_depth=14` roughly halves it. But it changes the numbers you quote
   in the report, so if you do this, re-run `03_train_models.py` and update every figure —
   do not report metrics from one model and deploy another.
2. **Downcast the dataframe.** Add `df = df.astype({c: "float32" for c in
   df.select_dtypes("float64").columns})` in `load_data()`. Saves about 20 MB and changes no
   result at the precision anyone reports.
3. **Load models lazily.** Only M1 and M2 are needed before the user opens the anomaly tab.
   Splitting `load_models()` per model defers roughly a third of the memory.
4. **Drop unused columns at load.** The dashboard touches maybe 60 of the 97 columns.

Do these only if you actually hit the limit. Option 1 in particular is a trade against the
integrity of your reported results, and integrity is worth more than 90 MB.
