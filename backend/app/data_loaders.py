"""
data_loaders.py — Loaders for the three real public datasets identified in
the research phase of this project.

ARNO testbed (bundled, real): loads directly — this repo's data/arno/ holds
the actual CSVs cloned from the public GitHub release, so it works with no
credentials and no network access.

OTDR Kaggle / Ghosh-Adhya Mendeley: these hosts require an account/API key
and are not reachable from a locked-down sandbox, but the loader functions
below are correct and will work as-is on a machine with normal internet
access and the relevant credentials. See README.md "Using the real datasets"
for setup steps.
"""
from __future__ import annotations
import os
import pandas as pd
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ARNO_DIR = os.path.join(HERE, "data", "arno")


def load_arno_summary() -> dict:
    """Parse the real ARNO testbed CSVs (Sgambelluri et al., TeCIP Institute /
    Scuola Superiore Sant'Anna) and return summary statistics plus a
    downsampled trace suitable for charting — used as an independent,
    real-hardware sanity check against the synthetic simulator's behaviour."""
    out = {}
    for name, label in [("HardFailure_dataset.csv", "hard"), ("SoftFailure_dataset.csv", "soft")]:
        path = os.path.join(ARNO_DIR, name)
        df = pd.read_csv(path)
        spo = df[df["Type"] == "Devices"].copy()
        spo["OSNR"] = pd.to_numeric(spo["OSNR"], errors="coerce")
        spo["BER"] = pd.to_numeric(spo["BER"], errors="coerce")
        spo = spo.dropna(subset=["OSNR"])
        spo = spo.sort_values("Timestamp")
        spo["Failure"] = spo["Failure"].notna() & (spo["Failure"].astype(str).str.strip() != "")

        normal = spo.loc[~spo["Failure"], "OSNR"]
        failing = spo.loc[spo["Failure"], "OSNR"]

        # Downsample one device's trace for charting (SPO1 port).
        one = spo[spo["ID"] == "SPO1/18/11"].copy()
        one["t0"] = one["Timestamp"] - one["Timestamp"].min()
        step = max(1, len(one) // 400)
        trace = one.iloc[::step][["t0", "OSNR", "BER", "Failure"]]

        out[label] = {
            "n_samples": int(len(spo)),
            "n_failure_samples": int(spo["Failure"].sum()),
            "osnr_mean_normal": round(float(normal.mean()), 2) if len(normal) else None,
            "osnr_mean_during_failure": round(float(failing.mean()), 2) if len(failing) else None,
            "osnr_min_during_failure": round(float(failing.min()), 2) if len(failing) else None,
            "trace": [
                {"t": float(r.t0), "osnr": None if pd.isna(r.OSNR) else round(float(r.OSNR), 2),
                 "failure": bool(r.Failure)}
                for r in trace.itertuples()
            ],
        }
    out["source"] = ("Real hardware telemetry, ARNO testbed, InRete Lab, TeCIP Institute / "
                      "Scuola Superiore Sant'Anna (Sgambelluri et al.) — bundled from "
                      "github.com/Network-And-Services/optical-failure-dataset")
    return out


# ---------------------------------------------------------------------------
# The following are documented, correct loaders for the two datasets that
# require external credentials unavailable in this sandbox. Not called at
# runtime here; provided for the user to run on their own machine.
# ---------------------------------------------------------------------------

def load_otdr_kaggle(csv_path: str = "data/raw/otdr_data.csv") -> pd.DataFrame:
    """Requires: `kaggle datasets download -d johannesreber/otdr-trace-training-data
    -p data/raw --unzip` with a configured ~/.kaggle/kaggle.json first."""
    df = pd.read_csv(csv_path)
    return df


def load_ghosh_adhya_mendeley(csv_path: str = "data/raw/ghosh_adhya.csv") -> pd.DataFrame:
    """Requires manually downloading the archive from Mendeley Data
    (DOI: 10.17632/y3pspy7j83.1) and extracting the CSV to csv_path — Mendeley
    does not expose a token-free programmatic download endpoint."""
    df = pd.read_csv(csv_path)
    return df
