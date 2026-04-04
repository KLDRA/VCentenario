import unittest
from unittest.mock import patch
from urllib.error import URLError
from typing import Dict

from vcentenario.http import HttpClient


class _FakeResponse:
    def __init__(self, url: str, status: int, headers: Dict[str, str], body: bytes) -> None:
        self._url = url
        self.status = status
        self.headers = headers
        self._body = body

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def geturl(self) -> str:
        return self._url

    def read(self) -> bytes:
        return self._body


class HttpClientTests(unittest.TestCase):
    def test_get_retries_temporary_network_errors(self) -> None:
        client = HttpClient(timeout=1, max_retries=1, retry_backoff_seconds=0)
        responses = [
            URLError("temporary failure"),
            _FakeResponse("https://example.test", 200, {"Content-Type": "application/xml"}, b"<ok/>"),
        ]

        def fake_urlopen(*args, **kwargs):
            result = responses.pop(0)
            if isinstance(result, Exception):
                raise result
            return result

        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            response = client.get("https://example.test", accept="application/xml")

        self.assertEqual(response.status, 200)
        self.assertEqual(response.body, b"<ok/>")
        self.assertIsNone(response.error)

    def test_get_returns_status_zero_when_network_keeps_failing(self) -> None:
        client = HttpClient(timeout=1, max_retries=1, retry_backoff_seconds=0)

        with patch("urllib.request.urlopen", side_effect=URLError("network down")):
            response = client.get("https://example.test")

        self.assertEqual(response.status, 0)
        self.assertEqual(response.body, b"")
        self.assertIn("network down", response.error or "")


if __name__ == "__main__":
    unittest.main()
