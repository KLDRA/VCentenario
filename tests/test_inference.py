import unittest

from vcentenario.inference import classify_traffic_level, infer_bridge_state
from vcentenario.models import CameraSnapshot, DetectorReading, Incident, PanelMessage


class InferenceTests(unittest.TestCase):
    def test_classify_traffic_level_ranges(self) -> None:
        self.assertEqual(classify_traffic_level(0), "fluido")
        self.assertEqual(classify_traffic_level(20), "denso")
        self.assertEqual(classify_traffic_level(40), "retenciones")
        self.assertEqual(classify_traffic_level(70), "congestion_fuerte")

    def test_infer_bridge_state_prefers_directional_pressure(self) -> None:
        panels = [
            PanelMessage(
                situation_id="1",
                record_id="r1",
                location_id="GUID_PMV_60859",
                road="SE-30",
                km=14.2,
                direction="negative",
                pictograms=["accident"],
                legends=["RETENCIONES EN PUENTE"],
                status="active",
                created_at="2026-04-04T08:00:00+02:00",
            )
        ]
        incidents = [
            Incident(
                situation_id="2",
                record_id="r2",
                road="SE-30",
                direction="negative",
                severity="high",
                validity_status="active",
                start_time="2026-04-04T08:00:00+02:00",
                end_time=None,
                incident_type="laneClosures",
                cause_type="roadMaintenance",
                from_km=13.8,
                to_km=14.3,
                latitude=37.37,
                longitude=-6.014,
                municipality="Sevilla",
                province="Sevilla",
            )
        ]
        snapshots = [
            CameraSnapshot(
                camera_id="1337",
                fetched_at="2026-04-04T08:02:00+02:00",
                http_status=200,
                content_length=70000,
                sha256="abc",
                image_path="/tmp/1337.jpg",
                last_modified=None,
                visual_change_score=0.25,
            )
        ]

        state = infer_bridge_state(panels, incidents, snapshots, recent_states=[])
        self.assertGreater(state.traffic_score, 0)
        self.assertEqual(state.reversible_probable, "negative")
        self.assertGreaterEqual(state.confidence, 0.4)

    def test_infer_bridge_state_uses_detectors_and_persistence(self) -> None:
        detectors = [
            DetectorReading(
                detector_id="GUID_DET_132943",
                measured_at="2026-04-04T08:00:00+02:00",
                road="SE-30",
                km=14.1,
                direction="positive",
                latitude=37.37,
                longitude=-6.013,
                average_speed=28.0,
                vehicle_flow=1800,
                occupancy=34.0,
            )
        ]
        recent_states = [
            {"reversible_probable": "positive", "confidence": 0.62, "breakdown": {"detectors": 20.0}},
            {"reversible_probable": "positive", "confidence": 0.58, "breakdown": {"detectors": 18.0}},
            {"reversible_probable": "negative", "confidence": 0.31, "breakdown": {"detectors": 11.0}},
            {"reversible_probable": "positive", "confidence": 0.61, "breakdown": {"detectors": 22.0}},
            {"reversible_probable": "positive", "confidence": 0.64, "breakdown": {"detectors": 24.0}},
            {"reversible_probable": "positive", "confidence": 0.66, "breakdown": {"detectors": 19.0}},
        ]

        state = infer_bridge_state([], [], [], detectors, recent_states=recent_states)
        self.assertEqual(state.reversible_probable, "positive")
        self.assertIn("detectors", state.breakdown)
        self.assertTrue(any(item.startswith("reversible:persistence:positive") for item in state.evidence))
        self.assertTrue(any(item.startswith("detectors:active:") for item in state.evidence))


if __name__ == "__main__":
    unittest.main()
