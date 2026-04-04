import tempfile
import unittest
from pathlib import Path

from vcentenario.models import BridgeState, CameraSnapshot, Incident, PanelMessage
from vcentenario.storage import Storage


class StorageTests(unittest.TestCase):
    def test_latest_camera_payloads_returns_only_existing_latest_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            snapshots_dir = root / "snapshots"
            snapshots_dir.mkdir()
            latest_path = snapshots_dir / "cam1_latest.jpg"
            latest_path.write_bytes(b"latest")
            old_path = snapshots_dir / "cam1_old.jpg"
            old_path.write_bytes(b"old")

            storage = Storage(root / "test.db")
            storage.init_db()
            storage.insert_camera_snapshots(
                [
                    CameraSnapshot(
                        camera_id="cam1",
                        fetched_at="2026-04-04T08:00:00+00:00",
                        http_status=200,
                        content_length=3,
                        sha256="old",
                        image_path=str(old_path),
                        last_modified=None,
                        visual_change_score=0.2,
                    ),
                    CameraSnapshot(
                        camera_id="cam1",
                        fetched_at="2026-04-04T09:00:00+00:00",
                        http_status=200,
                        content_length=6,
                        sha256="latest",
                        image_path=str(latest_path),
                        last_modified=None,
                        visual_change_score=0.1,
                    ),
                ]
            )

            payloads = storage.latest_camera_payloads(["cam1"])

        self.assertEqual(payloads["cam1"], b"latest")

    def test_prune_history_removes_old_rows_and_snapshot_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            snapshots_dir = root / "snapshots"
            snapshots_dir.mkdir()
            old_snapshot = snapshots_dir / "old.jpg"
            new_snapshot = snapshots_dir / "new.jpg"
            old_snapshot.write_bytes(b"old")
            new_snapshot.write_bytes(b"new")

            storage = Storage(root / "test.db")
            storage.init_db()
            storage.insert_bridge_state(
                BridgeState(
                    generated_at="2026-04-04T08:00:00+00:00",
                    traffic_score=10.0,
                    traffic_level="fluido",
                    reversible_probable="indeterminado",
                    confidence=0.2,
                )
            )
            storage.insert_bridge_state(
                BridgeState(
                    generated_at="2026-04-04T09:00:00+00:00",
                    traffic_score=20.0,
                    traffic_level="denso",
                    reversible_probable="negative",
                    confidence=0.4,
                )
            )
            storage.insert_collection_run(
                "2026-04-04T08:00:00+00:00",
                {"snapshots": 1},
                {"camera_snapshots": {"status": "ok", "count": 1}},
                [],
            )
            storage.insert_collection_run(
                "2026-04-04T09:00:00+00:00",
                {"snapshots": 1},
                {"camera_snapshots": {"status": "ok", "count": 1}},
                [],
            )
            storage.insert_panel_messages(
                "2026-04-04T08:00:00+00:00",
                [
                    PanelMessage(
                        situation_id="s1",
                        record_id="r1",
                        location_id="loc1",
                        road="SE-30",
                        km=14.0,
                        direction="negative",
                        pictograms=[],
                        legends=["RETENCIONES"],
                        status="active",
                        created_at=None,
                    )
                ],
            )
            storage.insert_panel_messages(
                "2026-04-04T09:00:00+00:00",
                [
                    PanelMessage(
                        situation_id="s2",
                        record_id="r2",
                        location_id="loc2",
                        road="SE-30",
                        km=14.2,
                        direction="negative",
                        pictograms=[],
                        legends=["OBRAS"],
                        status="active",
                        created_at=None,
                    )
                ],
            )
            storage.insert_incidents(
                "2026-04-04T08:00:00+00:00",
                [
                    Incident(
                        situation_id="i1",
                        record_id="ri1",
                        road="SE-30",
                        direction="negative",
                        severity="high",
                        validity_status="active",
                        start_time=None,
                        end_time=None,
                        incident_type="laneClosures",
                        cause_type=None,
                        from_km=13.9,
                        to_km=14.1,
                        latitude=None,
                        longitude=None,
                        municipality=None,
                        province=None,
                    )
                ],
            )
            storage.insert_incidents(
                "2026-04-04T09:00:00+00:00",
                [
                    Incident(
                        situation_id="i2",
                        record_id="ri2",
                        road="SE-30",
                        direction="negative",
                        severity="medium",
                        validity_status="active",
                        start_time=None,
                        end_time=None,
                        incident_type="roadworks",
                        cause_type=None,
                        from_km=14.0,
                        to_km=14.3,
                        latitude=None,
                        longitude=None,
                        municipality=None,
                        province=None,
                    )
                ],
            )
            storage.insert_camera_snapshots(
                [
                    CameraSnapshot(
                        camera_id="cam1",
                        fetched_at="2026-04-04T08:00:00+00:00",
                        http_status=200,
                        content_length=3,
                        sha256="old",
                        image_path=str(old_snapshot),
                        last_modified=None,
                        visual_change_score=0.5,
                    ),
                    CameraSnapshot(
                        camera_id="cam1",
                        fetched_at="2026-04-04T09:00:00+00:00",
                        http_status=200,
                        content_length=3,
                        sha256="new",
                        image_path=str(new_snapshot),
                        last_modified=None,
                        visual_change_score=0.3,
                    ),
                ]
            )

            result = storage.prune_history(
                keep_states=1,
                keep_collection_runs=1,
                keep_batches=1,
                keep_snapshots_per_camera=1,
            )

            with storage.connect() as con:
                state_count = con.execute("SELECT COUNT(*) FROM bridge_state").fetchone()[0]
                run_count = con.execute("SELECT COUNT(*) FROM collection_runs").fetchone()[0]
                message_count = con.execute("SELECT COUNT(*) FROM panel_messages").fetchone()[0]
                incident_count = con.execute("SELECT COUNT(*) FROM incidents").fetchone()[0]
                snapshot_count = con.execute("SELECT COUNT(*) FROM camera_snapshots").fetchone()[0]
            self.assertEqual(state_count, 1)
            self.assertEqual(run_count, 1)
            self.assertEqual(message_count, 1)
            self.assertEqual(incident_count, 1)
            self.assertEqual(snapshot_count, 1)
            self.assertEqual(result["snapshots_deleted"], 1)
            self.assertFalse(old_snapshot.exists())
            self.assertTrue(new_snapshot.exists())


if __name__ == "__main__":
    unittest.main()
