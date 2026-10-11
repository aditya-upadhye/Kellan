from __future__ import annotations

import sys
from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import uuid4

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import ConsoleSpanExporter, SimpleSpanProcessor

if TYPE_CHECKING:
    from typing import TextIO


@dataclass(slots=True)
class _TelemetryState:
    provider: TracerProvider | None = None


_state = _TelemetryState()


def configure_console_tracing(out: TextIO | None = None) -> TracerProvider:
    if _state.provider is not None:
        return _state.provider

    existing = trace.get_tracer_provider()
    if isinstance(existing, TracerProvider):
        provider = existing
    else:
        provider = TracerProvider(resource=Resource.create({"service.name": "matchlens"}))
        trace.set_tracer_provider(provider)
    provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter(out=out or sys.stdout)))
    _state.provider = provider
    return provider


def current_trace_id() -> str:
    context = trace.get_current_span().get_span_context()
    return f"{context.trace_id:032x}" if context.is_valid else uuid4().hex
