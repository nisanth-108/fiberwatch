"""Persistent store for timestamped Live-Link telemetry and confirmed outcomes.

The API accepts real device readings through POST /api/live/telemetry. A source
field distinguishes hardware, manual, and generated demo measurements.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any
from datetime import datetime, timezone

DB_PATH = Path(__file__).resolve().parent / "data" / "live_telemetry.sqlite3"


def _connect():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=20)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    with _connect() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS live_links (
            link_id TEXT PRIMARY KEY,
            route_name TEXT NOT NULL DEFAULT 'Unspecified route',
            lat REAL,
            lon REAL,
            created_at TEXT NOT NULL,
            last_seen TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS telemetry (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            link_id TEXT NOT NULL REFERENCES live_links(link_id) ON DELETE CASCADE,
            observed_at TEXT NOT NULL,
            osnr_db REAL NOT NULL,
            laser_current_ma REAL,
            ber REAL,
            rx_power_dbm REAL,
            temp_c REAL,
            humidity_pct REAL,
            precip_mm REAL NOT NULL DEFAULT 0,
            wind_kmh REAL NOT NULL DEFAULT 0,
            source TEXT NOT NULL DEFAULT 'hardware'
        );
        CREATE INDEX IF NOT EXISTS idx_telemetry_link_time
            ON telemetry(link_id, observed_at);
        CREATE TABLE IF NOT EXISTS outcomes (
            link_id TEXT PRIMARY KEY REFERENCES live_links(link_id) ON DELETE CASCADE,
            failure_class TEXT NOT NULL,
            outcome_status TEXT NOT NULL CHECK(outcome_status IN ('resolved', 'censored')),
            outcome_at TEXT,
            notes TEXT,
            labelled_at TEXT NOT NULL
        );
        """)


def save_reading(data: dict[str, Any]) -> dict[str, Any]:
    now = datetime.now(timezone.utc).isoformat()
    observed = data.get("observed_at") or now
    with _connect() as conn:
        conn.execute("""
            INSERT INTO live_links(link_id, route_name, lat, lon, created_at, last_seen)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(link_id) DO UPDATE SET
                route_name=CASE WHEN excluded.route_name != 'Unspecified route' THEN excluded.route_name ELSE live_links.route_name END,
                lat=COALESCE(excluded.lat, live_links.lat),
                lon=COALESCE(excluded.lon, live_links.lon),
                last_seen=excluded.last_seen
        """, (data["link_id"], data.get("route_name") or "Unspecified route",
              data.get("lat"), data.get("lon"), now, observed))
        cur = conn.execute("""
            INSERT INTO telemetry(link_id, observed_at, osnr_db, laser_current_ma, ber,
                rx_power_dbm, temp_c, humidity_pct, precip_mm, wind_kmh, source)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (data["link_id"], observed, data["osnr_db"], data.get("laser_current_ma"),
              data.get("ber"), data.get("rx_power_dbm"), data.get("temp_c"),
              data.get("humidity_pct"), data.get("precip_mm", 0), data.get("wind_kmh", 0),
              data.get("source", "hardware")))
        return {"id": cur.lastrowid, "link_id": data["link_id"], "observed_at": observed}


def upsert_link(link_id: str, route_name: str, lat: float | None, lon: float | None):
    now = datetime.now(timezone.utc).isoformat()
    with _connect() as conn:
        conn.execute("""
        INSERT INTO live_links(link_id, route_name, lat, lon, created_at, last_seen)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(link_id) DO UPDATE SET route_name=excluded.route_name,
            lat=COALESCE(excluded.lat, live_links.lat), lon=COALESCE(excluded.lon, live_links.lon)
        """, (link_id, route_name, lat, lon, now, now))


def save_outcome(link_id: str, failure_class: str, outcome_status: str,
                 outcome_at: str | None, notes: str | None = None):
    now = datetime.now(timezone.utc).isoformat()
    with _connect() as conn:
        exists = conn.execute("SELECT 1 FROM live_links WHERE link_id=?", (link_id,)).fetchone()
        if not exists:
            raise KeyError(link_id)
        conn.execute("""
        INSERT INTO outcomes(link_id, failure_class, outcome_status, outcome_at, notes, labelled_at)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(link_id) DO UPDATE SET failure_class=excluded.failure_class,
            outcome_status=excluded.outcome_status, outcome_at=excluded.outcome_at,
            notes=excluded.notes, labelled_at=excluded.labelled_at
        """, (link_id, failure_class, outcome_status, outcome_at, notes, now))


def list_links() -> list[dict[str, Any]]:
    with _connect() as conn:
        rows = conn.execute("""
        SELECT l.link_id, l.route_name, l.lat, l.lon, l.created_at, l.last_seen,
               COUNT(t.id) AS sample_count,
               MAX(t.observed_at) AS latest_at,
               o.failure_class, o.outcome_status, o.outcome_at,
               (SELECT t2.osnr_db FROM telemetry t2 WHERE t2.link_id=l.link_id
                 ORDER BY t2.observed_at DESC, t2.id DESC LIMIT 1) AS osnr_db,
               (SELECT t2.laser_current_ma FROM telemetry t2 WHERE t2.link_id=l.link_id
                 ORDER BY t2.observed_at DESC, t2.id DESC LIMIT 1) AS laser_current_ma,
               (SELECT t2.ber FROM telemetry t2 WHERE t2.link_id=l.link_id
                 ORDER BY t2.observed_at DESC, t2.id DESC LIMIT 1) AS ber,
               (SELECT t2.rx_power_dbm FROM telemetry t2 WHERE t2.link_id=l.link_id
                 ORDER BY t2.observed_at DESC, t2.id DESC LIMIT 1) AS rx_power_dbm,
               (SELECT t2.temp_c FROM telemetry t2 WHERE t2.link_id=l.link_id
                 ORDER BY t2.observed_at DESC, t2.id DESC LIMIT 1) AS temp_c,
               (SELECT t2.source FROM telemetry t2 WHERE t2.link_id=l.link_id
                 ORDER BY t2.observed_at DESC, t2.id DESC LIMIT 1) AS source
        FROM live_links l LEFT JOIN telemetry t ON t.link_id=l.link_id
        LEFT JOIN outcomes o ON o.link_id=l.link_id
        GROUP BY l.link_id ORDER BY latest_at DESC
        """).fetchall()
        return [dict(r) for r in rows]


def get_readings(link_id: str) -> list[dict[str, Any]]:
    with _connect() as conn:
        rows = conn.execute("""
        SELECT observed_at, osnr_db, laser_current_ma, ber, rx_power_dbm,
               temp_c, humidity_pct, precip_mm, wind_kmh, source
        FROM telemetry WHERE link_id=? ORDER BY observed_at, id
        """, (link_id,)).fetchall()
        return [dict(r) for r in rows]


def training_counts() -> dict[str, Any]:
    with _connect() as conn:
        totals = conn.execute("""
        SELECT COUNT(DISTINCT l.link_id) AS links, COUNT(t.id) AS samples,
               COUNT(DISTINCT CASE WHEN o.outcome_status='resolved' THEN l.link_id END) AS resolved,
               COUNT(DISTINCT CASE WHEN o.outcome_status='censored' THEN l.link_id END) AS censored
        FROM live_links l LEFT JOIN telemetry t ON t.link_id=l.link_id
        LEFT JOIN outcomes o ON o.link_id=l.link_id
        """).fetchone()
        classes = conn.execute("""
        SELECT o.failure_class, COUNT(*) AS links FROM outcomes o GROUP BY o.failure_class
        """).fetchall()
        sources = conn.execute("SELECT source, COUNT(*) AS samples FROM telemetry GROUP BY source").fetchall()
        labelled_links = conn.execute("SELECT COUNT(*) FROM outcomes").fetchone()[0]
    return {
        "links": int(totals["links"] or 0), "samples": int(totals["samples"] or 0),
        "resolved_links": int(totals["resolved"] or 0), "censored_links": int(totals["censored"] or 0),
        "labelled_links": int(labelled_links or 0),
        "class_counts": {r["failure_class"]: int(r["links"]) for r in classes},
        "source_counts": {r["source"]: int(r["samples"]) for r in sources},
    }


def get_training_records() -> list[dict[str, Any]]:
    with _connect() as conn:
        links = conn.execute("""
        SELECT l.link_id, l.route_name, l.lat, l.lon, o.failure_class,
               o.outcome_status, o.outcome_at
        FROM live_links l JOIN outcomes o ON o.link_id=l.link_id
        """).fetchall()
    result = []
    for link in links:
        row = dict(link)
        row["readings"] = get_readings(row["link_id"])
        result.append(row)
    return result


def clear_demo_source():
    with _connect() as conn:
        ids = [r[0] for r in conn.execute(
            "SELECT DISTINCT link_id FROM telemetry WHERE source='demo_seed'").fetchall()]
        for link_id in ids:
            conn.execute("DELETE FROM live_links WHERE link_id=?", (link_id,))


def import_demo_link(link_id: str, route_name: str, lat: float, lon: float,
                     readings: list[dict[str, Any]], failure_class: str,
                     outcome_status: str, outcome_at: str | None):
    upsert_link(link_id, route_name, lat, lon)
    with _connect() as conn:
        conn.execute("DELETE FROM telemetry WHERE link_id=?", (link_id,))
        conn.execute("DELETE FROM outcomes WHERE link_id=?", (link_id,))
        conn.executemany("""
        INSERT INTO telemetry(link_id, observed_at, osnr_db, laser_current_ma, ber,
            rx_power_dbm, temp_c, humidity_pct, precip_mm, wind_kmh, source)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'demo_seed')
        """, [(link_id, r["observed_at"], r["osnr_db"], r["laser_current_ma"], r["ber"],
               r["rx_power_dbm"], r["temp_c"], r["humidity_pct"], r["precip_mm"], r["wind_kmh"])
              for r in readings])
    save_outcome(link_id, failure_class, outcome_status, outcome_at,
                 "Generated demo outcome label; not a field maintenance record.")
