import tempfile
import unittest
from pathlib import Path

from vcentenario.service import VCentenarioService
from vcentenario.webapp import DashboardServer


class WebAppConfigTests(unittest.TestCase):
    def test_dashboard_server_defaults_refresh_to_disabled(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            service = VCentenarioService(db_path=root / "test.db", snapshots_dir=root / "snapshots")
            server = DashboardServer(service=service, host="127.0.0.1", port=8080)

        self.assertFalse(server.enable_refresh_endpoint)
        self.assertGreaterEqual(server.refresh_min_interval_seconds, 0)


if __name__ == "__main__":
    unittest.main()
