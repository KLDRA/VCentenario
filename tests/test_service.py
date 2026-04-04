import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from vcentenario.models import Incident
from vcentenario.service import VCentenarioService


class _FailingPanelCollector:
    def fetch_inventory(self):
        raise RuntimeError("paneles offline")

    def fetch_active_messages(self, inventory):
        raise AssertionError("No debería llamarse cuando el inventario falla")


class _StaticIncidentCollector:
    def fetch_bridge_incidents(self):
        return [
            Incident(
                situation_id="s1",
                record_id="r1",
                road="SE-30",
                direction="negative",
                severity="high",
                validity_status="active",
                start_time="2026-04-04T08:00:00+02:00",
                end_time=None,
                incident_type="laneClosures",
                cause_type="roadMaintenance",
                from_km=13.9,
                to_km=14.2,
                latitude=37.37,
                longitude=-6.01,
                municipality="Sevilla",
                province="Sevilla",
            )
        ]


class _EmptyCameraCollector:
    def fetch_inventory(self):
        return {}

    def fetch_snapshots(self, cameras, snapshots_dir, previous_payloads=None):
        return []


class _EmptyDetectorCollector:
    def fetch_inventory(self):
        return {}

    def fetch_bridge_measurements(self, inventory):
        return []


class _StaleDetectorCollector:
    def fetch_inventory(self):
        return {"det1": object()}

    def fetch_bridge_measurements(self, inventory):
        stale = datetime.now(timezone.utc) - timedelta(days=400)
        return []


class ServiceTests(unittest.TestCase):
    def test_run_once_tolerates_partial_source_failures(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            service = VCentenarioService(db_path=root / "test.db", snapshots_dir=root / "snapshots")
            service.panel_collector = _FailingPanelCollector()
            service.incident_collector = _StaticIncidentCollector()
            service.camera_collector = _EmptyCameraCollector()
            service.detector_collector = _EmptyDetectorCollector()

            result = service.run_once()
            latest_run = service.storage.latest_collection_run()

        self.assertEqual(result["counts"]["incidents"], 1)
        self.assertEqual(result["source_status"]["panel_inventory"]["status"], "error")
        self.assertEqual(result["source_status"]["panel_messages"]["status"], "skipped")
        self.assertEqual(result["source_status"]["incidents"]["status"], "ok")
        self.assertEqual(result["source_status"]["detector_readings"]["status"], "skipped")
        self.assertEqual(result["state"]["reversible_probable"], "negative")
        self.assertTrue(result["warnings"])
        self.assertIsNotNone(latest_run)
        self.assertEqual(latest_run["source_status"]["panel_inventory"]["status"], "error")


if __name__ == "__main__":
    unittest.main()
