from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from app.config import settings

_provider: TracerProvider | None = None


def setup_tracing(app) -> None:  # type: ignore[type-arg]
    global _provider
    if not settings.OTEL_TRACES_ENABLED:
        return

    resource = Resource({
        SERVICE_NAME: settings.OTEL_SERVICE_NAME,
        "deployment.environment": "minikube",
    })
    exporter = OTLPSpanExporter(
        endpoint=settings.OTEL_EXPORTER_OTLP_ENDPOINT,
        insecure=True,
    )
    processor = BatchSpanProcessor(exporter)
    _provider = TracerProvider(resource=resource)
    _provider.add_span_processor(processor)
    trace.set_tracer_provider(_provider)
    FastAPIInstrumentor.instrument_app(app, tracer_provider=_provider)


def get_tracer(name: str = "fraud-alert-agent") -> trace.Tracer:
    return trace.get_tracer(name)


def shutdown_tracing() -> None:
    global _provider
    if _provider is not None:
        _provider.force_flush()
        _provider.shutdown()
