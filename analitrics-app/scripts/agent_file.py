from __future__ import annotations

import argparse
import json
import os
import socket
import tempfile
import warnings
from dataclasses import asdict
from pathlib import Path
from urllib.parse import urlparse
from typing import Any, Literal, TypedDict

import duckdb

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
    load_csv,
    load_workbook,
    normalize_identifier,
    profile_tables,
    resolve_file,
    validate_select_sql,
)


class AgentState(TypedDict, total=False):
    args: argparse.Namespace
    question: str
    metadata: FileMetadata
    files: list[FileMetadata]
    local_path: str
    local_paths: list[str]
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


def csv_list(value: str | None) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def arg_values(args: argparse.Namespace, attr: str) -> list[str]:
    values = getattr(args, attr) or []
    if isinstance(values, str):
        return [values]
    return list(values)


def resolve_files(args: argparse.Namespace) -> list[FileMetadata]:
    file_ids = arg_values(args, "file_id") + csv_list(getattr(args, "file_ids", None))
    filenames = arg_values(args, "filename") + csv_list(getattr(args, "filenames", None))

    if not file_ids and not filenames:
        raise RuntimeError("Provide --file-id, --filename, --file-ids or --filenames")

    files: list[FileMetadata] = []
    seen: set[str] = set()
    for file_id in file_ids:
        metadata = resolve_file(
            argparse.Namespace(file_id=file_id, filename=None, tenant_id=args.tenant_id)
        )
        if metadata.file_id not in seen:
            files.append(metadata)
            seen.add(metadata.file_id)

    for filename in filenames:
        metadata = resolve_file(
            argparse.Namespace(file_id=None, filename=filename, tenant_id=args.tenant_id)
        )
        if metadata.file_id not in seen:
            files.append(metadata)
            seen.add(metadata.file_id)

    return files


def table_name_for_file(metadata: FileMetadata, table: str) -> str:
    file_stem = normalize_identifier(Path(metadata.filename).stem, "file")
    short_id = normalize_identifier(metadata.file_id.split("-")[0], "file")
    return normalize_identifier(f"{file_stem}_{short_id}_{table}", "table")


def load_files_into_duckdb(
    files: list[FileMetadata],
    tmpdir: tempfile.TemporaryDirectory[str],
) -> tuple[duckdb.DuckDBPyConnection, list[str], list[str], dict[str, list[str]]]:
    con = duckdb.connect(database=":memory:")
    all_tables: list[str] = []
    local_paths: list[str] = []
    table_map: dict[str, list[str]] = {}

    for metadata in files:
        file_dir = Path(tmpdir.name) / metadata.file_id
        file_dir.mkdir(parents=True, exist_ok=True)
        local_path = download_from_rustfs(metadata, file_dir)
        local_paths.append(str(local_path))

        extension = local_path.suffix.lower()
        if extension == ".csv" or metadata.mime_type in {"text/csv", "application/csv"}:
            raw_tables = load_csv(con, local_path, metadata.filename)
        else:
            raw_tables = load_workbook(con, local_path)

        renamed_tables: list[str] = []
        for raw_table in raw_tables:
            final_table = table_name_for_file(metadata, raw_table)
            if final_table != raw_table:
                con.execute(f'create or replace table "{final_table}" as select * from "{raw_table}"')
                con.execute(f'drop table "{raw_table}"')
            renamed_tables.append(final_table)
            all_tables.append(final_table)
        table_map[metadata.file_id] = renamed_tables

    return con, all_tables, local_paths, table_map


def combined_schema_prompt(files: list[FileMetadata], profiles: list[dict[str, Any]]) -> str:
    compact_profiles = [
        {
            "table": profile["table"],
            "row_count": profile["row_count"],
            "columns": profile["columns"],
            "sample": profile["sample"][:3],
            "source_file_id": profile.get("source_file_id"),
            "source_filename": profile.get("source_filename"),
        }
        for profile in profiles
    ]
    return json.dumps(
        {
            "files": [
                {
                    "file_id": metadata.file_id,
                    "filename": metadata.filename,
                    "tenantId": metadata.tenant_id,
                    "mimeType": metadata.mime_type,
                    "bytes": metadata.bytes,
                }
                for metadata in files
            ],
            "duckdb_schema": compact_profiles,
        },
        ensure_ascii=False,
        indent=2,
    )


def enrich_profiles_with_file_context(
    files: list[FileMetadata],
    profiles: list[dict[str, Any]],
    table_map: dict[str, list[str]],
) -> list[dict[str, Any]]:
    by_file = {metadata.file_id: metadata for metadata in files}
    table_to_file: dict[str, FileMetadata] = {}
    for file_id, tables in table_map.items():
        metadata = by_file[file_id]
        for table in tables:
            table_to_file[table] = metadata

    enriched: list[dict[str, Any]] = []
    for profile in profiles:
        metadata = table_to_file.get(str(profile.get("table")))
        enriched.append(
            {
                **profile,
                "source_file_id": metadata.file_id if metadata else None,
                "source_filename": metadata.filename if metadata else None,
            }
        )
    return enriched


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
        tmpdir = tempfile.TemporaryDirectory(prefix="analitrics-agent-")
        files = resolve_files(args)
        con, tables, local_paths, table_map = load_files_into_duckdb(files, tmpdir)
        profiles = enrich_profiles_with_file_context(files, profile_tables(con, tables, args.sample_rows), table_map)
        RUNTIME["tmpdir"] = tmpdir
        RUNTIME["con"] = con
        set_span_attrs(
            span,
            {
                "analitrics.tenant_id": args.tenant_id,
                "analitrics.file_ids": [metadata.file_id for metadata in files],
                "analitrics.filenames": [metadata.filename for metadata in files],
                "analitrics.bytes_total": sum(metadata.bytes for metadata in files),
                "analitrics.tables": tables,
                "analitrics.file_count": len(files),
                "analitrics.table_count": len(tables),
                "analitrics.row_count_total": sum(int(p.get("row_count") or 0) for p in profiles),
            },
        )
        return {
            **state,
            "metadata": files[0],
            "files": files,
            "local_path": local_paths[0],
            "local_paths": local_paths,
            "tables": tables,
            "profiles": profiles,
        }


def check_question_scope(state: AgentState) -> AgentState:
    with TRACER.start_as_current_span("check_question_scope") as span:
        payload = {
            "question": state["question"],
            "available_data": json.loads(combined_schema_prompt(state["files"], state["profiles"])),
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
        plan = llm_json(
            system=(
                "Eres un analista de datos. Genera SQL DuckDB de solo lectura para responder "
                "la pregunta del usuario usando exclusivamente las tablas disponibles. "
                "Puede haber múltiples archivos y múltiples hojas; cruza tablas solo si la pregunta lo requiere "
                "y si los nombres/columnas lo sustentan. Responde JSON con keys: sql, rationale. "
                "No uses INSERT, UPDATE, DELETE, CREATE, DROP, COPY, ATTACH, INSTALL, LOAD, PRAGMA ni llamadas externas. "
                "Cita todos los nombres de tabla con comillas dobles. Evita aliases reservados como table; usa table_name."
            ),
            payload={
                "question": state["question"],
                "available_data": json.loads(combined_schema_prompt(state["files"], state["profiles"])),
            },
            model_env="ANALITRICS_NL_SQL_MODEL",
            default_model="gpt-4.1-mini",
        )
        plan = {"sql": str(plan.get("sql", "")), "rationale": str(plan.get("rationale", ""))}
        set_span_attrs(span, {"analitrics.sql": plan.get("sql"), "analitrics.sql_rationale": plan.get("rationale")})
        return {**state, "plan": plan, "sql": plan["sql"]}


def repair_sql(state: AgentState, error: str) -> dict[str, str]:
    repaired = llm_json(
        system=(
            "Repara SQL DuckDB de solo lectura que falló validación o EXPLAIN. "
            "Devuelve JSON con keys: sql, rationale. Usa únicamente tablas/columnas disponibles. "
            "Cita nombres de tabla con comillas dobles. Evita aliases reservados como table; usa table_name. "
            "No uses INSERT, UPDATE, DELETE, CREATE, DROP, COPY, ATTACH, INSTALL, LOAD, PRAGMA ni llamadas externas."
        ),
        payload={
            "question": state["question"],
            "available_data": json.loads(combined_schema_prompt(state["files"], state["profiles"])),
            "failed_sql": state["sql"],
            "error": error,
        },
        model_env="ANALITRICS_SQL_REPAIR_MODEL",
        default_model="gpt-4.1-mini",
    )
    return {"sql": str(repaired.get("sql", "")), "rationale": str(repaired.get("rationale", ""))}


def validate_sql_node(state: AgentState) -> AgentState:
    with TRACER.start_as_current_span("validate_sql") as span:
        con = RUNTIME["con"]
        sql = state["sql"]
        for attempt in range(2):
            try:
                validate_select_sql(sql)
                con.execute(f"explain {sql}").fetchall()
                set_span_attrs(
                    span,
                    {
                        "analitrics.sql_valid": True,
                        "analitrics.sql_validation_attempt": attempt + 1,
                        "analitrics.sql": sql,
                    },
                )
                if sql != state["sql"]:
                    plan = {**state.get("plan", {}), "sql": sql, "rationale": "SQL repaired after validation error."}
                    return {**state, "sql": sql, "plan": plan}
                return state
            except Exception as exc:
                error = str(exc)
                set_span_attrs(
                    span,
                    {
                        "analitrics.sql_valid": False,
                        "analitrics.sql_validation_attempt": attempt + 1,
                        "analitrics.error": error,
                    },
                )
                if attempt == 0:
                    repaired = repair_sql({**state, "sql": sql}, error)
                    sql = repaired["sql"]
                    set_span_attrs(span, {"analitrics.repaired_sql": sql})
                    continue
                span.set_status(Status(StatusCode.ERROR, error))
                raise
        return state


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
                    "analitrics.file_ids_arg": args.file_ids,
                    "analitrics.filename_arg": args.filename,
                    "analitrics.filenames_arg": args.filenames,
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
        files = result.get("files") or []
        output = {
            "agent": "langgraph-file-analyst",
            "in_scope": result.get("in_scope"),
            "scope_reason": result.get("scope_reason"),
            "file": metadata.__dict__ if metadata else None,
            "files": [asdict(file) for file in files],
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
    parser.add_argument("--file-id", action="append", help="LibreChat file_id. Can be passed multiple times.")
    parser.add_argument("--filename", action="append", help="LibreChat filename. Can be passed multiple times.")
    parser.add_argument("--file-ids", help="Comma-separated LibreChat file_ids.")
    parser.add_argument("--filenames", help="Comma-separated LibreChat filenames.")
    parser.add_argument("--tenant-id", default="analitrics")
    parser.add_argument("--question", required=True)
    parser.add_argument("--sample-rows", type=int, default=5)
    return parser.parse_args()


if __name__ == "__main__":
    run(parse_args())
