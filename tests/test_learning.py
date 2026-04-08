import tempfile
import unittest
from pathlib import Path

from vcentenario.learning import build_forecast, classify_traffic_level
from vcentenario.models import BridgeState
from vcentenario.storage import Storage


class LearningTests(unittest.TestCase):
    def test_build_forecast_uses_hour_profiles(self) -> None:
        profiles = {
            (5, 16): {"sample_count": 8, "ema_score": 12.0, "ema_vehicle_count": 4.0},
            (5, 17): {"sample_count": 10, "ema_score": 28.0, "ema_vehicle_count": 8.0},
        }
        recent_states = [
            {"traffic_score": 8.0},
            {"traffic_score": 10.0},
            {"traffic_score": 12.0},
        ]

        forecast = build_forecast(
            reference_time="2026-04-04T14:00:00+00:00",
            current_score=11.0,
            recent_states=recent_states,
            profiles=profiles,
            timezone_name="Europe/Madrid",
        )

        self.assertEqual(forecast["slot_hour"], 16)
        self.assertEqual(forecast["predicted_level_next"], classify_traffic_level(forecast["predicted_score_next"]))
        self.assertGreater(forecast["predicted_score_next"], 15.0)
        self.assertEqual(forecast["profile_samples_next"], 10)

    def test_storage_updates_profile_and_exposes_latest_state_forecast(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            storage = Storage(Path(tmp) / "test.db")
            storage.init_db()
            state = BridgeState(
                generated_at="2026-04-04T14:00:00+00:00",
                traffic_score=11.0,
                traffic_level="fluido",
                reversible_probable="indeterminado",
                confidence=0.25,
                breakdown={"vehicle_count": 5.0},
            )

            learning_context = storage.update_traffic_profile(state)
            state.learning_context = learning_context
            state.forecast = storage.predict_traffic(state.generated_at, state, [])
            storage.insert_bridge_state(state)
            latest = storage.latest_state()

        self.assertIsNotNone(latest)
        self.assertEqual(latest["learning_context"]["sample_count"], 1)
        self.assertIn("predicted_level_next", latest["forecast"])

    def test_ml_predictor(self) -> None:
        try:
            from vcentenario.learning import MLPredictor
            predictor = MLPredictor(None)
            features = {
                'hour': 9,
                'avg_speed_north': 40.0,
                'avg_speed_south': 50.0,
                'incident_count': 1,
                'panel_score': 20.0,
            }
            level = predictor.predict_traffic_level(features)
            direction = predictor.predict_reversible_direction(features)
            self.assertIn(level, ['fluido', 'denso', 'retenciones', 'congestion_fuerte', 'unknown'])
            self.assertIn(direction, ['positive', 'negative', 'indeterminado'])
        except ImportError:
            self.skipTest("ML dependencies not available")


if __name__ == "__main__":
    unittest.main()
