"""
models.py — Track A/B/C model training and inference.

Track A: fault-type classifier (Random Forest).
Track B: soft-failure time-to-failure regressor (Random Forest) — trained
         only on soft-failure trajectories (edfa/nli/ecl). Hard-cut rows are
         deliberately excluded, and a comparison metric is kept so the app
         can show *why*: including them makes the model dramatically worse,
         which is the empirical demonstration of the hard-vs-soft distinction.
Track C: hard-failure hazard scorer (Cox Proportional Hazards via lifelines)
         on link-level aggregates with environmental covariates.
"""
from __future__ import annotations
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier, RandomForestRegressor
from sklearn.model_selection import GroupShuffleSplit
from sklearn.metrics import mean_absolute_error, f1_score
from lifelines import CoxPHFitter

from .features import FEATURE_COLUMNS

SOFT_CLASSES = ("edfa", "nli", "ecl")


def _trajectory_split(df: pd.DataFrame, test_size=0.25, seed=13):
    """Trajectory-level split (by link_id), never sample-level — matches the
    leakage-safe methodology used throughout the source documents."""
    gss = GroupShuffleSplit(n_splits=1, test_size=test_size, random_state=seed)
    train_idx, test_idx = next(gss.split(df, groups=df["link_id"]))
    return df.iloc[train_idx], df.iloc[test_idx]


def train_track_a(feat_df: pd.DataFrame):
    train, test = _trajectory_split(feat_df)
    X_train, y_train = train[FEATURE_COLUMNS], train["failure_class"]
    X_test, y_test = test[FEATURE_COLUMNS], test["failure_class"]
    clf = RandomForestClassifier(n_estimators=150, max_depth=12, min_samples_leaf=4,
                                  random_state=13, n_jobs=-1)
    clf.fit(X_train, y_train)
    preds = clf.predict(X_test)
    metrics = {
        "macro_f1": round(float(f1_score(y_test, preds, average="macro")), 4),
        "n_train": int(len(X_train)), "n_test": int(len(X_test)),
        "classes": sorted(feat_df["failure_class"].unique().tolist()),
    }
    importances = dict(sorted(zip(FEATURE_COLUMNS, clf.feature_importances_.tolist()),
                               key=lambda kv: -kv[1])[:8])
    return clf, metrics, importances


def train_track_b(feat_df: pd.DataFrame):
    soft = feat_df[feat_df["failure_class"].isin(SOFT_CLASSES) & feat_df["ttf_days"].notna()]
    train, test = _trajectory_split(soft)
    X_train, y_train = train[FEATURE_COLUMNS], train["ttf_days"]
    X_test, y_test = test[FEATURE_COLUMNS], test["ttf_days"]
    reg = RandomForestRegressor(n_estimators=150, max_depth=12, min_samples_leaf=4,
                                 random_state=13, n_jobs=-1)
    reg.fit(X_train, y_train)
    preds = reg.predict(X_test)
    mae_soft = float(mean_absolute_error(y_test, preds))

    # Comparison run: what happens if hard-cuts are included (naively), to
    # make the hard-vs-soft distinction an observed result, not just a claim.
    mixed = feat_df[feat_df["ttf_days"].notna()]
    mtrain, mtest = _trajectory_split(mixed)
    reg_mixed = RandomForestRegressor(n_estimators=150, max_depth=12, min_samples_leaf=4,
                                       random_state=13, n_jobs=-1)
    reg_mixed.fit(mtrain[FEATURE_COLUMNS], mtrain["ttf_days"])
    mae_mixed = float(mean_absolute_error(mtest["ttf_days"], reg_mixed.predict(mtest[FEATURE_COLUMNS])))

    metrics = {
        "mae_days_soft_only": round(mae_soft, 2),
        "mae_days_with_hard_cuts": round(mae_mixed, 2),
        "degradation_factor": round(mae_mixed / max(mae_soft, 0.01), 2),
        "n_train": int(len(X_train)), "n_test": int(len(X_test)),
    }
    importances = dict(sorted(zip(FEATURE_COLUMNS, reg.feature_importances_.tolist()),
                               key=lambda kv: -kv[1])[:8])
    return reg, metrics, importances


def build_hazard_table(link_results) -> pd.DataFrame:
    rows = []
    for link in link_results:
        df = link.df
        rows.append({
            "link_id": link.link_id,
            "duration": float(len(df)),
            "event": link.failure_class == "hard_cut",
            "avg_temp": float(df["temp_c"].mean()),
            "avg_humidity": float(df["humidity_pct"].mean()),
            "avg_precip": float(df["precip_mm"].mean()),
            "avg_wind": float(df["wind_kmh"].mean()),
        })
    return pd.DataFrame(rows)


def train_track_c(hazard_df: pd.DataFrame):
    cph = CoxPHFitter(penalizer=0.1)
    cph.fit(hazard_df, duration_col="duration", event_col="event",
            formula="avg_temp + avg_humidity + avg_precip + avg_wind")
    hazard_ratios = {k: round(float(v), 3) for k, v in np.exp(cph.params_).to_dict().items()}
    ci = np.exp(cph.confidence_intervals_)
    hazard_ci = {k: [round(float(ci.loc[k].iloc[0]), 3), round(float(ci.loc[k].iloc[1]), 3)]
                 for k in cph.params_.index}
    metrics = {
        "concordance_index": round(float(cph.concordance_index_), 4),
        "n_links": int(len(hazard_df)),
        "n_events": int(hazard_df["event"].sum()),
        "hazard_ratios": hazard_ratios,
        "hazard_ratio_95ci": hazard_ci,
    }
    return cph, metrics


def score_hazard(cph: CoxPHFitter, hazard_df: pd.DataFrame) -> pd.Series:
    """Per-link relative hazard score (higher = riskier), scaled 0-100 for
    UI display."""
    partial_hazard = cph.predict_partial_hazard(hazard_df)
    ranks = partial_hazard.rank(pct=True) * 100
    return pd.Series(ranks.values, index=hazard_df["link_id"].values)
