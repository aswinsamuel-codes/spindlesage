"""Where gateways send telemetry: the SpindleSage API's /telemetry endpoint.

Gateways (the MQTT bridge, the OPC UA collector) authenticate with an API key
that has the `ingest` role, which can send telemetry and nothing else. The
key is read from an environment variable, never from the command line, so it
does not end up in shell history or process listings.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field

from core.telemetry.schema import CncTelemetryReading

log = logging.getLogger(__name__)

INGEST_KEY_ENV = "SPINDLESAGE_INGEST_KEY"

# post(path, json_body) -> (status_code, parsed_json_or_None)
PostFn = Callable[[str, dict], tuple[int, dict | None]]


class SinkError(RuntimeError):
    def __init__(self, message: str, retryable: bool):
        super().__init__(message)
        self.retryable = retryable


def ingest_key_from_env() -> str:
    key = os.environ.get(INGEST_KEY_ENV)
    if not key:
        raise SystemExit(
            f"Set {INGEST_KEY_ENV} to an API key with the 'ingest' role "
            "(create one with: python -m apps.api.keys add --user gateway --role ingest)"
        )
    return key


def urllib_post(base_url: str, api_key: str, timeout: float = 10.0) -> PostFn:
    def post(path: str, body: dict) -> tuple[int, dict | None]:
        request = urllib.request.Request(
            base_url.rstrip("/") + path,
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json", "X-API-Key": api_key},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.status, json.loads(response.read() or b"null")
        except urllib.error.HTTPError as exc:
            try:
                payload = json.loads(exc.read() or b"null")
            except json.JSONDecodeError:
                payload = None
            return exc.code, payload
        except (urllib.error.URLError, TimeoutError) as exc:
            raise SinkError(f"Cannot reach the API at {base_url}: {exc}", retryable=True) from exc

    return post


class ApiTelemetrySink:
    def __init__(self, post: PostFn):
        self._post = post

    @classmethod
    def from_url(cls, base_url: str, api_key: str) -> ApiTelemetrySink:
        return cls(urllib_post(base_url, api_key))

    def send(self, readings: list[CncTelemetryReading]) -> dict:
        status, payload = self._post(
            "/telemetry", {"readings": [r.model_dump(mode="json") for r in readings]}
        )
        if status in (401, 403):
            raise SinkError(f"API refused the ingest key (HTTP {status})", retryable=False)
        if status >= 500:
            raise SinkError(f"API error (HTTP {status})", retryable=True)
        if status >= 400:
            detail = (payload or {}).get("detail")
            raise SinkError(f"API rejected the batch (HTTP {status}): {detail}", retryable=False)
        return payload or {}


@dataclass
class ForwarderStats:
    received: int = 0
    accepted: int = 0
    rejected: int = 0
    failed_batches: int = 0
    rejections: list[dict] = field(default_factory=list)


class TelemetryForwarder:
    """Batches readings and sends them to a sink. Safe to call from any thread."""

    def __init__(self, sink, batch_size: int = 25, max_buffer: int = 5000):
        self.sink = sink
        self.batch_size = batch_size
        self.max_buffer = max_buffer
        self.stats = ForwarderStats()
        self._pending: list[CncTelemetryReading] = []
        self._lock = threading.Lock()

    def add(self, reading: CncTelemetryReading) -> None:
        with self._lock:
            self.stats.received += 1
            self._pending.append(reading)
            if len(self._pending) > self.max_buffer:
                # The API is unreachable for too long: drop the oldest readings.
                dropped = len(self._pending) - self.max_buffer
                del self._pending[:dropped]
                log.warning("Dropped %d buffered readings (buffer full)", dropped)
            ready = len(self._pending) >= self.batch_size
        if ready:
            self.flush()

    def flush(self) -> None:
        with self._lock:
            batch, self._pending = self._pending, []
        if not batch:
            return
        try:
            result = self.sink.send(batch)
        except SinkError as exc:
            self.stats.failed_batches += 1
            if exc.retryable:
                with self._lock:
                    self._pending = batch + self._pending
            log.error("Forwarding failed: %s", exc)
            if not exc.retryable:
                raise
            return
        with self._lock:
            self.stats.accepted += int(result.get("accepted", 0))
            rejected = result.get("rejected", [])
            self.stats.rejected += len(rejected)
            self.stats.rejections.extend(rejected[-20:])
            self.stats.rejections = self.stats.rejections[-50:]
