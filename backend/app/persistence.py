"""
persistence.py — Persistence-filter alerting.

Only raises an alarm after k consecutive sub-threshold readings, which cuts
false-alarm rate substantially at the cost of a small, bounded delay (the
validated pattern from the reference architecture).
"""
from __future__ import annotations
import numpy as np

DEFAULT_K = 3
TTF_WATCH_DAYS = 45     # below this predicted TTF -> "watch"
TTF_ALERT_DAYS = 14     # below this predicted TTF -> "alert"
HAZARD_WATCH_PCT = 70   # hazard score percentile -> "watch"
HAZARD_ALERT_PCT = 90   # hazard score percentile -> "alert"


def status_for_link(predicted_ttf: float | None, hazard_score: float, recent_breach_count: int,
                     k: int = DEFAULT_K) -> str:
    """Combine the soft-failure TTF signal and the hard-failure hazard signal
    into one status. The persistence filter (recent_breach_count >= k) gates
    whether a soft-failure signal is allowed to escalate to 'alert'."""
    soft_alert = predicted_ttf is not None and predicted_ttf <= TTF_ALERT_DAYS
    soft_watch = predicted_ttf is not None and predicted_ttf <= TTF_WATCH_DAYS
    hard_alert = hazard_score >= HAZARD_ALERT_PCT
    hard_watch = hazard_score >= HAZARD_WATCH_PCT

    if (soft_alert and recent_breach_count >= k) or hard_alert:
        return "alert"
    if soft_watch or hard_watch:
        return "watch"
    return "normal"


def breach_run_length(osnr_series, threshold: float = 18.0) -> int:
    """Length of the current consecutive run of sub-threshold OSNR readings,
    counting back from the most recent sample."""
    count = 0
    for v in reversed(list(osnr_series)):
        if v <= threshold:
            count += 1
        else:
            break
    return count
