"""OTLP traces when the SDK is installed and not disabled; no-op otherwise."""
from __future__ import annotations

import os
import uuid
from contextlib import contextmanager

_initialized = False
_service = "agentruntime"
_last_trace_id: str | None = None


def init_tracing(service_name: str = "agentruntime", endpoint: str | None = None) -> None:
    global _initialized, _service
    _service = service_name
    if _initialized:
        return
    if os.getenv("OTEL_SDK_DISABLED", "").lower() in {"1", "true", "yes"}:
        _initialized = True
        return
    try:
        from opentelemetry import trace
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter

        resource = Resource.create({"service.name": service_name})
        provider = TracerProvider(resource=resource)
        try:
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

            url = (endpoint or os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4318")).rstrip("/")
            if not url.endswith("/v1/traces"):
                url = f"{url}/v1/traces"
            provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=url)))
        except Exception:
            provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))
        trace.set_tracer_provider(provider)
    except Exception:
        pass
    _initialized = True


@contextmanager
def span(name: str, **attrs):
    global _last_trace_id
    try:
        from opentelemetry import trace

        tracer = trace.get_tracer(_service)
        with tracer.start_as_current_span(name) as current:
            for key, value in attrs.items():
                if value is not None:
                    current.set_attribute(key, str(value) if not isinstance(value, (bool, int, float, str)) else value)
            ctx = current.get_span_context()
            _last_trace_id = format(ctx.trace_id, "032x") if ctx and ctx.trace_id else uuid.uuid4().hex
            yield current
            return
    except Exception:
        pass
    _last_trace_id = uuid.uuid4().hex
    yield None


def current_trace_id() -> str | None:
    if _last_trace_id:
        return _last_trace_id
    try:
        from opentelemetry import trace

        ctx = trace.get_current_span().get_span_context()
        if ctx and ctx.trace_id:
            return format(ctx.trace_id, "032x")
    except Exception:
        pass
    return None
