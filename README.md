# FiberWatch — Fiber Optic Failure Forecasting

A working full-stack AIOps application: a FastAPI backend running real trained
models (Random Forest classification + regression, Cox Proportional Hazards
survival analysis) over physics-informed synthetic telemetry fused with
weather data, and a React control-room dashboard on top of it.

This is the implementation of the [Execution Blueprint](../) documents,
combining the strongest, most validated elements of three earlier project
specifications into one running system rather than another document.

## What was combined from where

| Element | Source | Why it was kept |
|---|---|---|
| Hard-vs-soft failure split as two separate model tracks | v2.0 Blueprint | The single most important scoping decision — hard cuts have no telemetry precursor; conflating them with soft failures silently breaks a TTF model. This app *proves* it empirically (see Model Performance tab). |
| Physics-inspired features (OSNR lags, velocity, acceleration, rolling stats) | v2.0 Blueprint | Empirically the dominant feature set for this task in the reference literature; confirmed again here via feature-importance output. |
| Random Forest as primary model (not LSTM/CNN) | v2.0 Blueprint | Validated finding: tree ensembles match or beat deep sequence models on this feature set, at a fraction of the inference cost. |
| Weibull/Cox survival framing for hard failures | v2.0 + v1.0 + Project Spec (all three) | Correct statistical treatment of failures that are absent, not zero, until they happen. |
| Weather-driven synthetic simulator with a live-API-with-fallback pattern | v1.0 Blueprint (`fetch_weather`) | Directly reused pattern: try Open-Meteo, fall back to a seeded synthetic series if unreachable. |
| Persistence-filter alerting (k consecutive breaches) | v2.0 Blueprint | Cuts false-alarm rate substantially at a small, bounded delay cost — implemented here as `persistence.py`. |
| Three-modeling-approaches framing (classify / detect / forecast) | Project Spec + v1.0 Blueprint | Clean separation of concerns, mapped here onto Track A / B / C. |
| Real ARNO testbed hardware data as an independent check | New in this build | None of the three prior documents executed against real data — this app bundles actual hardware telemetry from a public GitHub release and validates the 18dB soft-alarm threshold against it directly. |

## Architecture

```
backend/  (FastAPI, Python)
  app/
    simulator.py      physics-informed synthetic telemetry generator
    features.py        physics-inspired feature engineering
    models.py           Track A (classifier) / B (TTF regressor) / C (Cox hazard)
    persistence.py     persistence-filter alerting logic
    data_loaders.py    real ARNO loader (bundled) + OTDR/Mendeley loaders (bring your own credentials)
    main.py              FastAPI app + REST endpoints
    data/arno/           real hardware telemetry, bundled (Sgambelluri et al.)
frontend/  (React + Vite)
  src/
    App.jsx, api.js
    components/         MonitoringView, DetailPanel, ModelPerformanceView, HardwareValidationView, ...
```

REST endpoints: `GET /api/links`, `GET /api/links/{id}`, `GET /api/alerts`,
`GET /api/model-info`, `GET /api/real-validation`, `POST /api/regenerate`.

## Running it

Requires Python 3.10+ and Node 18+.

```bash
# backend
cd backend
python3 -m venv venv && source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
# first startup trains all three model tracks — takes ~30–50s, this is normal

# frontend (separate terminal)
cd frontend
npm install
npm run dev
# open the printed localhost URL — Vite proxies /api to :8000 automatically
```

Click **Regenerate** in the top bar at any point to reseed the synthetic
dataset and retrain all three tracks live — this is a real retrain, not a
cached response.

## Using the real public datasets instead of synthetic data

The ARNO hardware dataset is already bundled and powers the **Hardware
Validation** tab with no setup. The other two datasets referenced in the
research phase need your own credentials, since Kaggle and Mendeley aren't
reachable from a sandboxed build environment:

- **OTDR Trace Training Data** (Kaggle): `kaggle datasets download -d
  johannesreber/otdr-trace-training-data -p data/raw --unzip` after placing
  `kaggle.json` at `~/.kaggle/`. Loader: `data_loaders.load_otdr_kaggle()`.
- **Ghosh & Adhya (2025) soft-failure benchmark** (Mendeley, DOI
  10.17632/y3pspy7j83.1): download manually and point
  `data_loaders.load_ghosh_adhya_mendeley()` at the extracted CSV.

Both loaders are correct and ready to call — they just aren't wired into
`main.py`'s startup path, since that path needs to work with zero
credentials out of the box. Swapping one in is a matter of replacing the
call to `simulator.generate_dataset()` in `Store.build()` with your loaded
DataFrame, reshaped to match what `features.build_dataset_features()`
expects (see the docstring there).

## What's honestly a simplification here

- The Action Layer is a dashboard, not the GitOps/Kubernetes/Terraform
  orchestration loop described as the "Production-Grade Reference" in the
  v2.0 Blueprint — appropriate for a project of this scope, and the
  Blueprint explains what that upgrade path looks like.
- The Cox hazard model's confidence intervals are wide (see the Model
  Performance tab) because there are only a handful of hard-cut events in
  a 130-link sample. The app reports this directly rather than
  overstating confidence — more resolved incidents narrow it.
- The IEEE paper / slide deck / literature review deliverables specified
  in the earlier blueprints are separate artifacts from this web app; ask
  if you want those generated too.

## Dashboard improvements in this version

The Monitoring tab now starts with a network operations overview designed for
quick interpretation:

- Active-link risk distribution with Normal, Watch, and Critical counts.
- Median estimated remaining useful life (RUL) for active links that receive a
  soft-failure estimate.
- RUL bands (0–14, 15–45, and 46+ days) to show where maintenance attention is
  concentrated.
- A clickable corridor map using the simulator's existing latitude/longitude
  fields. The plotted locations are illustrative simulation points, not
  verified positions of installed infrastructure.
- A searchable link explorer with lifecycle and risk-status filters.
- Link detail cards that explain the predicted fault, OSNR trace, current
  telemetry, model score, and a recommended inspection action.
- An observed cohort failure rate calculated as confirmed simulated events per
  1,000 observed link-days. It is a retrospective simulation statistic, not an
  individual link's future failure probability.

### Reading the prediction values correctly

- **Estimated remaining useful life:** Track B's point estimate for gradual
  soft-failure trajectories. It is not a guaranteed countdown. Sudden hard
  cuts deliberately do not receive a remaining-life estimate.
- **Hard-failure hazard percentile:** Track C's relative rank within the
  generated cohort. A value at the 90th percentile is not a 90% probability of
  failure.
- **Classifier score:** Track A's `predict_proba` score. It is displayed as a
  model score and is not claimed to be calibrated confidence.
- **Track B MAE:** The held-out mean absolute error is shown as context for the
  RUL estimate. MAE is an average test error, not a per-link prediction
  interval.

The new `GET /api/analytics` endpoint returns the event count, hard/soft event
split, observed link-day exposure, and historical events per 1,000 link-days
for the currently generated simulation cohort.

## Updated API endpoints

The REST API now also includes `GET /api/analytics` alongside the existing
health, links, model-info, hardware-validation, alerts, and regenerate routes.

## Live-Link: hardware telemetry and model retraining

The new **Live-Link** workspace is the telemetry ingestion and labelled-learning
path. It is separate from the original simulated Monitoring cohort. Incoming
readings are stored in a local SQLite database at
`backend/app/data/live_telemetry.sqlite3` and are retained across API restarts.

### 1. Send a physical measurement to the API

Run the backend, then send one JSON measurement per link observation:

```bash
curl -X POST http://127.0.0.1:8000/api/live/telemetry \
  -H "Content-Type: application/json" \
  -d '{
    "link_id": "LAB-FL-01",
    "route_name": "Optical lab bench",
    "observed_at": "2026-10-30T10:30:00Z",
    "osnr_db": 22.8,
    "laser_current_ma": 65.1,
    "ber": 1e-9,
    "rx_power_dbm": -11.8,
    "temp_c": 28,
    "humidity_pct": 60,
    "source": "hardware"
  }'
```

The available fields are `link_id`, `observed_at`, `osnr_db`,
`laser_current_ma`, `ber`, `rx_power_dbm`, `temp_c`, `humidity_pct`,
`precip_mm`, `wind_kmh`, `route_name`, `lat`, `lon`, and `source`. OSNR is
required. Other measurements can be omitted when the instrument does not
provide them. Source values are `hardware`, `manual`, `simulator_demo`, or
`demo_seed`; do not label manually entered or generated data as hardware.

The endpoint is an ingestion interface, not a driver for every optical
instrument. A supported instrument API, vendor SDK, serial output, or PC
measurement gateway must first translate the instrument's calibrated values
into this JSON schema. An optional JSON-line serial bridge is provided in
`backend/device_gateway_serial.py` (requires optional `pyserial`). It forwards
measurements; it does not measure optical properties by itself.

### 2. Inspect the live feed

- `GET /api/live/links` — link inventory, latest measurement, freshness, and
  predictions when enough daily history exists.
- `GET /api/live/links/{link_id}` — full timestamped history.
- `GET /api/live/summary` — ingestion and data-source counts.
- `GET /api/live/training` — labelled-data coverage and active model sources.

The dashboard polls the live API every five seconds. Measurements are stored
immediately; **real-time display does not mean the instrument is connected
without a gateway**.

### 3. Confirm outcomes before training

Supervised learning needs outcome labels. After a link's condition is confirmed
by OTDR, instrument diagnostics, or a maintenance record, use the Live-Link
screen to label it as `edfa`, `nli`, `ecl`, or `hard_cut` and provide the
confirmed event time. A link with no failure observed by the end of monitoring
is labelled `none` / censored. Do not label a link as failed solely because the
model predicted a failure.

`POST /api/live/labels` records the same information programmatically. The
training action uses only labelled links and keeps all observations from one
link together when making the Track A/B holdout split.

### 4. How the three tracks use Live-Link data

- **Track A — fault classifier:** trains from daily link histories with a
  confirmed fault class. Evaluation holds out independent links, not random
  rows from the same route.
- **Track B — remaining-life regressor:** trains only on confirmed gradual
  soft-failure events (`edfa`, `nli`, `ecl`). Hard cuts and right-censored links
  do not receive invented RUL labels. A minimum of five independent soft
  failure links is required.
- **Track C — hard-cut survival model:** uses confirmed hard cuts as events and
  non-hard-cut links as censored observations. It requires at least five
  confirmed hard cuts and five censored links; its displayed concordance is an
  in-sample fit diagnostic, not a held-out score.

Tracks are retrained independently. A track is replaced only when its own data
requirements are met; otherwise its previous model remains active. Successful
Live-Link models are saved under `backend/app/data/live_models/` and restored
when the API restarts. These local model files are generated at runtime and
are not included in the source archive.

### 5. Demo workflow without hardware

Open the **Live-Link** tab and choose **Load demo fleet**. This copies the
currently generated synthetic trajectories into the persistent Live-Link
store, tags them `demo_seed`, and adds generated outcome labels so the complete
retraining path can be demonstrated without an instrument. These records are
not physical measurements. Use real hardware records and confirmed field
outcomes before claiming field-trained performance.

### Sampling cadence and prediction limits

The current model features were developed for daily telemetry. Incoming
higher-frequency readings are averaged into daily observations before model
inference and training. At least 11 consecutive daily observations are needed to
form the 10-lag feature window. This is intentionally conservative: treating
11 readings taken over 11 minutes as 11 days would produce misleading RUL
outputs. If the project later needs minute-level prediction, it should train
and validate a new model on consistently sampled minute-level histories.

A live telemetry stream by itself cannot train supervised fault classification
or RUL regression. Confirmed outcomes are required. The API records readings
and outcomes separately to preserve that distinction.

### Training source isolation

The Live-Link screen requires an explicit training source:

- **Generated demo fleet only** (`source=demo`) — for rehearsing the full retraining workflow.
- **Hardware / manually ingested only** (`source=ingested`) — excludes generated demo records.
- **All sources** (`source=mixed`) — combines both only when explicitly selected.

The backend defaults to `ingested` when called directly. Each model's source is
shown in Model Performance and persisted with the model artifact so demo-based
training is not later mistaken for hardware-trained performance.

### Local deployment note

The telemetry API is unauthenticated and intended for a local project network
or a trusted lab gateway. Add authentication, authorization, TLS, input-rate
limits, and an audit trail before exposing it beyond a controlled network.
