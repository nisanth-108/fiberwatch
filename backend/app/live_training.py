"""Build leakage-aware training sets from labelled Live-Link histories.

Telemetry without a confirmed outcome is never silently treated as a fault
label. Models are trained per track only when independent-link requirements
are satisfied. Daily aggregation keeps cadence consistent with the bundled
synthetic training data; high-frequency readings are averaged per UTC day.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier, RandomForestRegressor
from sklearn.metrics import f1_score, mean_absolute_error
from sklearn.model_selection import train_test_split
from lifelines import CoxPHFitter

from .features import FEATURE_COLUMNS, LAG_WINDOW, build_features
from .models import SOFT_CLASSES

ALLOWED_CLASSES = {"none", "edfa", "nli", "ecl", "hard_cut"}


def _daily_frame(record: dict) -> pd.DataFrame:
    raw = pd.DataFrame(record.get("readings", []))
    if raw.empty:
        return raw
    raw["observed_at"] = pd.to_datetime(raw["observed_at"], utc=True, errors="coerce")
    raw = raw.dropna(subset=["observed_at"]).sort_values("observed_at")
    if raw.empty:
        return raw
    defaults = {
        "laser_current_ma": 65.0, "ber": np.nan, "rx_power_dbm": np.nan,
        "temp_c": 25.0, "humidity_pct": 50.0, "precip_mm": 0.0, "wind_kmh": 0.0,
    }
    for column, default in defaults.items():
        if column not in raw:
            raw[column] = default
    raw["date"] = raw["observed_at"].dt.floor("D")
    numeric = ["osnr_db", "laser_current_ma", "ber", "rx_power_dbm", "temp_c",
               "humidity_pct", "precip_mm", "wind_kmh"]
    for column in numeric:
        raw[column] = pd.to_numeric(raw[column], errors="coerce")
    daily = raw.groupby("date", as_index=False)[numeric].mean().sort_values("date")
    # Use only the latest uninterrupted daily run. The original feature model
    # assumes one observation per day; a 10-row lag must not silently become
    # ten irregularly spaced samples or a pseudo-day countdown.
    day_group = daily["date"].diff().dt.total_seconds().div(86400).fillna(1).ne(1).cumsum()
    latest_group = day_group.iloc[-1]
    daily = daily.loc[day_group == latest_group].copy().reset_index(drop=True)
    daily["link_id"] = record["link_id"]
    daily["day"] = (daily["date"] - daily["date"].iloc[0]).dt.total_seconds() / 86400.0
    daily_defaults = {
        "laser_current_ma": 65.0, "ber": 1e-9, "rx_power_dbm": -12.0,
        "temp_c": 25.0, "humidity_pct": 50.0, "precip_mm": 0.0, "wind_kmh": 0.0,
    }
    for column, default in daily_defaults.items():
        daily[column] = daily[column].fillna(default)
    return daily.reset_index(drop=True)


def build_live_training_frames(records: list[dict]):
    feature_frames = []
    hazard_rows = []
    eligible_links = []
    for record in records:
        if record.get("failure_class") not in ALLOWED_CLASSES:
            continue
        daily = _daily_frame(record)
        if len(daily) < LAG_WINDOW + 1:
            continue
        outcome_at = pd.to_datetime(record.get("outcome_at"), utc=True, errors="coerce")
        if record.get("outcome_status") == "resolved" and pd.notna(outcome_at):
            daily = daily[daily["date"] <= outcome_at.floor("D")].copy()
        if len(daily) < LAG_WINDOW + 1:
            continue
        feats = build_features(daily)
        if feats.empty:
            continue
        label = record["failure_class"]
        feats["failure_class"] = label
        if label in SOFT_CLASSES and record.get("outcome_status") == "resolved" and pd.notna(outcome_at):
            sample_dates = pd.to_datetime(daily["date"].iloc[LAG_WINDOW:].values, utc=True)
            feats["ttf_days"] = (outcome_at - sample_dates).total_seconds() / 86400.0
            feats["ttf_days"] = feats["ttf_days"].clip(lower=0)
        else:
            feats["ttf_days"] = np.nan
        feats["censored"] = record.get("outcome_status") == "censored"
        feature_frames.append(feats)
        eligible_links.append(record["link_id"])

        start = daily["date"].iloc[0]
        end = outcome_at.floor("D") if record.get("outcome_status") == "resolved" and pd.notna(outcome_at) else daily["date"].iloc[-1]
        duration = max(1.0, (end - start).total_seconds() / 86400.0)
        hazard_rows.append({
            "link_id": record["link_id"], "duration": duration,
            "event": bool(label == "hard_cut" and record.get("outcome_status") == "resolved"),
            "avg_temp": float(daily["temp_c"].mean()),
            "avg_humidity": float(daily["humidity_pct"].mean()),
            "avg_precip": float(daily["precip_mm"].mean()),
            "avg_wind": float(daily["wind_kmh"].mean()),
        })
    feature_df = pd.concat(feature_frames, ignore_index=True) if feature_frames else pd.DataFrame()
    hazard_df = pd.DataFrame(hazard_rows)
    return feature_df, hazard_df, eligible_links


def _group_split(frame: pd.DataFrame, label_col: str, test_size=0.25):
    link_labels = frame[["link_id", label_col]].drop_duplicates("link_id")
    counts = link_labels[label_col].value_counts()
    if len(counts) < 2 or counts.min() < 2:
        raise ValueError("Need at least two independently labelled links in every class for a link-held-out evaluation.")
    n_links = len(link_labels)
    n_classes = len(counts)
    n_test = max(n_classes, int(np.ceil(test_size * n_links)))
    if n_links - n_test < n_classes:
        raise ValueError("Need at least two independently labelled links per class so every class appears in both train and test sets.")
    train_ids, test_ids = train_test_split(
        link_labels["link_id"].values, test_size=n_test, random_state=41,
        stratify=link_labels[label_col].values,
    )
    return frame[frame.link_id.isin(train_ids)], frame[frame.link_id.isin(test_ids)]


def train_from_live(records: list[dict]) -> dict:
    feat_df, hazard_df, eligible = build_live_training_frames(records)
    outcomes = {r["link_id"]: r["failure_class"] for r in records}
    seen_sources = {sample.get("source", "hardware") for record in records for sample in record.get("readings", [])}
    demo_sources = {"demo_seed", "simulator_demo"}
    field_sources = {"hardware", "manual"}
    if seen_sources and seen_sources.issubset(demo_sources):
        training_source = "demo_labelled_data"
    elif seen_sources and seen_sources.issubset({"hardware"}):
        training_source = "hardware_labelled_data"
    elif seen_sources and seen_sources.issubset(field_sources):
        training_source = "ingested_labelled_data"
    elif seen_sources & demo_sources and seen_sources & field_sources:
        training_source = "mixed_demo_and_ingested_data"
    else:
        training_source = "ingested_labelled_data"
    result = {
        "eligible_links": len(eligible), "feature_rows": int(len(feat_df)),
        "training_source": training_source,
        "input_sources": sorted(seen_sources),
        "tracks": {}, "trained_models": {},
    }

    # Track A: classifier, evaluated on independent links (never split rows
    # from the same fiber route across train and test).
    if not feat_df.empty:
        try:
            train, test = _group_split(feat_df, "failure_class")
            if train["failure_class"].nunique() < 2:
                raise ValueError("Training split does not contain at least two fault classes.")
            clf = RandomForestClassifier(n_estimators=180, max_depth=12,
                                         min_samples_leaf=4, random_state=41, n_jobs=-1)
            clf.fit(train[FEATURE_COLUMNS], train["failure_class"])
            pred = clf.predict(test[FEATURE_COLUMNS])
            result["trained_models"]["A"] = clf
            result["tracks"]["A"] = {
                "status": "trained", "model": "RandomForestClassifier",
                "macro_f1": round(float(f1_score(test["failure_class"], pred, average="macro")), 4),
                "train_links": int(train.link_id.nunique()), "test_links": int(test.link_id.nunique()),
                "n_train": int(len(train)), "n_test": int(len(test)),
                "classes": sorted(feat_df.failure_class.unique().tolist()),
                "evaluation": "link-held-out; generated and field records are not mixed unless explicitly imported",
            }
        except Exception as exc:
            result["tracks"]["A"] = {"status": "waiting_for_data", "reason": str(exc)}
    else:
        result["tracks"]["A"] = {"status": "waiting_for_data", "reason": "No labelled links with at least 11 daily observations."}

    # Track B: only confirmed gradual soft-failure events have a meaningful
    # remaining-life target. Right-censored links are intentionally excluded.
    soft = feat_df[feat_df["failure_class"].isin(SOFT_CLASSES) & feat_df["ttf_days"].notna()].copy() if not feat_df.empty else pd.DataFrame()
    soft_link_count = int(soft.link_id.nunique()) if not soft.empty else 0
    if soft_link_count >= 5:
        try:
            link_ids = soft.link_id.drop_duplicates().values
            train_ids, test_ids = train_test_split(link_ids, test_size=0.25, random_state=41)
            train, test = soft[soft.link_id.isin(train_ids)], soft[soft.link_id.isin(test_ids)]
            reg = RandomForestRegressor(n_estimators=180, max_depth=12,
                                        min_samples_leaf=4, random_state=41, n_jobs=-1)
            reg.fit(train[FEATURE_COLUMNS], train["ttf_days"])
            mae = mean_absolute_error(test["ttf_days"], reg.predict(test[FEATURE_COLUMNS]))
            result["trained_models"]["B"] = reg
            result["tracks"]["B"] = {
                "status": "trained", "model": "RandomForestRegressor",
                "mae_days_soft_only": round(float(mae), 2),
                "train_links": int(train.link_id.nunique()), "test_links": int(test.link_id.nunique()),
                "target": "days until confirmed soft-failure event",
            }
        except Exception as exc:
            result["tracks"]["B"] = {"status": "waiting_for_data", "reason": str(exc)}
    else:
        result["tracks"]["B"] = {"status": "waiting_for_data",
            "reason": f"Need at least 5 independent, confirmed soft-failure links with 11+ daily observations; currently {soft_link_count}."}

    # Track C: right-censored survival analysis. Fit requires both event and
    # non-event cohorts; report concordance as in-sample fit diagnostic only.
    hard_events = int(hazard_df["event"].sum()) if not hazard_df.empty else 0
    censored = int((~hazard_df["event"]).sum()) if not hazard_df.empty else 0
    if hard_events >= 5 and censored >= 5:
        try:
            cph = CoxPHFitter(penalizer=0.1)
            cph.fit(hazard_df.drop(columns=["link_id"]), duration_col="duration", event_col="event",
                    formula="avg_temp + avg_humidity + avg_precip + avg_wind")
            result["trained_models"]["C"] = cph
            ratios = np.exp(cph.params_).to_dict()
            ci = np.exp(cph.confidence_intervals_)
            result["tracks"]["C"] = {
                "status": "trained", "model": "CoxPHFitter",
                "concordance_index": round(float(cph.concordance_index_), 4),
                "concordance_index_fit": round(float(cph.concordance_index_), 4),
                "n_links": int(len(hazard_df)), "n_events": hard_events,
                "hard_cut_events": hard_events, "censored_links": censored,
                "hazard_ratios": {k: round(float(v), 3) for k, v in ratios.items()},
                "hazard_ratio_95ci": {k: [round(float(ci.loc[k].iloc[0]), 3), round(float(ci.loc[k].iloc[1]), 3)] for k in cph.params_.index},
                "evaluation": "in-sample fit diagnostic; not an independent validation score",
            }
        except Exception as exc:
            result["tracks"]["C"] = {"status": "waiting_for_data", "reason": str(exc)}
    else:
        result["tracks"]["C"] = {"status": "waiting_for_data",
            "reason": f"Need at least 5 confirmed hard-cut events and 5 censored links; currently {hard_events} and {censored}."}

    result["outcome_class_counts"] = {key: sum(1 for value in outcomes.values() if value == key)
                                      for key in sorted(set(outcomes.values()))}
    return result
