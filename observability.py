from __future__ import annotations
import os
from typing import Optional

def otel_enabled() -> bool:
    return os.getenv("OTEL_ENABLE", "").strip() in {"1","true","yes","on"}

def init_otel(service_name: str = "public-admin-demo") -> None:
    if not otel_enabled():
        return
    try:
        from opentelemetry import trace
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter

        exporter = None
        try:
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
            endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "").strip()
            if endpoint:
                exporter = OTLPSpanExporter(endpoint=endpoint)
        except Exception:
            exporter = None

        resource = Resource.create({"service.name": service_name})
        provider = TracerProvider(resource=resource)
        if exporter is not None:
            provider.add_span_processor(BatchSpanProcessor(exporter))
        else:
            provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))
        trace.set_tracer_provider(provider)

        # optional instrumentation
        try:
            from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
            HTTPXClientInstrumentor().instrument()
        except Exception:
            pass
    except Exception:
        return

def current_trace_ids() -> Optional[dict]:
    try:
        from opentelemetry import trace
        span = trace.get_current_span()
        ctx = span.get_span_context()
        if not ctx or not getattr(ctx, "is_valid", False):
            return None
        return {
            "trace_id": format(ctx.trace_id, "032x"),
            "span_id": format(ctx.span_id, "016x"),
        }
    except Exception:
        return None
