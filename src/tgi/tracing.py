"""OpenTelemetry tracing configuration with JSONL file export."""

from __future__ import annotations

import json
import logging
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    SimpleSpanProcessor,
    SpanExporter,
    SpanExportResult,
)

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence

    from opentelemetry.sdk.trace import ReadableSpan

logger = logging.getLogger(__name__)


class JSONLFileExporter(SpanExporter):
    """Exports spans as JSONL to a file (<app_name>-otel.log).

    Rotates by size like the application log: this file is the larger of the two, a
    single run over a 90 bloc document writes about 460 kB, so an unbounded file
    would eventually fill the disk of a long lived service.
    """

    __slots__ = ("_backup_count", "_lock", "_max_bytes", "_path")

    def __init__(self, path: Path, max_bytes: int = 10 * 1024 * 1024, backup_count: int = 5) -> None:
        self._path = path
        self._max_bytes = max_bytes
        self._backup_count = backup_count
        # Exporters are called from the batch processor thread as well as the caller.
        self._lock = threading.Lock()

    def _rotate_if_needed(self) -> None:
        """Roll <file> to <file>.1, shifting older backups, dropping the oldest."""
        if self._max_bytes <= 0 or self._backup_count <= 0:
            return
        try:
            if self._path.stat().st_size < self._max_bytes:
                return
        except OSError:
            return
        oldest = self._path.with_name(f"{self._path.name}.{self._backup_count}")
        oldest.unlink(missing_ok=True)
        for index in range(self._backup_count - 1, 0, -1):
            source = self._path.with_name(f"{self._path.name}.{index}")
            if source.exists():
                source.replace(self._path.with_name(f"{self._path.name}.{index + 1}"))
        self._path.replace(self._path.with_name(f"{self._path.name}.1"))

    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        """Write spans as JSON lines to the log file."""
        with self._lock:
            self._rotate_if_needed()
            return self._write(spans)

    def _write(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        with self._path.open("a", encoding="utf-8") as fh:
            for span in spans:
                record: dict[str, Any] = {
                    "name": span.name,
                    "trace_id": f"{span.context.trace_id:032x}" if span.context else "",
                    "span_id": f"{span.context.span_id:016x}" if span.context else "",
                    "parent_span_id": (f"{span.parent.span_id:016x}" if span.parent else None),
                    "start_time": span.start_time,
                    "end_time": span.end_time,
                    "status": span.status.status_code.name if span.status else "UNSET",
                    "attributes": dict(span.attributes) if span.attributes else {},
                }
                if span.events:
                    record["events"] = [
                        {
                            "name": event.name,
                            "timestamp": event.timestamp,
                            "attributes": dict(event.attributes) if event.attributes else {},
                        }
                        for event in span.events
                    ]
                fh.write(json.dumps(record, default=str) + "\n")
        return SpanExportResult.SUCCESS

    def shutdown(self) -> None:
        """No resources to release."""


def configure_tracing(
    app_name: str = "app",
    *,
    log_dir: Path | None = None,
    destination: str | None = None,
    api_key: str | None = None,
    max_bytes: int = 10 * 1024 * 1024,
    backup_count: int = 5,
) -> TracerProvider:
    """Configure OpenTelemetry tracing.

    Spans always go to <app_name>-otel.log as JSONL, which is what tgi.stats reads.
    When destination is set they are additionally exported over OTLP HTTP, batched so
    a slow or unreachable collector never blocks a request.

    Args:
        app_name: Application name, used for service name and log file (<app_name>-otel.log)
        log_dir: Directory for the JSONL log file (default: current working directory)
        destination: OTLP HTTP traces endpoint, for example http://collector:4318/v1/traces
        api_key: Bearer token for that endpoint, when it requires one
        max_bytes: Rotate the JSONL file once it reaches this size
        backup_count: How many rotated JSONL files to keep
    """
    directory = log_dir or Path.cwd()
    directory.mkdir(parents=True, exist_ok=True)
    otel_path = directory / f"{app_name}-otel.log"

    resource = Resource.create({"service.name": app_name})
    provider = TracerProvider(resource=resource)
    provider.add_span_processor(
        SimpleSpanProcessor(JSONLFileExporter(otel_path, max_bytes=max_bytes, backup_count=backup_count))
    )

    if destination:
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else None
        # Batched on purpose: an unreachable collector must not slow the pipeline.
        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=destination, headers=headers)))
        logger.info("OpenTelemetry tracing also exporting to %s", destination)

    trace.set_tracer_provider(provider)
    logger.info("OpenTelemetry tracing configured, writing to %s", otel_path)
    return provider


@contextmanager
def trace_span(
    name: str,
    attributes: dict[str, Any] | None = None,
) -> Iterator[trace.Span]:
    """Context manager for creating traced spans.

    Follows the category.operation naming convention
    (e.g., 'api.fetch_users', 'db.query', 'llm.call').

    Args:
        name: Span name in category.operation format
        attributes: Optional span attributes
    """
    tracer = trace.get_tracer(__name__)
    with tracer.start_as_current_span(name, attributes=attributes) as span:
        try:
            yield span
        except Exception as exc:
            span.set_status(trace.StatusCode.ERROR, str(exc))
            span.record_exception(exc)
            raise
