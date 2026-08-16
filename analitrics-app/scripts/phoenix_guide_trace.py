from __future__ import annotations

import os
import socket
from urllib.parse import urlparse

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor


STEPS = [
    (
        "01_analitrics_agent_run",
        "Ejecucion completa de una pregunta del usuario. Revisar tenant, file_id, pregunta, alcance, SQL, filas y grafico.",
    ),
    (
        "02_resolve_and_profile",
        "Resuelve metadata en MongoDB, descarga el archivo original desde RustFS, carga DuckDB y genera profiling tecnico.",
    ),
    (
        "03_check_question_scope",
        "Determina si la pregunta pertenece a la data cargada. Si in_scope=false no debe generar SQL ni ejecutar herramientas.",
    ),
    (
        "04_generate_sql",
        "Genera SQL DuckDB de solo lectura usando catalogo/schema/muestras pequenas, no el archivo completo.",
    ),
    (
        "05_validate_sql",
        "Bloquea SQL no permitido. Debe quedar analitrics.sql_valid=true antes de ejecutar.",
    ),
    (
        "06_execute_sql",
        "Ejecuta el SQL validado en DuckDB. Revisar analitrics.row_count y analitrics.result_columns.",
    ),
    (
        "07_compose_answer",
        "Redacta la respuesta usando solo resultados de SQL y contexto analitico disponible.",
    ),
    (
        "08_critique_answer",
        "Revisa consistencia de la respuesta. Revisar analitrics.critic_approved y analitrics.critic_issues.",
    ),
    (
        "09_generate_chart_spec",
        "Decide si corresponde grafico y genera una spec Vega-Lite minimalista si aplica.",
    ),
]


def endpoint_is_reachable(endpoint: str, timeout: float = 0.5) -> bool:
    parsed = urlparse(endpoint)
    host = parsed.hostname
    port = parsed.port or 4317
    if not host:
        return False
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def main() -> None:
    endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://phoenix:4317")
    if not endpoint_is_reachable(endpoint):
        raise SystemExit(f"Phoenix OTLP endpoint is not reachable: {endpoint}")

    provider = TracerProvider(
        resource=Resource.create(
            {
                "service.name": "analitrics-guide",
                "openinference.project.name": os.getenv("PHOENIX_PROJECT_NAME", "analitrics-mvp"),
            }
        )
    )
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint, insecure=True)))
    trace.set_tracer_provider(provider)
    tracer = trace.get_tracer("analitrics.guide")

    with tracer.start_as_current_span("como_leer_analitrics_mvp") as root:
        root.set_attribute("analitrics.guide", True)
        root.set_attribute("analitrics.note", "Guia de lectura de traces del agente Analitrics MVP.")
        root.set_attribute("analitrics.project_to_use", "analitrics-mvp")
        root.set_attribute("analitrics.ignore_project", "default")
        root.set_attribute(
            "analitrics.warning",
            "No registrar archivos completos, resultados completos, credenciales ni datos sensibles por defecto.",
        )
        for name, note in STEPS:
            with tracer.start_as_current_span(name) as span:
                span.set_attribute("analitrics.guide", True)
                span.set_attribute("analitrics.note", note)

    provider.shutdown()
    print("Phoenix guide trace emitted to project analitrics-mvp")


if __name__ == "__main__":
    main()
