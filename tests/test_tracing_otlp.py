"""Tests for OTLP export, against a real local receiver."""

from __future__ import annotations

import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any

import pytest
from opentelemetry import trace

from tgi.tracing import configure_tracing, trace_span

_received: list[dict[str, Any]] = []


class _Collector(BaseHTTPRequestHandler):
    """Minimal OTLP HTTP receiver: records what the exporter actually sends."""

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length)
        _received.append({"path": self.path, "headers": dict(self.headers), "size": len(body)})
        self.send_response(200)
        self.send_header("Content-Type", "application/x-protobuf")
        self.end_headers()
        self.wfile.write(b"")

    def log_message(self, *args: Any) -> None:
        """Silence the default stderr logging."""


@pytest.fixture(autouse=True)
def _reset_tracer() -> None:
    trace._TRACER_PROVIDER = None  # type: ignore[attr-defined]
    trace._TRACER_PROVIDER_SET_ONCE._done = False  # type: ignore[attr-defined]
    _received.clear()


@pytest.fixture
def collector() -> Any:
    server = HTTPServer(("127.0.0.1", 0), _Collector)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}/v1/traces"
    server.shutdown()
    server.server_close()


def test_spans_reach_the_collector(collector: str, tmp_path: Path) -> None:
    """TGI_OTEL_DESTINATION must actually ship spans, not just exist in the config."""
    provider = configure_tracing(app_name="otlp_test", log_dir=tmp_path, destination=collector)
    with trace_span("test.operation", {"key": "value"}):
        pass
    provider.force_flush(5000)

    assert _received, "the collector received nothing"
    assert _received[0]["path"] == "/v1/traces"
    assert _received[0]["size"] > 0


def test_api_key_is_sent_as_a_bearer_token(collector: str, tmp_path: Path) -> None:
    provider = configure_tracing(app_name="otlp_auth", log_dir=tmp_path, destination=collector, api_key="secret-token")
    with trace_span("test.authenticated"):
        pass
    provider.force_flush(5000)

    assert _received
    authorization = _received[0]["headers"].get("Authorization")
    assert authorization == "Bearer secret-token"


def test_jsonl_file_is_written_even_with_a_collector(collector: str, tmp_path: Path) -> None:
    """The local JSONL export is what tgi-stats reads, it must never be replaced."""
    provider = configure_tracing(app_name="otlp_both", log_dir=tmp_path, destination=collector)
    with trace_span("test.both"):
        pass
    provider.force_flush(5000)

    lines = (tmp_path / "otlp_both-otel.log").read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    assert "test.both" in lines[0]
    assert _received


def test_unreachable_collector_does_not_break_the_caller(tmp_path: Path) -> None:
    """An unreachable collector must not fail the pipeline."""
    provider = configure_tracing(app_name="otlp_down", log_dir=tmp_path, destination="http://127.0.0.1:9/v1/traces")
    with trace_span("test.resilient"):
        pass
    provider.force_flush(2000)
    # The local file still has the span, and nothing was raised
    assert "test.resilient" in (tmp_path / "otlp_down-otel.log").read_text(encoding="utf-8")


def test_no_destination_means_file_only(tmp_path: Path) -> None:
    provider = configure_tracing(app_name="otlp_off", log_dir=tmp_path)
    with trace_span("test.local"):
        pass
    provider.force_flush(2000)
    assert "test.local" in (tmp_path / "otlp_off-otel.log").read_text(encoding="utf-8")
    assert _received == []
