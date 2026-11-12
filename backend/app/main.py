"""
main.py — FastAPI application: fiber-optic failure-forecasting AIOps API.

Endpoints
---------
GET  /api/health
GET  /api/links                 summary list for the dashboard grid
GET  /api/links/{link_id}       full detail: daily trace + live prediction
GET  /api/alerts                links currently at watch/alert status
GET  /api/model-info            Track A/B/C metrics + feature importances
GET  /api/real-validation       real ARNO hardware data, as an independent check
POST /api/regenerate            regenerate the synthetic dataset and retrain
"""
from __future__ import annotations
import time
import numpy as np
import pandas as pd
from datetime import datetime, timezone
from pydantic import BaseModel, Field
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from . import simulator, features, models, persistence, data_loaders, live_store, live_training, model_artifacts

app = FastAPI(title="Fiber Optic Failure Forecasting API", version="2.1")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


class Store:
    def __init__(self):
        self.links = []
        self.feat_df = None
        self.hazard_df = None
        self.clf = self.reg = self.cph = None
        self.a_metrics = self.a_importance = None
        self.b_metrics = self.b_importance = None
        self.c_metrics = None
        self.hazard_scores = None
        self.trained_at = None
        self.latest_cache = {}
        self.model_sources = {"A": "simulation_baseline", "B": "simulation_baseline", "C": "simulation_baseline"}

    def build(self, n_links=130, days=540, seed=7):
        t0 = time.time()
        self.links = simulator.generate_dataset(n_links=n_links, days=days, seed=seed)
        self.feat_df = features.build_dataset_features(self.links)
        self.hazard_df = models.build_hazard_table(self.links)

        self.clf, self.a_metrics, self.a_importance = models.train_track_a(self.feat_df)
        self.reg, self.b_metrics, self.b_importance = models.train_track_b(self.feat_df)
        self.cph, self.c_metrics = models.train_track_c(self.hazard_df)
        self.hazard_scores = models.score_hazard(self.cph, self.hazard_df)

        self.latest_cache = {}
        self.model_sources = {"A": "simulation_baseline", "B": "simulation_baseline", "C": "simulation_baseline"}
        for link in self.links:
            f = features.build_features(link.df)
            if f.empty:
                continue
            last = f.iloc[[-1]]
            class_probs = dict(zip(self.clf.classes_, self.clf.predict_proba(last[features.FEATURE_COLUMNS])[0]))
            pred_class = max(class_probs, key=class_probs.get)
            pred_ttf = None
            if pred_class in models.SOFT_CLASSES and class_probs[pred_class] >= 0.35:
                pred_ttf = float(self.reg.predict(last[features.FEATURE_COLUMNS])[0])
            breach_run = persistence.breach_run_length(link.df["osnr_db"])
            hazard = float(self.hazard_scores.get(link.link_id, 0))
            status = persistence.status_for_link(pred_ttf, hazard, breach_run)
            self.latest_cache[link.link_id] = dict(
                predicted_class=pred_class, class_confidence=round(class_probs[pred_class], 3),
                predicted_ttf_days=round(pred_ttf, 1) if pred_ttf is not None else None,
                hazard_score=round(hazard, 1), breach_run_days=breach_run, status=status,
                last_osnr=round(float(link.df["osnr_db"].iloc[-1]), 2),
                last_laser_current=round(float(link.df["laser_current_ma"].iloc[-1]), 2),
                last_day=int(link.df["day"].iloc[-1]),
                sparkline=[{"osnr": round(float(v), 2)} for v in link.df["osnr_db"].tail(40).tolist()],
            )
        self.trained_at = time.time()
        self.build_seconds = round(self.trained_at - t0, 2)


store = Store()


@app.on_event("startup")
def _startup():
    live_store.init_db()
    store.build()
    model_artifacts.load(store)


@app.get("/api/health")
def health():
    return {"status": "ok", "links_loaded": len(store.links), "trained_at": store.trained_at}


@app.get("/api/links")
def list_links():
    out = []
    for link in store.links:
        c = store.latest_cache.get(link.link_id)
        if not c:
            continue
        out.append({
            "link_id": link.link_id, "route_name": link.route_name,
            "lat": round(link.lat, 4), "lon": round(link.lon, 4),
            "true_failure_class": link.failure_class,  # shown for demo transparency
            "lifecycle": "ongoing" if link.censored else "resolved_incident",
            **c,
        })
    order = {"alert": 0, "watch": 1, "normal": 2}
    out.sort(key=lambda r: (order[r["status"]], -(r["hazard_score"] or 0)))
    return out


@app.get("/api/links/{link_id}")
def link_detail(link_id: str):
    link = next((l for l in store.links if l.link_id == link_id), None)
    if link is None:
        raise HTTPException(404, "link not found")
    c = store.latest_cache.get(link_id, {})
    df = link.df
    trace = [
        {"day": int(r.day), "osnr": round(float(r.osnr_db), 3),
         "laser_current": round(float(r.laser_current_ma), 3),
         "ber": float(r.ber), "rx_power": round(float(r.rx_power_dbm), 2),
         "temp": round(float(r.temp_c), 2), "humidity": round(float(r.humidity_pct), 2)}
        for r in df.itertuples()
    ]
    return {
        "link_id": link.link_id, "route_name": link.route_name,
        "lat": link.lat, "lon": link.lon,
        "true_failure_class": link.failure_class, "censored": link.censored,
        "failure_day": link.failure_day,
        "lifecycle": "ongoing" if link.censored else "resolved_incident",
        "prediction": c,
        "trace": trace,
    }


@app.get("/api/alerts")
def alerts():
    return [r for r in list_links() if r["status"] != "normal"]


@app.get("/api/model-info")
def model_info():
    if store.model_sources.get("B") == "simulation_baseline":
        b_note = ("Excludes hard_cut trajectories from training — see "
                  "mae_days_with_hard_cuts for the empirical cost of not doing so.")
    else:
        b_note = ("Trained from outcome-labelled Live-Link histories. Only confirmed gradual "
                  "soft failures contribute RUL targets; hard cuts and censored links are excluded.")
    return {
        "model_sources": store.model_sources,
        "track_a_classifier": {"model": "RandomForestClassifier", **store.a_metrics,
                                "top_features": store.a_importance},
        "track_b_ttf_regressor": {"model": "RandomForestRegressor", **store.b_metrics,
                                   "top_features": store.b_importance, "note": b_note},
        "track_c_hazard": {"model": "CoxPHFitter (lifelines)", **store.c_metrics},
        "build_seconds": store.build_seconds,
        "n_links": len(store.links),
    }


@app.get("/api/real-validation")
def real_validation():
    try:
        return data_loaders.load_arno_summary()
    except FileNotFoundError:
        raise HTTPException(404, "ARNO dataset not bundled in this deployment")


@app.post("/api/regenerate")
def regenerate(n_links: int = 130, days: int = 540, seed: int | None = None):
    store.build(n_links=n_links, days=days, seed=seed or np.random.randint(1, 100000))
    model_artifacts.clear()
    return {"status": "retrained", "n_links": len(store.links), "build_seconds": store.build_seconds}


@app.get("/api/analytics")
def analytics():
    """Cohort-level reliability metrics for the currently generated dataset.

    The exposure denominator uses observed link-days (including the event day
    for failed links). These are descriptive rates for the bundled simulation
    cohort, not a forecast or a production-network reliability guarantee.
    """
    exposure_link_days = 0
    total_events = 0
    hard_events = 0
    soft_events = 0

    for link in store.links:
        observed_days = len(link.df)
        exposure_link_days += observed_days
        if not link.censored and link.failure_day is not None:
            total_events += 1
            if link.failure_class == "hard_cut":
                hard_events += 1
            elif link.failure_class in models.SOFT_CLASSES:
                soft_events += 1

    rate = (total_events / exposure_link_days * 1000) if exposure_link_days else 0.0
    return {
        "cohort_type": "simulated",
        "link_count": len(store.links),
        "observed_failures": total_events,
        "hard_failures": hard_events,
        "soft_failures": soft_events,
        "exposure_link_days": exposure_link_days,
        "failures_per_1000_link_days": round(rate, 3),
        "interpretation": "Historical event rate within the generated simulation cohort; not an individual-link probability.",
    }


# ---------------------------------------------------------------------------
# Live-Link telemetry ingestion, outcome labelling, and supervised retraining
# ---------------------------------------------------------------------------
class TelemetryReading(BaseModel):
    link_id: str = Field(min_length=2, max_length=80)
    route_name: str | None = Field(default=None, max_length=160)
    lat: float | None = Field(default=None, ge=-90, le=90)
    lon: float | None = Field(default=None, ge=-180, le=180)
    observed_at: datetime | None = None
    osnr_db: float = Field(ge=0, le=100)
    laser_current_ma: float | None = Field(default=None, ge=0, le=10000)
    ber: float | None = Field(default=None, ge=0, le=1)
    rx_power_dbm: float | None = Field(default=None, ge=-150, le=50)
    temp_c: float | None = Field(default=None, ge=-80, le=150)
    humidity_pct: float | None = Field(default=None, ge=0, le=100)
    precip_mm: float = Field(default=0, ge=0)
    wind_kmh: float = Field(default=0, ge=0)
    source: str = Field(default="hardware", pattern="^(hardware|manual|simulator_demo|demo_seed)$")


class OutcomeLabel(BaseModel):
    link_id: str = Field(min_length=2, max_length=80)
    failure_class: str = Field(pattern="^(none|edfa|nli|ecl|hard_cut)$")
    outcome_status: str = Field(pattern="^(resolved|censored)$")
    outcome_at: datetime | None = None
    notes: str | None = Field(default=None, max_length=1000)


@app.post("/api/live/telemetry")
def ingest_live_telemetry(reading: TelemetryReading):
    """Ingest one timestamped device/manual measurement.

    Device gateways should POST JSON here. A 2xx response confirms storage,
    not that the optical measurement itself has been independently verified.
    """
    payload = reading.model_dump()
    if payload.get("observed_at") is not None:
        observed = payload["observed_at"]
        if observed.tzinfo is None:
            observed = observed.replace(tzinfo=timezone.utc)
        payload["observed_at"] = observed.astimezone(timezone.utc).isoformat()
    try:
        saved = live_store.save_reading(payload)
    except Exception as exc:
        raise HTTPException(400, f"Could not store telemetry: {exc}")
    return {"status": "stored", **saved, "source": reading.source}


@app.get("/api/live/links")
def live_links():
    output = []
    for link in live_store.list_links():
        readings = live_store.get_readings(link["link_id"])
        if not readings:
            continue
        last = readings[-1]
        # Convert the incoming device cadence to daily aggregates before using
        # models trained on daily samples. This prevents minute-level readings
        # being misinterpreted as days of degradation history.
        record = {"link_id": link["link_id"], "readings": readings}
        daily = live_training._daily_frame(record)
        osnr_values = [float(v) for v in (daily["osnr_db"].tolist() if not daily.empty else [r["osnr_db"] for r in readings])]
        breach_run = persistence.breach_run_length(osnr_values, threshold=18.0)
        prediction = {"predicted_class": None, "class_score": None,
                      "predicted_ttf_days": None, "prediction_ready": False}
        feat = features.build_features(daily) if len(daily) >= features.LAG_WINDOW + 1 else pd.DataFrame()
        if not feat.empty:
            x = feat.iloc[[-1]][features.FEATURE_COLUMNS]
            try:
                probs = dict(zip(store.clf.classes_, store.clf.predict_proba(x)[0]))
                pred_class = max(probs, key=probs.get)
                prediction.update({"predicted_class": pred_class,
                                   "class_score": round(float(probs[pred_class]), 3),
                                   "prediction_ready": True,
                                   "classifier_source": store.model_sources.get("A", "simulation_baseline")})
                if pred_class in models.SOFT_CLASSES:
                    prediction["predicted_ttf_days"] = round(float(store.reg.predict(x)[0]), 1)
                    prediction["rul_source"] = store.model_sources.get("B", "simulation_baseline")
            except Exception:
                pass
        ttf = prediction.get("predicted_ttf_days")
        if float(last["osnr_db"]) <= 15 or (ttf is not None and ttf <= 14 and breach_run >= 3):
            status = "critical"
        elif float(last["osnr_db"]) <= 18 or (ttf is not None and ttf <= 45):
            status = "watch"
        else:
            status = "normal"
        try:
            last_seen = pd.to_datetime(link["latest_at"], utc=True)
            age_minutes = max(0.0, (pd.Timestamp.now(tz="UTC") - last_seen).total_seconds() / 60)
        except Exception:
            age_minutes = None
        output.append({**link, **prediction, "status": status,
                       "breach_run_days": breach_run, "telemetry_age_minutes": round(age_minutes, 1) if age_minutes is not None else None,
                       "is_stale": age_minutes is None or age_minutes > 15,
                       "daily_observations": int(len(daily)),
                       "_hazard_covariates": {
                           "avg_temp": float(daily["temp_c"].mean()) if not daily.empty else 25.0,
                           "avg_humidity": float(daily["humidity_pct"].mean()) if not daily.empty else 50.0,
                           "avg_precip": float(daily["precip_mm"].mean()) if not daily.empty else 0.0,
                           "avg_wind": float(daily["wind_kmh"].mean()) if not daily.empty else 0.0,
                       }})
    # Track C is a cohort-relative hazard score, not an absolute probability.
    # Only rank when at least five live links are available for a meaningful
    # comparison group.
    hazard_rows = [item["_hazard_covariates"] for item in output]
    if store.cph is not None and len(hazard_rows) >= 5:
        try:
            hazard_frame = pd.DataFrame(hazard_rows)
            partial = store.cph.predict_partial_hazard(hazard_frame)
            ranks = partial.rank(pct=True) * 100
            for item, rank in zip(output, ranks.tolist()):
                item["hard_failure_hazard_percentile"] = round(float(rank), 1)
                item["hazard_source"] = store.model_sources.get("C", "simulation_baseline")
        except Exception:
            pass
    for item in output:
        hazard = item.get("hard_failure_hazard_percentile")
        osnr = float(item.get("osnr_db") or 100)
        ttf = item.get("predicted_ttf_days")
        if osnr <= 15 or (ttf is not None and ttf <= 14 and item["breach_run_days"] >= 3) or (hazard is not None and hazard >= 90):
            item["status"] = "critical"
        elif osnr <= 18 or (ttf is not None and ttf <= 45) or (hazard is not None and hazard >= 70):
            item["status"] = "watch"
        item.pop("_hazard_covariates", None)
    order = {"critical": 0, "watch": 1, "normal": 2}
    output.sort(key=lambda x: (order.get(x["status"], 3), x["link_id"]))
    return output


@app.get("/api/live/links/{link_id}")
def live_link_detail(link_id: str):
    link = next((x for x in live_store.list_links() if x["link_id"] == link_id), None)
    if link is None:
        raise HTTPException(404, "Live-Link not found")
    readings = live_store.get_readings(link_id)
    return {**link, "readings": readings,
            "outcome_label": {"failure_class": link.get("failure_class"),
                              "outcome_status": link.get("outcome_status"),
                              "outcome_at": link.get("outcome_at")}}


@app.get("/api/live/summary")
def live_summary():
    counts = live_store.training_counts()
    raw_links = live_store.list_links()
    now = pd.Timestamp.now(tz="UTC")
    critical = watch = stale = 0
    latest = None
    for link in raw_links:
        try:
            age = (now - pd.to_datetime(link["latest_at"], utc=True)).total_seconds() / 60
        except Exception:
            age = float("inf")
        stale += int(age > 15)
        osnr = link.get("osnr_db")
        if osnr is not None and float(osnr) <= 15:
            critical += 1
        elif osnr is not None and float(osnr) <= 18:
            watch += 1
        if link.get("latest_at") and (latest is None or link["latest_at"] > latest):
            latest = link["latest_at"]
    return {
        **counts,
        "active_links": len(raw_links),
        "critical_links": critical,
        "watch_links": watch,
        "stale_links": stale,
        "latest_observation": latest,
        "model_sources": store.model_sources,
        "note": "Live-Link means persisted incoming measurements. Records marked demo_seed are generated data, not field measurements.",
    }


@app.get("/api/live/training")
def live_training_status():
    counts = live_store.training_counts()
    return {
        **counts,
        "model_sources": store.model_sources,
        "daily_history_requirement": features.LAG_WINDOW + 1,
        "training_policy": "Only outcome-labelled link histories are eligible. RUL uses confirmed soft failures only; right-censored histories are excluded from RUL regression.",
    }


@app.post("/api/live/labels")
def label_live_outcome(label: OutcomeLabel):
    if label.outcome_status == "resolved":
        if label.failure_class == "none" or label.outcome_at is None:
            raise HTTPException(422, "A resolved failure requires a fault class and outcome_at timestamp.")
    elif label.failure_class != "none":
        raise HTTPException(422, "A censored (not yet failed) link must use failure_class='none'.")
    try:
        outcome = label.outcome_at
        if outcome is not None and outcome.tzinfo is None:
            outcome = outcome.replace(tzinfo=timezone.utc)
        outcome_at = outcome.astimezone(timezone.utc).isoformat() if outcome else None
        live_store.save_outcome(label.link_id, label.failure_class, label.outcome_status,
                                outcome_at, label.notes)
    except KeyError:
        raise HTTPException(404, "Link has no telemetry yet. Ingest at least one reading first.")
    return {"status": "label_saved", "link_id": label.link_id,
            "failure_class": label.failure_class, "outcome_status": label.outcome_status}


@app.post("/api/live/train")
def train_from_live_link(source: str = Query(default="ingested", pattern="^(ingested|demo|mixed)$")):
    records = live_store.get_training_records()
    if source == "demo":
        records = [r for r in records if r.get("readings") and all(x.get("source") in {"demo_seed", "simulator_demo"} for x in r["readings"])]
    elif source == "ingested":
        records = [r for r in records if r.get("readings") and all(x.get("source") in {"hardware", "manual"} for x in r["readings"])]
    if not records:
        raise HTTPException(409, "No labelled histories for this source. Add measurements, confirm outcomes, or select the demo dataset explicitly.")
    result = live_training.train_from_live(records)
    applied = []
    if "A" in result["trained_models"]:
        store.clf = result["trained_models"]["A"]
        store.a_metrics = {k: v for k, v in result["tracks"]["A"].items() if k != "status"}
        store.a_importance = dict(sorted(zip(features.FEATURE_COLUMNS, store.clf.feature_importances_),
                                         key=lambda kv: -kv[1])[:8])
        store.model_sources["A"] = result["training_source"]
        applied.append("A")
    if "B" in result["trained_models"]:
        store.reg = result["trained_models"]["B"]
        store.b_metrics = {k: v for k, v in result["tracks"]["B"].items() if k != "status"}
        store.b_importance = dict(sorted(zip(features.FEATURE_COLUMNS, store.reg.feature_importances_),
                                         key=lambda kv: -kv[1])[:8])
        store.model_sources["B"] = result["training_source"]
        applied.append("B")
    if "C" in result["trained_models"]:
        store.cph = result["trained_models"]["C"]
        store.c_metrics = {k: v for k, v in result["tracks"]["C"].items() if k != "status"}
        store.model_sources["C"] = result["training_source"]
        applied.append("C")
    if applied:
        model_artifacts.save(store)
    result.pop("trained_models", None)
    result["applied_tracks"] = applied
    result["model_sources"] = store.model_sources
    result["message"] = ("Updated model tracks from labelled Live-Link data." if applied
                         else "No model was replaced; more independent labelled link histories are required.")
    return result


@app.post("/api/live/seed-demo")
def seed_live_demo():
    """Copy the current generated training cohort into Live-Link's persistent
    store so the ingestion -> labelling -> retraining workflow can be tried
    without optical instruments. Every inserted record is visibly tagged demo.
    """
    live_store.clear_demo_source()
    imported = 0
    for link in store.links:
        readings = []
        for row in link.df.itertuples():
            readings.append({
                "observed_at": pd.Timestamp(row.date).isoformat(),
                "osnr_db": float(row.osnr_db), "laser_current_ma": float(row.laser_current_ma),
                "ber": float(row.ber), "rx_power_dbm": float(row.rx_power_dbm),
                "temp_c": float(row.temp_c), "humidity_pct": float(row.humidity_pct),
                "precip_mm": float(row.precip_mm), "wind_kmh": float(row.wind_kmh),
            })
        outcome_at = None
        if link.failure_day is not None:
            outcome_at = pd.Timestamp(link.df["date"].iloc[-1]).isoformat()
        live_store.import_demo_link(
            f"DEMO-{link.link_id}", link.route_name, float(link.lat), float(link.lon), readings,
            link.failure_class if link.failure_day is not None else "none",
            "resolved" if link.failure_day is not None else "censored", outcome_at)
        imported += 1
    return {"status": "demo_seeded", "links_imported": imported,
            "note": "Generated simulation telemetry copied into the persistent Live-Link store; not physical hardware data."}
