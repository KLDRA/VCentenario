from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from .config import (
    KEEP_BATCHES,
    KEEP_COLLECTION_RUNS,
    KEEP_SNAPSHOTS_PER_CAMERA,
    KEEP_STATES,
    LOCAL_TIMEZONE,
    PROFILE_EMA_ALPHA,
)
from .learning import build_forecast, ema, local_slot_from_iso
from .models import (
    BridgeState,
    Camera,
    CameraSnapshot,
    DetectorLocation,
    DetectorReading,
    Incident,
    PanelLocation,
    PanelMessage,
)
from .utils import dumps_json, ensure_dir


class Storage:
    def __init__(self, db_path: Path) -> None:
        ensure_dir(db_path.parent)
        self.db_path = db_path

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        return connection

    def init_db(self) -> None:
        with self.connect() as con:
            con.executescript(
                """
                CREATE TABLE IF NOT EXISTS panel_locations (
                    location_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    road TEXT,
                    km REAL,
                    direction TEXT,
                    latitude REAL,
                    longitude REAL,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS panel_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    collected_at TEXT NOT NULL,
                    situation_id TEXT NOT NULL,
                    record_id TEXT NOT NULL,
                    location_id TEXT NOT NULL,
                    road TEXT,
                    km REAL,
                    direction TEXT,
                    pictograms_json TEXT NOT NULL,
                    legends_json TEXT NOT NULL,
                    status TEXT,
                    created_at TEXT
                );

                CREATE TABLE IF NOT EXISTS incidents (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    collected_at TEXT NOT NULL,
                    situation_id TEXT NOT NULL,
                    record_id TEXT NOT NULL,
                    road TEXT,
                    direction TEXT,
                    severity TEXT,
                    validity_status TEXT,
                    start_time TEXT,
                    end_time TEXT,
                    incident_type TEXT,
                    cause_type TEXT,
                    from_km REAL,
                    to_km REAL,
                    latitude REAL,
                    longitude REAL,
                    municipality TEXT,
                    province TEXT
                );

                CREATE TABLE IF NOT EXISTS cameras (
                    camera_id TEXT PRIMARY KEY,
                    road TEXT,
                    km REAL,
                    direction TEXT,
                    latitude REAL,
                    longitude REAL,
                    image_url TEXT NOT NULL,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS detector_locations (
                    detector_id TEXT PRIMARY KEY,
                    road TEXT,
                    km REAL,
                    direction TEXT,
                    latitude REAL,
                    longitude REAL,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS detector_readings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    collected_at TEXT NOT NULL,
                    detector_id TEXT NOT NULL,
                    measured_at TEXT,
                    road TEXT,
                    km REAL,
                    direction TEXT,
                    latitude REAL,
                    longitude REAL,
                    average_speed REAL,
                    vehicle_flow INTEGER,
                    occupancy REAL
                );

                CREATE TABLE IF NOT EXISTS camera_snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    fetched_at TEXT NOT NULL,
                    camera_id TEXT NOT NULL,
                    http_status INTEGER NOT NULL,
                    content_length INTEGER NOT NULL,
                    sha256 TEXT,
                    image_path TEXT,
                    last_modified TEXT,
                    visual_change_score REAL,
                    vehicle_count INTEGER,
                    vehicle_counts_by_direction_json TEXT NOT NULL DEFAULT '{}'
                );

                CREATE TABLE IF NOT EXISTS bridge_state (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    generated_at TEXT NOT NULL,
                    traffic_score REAL NOT NULL,
                    traffic_level TEXT NOT NULL,
                    reversible_probable TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    official INTEGER NOT NULL,
                    evidence_json TEXT NOT NULL,
                    breakdown_json TEXT NOT NULL,
                    forecast_json TEXT NOT NULL DEFAULT '{}',
                    learning_context_json TEXT NOT NULL DEFAULT '{}'
                );

                CREATE TABLE IF NOT EXISTS collection_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    collected_at TEXT NOT NULL,
                    counts_json TEXT NOT NULL,
                    source_status_json TEXT NOT NULL,
                    warnings_json TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS traffic_profiles (
                    weekday INTEGER NOT NULL,
                    hour INTEGER NOT NULL,
                    sample_count INTEGER NOT NULL,
                    ema_score REAL NOT NULL,
                    ema_vehicle_count REAL NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (weekday, hour)
                );

                CREATE INDEX IF NOT EXISTS idx_panel_messages_collected_at
                    ON panel_messages (collected_at DESC);
                CREATE INDEX IF NOT EXISTS idx_incidents_collected_at
                    ON incidents (collected_at DESC);
                CREATE INDEX IF NOT EXISTS idx_camera_snapshots_camera_fetched
                    ON camera_snapshots (camera_id, fetched_at DESC);
                CREATE INDEX IF NOT EXISTS idx_camera_snapshots_fetched_at
                    ON camera_snapshots (fetched_at DESC);
                CREATE INDEX IF NOT EXISTS idx_detector_readings_collected_at
                    ON detector_readings (collected_at DESC);
                CREATE INDEX IF NOT EXISTS idx_bridge_state_generated_at
                    ON bridge_state (generated_at DESC);
                CREATE INDEX IF NOT EXISTS idx_collection_runs_collected_at
                    ON collection_runs (collected_at DESC);
                """
            )
            self._ensure_column(
                con,
                table_name="camera_snapshots",
                column_name="vehicle_counts_by_direction_json",
                column_definition="TEXT NOT NULL DEFAULT '{}'",
            )
            self._ensure_column(
                con,
                table_name="bridge_state",
                column_name="forecast_json",
                column_definition="TEXT NOT NULL DEFAULT '{}'",
            )
            self._ensure_column(
                con,
                table_name="bridge_state",
                column_name="learning_context_json",
                column_definition="TEXT NOT NULL DEFAULT '{}'",
            )

    def upsert_panel_locations(self, locations: Iterable[PanelLocation]) -> None:
        with self.connect() as con:
            con.executemany(
                """
                INSERT INTO panel_locations (location_id, name, road, km, direction, latitude, longitude)
                VALUES (:location_id, :name, :road, :km, :direction, :latitude, :longitude)
                ON CONFLICT(location_id) DO UPDATE SET
                    name=excluded.name,
                    road=excluded.road,
                    km=excluded.km,
                    direction=excluded.direction,
                    latitude=excluded.latitude,
                    longitude=excluded.longitude,
                    updated_at=CURRENT_TIMESTAMP
                """,
                [location.__dict__ for location in locations],
            )

    def insert_panel_messages(self, collected_at: str, messages: Iterable[PanelMessage]) -> None:
        with self.connect() as con:
            con.executemany(
                """
                INSERT INTO panel_messages (
                    collected_at, situation_id, record_id, location_id, road, km, direction,
                    pictograms_json, legends_json, status, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        collected_at,
                        msg.situation_id,
                        msg.record_id,
                        msg.location_id,
                        msg.road,
                        msg.km,
                        msg.direction,
                        dumps_json(msg.pictograms),
                        dumps_json(msg.legends),
                        msg.status,
                        msg.created_at,
                    )
                    for msg in messages
                ],
            )

    def insert_incidents(self, collected_at: str, incidents: Iterable[Incident]) -> None:
        with self.connect() as con:
            con.executemany(
                """
                INSERT INTO incidents (
                    collected_at, situation_id, record_id, road, direction, severity, validity_status,
                    start_time, end_time, incident_type, cause_type, from_km, to_km,
                    latitude, longitude, municipality, province
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        collected_at,
                        incident.situation_id,
                        incident.record_id,
                        incident.road,
                        incident.direction,
                        incident.severity,
                        incident.validity_status,
                        incident.start_time,
                        incident.end_time,
                        incident.incident_type,
                        incident.cause_type,
                        incident.from_km,
                        incident.to_km,
                        incident.latitude,
                        incident.longitude,
                        incident.municipality,
                        incident.province,
                    )
                    for incident in incidents
                ],
            )

    def upsert_cameras(self, cameras: Iterable[Camera]) -> None:
        with self.connect() as con:
            con.executemany(
                """
                INSERT INTO cameras (camera_id, road, km, direction, latitude, longitude, image_url)
                VALUES (:camera_id, :road, :km, :direction, :latitude, :longitude, :image_url)
                ON CONFLICT(camera_id) DO UPDATE SET
                    road=excluded.road,
                    km=excluded.km,
                    direction=excluded.direction,
                    latitude=excluded.latitude,
                    longitude=excluded.longitude,
                    image_url=excluded.image_url,
                    updated_at=CURRENT_TIMESTAMP
                """,
                [camera.__dict__ for camera in cameras],
            )

    def upsert_detector_locations(self, locations: Iterable[DetectorLocation]) -> None:
        with self.connect() as con:
            con.executemany(
                """
                INSERT INTO detector_locations (detector_id, road, km, direction, latitude, longitude)
                VALUES (:detector_id, :road, :km, :direction, :latitude, :longitude)
                ON CONFLICT(detector_id) DO UPDATE SET
                    road=excluded.road,
                    km=excluded.km,
                    direction=excluded.direction,
                    latitude=excluded.latitude,
                    longitude=excluded.longitude,
                    updated_at=CURRENT_TIMESTAMP
                """,
                [location.__dict__ for location in locations],
            )

    def insert_detector_readings(self, collected_at: str, readings: Iterable[DetectorReading]) -> None:
        with self.connect() as con:
            con.executemany(
                """
                INSERT INTO detector_readings (
                    collected_at, detector_id, measured_at, road, km, direction, latitude,
                    longitude, average_speed, vehicle_flow, occupancy
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        collected_at,
                        reading.detector_id,
                        reading.measured_at,
                        reading.road,
                        reading.km,
                        reading.direction,
                        reading.latitude,
                        reading.longitude,
                        reading.average_speed,
                        reading.vehicle_flow,
                        reading.occupancy,
                    )
                    for reading in readings
                ],
            )

    def insert_camera_snapshots(self, snapshots: Iterable[CameraSnapshot]) -> None:
        with self.connect() as con:
            con.executemany(
                """
                INSERT INTO camera_snapshots (
                    fetched_at, camera_id, http_status, content_length, sha256,
                    image_path, last_modified, visual_change_score, vehicle_count,
                    vehicle_counts_by_direction_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        snapshot.fetched_at,
                        snapshot.camera_id,
                        snapshot.http_status,
                        snapshot.content_length,
                        snapshot.sha256,
                        snapshot.image_path,
                        snapshot.last_modified,
                        snapshot.visual_change_score,
                        snapshot.vehicle_count,
                        dumps_json(snapshot.vehicle_counts_by_direction),
                    )
                    for snapshot in snapshots
                ],
            )

    def insert_bridge_state(self, state: BridgeState) -> None:
        with self.connect() as con:
            con.execute(
                """
                INSERT INTO bridge_state (
                    generated_at, traffic_score, traffic_level, reversible_probable,
                    confidence, official, evidence_json, breakdown_json,
                    forecast_json, learning_context_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    state.generated_at,
                    state.traffic_score,
                    state.traffic_level,
                    state.reversible_probable,
                    state.confidence,
                    int(state.official),
                    dumps_json(state.evidence),
                    dumps_json(state.breakdown),
                    dumps_json(state.forecast),
                    dumps_json(state.learning_context),
                ),
            )

    def insert_collection_run(
        self,
        collected_at: str,
        counts: Dict[str, int],
        source_status: Dict[str, Dict[str, Any]],
        warnings: List[str],
    ) -> None:
        with self.connect() as con:
            con.execute(
                """
                INSERT INTO collection_runs (
                    collected_at, counts_json, source_status_json, warnings_json
                )
                VALUES (?, ?, ?, ?)
                """,
                (
                    collected_at,
                    dumps_json(counts),
                    dumps_json(source_status),
                    dumps_json(warnings),
                ),
            )

    def latest_state(self) -> Optional[sqlite3.Row]:
        with self.connect() as con:
            row = con.execute(
                "SELECT * FROM bridge_state ORDER BY generated_at DESC LIMIT 1"
            ).fetchone()
        if row is None:
            return None
        return self._decode_state_row(row)

    def latest_camera_payload(self, camera_id: str) -> Optional[bytes]:
        with self.connect() as con:
            row = con.execute(
                """
                SELECT image_path
                FROM camera_snapshots
                WHERE camera_id = ? AND http_status = 200 AND image_path IS NOT NULL
                ORDER BY fetched_at DESC
                LIMIT 1
                """,
                (camera_id,),
            ).fetchone()
        if not row:
            return None
        image_path = row["image_path"]
        if not image_path:
            return None
        path = Path(image_path)
        if not path.exists():
            return None
        return path.read_bytes()

    def latest_camera_payloads(self, camera_ids: Iterable[str]) -> Dict[str, bytes]:
        camera_ids = list(camera_ids)
        if not camera_ids:
            return {}
        placeholders = ",".join("?" for _ in camera_ids)
        with self.connect() as con:
            rows = con.execute(
                f"""
                SELECT camera_id, image_path
                FROM camera_snapshots
                WHERE http_status = 200
                  AND image_path IS NOT NULL
                  AND camera_id IN ({placeholders})
                ORDER BY camera_id ASC, fetched_at DESC, id DESC
                """,
                camera_ids,
            ).fetchall()
        payloads: Dict[str, bytes] = {}
        for row in rows:
            camera_id = row["camera_id"]
            if camera_id in payloads:
                continue
            image_path = row["image_path"]
            if not image_path:
                continue
            path = Path(image_path)
            if not path.exists():
                continue
            payloads[camera_id] = path.read_bytes()
        return payloads

    def recent_states(self, limit: int = 12) -> List[Dict[str, Any]]:
        with self.connect() as con:
            rows = con.execute(
                """
                SELECT *
                FROM bridge_state
                ORDER BY generated_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        states: List[Dict[str, Any]] = []
        for row in reversed(rows):
            states.append(self._decode_state_row(row))
        return states

    def latest_collection_run(self) -> Optional[Dict[str, Any]]:
        with self.connect() as con:
            row = con.execute(
                """
                SELECT *
                FROM collection_runs
                ORDER BY collected_at DESC, id DESC
                LIMIT 1
                """
            ).fetchone()
        if row is None:
            return None
        data = dict(row)
        data["counts"] = json.loads(data.pop("counts_json"))
        data["source_status"] = json.loads(data.pop("source_status_json"))
        data["warnings"] = json.loads(data.pop("warnings_json"))
        return data

    def latest_panel_messages(self, limit: int = 20) -> List[Dict[str, Any]]:
        with self.connect() as con:
            collected = con.execute(
                "SELECT MAX(collected_at) AS collected_at FROM panel_messages"
            ).fetchone()
            if not collected or not collected["collected_at"]:
                return []
            rows = con.execute(
                """
                SELECT pm.*, pl.name AS location_name, pl.latitude, pl.longitude
                FROM panel_messages pm
                LEFT JOIN panel_locations pl ON pl.location_id = pm.location_id
                WHERE pm.collected_at = ?
                ORDER BY pm.km ASC, pm.location_id ASC, pm.record_id ASC
                LIMIT ?
                """,
                (collected["collected_at"], limit),
            ).fetchall()
        messages: List[Dict[str, Any]] = []
        for row in rows:
            data = dict(row)
            data["pictograms"] = json.loads(data.pop("pictograms_json"))
            data["legends"] = json.loads(data.pop("legends_json"))
            messages.append(data)
        return messages

    def latest_incidents(self, limit: int = 20) -> List[Dict[str, Any]]:
        with self.connect() as con:
            collected = con.execute(
                "SELECT MAX(collected_at) AS collected_at FROM incidents"
            ).fetchone()
            if not collected or not collected["collected_at"]:
                return []
            rows = con.execute(
                """
                SELECT *
                FROM incidents
                WHERE collected_at = ?
                ORDER BY
                    CASE severity
                        WHEN 'highest' THEN 1
                        WHEN 'high' THEN 2
                        WHEN 'medium' THEN 3
                        WHEN 'low' THEN 4
                        ELSE 5
                    END,
                    COALESCE(from_km, to_km) ASC
                LIMIT ?
                """,
                (collected["collected_at"], limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def latest_cameras(self) -> List[Dict[str, Any]]:
        with self.connect() as con:
            rows = con.execute(
                """
                SELECT
                    c.*,
                    s.fetched_at,
                    s.http_status,
                    s.content_length,
                    s.sha256,
                    s.image_path,
                    s.last_modified,
                    s.visual_change_score,
                    s.vehicle_count,
                    s.vehicle_counts_by_direction_json
                FROM cameras c
                LEFT JOIN camera_snapshots s
                    ON s.id = (
                        SELECT cs.id
                        FROM camera_snapshots cs
                        WHERE cs.camera_id = c.camera_id
                        ORDER BY cs.fetched_at DESC
                        LIMIT 1
                    )
                ORDER BY c.km ASC, c.camera_id ASC
                """
            ).fetchall()
        cameras: List[Dict[str, Any]] = []
        for row in rows:
            data = dict(row)
            raw = data.get("vehicle_counts_by_direction_json") or "{}"
            data["vehicle_counts_by_direction"] = json.loads(raw)
            data.pop("vehicle_counts_by_direction_json", None)
            cameras.append(data)
        return cameras

    def latest_detector_readings(self, limit: int = 20) -> List[Dict[str, Any]]:
        with self.connect() as con:
            collected = con.execute(
                "SELECT MAX(collected_at) AS collected_at FROM detector_readings"
            ).fetchone()
            if not collected or not collected["collected_at"]:
                return []
            rows = con.execute(
                """
                SELECT *
                FROM detector_readings
                WHERE collected_at = ?
                ORDER BY km ASC, detector_id ASC
                LIMIT ?
                """,
                (collected["collected_at"], limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def update_traffic_profile(self, state: BridgeState) -> Dict[str, Any]:
        weekday, hour, local_time = local_slot_from_iso(state.generated_at, LOCAL_TIMEZONE)
        vehicle_signal = float(state.breakdown.get("vehicle_count", 0.0))
        with self.connect() as con:
            existing = con.execute(
                """
                SELECT *
                FROM traffic_profiles
                WHERE weekday = ? AND hour = ?
                """,
                (weekday, hour),
            ).fetchone()
            sample_count = int(existing["sample_count"]) + 1 if existing else 1
            ema_score = ema(float(existing["ema_score"]), state.traffic_score, PROFILE_EMA_ALPHA) if existing else state.traffic_score
            ema_vehicle = ema(float(existing["ema_vehicle_count"]), vehicle_signal, PROFILE_EMA_ALPHA) if existing else vehicle_signal
            con.execute(
                """
                INSERT INTO traffic_profiles (weekday, hour, sample_count, ema_score, ema_vehicle_count, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(weekday, hour) DO UPDATE SET
                    sample_count = excluded.sample_count,
                    ema_score = excluded.ema_score,
                    ema_vehicle_count = excluded.ema_vehicle_count,
                    updated_at = excluded.updated_at
                """,
                (weekday, hour, sample_count, ema_score, ema_vehicle, state.generated_at),
            )
        return {
            "slot_weekday": weekday,
            "slot_hour": hour,
            "slot_local_time": local_time,
            "sample_count": sample_count,
            "ema_score": round(ema_score, 2),
            "ema_vehicle_count": round(ema_vehicle, 2),
        }

    def traffic_profiles(self) -> Dict[tuple[int, int], Dict[str, Any]]:
        with self.connect() as con:
            rows = con.execute("SELECT * FROM traffic_profiles").fetchall()
        return {
            (int(row["weekday"]), int(row["hour"])): dict(row)
            for row in rows
        }

    def predict_traffic(
        self,
        reference_time: str,
        current_state: BridgeState,
        recent_states: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        return build_forecast(
            reference_time=reference_time,
            current_score=current_state.traffic_score,
            recent_states=recent_states,
            profiles=self.traffic_profiles(),
            timezone_name=LOCAL_TIMEZONE,
        )

    def prune_history(
        self,
        keep_states: int = KEEP_STATES,
        keep_collection_runs: int = KEEP_COLLECTION_RUNS,
        keep_batches: int = KEEP_BATCHES,
        keep_snapshots_per_camera: int = KEEP_SNAPSHOTS_PER_CAMERA,
    ) -> Dict[str, int]:
        keep_states = max(1, keep_states)
        keep_collection_runs = max(1, keep_collection_runs)
        keep_batches = max(1, keep_batches)
        keep_snapshots_per_camera = max(1, keep_snapshots_per_camera)

        with self.connect() as con:
            stale_snapshot_rows = con.execute(
                """
                SELECT id, image_path
                FROM (
                    SELECT
                        id,
                        image_path,
                        ROW_NUMBER() OVER (
                            PARTITION BY camera_id
                            ORDER BY fetched_at DESC, id DESC
                        ) AS row_num
                    FROM camera_snapshots
                )
                WHERE row_num > ?
                """,
                (keep_snapshots_per_camera,),
            ).fetchall()

            snapshot_ids = [row["id"] for row in stale_snapshot_rows]
            removed_snapshot_files = 0
            if snapshot_ids:
                placeholders = ",".join("?" for _ in snapshot_ids)
                con.execute(
                    f"DELETE FROM camera_snapshots WHERE id IN ({placeholders})",
                    snapshot_ids,
                )
                for row in stale_snapshot_rows:
                    image_path = row["image_path"]
                    if not image_path:
                        continue
                    path = Path(image_path)
                    if path.exists():
                        path.unlink()
                        removed_snapshot_files += 1

            deleted_states = con.execute(
                """
                DELETE FROM bridge_state
                WHERE id NOT IN (
                    SELECT id
                    FROM bridge_state
                    ORDER BY generated_at DESC, id DESC
                    LIMIT ?
                )
                """,
                (keep_states,),
            ).rowcount

            deleted_runs = con.execute(
                """
                DELETE FROM collection_runs
                WHERE id NOT IN (
                    SELECT id
                    FROM collection_runs
                    ORDER BY collected_at DESC, id DESC
                    LIMIT ?
                )
                """,
                (keep_collection_runs,),
            ).rowcount

            deleted_panel_messages = con.execute(
                """
                DELETE FROM panel_messages
                WHERE collected_at NOT IN (
                    SELECT collected_at
                    FROM (
                        SELECT collected_at
                        FROM panel_messages
                        GROUP BY collected_at
                        ORDER BY collected_at DESC
                        LIMIT ?
                    )
                )
                """,
                (keep_batches,),
            ).rowcount

            deleted_detector_readings = con.execute(
                """
                DELETE FROM detector_readings
                WHERE collected_at NOT IN (
                    SELECT collected_at
                    FROM (
                        SELECT collected_at
                        FROM detector_readings
                        GROUP BY collected_at
                        ORDER BY collected_at DESC
                        LIMIT ?
                    )
                )
                """,
                (keep_batches,),
            ).rowcount

            deleted_incidents = con.execute(
                """
                DELETE FROM incidents
                WHERE collected_at NOT IN (
                    SELECT collected_at
                    FROM (
                        SELECT collected_at
                        FROM incidents
                        GROUP BY collected_at
                        ORDER BY collected_at DESC
                        LIMIT ?
                    )
                )
                """,
                (keep_batches,),
            ).rowcount

        return {
            "states_deleted": deleted_states,
            "collection_runs_deleted": deleted_runs,
            "panel_messages_deleted": deleted_panel_messages,
            "detector_readings_deleted": deleted_detector_readings,
            "incidents_deleted": deleted_incidents,
            "snapshots_deleted": len(snapshot_ids),
            "snapshot_files_deleted": removed_snapshot_files,
        }

    def vacuum(self) -> None:
        with self.connect() as con:
            con.execute("VACUUM")

    @staticmethod
    def _ensure_column(
        con: sqlite3.Connection,
        table_name: str,
        column_name: str,
        column_definition: str,
    ) -> None:
        columns = {
            row["name"]
            for row in con.execute(f"PRAGMA table_info({table_name})").fetchall()
        }
        if column_name not in columns:
            con.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_definition}")

    @staticmethod
    def _decode_state_row(row: sqlite3.Row) -> Dict[str, Any]:
        data = dict(row)
        data["official"] = bool(data["official"])
        data["evidence"] = json.loads(data.pop("evidence_json"))
        data["breakdown"] = json.loads(data.pop("breakdown_json"))
        data["forecast"] = json.loads(data.pop("forecast_json", "{}"))
        data["learning_context"] = json.loads(data.pop("learning_context_json", "{}"))
        return data
