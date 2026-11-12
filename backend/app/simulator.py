"""
simulator.py — Physics-informed synthetic fiber-link telemetry generator.

Combines:
- The five-process degradation taxonomy (Ornstein-Uhlenbeck amplifier drift,
  exponential EDFA decay, Weibull connector wear-out, step hard-cuts,
  damped-oscillatory instability) from the v2.0 Execution Blueprint.
- The weather-driven attenuation model with a graceful synthetic fallback
  when the live API is unreachable, from the v1.0 AI Execution Blueprint.
- The simpler calibration-table defaults from the original Project Spec.

Each link is one (near-real-world) fiber route between two points on a real
corridor, so the environmental fusion has a genuine geography behind it.
"""
from __future__ import annotations
import numpy as np
import pandas as pd
import requests
from dataclasses import dataclass, field
from datetime import datetime, timedelta

OSNR_START = 24.0          # dB, healthy coherent-link starting OSNR
OSNR_SOFT_ALARM = 18.0     # dB, ITU-T G.709-referenced soft-failure alarm threshold
OSNR_HARD_FAIL = 15.0      # dB, hard-failure threshold
LASER_CURRENT_START = 65.0  # mA, nominal external-cavity-laser bias current

# A real-world corridor so the environmental join has genuine geography.
# (Guntur -> Vijayawada -> Visakhapatnam, NH16 corridor, Andhra Pradesh)
ROUTE_WAYPOINTS = [
    (16.3067, 80.4365, "Guntur"),
    (16.5062, 80.6480, "Vijayawada"),
    (17.0005, 81.7799, "Eluru"),
    (17.6868, 83.2185, "Visakhapatnam"),
]

FAILURE_CLASSES = ["none", "edfa", "nli", "ecl", "hard_cut"]


def _route_for_link(rng: np.random.Generator) -> tuple[float, float, str]:
    i = rng.integers(0, len(ROUTE_WAYPOINTS) - 1)
    (lat1, lon1, n1), (lat2, lon2, n2) = ROUTE_WAYPOINTS[i], ROUTE_WAYPOINTS[i + 1]
    t = rng.uniform(0, 1)
    return lat1 + t * (lat2 - lat1), lon1 + t * (lon2 - lon1), f"{n1}\u2013{n2} span {rng.integers(1, 9)}"


def fetch_weather(lat: float, lon: float, start_date: str, end_date: str) -> pd.DataFrame:
    """Pull real daily temperature/humidity/precip from Open-Meteo.
    Falls back to a synthetic seasonal series if the API is unreachable
    (e.g. sandboxed environments without open egress) — same defensive
    pattern as the earlier blueprint's fetch_weather()."""
    url = "https://archive-api.open-meteo.com/v1/archive"
    params = dict(
        latitude=lat, longitude=lon, start_date=start_date, end_date=end_date,
        timezone="auto",
        daily="temperature_2m_mean,relative_humidity_2m_mean,precipitation_sum,wind_speed_10m_max",
    )
    try:
        r = requests.get(url, params=params, timeout=6)
        r.raise_for_status()
        d = r.json()["daily"]
        return pd.DataFrame({
            "date": pd.to_datetime(d["time"]),
            "temp": d["temperature_2m_mean"],
            "humidity": d["relative_humidity_2m_mean"],
            "precip": d["precipitation_sum"],
            "wind": d["wind_speed_10m_max"],
        })
    except Exception:
        days = pd.date_range(start_date, end_date, freq="D")
        t = np.arange(len(days))
        rng = np.random.default_rng(int(lat * 1000 + lon * 1000))
        temp = 28 + 6 * np.sin(2 * np.pi * (t - 100) / 365) + rng.normal(0, 1.6, len(t))
        hum = 62 + 18 * np.sin(2 * np.pi * (t - 160) / 365) + rng.normal(0, 4, len(t))
        precip = np.clip(6 * np.sin(2 * np.pi * (t - 160) / 365) + rng.normal(0, 3, len(t)), 0, None) ** 1.3
        wind = 12 + 5 * np.abs(np.sin(2 * np.pi * t / 365)) + rng.normal(0, 2, len(t))
        return pd.DataFrame({"date": days, "temp": temp, "humidity": hum,
                              "precip": precip, "wind": np.clip(wind, 0, None)})


@dataclass
class LinkResult:
    link_id: str
    route_name: str
    lat: float
    lon: float
    df: pd.DataFrame
    failure_class: str
    failure_day: int | None
    censored: bool


def _simulate_one(link_id: str, weather: pd.DataFrame, rng: np.random.Generator) -> LinkResult:
    n = len(weather)
    lat, lon, route_name = _route_for_link(rng)
    temp_ref = weather["temp"].mean()

    osnr = np.full(n, OSNR_START, dtype=float)
    laser_current = np.full(n, LASER_CURRENT_START, dtype=float)

    # Pick a degradation archetype for this link (mirrors the five-process
    # taxonomy; probabilities tuned so most links stay healthy, matching
    # real backbone reliability — over-engineered to fail rarely).
    archetype = rng.choice(
        ["healthy", "edfa_decay", "nli_drift", "ecl_aging", "hard_cut", "connector_wearout"],
        p=[0.49, 0.11, 0.10, 0.10, 0.12, 0.08],
    )

    thermal_stress = 0.010 * (weather["temp"].values - temp_ref)
    humidity_stress = 0.006 * np.clip(weather["humidity"].values - 70, 0, None)
    env_drift = thermal_stress + humidity_stress  # dB/day-ish nudge, environment-coupled

    failure_day = None
    failure_class = "none"

    if archetype == "edfa_decay":
        # Exponential EDFA pump-laser aging, accelerated by heat.
        rate = 0.010 + 0.0025 * max(0.0, (weather["temp"].mean() - temp_ref)) / 5
        decline = 3.98 * (1 - np.exp(-rate * np.arange(n) / 10))
        osnr = OSNR_START - decline - np.cumsum(env_drift) * 0.3
        failure_class = "edfa"
    elif archetype == "nli_drift":
        # Nonlinear-interference drift: accelerating (super-linear) decline.
        t = np.arange(n)
        decline = 5.09 * (t / n) ** 1.8
        osnr = OSNR_START - decline - np.cumsum(env_drift) * 0.3
        failure_class = "nli"
    elif archetype == "ecl_aging":
        # External-cavity-laser aging: near-invisible on OSNR (AGC-compensated)
        # but visible on laser bias current — the key non-obvious variable.
        osnr = OSNR_START - rng.normal(0, 0.15, n).cumsum() * 0.02 - np.cumsum(env_drift) * 0.1
        laser_current = LASER_CURRENT_START + 2.0 * (np.arange(n) / n) ** 1.3 + rng.normal(0, 0.3, n)
        failure_class = "ecl"
    elif archetype == "connector_wearout":
        # Weibull wear-out hazard on a connector/splice.
        shape, scale = 2.2, n * 1.3
        haz = (shape / scale) * (np.arange(1, n + 1) / scale) ** (shape - 1)
        decline = np.cumsum(haz) * 40
        osnr = OSNR_START - decline - np.cumsum(env_drift) * 0.3
        failure_class = "edfa"  # same downstream signature family for modeling purposes
    elif archetype == "hard_cut":
        # Step failure: nominal until the instant of the cut — no telemetry
        # precursor by design. Timing is driven by *environmental* hazard
        # (precipitation/wind, proxying construction and storm-driven
        # excavation risk) rather than picked uniformly, so the link's own
        # signal history stays uninformative while the Cox hazard model
        # (which sees environmental covariates, not telemetry) has genuine
        # signal to recover — this is the hard/soft distinction operating
        # at the data-generating level, not just asserted in prose.
        osnr = OSNR_START - np.cumsum(env_drift) * 0.15 + rng.normal(0, 0.08, n).cumsum() * 0.05
        precip_risk = np.clip(weather["precip"].values, 0, None)
        wind_risk = np.clip(weather["wind"].values - 10, 0, None)
        hazard_rate = 0.5 + 0.20 * precip_risk + 0.06 * wind_risk
        hazard_rate[: min(15, n)] = 0.0  # keep enough pre-event history for features
        hazard_rate = hazard_rate / hazard_rate.sum()
        cut_day = int(rng.choice(np.arange(n), p=hazard_rate))
        osnr[cut_day:] = 2.0
        failure_day = cut_day
        failure_class = "hard_cut"
    else:  # healthy
        osnr = OSNR_START - np.cumsum(env_drift) * 0.08 + rng.normal(0, 0.05, n).cumsum() * 0.03

    osnr = osnr + rng.normal(0, 0.06, n)  # measurement noise
    laser_current = laser_current + rng.normal(0, 0.12, n)

    if failure_class in ("edfa", "nli") and failure_day is None:
        below = np.where(osnr <= OSNR_HARD_FAIL)[0]
        if len(below):
            failure_day = int(below[0])
    if failure_class == "ecl" and failure_day is None:
        # ECL "failure" defined on current drift, not OSNR.
        cur_thresh = LASER_CURRENT_START + 1.9
        above = np.where(laser_current >= cur_thresh)[0]
        if len(above):
            failure_day = int(above[0])

    censored = failure_day is None
    cutoff = (failure_day + 1) if failure_day is not None else n

    ber = np.clip(10 ** (-(osnr[:cutoff] - 6) / 2), 1e-15, 1e-1)
    rx_power = -12 + 0.15 * (osnr[:cutoff] - OSNR_START) + rng.normal(0, 0.1, cutoff)

    df = pd.DataFrame({
        "link_id": link_id,
        "day": np.arange(cutoff),
        "date": weather["date"].values[:cutoff],
        "osnr_db": osnr[:cutoff],
        "laser_current_ma": laser_current[:cutoff],
        "ber": ber,
        "rx_power_dbm": rx_power,
        "temp_c": weather["temp"].values[:cutoff],
        "humidity_pct": weather["humidity"].values[:cutoff],
        "precip_mm": weather["precip"].values[:cutoff],
        "wind_kmh": weather["wind"].values[:cutoff],
    })
    return LinkResult(link_id, route_name, lat, lon, df, failure_class, failure_day, censored)


def generate_dataset(n_links: int = 90, days: int = 540, seed: int = 7) -> list[LinkResult]:
    rng = np.random.default_rng(seed)
    end = datetime.utcnow().date()
    start = end - timedelta(days=days)
    # One shared weather pull per rough region avoids n_links separate calls;
    # each link still gets a slightly different point sample for realism.
    weather = fetch_weather(16.7, 81.0, start.isoformat(), end.isoformat())
    results = []
    for i in range(n_links):
        link_rng = np.random.default_rng(seed * 1000 + i)
        w = weather.copy()
        jitter = link_rng.normal(0, 0.6, len(w))
        w["temp"] = w["temp"] + jitter
        results.append(_simulate_one(f"FL-{i:03d}", w, link_rng))
    return results
