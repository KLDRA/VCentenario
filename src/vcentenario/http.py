from __future__ import annotations

import logging
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Dict, Optional

from .config import HTTP_MAX_RETRIES, HTTP_RETRY_BACKOFF_SECONDS, REQUEST_TIMEOUT, USER_AGENT


RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


@dataclass
class HttpResponse:
    url: str
    status: int
    headers: Dict[str, str]
    body: bytes
    error: Optional[str] = None


class HttpClient:
    def __init__(
        self,
        timeout: int = REQUEST_TIMEOUT,
        user_agent: str = USER_AGENT,
        max_retries: int = HTTP_MAX_RETRIES,
        retry_backoff_seconds: float = HTTP_RETRY_BACKOFF_SECONDS,
    ) -> None:
        self.timeout = timeout
        self.user_agent = user_agent
        self.max_retries = max_retries
        self.retry_backoff_seconds = retry_backoff_seconds
        self.logger = logging.getLogger(__name__)

    def get(self, url: str, accept: Optional[str] = None) -> HttpResponse:
        last_error: Optional[str] = None
        for attempt in range(self.max_retries + 1):
            request = urllib.request.Request(url, method="GET")
            request.add_header("User-Agent", self.user_agent)
            if accept:
                request.add_header("Accept", accept)
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    return HttpResponse(
                        url=response.geturl(),
                        status=response.status,
                        headers={k.lower(): v for k, v in response.headers.items()},
                        body=response.read(),
                    )
            except urllib.error.HTTPError as exc:
                response = HttpResponse(
                    url=url,
                    status=exc.code,
                    headers={k.lower(): v for k, v in exc.headers.items()},
                    body=exc.read(),
                    error=str(exc),
                )
                if exc.code in RETRYABLE_STATUS_CODES and attempt < self.max_retries:
                    self._sleep_before_retry(url, attempt, f"HTTP {exc.code}")
                    continue
                return response
            except urllib.error.URLError as exc:
                last_error = str(getattr(exc, "reason", exc))
                if attempt < self.max_retries:
                    self._sleep_before_retry(url, attempt, last_error)
                    continue
                return HttpResponse(url=url, status=0, headers={}, body=b"", error=last_error)
        return HttpResponse(url=url, status=0, headers={}, body=b"", error=last_error or "unknown error")

    def _sleep_before_retry(self, url: str, attempt: int, reason: str) -> None:
        delay = self.retry_backoff_seconds * (2 ** attempt)
        self.logger.warning(
            "Reintentando GET %s en %.1fs tras fallo temporal (%s)", url, delay, reason
        )
        time.sleep(delay)
