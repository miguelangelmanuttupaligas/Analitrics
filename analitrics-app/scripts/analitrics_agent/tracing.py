from __future__ import annotations

import os
import hashlib
import re
import sys
import unicodedata
from typing import Any

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from .config import bool_env, endpoint_is_reachable
from .json_utils import compact_json


class TracingManager:
    def __init__(self) -> None:
        self._provider: TracerProvider | None = None
        self._setup_attempted = False
        self.tracer = trace.get_tracer("analitrics.agent")

    def setup(self) -> None:
        if self._provider is not None or self._setup_attempted:
            return
        self._setup_attempted = True
        if not bool_env("ANALITRICS_TRACING_ENABLED", False):
            return

        endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://phoenix:4317")
        if not endpoint_is_reachable(endpoint):
            print(f"Tracing disabled: Phoenix OTLP endpoint is not reachable: {endpoint}", file=sys.stderr)
            return

        resource = Resource.create(
            {
                "service.name": "analitrics-agent",
                "service.version": "mvp",
                "deployment.environment": os.getenv("ANALITRICS_ENV", "local"),
                "openinference.project.name": os.getenv("PHOENIX_PROJECT_NAME", "analitrics-mvp"),
            }
        )
        provider = TracerProvider(resource=resource)
        exporter = OTLPSpanExporter(endpoint=endpoint, insecure=endpoint.startswith("http://"))
        provider.add_span_processor(BatchSpanProcessor(exporter))
        trace.set_tracer_provider(provider)
        self._provider = provider
        self.tracer = trace.get_tracer("analitrics.agent")

    def shutdown(self) -> None:
        if self._provider is not None:
            self._provider.force_flush()


def set_span_attrs(span: Any, attrs: dict[str, Any]) -> None:
    for key, value in attrs.items():
        if value is None:
            continue
        if isinstance(value, (str, bool, int, float)):
            span.set_attribute(key, value)
        else:
            span.set_attribute(key, compact_json(value))


def normalize_search_text(value: str | None) -> str:
    text = unicodedata.normalize("NFKD", value or "")
    text = "".join(char for char in text if not unicodedata.combining(char))
    text = re.sub(r"\s+", " ", text.lower()).strip()
    return text


def stable_text_hash(value: str | None) -> str:
    return hashlib.sha256(normalize_search_text(value).encode("utf-8")).hexdigest()


def current_trace_id(span: Any) -> str | None:
    context = span.get_span_context()
    if not context or not context.is_valid:
        return None
    return trace.format_trace_id(context.trace_id)
