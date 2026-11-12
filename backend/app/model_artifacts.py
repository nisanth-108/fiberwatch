"""Persist locally retrained Live-Link model tracks between API restarts."""
from __future__ import annotations
import json
from pathlib import Path
import joblib

ARTIFACT_DIR = Path(__file__).resolve().parent / "data" / "live_models"


def save(store):
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    for track, model in (("A", store.clf), ("B", store.reg), ("C", store.cph)):
        if store.model_sources.get(track) != "simulation_baseline" and model is not None:
            joblib.dump(model, ARTIFACT_DIR / f"track_{track}.joblib")
    metadata = {
        "model_sources": store.model_sources,
        "a_metrics": store.a_metrics, "a_importance": store.a_importance,
        "b_metrics": store.b_metrics, "b_importance": store.b_importance,
        "c_metrics": store.c_metrics,
    }
    (ARTIFACT_DIR / "metadata.json").write_text(json.dumps(metadata, indent=2, default=float), encoding="utf-8")


def load(store):
    metadata_path = ARTIFACT_DIR / "metadata.json"
    if not metadata_path.exists():
        return
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    for track, attr in (("A", "clf"), ("B", "reg"), ("C", "cph")):
        path = ARTIFACT_DIR / f"track_{track}.joblib"
        if metadata.get("model_sources", {}).get(track) != "simulation_baseline" and path.exists():
            setattr(store, attr, joblib.load(path))
    store.model_sources = metadata.get("model_sources", store.model_sources)
    for key in ("a_metrics", "a_importance", "b_metrics", "b_importance", "c_metrics"):
        if metadata.get(key) is not None:
            setattr(store, key, metadata[key])


def clear():
    if not ARTIFACT_DIR.exists():
        return
    for path in ARTIFACT_DIR.glob("track_*.joblib"):
        path.unlink(missing_ok=True)
    (ARTIFACT_DIR / "metadata.json").unlink(missing_ok=True)
