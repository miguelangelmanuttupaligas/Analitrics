from __future__ import annotations

import argparse
import json
import os
import socket
import tempfile
import warnings
from pathlib import Path
from urllib.parse import urlparse
from typing import Any, Literal, TypedDict

warnings.filterwarnings("ignore", message=r"The default value of `allowed_objects`.*")

try:
    from langchain_core._api.deprecation import suppress_langchain_deprecation_warning
except Exception:  # pragma: no cover - best-effort compatibility with langchain internals
    suppress_langchain_deprecation_warning = None

if suppress_langchain_deprecation_warning is None:
    from langgraph.graph import END, StateGraph
else:
    with suppress_langchain_deprecation_warning():
        from langgraph.graph import END, StateGraph
from openai import OpenAI
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.trace import Status, StatusCode

from nl_sql_file import (
    FileMetadata,
    compose_answer,
    critique_answer,
    download_from_rustfs,
    env,
    generate_sql,
    load_file_into_duckdb,
    profile_tables,
    resolve_file,
    schema_prompt,
    validate_select_sql,
)


class AgentState(TypedDict, total=False):
    args: argparse.Namespace
    question: str
    metadata: FileMetadata
    local_path: str
    tables: list[str]
    profiles: list[dict[str, Any]]
    in_scope: bool
    scope_reason: str
    plan: dict[str, str]
    sql: str
    rows: list[dict[str, Any]]
    answer: str
    critic: dict[str, Any]
    chart_spec: dict[str, Any]
    error: str


RUNTIME: dict[str, Any] = {}
TRACER = trace.get_tracer("analitrics.agent")
TRACER_PROVIDER: TracerProvider | None = None


def bool_env(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def endpoint_is_reachable(endpoint: str, timeout: float = 0.35) -> bool:
    parsed = urlparse(endpoint)
    host = parsed.hostname
    port = parsed.port or (443 if parsed.scheme == "https" else 4317)
    if not host:
        return False
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def setup_tracing(args: argparse.Namespace) -> None:
    global TRACER, TRACER_PROVIDER
    if not bool_env("ANALITRICS_TRACING_ENABLED", False):
        return

    endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://phoenix:4317")
    if not endpoint_is_reachable(endpoint):
        print(f"Tracing disabled: Phoenix OTLP endpoint is not reachable: {endpoint}", file=os.sys.stderr)
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
    TRACER_PROVIDER = provider
    TRACER = trace.get_tracer("analitrics.agent")


def shutdown_tracing() -> None:
    if TRACER_PROVIDER is not None:
        TRACER_PROVIDER.shutdown()


def compact_json(value: Any, limit: int = 2000) -> str:
    text = json.dumps(value, ensure_ascii=False, default=str)
    return text if len(text) <= limit else text[: limit - 1] + "…"


def set_span_attrs(span: Any, attrs: dict[str, Any]) -> None:
    for key, value in attrs.items():
        if value is None:
            continue
        if isinstance(value, (str, bool, int, float)):
            span.set_attribute(key, value)
        else:
            span.set_attribute(key, compact_json(value))


def llm_json(system: str, payload: dict[str, Any], model_env: str, default_model: str) -> dict[str, Any]:
    model = env(model_env, env("ANALITRICS_NL_SQL_MODEL", default_model))
    with TRACER.start_as_current_span("llm_json") as span:
        set_span_attrs(
            span,
            {
                "llm.model": model,
                "llm.model_env": model_env,
                "llm.payload_summary": {
                    "keys": sorted(payload.keys()),
                    "question": payload.get("question"),
                },
            },
        )
        client = OpenAI(api_key=env("OPENAI_API_KEY"))
        response = client.chat.completions.create(
            model=model,
            temperature=0,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False, indent=2)},
            ],
        )
        parsed = json.loads(response.choices[0].message.content or "{}")
        set_span_attrs(span, {"llm.output_keys": sorted(parsed.keys())})
        return parsed


def resolve_and_profile(state: AgentState) -> AgentState:
    with TRACER.start_as_current_span("resolve_and_profile") as span:
        args = state["args"]
        metadata = resolve_file(args)
        tmpdir = tempfile.TemporaryDirectory(prefix="analitrics-agent-")
        local_path = download_from_rustfs(metadata, Path(tmpdir.name))
        con, tables = load_file_into_duckdb(metadata, local_path)
        profiles = profile_tables(con, tables, args.sample_rows)
        RUNTIME["tmpdir"] = tmpdir
        RUNTIME["con"] = con
        set_span_attrs(
            span,
            {
                "analitrics.tenant_id": metadata.tenant_id,
                "analitrics.file_id": metadata.file_id,
                "analitrics.filename": metadata.filename,
                "analitrics.bytes": metadata.bytes,
                "analitrics.tables": tables,
                "analitrics.table_count": len(tables),
                "analitrics.row_count_total": sum(int(p.get("row_count") or 0) for p in profiles),
            },
        )
        return {
            **state,
            "metadata": metadata,
            "local_path": str(local_path),
            "tables": tables,
            "profiles": profiles,
        }


def check_question_scope(state: AgentState) -> AgentState:
    with TRACER.start_as_current_span("check_question_scope") as span:
        payload = {
            "question": state["question"],
            "available_data": json.loads(schema_prompt(state["metadata"], state["profiles"])),
        }
        result = llm_json(
            system=(
                "Clasifica si la pregunta del usuario puede responderse usando exclusivamente la data "
                "tabular disponible, su schema, profiling, diccionario o resultados derivados. "
                "Responde JSON con keys: in_scope(boolean), reason(string). "
                "Marca false para preguntas generales, programación, historia, consejos, opiniones o cualquier "
                "tema no relacionado con los archivos disponibles."
            ),
            payload=payload,
            model_env="ANALITRICS_SCOPE_MODEL",
            default_model="gpt-4.1-mini",
        )
        in_scope = bool(result.get("in_scope"))
        reason = str(result.get("reason") or "")
        set_span_attrs(span, {"analitrics.in_scope": in_scope, "analitrics.scope_reason": reason})
        if not in_scope:
            return {
                **state,
                "in_scope": False,
                "scope_reason": reason,
                "answer": "Solo puedo responder preguntas relacionadas con la data cargada en este chat.",
            }
        return {**state, "in_scope": True, "scope_reason": reason}


def route_after_scope(state: AgentState) -> Literal["generate_sql", "__end__"]:
    return "generate_sql" if state.get("in_scope") else "__end__"


def generate_sql_node(state: AgentState) -> AgentState:
    with TRACER.start_as_current_span("generate_sql") as span:
        plan = generate_sql(state["question"], state["metadata"], state["profiles"])
        set_span_attrs(span, {"analitrics.sql": plan.get("sql"), "analitrics.sql_rationale": plan.get("rationale")})
        return {**state, "plan": plan, "sql": plan["sql"]}


def validate_sql_node(state: AgentState) -> AgentState:
    with TRACER.start_as_current_span("validate_sql") as span:
        try:
            validate_select_sql(state["sql"])
            set_span_attrs(span, {"analitrics.sql_valid": True})
            return state
        except Exception as exc:
            set_span_attrs(span, {"analitrics.sql_valid": False, "analitrics.error": str(exc)})
            span.set_status(Status(StatusCode.ERROR, str(exc)))
            raise


def execute_sql_node(state: AgentState) -> AgentState:
    with TRACER.start_as_current_span("execute_sql") as span:
        con = RUNTIME["con"]
        rows_df = con.execute(state["sql"]).fetchdf()
        rows = json.loads(rows_df.to_json(orient="records", date_format="iso"))
        set_span_attrs(
            span,
            {
                "analitrics.row_count": len(rows),
                "analitrics.result_columns": list(rows[0].keys()) if rows else [],
            },
        )
        return {**state, "rows": rows}


def compose_answer_node(state: AgentState) -> AgentState:
    with TRACER.start_as_current_span("compose_answer") as span:
        answer = compose_answer(state["question"], state["sql"], state["rows"])
        set_span_attrs(span, {"analitrics.answer_preview": answer[:500]})
        return {**state, "answer": answer}


def critique_answer_node(state: AgentState) -> AgentState:
    with TRACER.start_as_current_span("critique_answer") as span:
        critic = critique_answer(state["question"], state["sql"], state["rows"], state["answer"])
        answer = critic.get("revised_answer") if critic.get("approved") is False else state["answer"]
        set_span_attrs(
            span,
            {
                "analitrics.critic_approved": critic.get("approved"),
                "analitrics.critic_issues": critic.get("issues"),
            },
        )
        return {**state, "critic": critic, "answer": str(answer or state["answer"])}


def generate_chart_spec_node(state: AgentState) -> AgentState:
    with TRACER.start_as_current_span("generate_chart_spec") as span:
        rows = state.get("rows") or []
        if not rows:
            result = {"chart_required": False, "reason": "No hay filas para graficar."}
            set_span_attrs(span, {"analitrics.chart_required": False})
            return {**state, "chart_spec": result}
        result = llm_json(
            system=(
                "Decide si los resultados deben tener gráfico. Si aplica, genera una especificación Vega-Lite "
                "minimalista y válida. Responde JSON con keys: chart_required(boolean), reason(string), spec(object|null). "
                "No inventes columnas; usa solo columnas presentes en rows."
            ),
            payload={
                "question": state["question"],
                "rows_preview": rows[:50],
                "columns": list(rows[0].keys()) if rows else [],
            },
            model_env="ANALITRICS_CHART_MODEL",
            default_model="gpt-4.1-mini",
        )
        set_span_attrs(
            span,
            {
                "analitrics.chart_required": result.get("chart_required"),
                "analitrics.chart_reason": result.get("reason"),
                "analitrics.chart_mark": (result.get("spec") or {}).get("mark") if isinstance(result.get("spec"), dict) else None,
            },
        )
        return {**state, "chart_spec": result}


def cleanup_runtime() -> None:
    con = RUNTIME.pop("con", None)
    if con is not None:
        con.close()
    tmpdir = RUNTIME.pop("tmpdir", None)
    if tmpdir is not None:
        tmpdir.cleanup()


def build_graph():
    graph = StateGraph(AgentState)
    graph.add_node("resolve_and_profile", resolve_and_profile)
    graph.add_node("check_question_scope", check_question_scope)
    graph.add_node("generate_sql", generate_sql_node)
    graph.add_node("validate_sql", validate_sql_node)
    graph.add_node("execute_sql", execute_sql_node)
    graph.add_node("compose_answer", compose_answer_node)
    graph.add_node("critique_answer", critique_answer_node)
    graph.add_node("generate_chart_spec", generate_chart_spec_node)

    graph.set_entry_point("resolve_and_profile")
    graph.add_edge("resolve_and_profile", "check_question_scope")
    graph.add_conditional_edges(
        "check_question_scope",
        route_after_scope,
        {"generate_sql": "generate_sql", "__end__": END},
    )
    graph.add_edge("generate_sql", "validate_sql")
    graph.add_edge("validate_sql", "execute_sql")
    graph.add_edge("execute_sql", "compose_answer")
    graph.add_edge("compose_answer", "critique_answer")
    graph.add_edge("critique_answer", "generate_chart_spec")
    graph.add_edge("generate_chart_spec", END)
    return graph.compile()


def run(args: argparse.Namespace) -> None:
    setup_tracing(args)
    app = build_graph()
    try:
        with TRACER.start_as_current_span("analitrics_agent_run") as span:
            set_span_attrs(
                span,
                {
                    "analitrics.question": args.question,
                    "analitrics.tenant_id": args.tenant_id,
                    "analitrics.file_id_arg": args.file_id,
                    "analitrics.filename_arg": args.filename,
                },
            )
            result = app.invoke({"args": args, "question": args.question})
            set_span_attrs(
                span,
                {
                    "analitrics.in_scope": result.get("in_scope"),
                    "analitrics.sql": result.get("sql"),
                    "analitrics.row_count": len(result.get("rows") or []),
                    "analitrics.chart_required": (result.get("chart_spec") or {}).get("chart_required")
                    if isinstance(result.get("chart_spec"), dict)
                    else None,
                },
            )
        metadata = result.get("metadata")
        output = {
            "agent": "langgraph-file-analyst",
            "in_scope": result.get("in_scope"),
            "scope_reason": result.get("scope_reason"),
            "file": metadata.__dict__ if metadata else None,
            "tables": result.get("profiles"),
            "plan": result.get("plan"),
            "sql": result.get("sql"),
            "row_count": len(result.get("rows") or []),
            "rows_preview": (result.get("rows") or [])[:20],
            "answer": result.get("answer"),
            "critic": result.get("critic"),
            "chart_spec": result.get("chart_spec"),
        }
        print(json.dumps(output, ensure_ascii=False, indent=2))
    finally:
        cleanup_runtime()
        shutdown_tracing()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Analitrics LangGraph agent over LibreChat S3 files")
    parser.add_argument("--file-id")
    parser.add_argument("--filename")
    parser.add_argument("--tenant-id", default="analitrics")
    parser.add_argument("--question", required=True)
    parser.add_argument("--sample-rows", type=int, default=5)
    return parser.parse_args()


if __name__ == "__main__":
    run(parse_args())
