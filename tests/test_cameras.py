import tempfile
import unittest
from pathlib import Path

from vcentenario.collectors import cameras as cameras_module
from vcentenario.collectors.cameras import CameraCollector, classify_vehicle_directions, merge_vehicle_detections
from vcentenario.http import HttpResponse
from vcentenario.models import Camera


class _FakeHttp:
    def __init__(self, responses):
        self._responses = list(responses)

    def get(self, url, accept=None):
        return self._responses.pop(0)


class _FakeYOLO:
    def __call__(self, image_path, verbose=False):
        class _Box:
            def __init__(self, cls):
                self.cls = cls

        class _Result:
            boxes = [_Box(2), _Box(7)]

        return [_Result()]


class CameraCollectorTests(unittest.TestCase):
    def test_classify_vehicle_directions_for_camera_1337(self) -> None:
        detections = [
            (2, 0.9, (60.0, 260.0, 120.0, 320.0)),
            (2, 0.8, (355.0, 205.0, 385.0, 235.0)),
            (7, 0.7, (430.0, 210.0, 470.0, 250.0)),
        ]

        counts = classify_vehicle_directions("1337", detections)

        self.assertEqual(counts["ascendente"], 2)
        self.assertEqual(counts["descendente"], 1)

    def test_classify_vehicle_directions_for_camera_1337_falls_back_outside_polygons(self) -> None:
        detections = [
            (2, 0.8, (700.0, 80.0, 740.0, 120.0)),
            (2, 0.7, (80.0, 80.0, 120.0, 120.0)),
        ]

        counts = classify_vehicle_directions("1337", detections)

        self.assertEqual(counts["ascendente"], 1)
        self.assertEqual(counts["descendente"], 1)

    def test_merge_vehicle_detections_deduplicates_overlapping_boxes(self) -> None:
        detections = [
            (2, 0.91, (10.0, 10.0, 50.0, 50.0)),
            (2, 0.73, (12.0, 12.0, 49.0, 49.0)),
            (7, 0.65, (100.0, 100.0, 160.0, 150.0)),
        ]

        merged = merge_vehicle_detections(detections)

        self.assertEqual(len(merged), 2)

    def test_merge_vehicle_detections_deduplicates_overlapping_boxes_across_classes(self) -> None:
        detections = [
            (2, 0.31, (370.0, 208.0, 384.0, 224.0)),
            (7, 0.28, (369.0, 207.0, 385.0, 225.0)),
        ]

        merged = merge_vehicle_detections(detections)

        self.assertEqual(len(merged), 1)

    def test_fetch_snapshots_does_not_reuse_vehicle_count_after_http_error(self) -> None:
        original_get_yolo_model = cameras_module.get_yolo_model
        original_detect_vehicles_with_yolo = cameras_module.detect_vehicles_with_yolo
        cameras_module.get_yolo_model = lambda: _FakeYOLO()
        cameras_module.detect_vehicles_with_yolo = lambda model, file_path: [
            (2, 0.9, (60.0, 260.0, 120.0, 320.0)),
            (2, 0.8, (430.0, 210.0, 470.0, 250.0)),
        ]
        try:
            cameras = {
                "1337": Camera(
                    camera_id="1337",
                    road="SE-30",
                    km=13.5,
                    direction="negative",
                    latitude=37.36,
                    longitude=-6.01,
                    image_url="https://example.test/1337.jpg",
                ),
                "167841": Camera(
                    camera_id="167841",
                    road="SE-30",
                    km=13.1,
                    direction="negative",
                    latitude=37.36,
                    longitude=-6.01,
                    image_url="https://example.test/167841.jpg",
                ),
            }
            collector = CameraCollector(
                _FakeHttp(
                    [
                        HttpResponse(
                            url="https://example.test/1337.jpg",
                            status=200,
                            headers={"content-type": "image/jpeg"},
                            body=b"fake-jpeg-data",
                        ),
                        HttpResponse(
                            url="https://example.test/167841.jpg",
                            status=404,
                            headers={"content-type": "text/plain"},
                            body=b"missing",
                            error="404",
                        ),
                    ]
                )
            )

            with tempfile.TemporaryDirectory() as tmp:
                snapshots = collector.fetch_snapshots(cameras, Path(tmp), previous_payloads={})
        finally:
            cameras_module.get_yolo_model = original_get_yolo_model
            cameras_module.detect_vehicles_with_yolo = original_detect_vehicles_with_yolo

        self.assertEqual(snapshots[0].vehicle_count, 2)
        self.assertEqual(snapshots[0].vehicle_counts_by_direction, {"ascendente": 1, "descendente": 1})
        self.assertIsNone(snapshots[1].vehicle_count)


if __name__ == "__main__":
    unittest.main()
