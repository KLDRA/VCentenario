import unittest
from datetime import datetime, timedelta, timezone

from vcentenario.collectors.detectors import DetectorCollector
from vcentenario.inference import classify_traffic_level, infer_bridge_state
from vcentenario.models import CameraSnapshot, DetectorReading, Incident, PanelMessage


class InferenceTests(unittest.TestCase):
    def test_detector_collector_discards_stale_measurements(self) -> None:
        collector = DetectorCollector(http=None)
        stale = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
        fresh = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()

        self.assertTrue(collector._is_stale_measurement(stale))
        self.assertFalse(collector._is_stale_measurement(fresh))

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

    def test_persistent_roadworks_and_heavy_vehicle_diversion_are_deweighted(self) -> None:
        panels = [
            PanelMessage(
                situation_id="1",
                record_id="r1",
                location_id="GUID_PMV_166911",
                road="SE-30",
                km=13.5,
                direction="negative",
                pictograms=["roadworks"],
                legends=["DESVIO OBLIGATORIO", "VEHICULO 20T"],
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
                severity="medium",
                validity_status="active",
                start_time="2026-04-04T08:00:00+02:00",
                end_time=None,
                incident_type="weightRestrictionInOperation",
                cause_type="roadMaintenance",
                from_km=13.8,
                to_km=14.3,
                latitude=37.37,
                longitude=-6.014,
                municipality="Sevilla",
                province="Sevilla",
            )
        ]
        recent_states = [
            {
                "evidence": [
                    "panel:GUID_PMV_166911:DESVIO OBLIGATORIO/VEHICULO 20T",
                    "incident:SE-30:weightRestrictionInOperation",
                ]
            }
            for _ in range(6)
        ]

        state = infer_bridge_state(panels, incidents, [], recent_states=recent_states)
        self.assertLess(state.breakdown["panels"], 3.0)
        self.assertLess(state.breakdown["incidents"], 3.5)
        self.assertIn("baseline:GUID_PMV_166911:panel", state.evidence)
        self.assertIn("baseline:weightRestrictionInOperation:incident", state.evidence)

    def test_light_camera_traffic_does_not_escalate_to_retentions(self) -> None:
        snapshots = [
            CameraSnapshot(
                camera_id="1337",
                fetched_at="2026-04-04T08:02:00+02:00",
                http_status=200,
                content_length=70000,
                sha256="abc",
                image_path="/tmp/1337.jpg",
                last_modified=None,
                visual_change_score=0.1,
                vehicle_count=15,
                vehicle_counts_by_direction={"ascendente": 8, "descendente": 7},
            )
        ]
        recent_states = [
            {"breakdown": {"panels": 2.0, "incidents": 2.0, "vehicle_count": 10.0, "camera_change": 4.0}}
            for _ in range(6)
        ]

        state = infer_bridge_state([], [], snapshots, recent_states=recent_states)
        self.assertIn(state.traffic_level, {"fluido", "denso"})
        self.assertLess(state.traffic_score, 35.0)

    def test_persistent_operational_signals_with_normal_camera_flow_stay_fluid(self) -> None:
        panels = [
            PanelMessage(
                situation_id="1",
                record_id="r1",
                location_id="GUID_PMV_60519",
                road="SE-30",
                km=14.1,
                direction="negative",
                pictograms=[],
                legends=["EN PUENTE", " CENTENARIO"],
                status="active",
                created_at="2026-04-04T08:00:00+02:00",
            ),
            PanelMessage(
                situation_id="2",
                record_id="r2",
                location_id="GUID_PMV_166911",
                road="SE-30",
                km=13.5,
                direction="negative",
                pictograms=["roadworks"],
                legends=["DESVIO OBLIGATORIO", "VEHICULO 20T"],
                status="active",
                created_at="2026-04-04T08:00:00+02:00",
            ),
        ]
        incidents = [
            Incident(
                situation_id="3",
                record_id="r3",
                road="SE-30",
                direction="negative",
                severity="medium",
                validity_status="active",
                start_time="2026-04-04T08:00:00+02:00",
                end_time=None,
                incident_type="weightRestrictionInOperation",
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
                visual_change_score=0.39,
                vehicle_count=9,
                vehicle_counts_by_direction={"ascendente": 5, "descendente": 4},
            ),
            CameraSnapshot(
                camera_id="167841",
                fetched_at="2026-04-04T08:02:00+02:00",
                http_status=503,
                content_length=0,
                sha256=None,
                image_path=None,
                last_modified=None,
                visual_change_score=None,
                vehicle_count=None,
            ),
        ]
        recent_states = [
            {
                "evidence": [
                    "panel:GUID_PMV_60519:EN PUENTE/ CENTENARIO",
                    "panel:GUID_PMV_166911:DESVIO OBLIGATORIO/VEHICULO 20T",
                    "incident:SE-30:weightRestrictionInOperation",
                ],
                "breakdown": {"panels": 2.7, "incidents": 2.1},
            }
            for _ in range(6)
        ]

        state = infer_bridge_state(panels, incidents, snapshots, recent_states=recent_states)

        self.assertEqual(state.traffic_level, "fluido")
        self.assertLess(state.traffic_score, 15.0)


if __name__ == "__main__":
    unittest.main()
