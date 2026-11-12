"""
features.py — Physics-inspired feature engineering.

Implements the feature set validated as the empirically dominant predictor
set for time-to-failure regression (10-lag window, velocity, acceleration,
rolling mean/std) plus environmental and reliability features layered on
top, per the fusion requirement of this project.
"""
from __future__ import annotations
import numpy as np
import pandas as pd

LAG_WINDOW = 10
ROLL_WINDOW = 5

FEATURE_COLUMNS = (
    [f"osnr_lag_{i}" for i in range(1, LAG_WINDOW + 1)]
    + ["osnr_now", "osnr_velocity", "osnr_acceleration", "osnr_roll_mean", "osnr_roll_std",
       "laser_current_ma", "laser_current_velocity",
       "temp_c", "humidity_pct", "precip_7d_sum", "wind_kmh",
       "link_age_days"]
)


def build_features(link_df: pd.DataFrame) -> pd.DataFrame:
    """Given one link's raw daily telemetry (as produced by simulator.py),
    return a per-day feature matrix aligned 1:1 with the input rows.
    Rows before LAG_WINDOW history is available are dropped (consistent
    with the validated methodology: a model should not predict on an
    incomplete history window)."""
    df = link_df.sort_values("day").reset_index(drop=True)
    osnr = df["osnr_db"]

    feat = pd.DataFrame(index=df.index)
    for i in range(1, LAG_WINDOW + 1):
        feat[f"osnr_lag_{i}"] = osnr.shift(i)
    feat["osnr_now"] = osnr
    feat["osnr_velocity"] = osnr.diff()
    feat["osnr_acceleration"] = feat["osnr_velocity"].diff()
    feat["osnr_roll_mean"] = osnr.rolling(ROLL_WINDOW).mean()
    feat["osnr_roll_std"] = osnr.rolling(ROLL_WINDOW).std()

    feat["laser_current_ma"] = df["laser_current_ma"]
    feat["laser_current_velocity"] = df["laser_current_ma"].diff()

    feat["temp_c"] = df["temp_c"]
    feat["humidity_pct"] = df["humidity_pct"]
    feat["precip_7d_sum"] = df["precip_mm"].rolling(7, min_periods=1).sum()
    feat["wind_kmh"] = df["wind_kmh"]

    feat["link_age_days"] = df["day"]
    feat["link_id"] = df["link_id"]
    feat["day"] = df["day"]

    return feat.iloc[LAG_WINDOW:].reset_index(drop=True)


def build_dataset_features(link_results) -> pd.DataFrame:
    """Build features across all links and attach labels:
    - failure_class: classification target
    - ttf_days: censored time-to-failure regression target (NaN if censored
      or if the link's failure is a hard_cut, which is deliberately excluded
      from TTF training — see models.py)
    """
    rows = []
    for link in link_results:
        f = build_features(link.df)
        if f.empty:
            continue
        f["failure_class"] = link.failure_class
        if link.failure_day is not None:
            f["ttf_days"] = (link.failure_day - f["day"]).clip(lower=0)
        else:
            f["ttf_days"] = np.nan
        f["censored"] = link.censored
        rows.append(f)
    return pd.concat(rows, ignore_index=True) if rows else pd.DataFrame(columns=FEATURE_COLUMNS)
