from __future__ import annotations

import json
from typing import Any, Callable, Literal

from opentelemetry.trace import Status, StatusCode

from nl_sql_file import compose_answer, critique_answer

from .analytical_context import AnalyticalContextBuilder
from .duckdb_workspace import DuckDbTableCatalog, DuckDbWorkspace, DuckDbWorkspaceFactory, ProfileEnricher
from .control_plane import CatalogRepository
from .file_resolver import FileResolver
from .llm_client import JsonLlmClient
from .models import AgentRequest, AgentState
from .prompts import SCOPE_SYSTEM_PROMPT
from .schema_context import SchemaContextBuilder
from .sql_generation import SqlGenerator
from .sql_validation import SqlReadOnlyValidator
from .tracing import set_span_attrs

CHART_INTENT_TERMS = (
    "grafico",
    "gráfico",
    "visualiza",
    "visualizar",
    "barras",
    "barra",
    "linea",
    "línea",
    "torta",
    "pie",
    "donut",
    "chart",
    "plot",
)

LINE_CHART_TERMS = (
    "linea",
    "línea",
    "tendencia",
    "evolucion",
    "evolución",
    "serie",
    "series",
)


class AgentRuntime:
    def __init__(self) -> None:
        self.workspace: DuckDbWorkspace | None = None

    def set_workspace(self, workspace: DuckDbWorkspace) -> None:
        self.workspace = workspace

    def close(self) -> None:
        if self.workspace is not None:
            self.workspace.close()
            self.workspace = None


class AnalyticalAgentNodes:
    def __init__(
        self,
        request: AgentRequest,
        runtime: AgentRuntime,
        tracer: Any,
        file_resolver: FileResolver,
        workspace_factory: DuckDbWorkspaceFactory,
        profile_enricher: ProfileEnricher,
        table_catalog: DuckDbTableCatalog,
        catalog_repository: CatalogRepository,
        schema_context_builder: SchemaContextBuilder,
        llm_client: JsonLlmClient,
        sql_generator: SqlGenerator,
        sql_validator: SqlReadOnlyValidator,
        analytical_context_builder: AnalyticalContextBuilder | None = None,
        progress: Callable[[str], None] | None = None,
        token: Callable[[str], None] | None = None,
    ) -> None:
        self._request = request
        self._runtime = runtime
        self._tracer = tracer
        self._file_resolver = file_resolver
        self._workspace_factory = workspace_factory
        self._profile_enricher = profile_enricher
        self._table_catalog = table_catalog
        self._catalog_repository = catalog_repository
        self._schema_context_builder = schema_context_builder
        self._llm_client = llm_client
        self._sql_generator = sql_generator
        self._sql_validator = sql_validator
        self._analytical_context_builder = analytical_context_builder or AnalyticalContextBuilder()
        self._progress = progress
        self._token = token

    def resolve_and_profile(self, state: AgentState) -> AgentState:
        with self._tracer.start_as_current_span("resolve_and_profile") as span:
            self._emit_progress("Resolviendo archivos...")
            files = self._file_resolver.resolve(self._request)
            self._emit_progress("Cargando DuckDB...")
            workspace = self._workspace_factory.create(self._request, files)
            profiles = self._workspace_factory.profile(workspace, self._request.sample_rows)
            profiles = self._profile_enricher.enrich(files, profiles, workspace.table_map)
            catalog_profile = self._table_catalog.materialize_catalog_table(workspace.connection, profiles)
            profiles = [*profiles, catalog_profile]
            tables = [*workspace.tables, "__analitrics_catalog"]
            self._catalog_repository.save_conversation(
                self._request,
                files,
                profiles,
                workspace.table_map,
                workspace.cache_path,
                workspace.cache_hits,
            )
            catalog_feedback = self._catalog_repository.find_feedback_for_request(
                self._request,
                [metadata.file_id for metadata in files],
            )
            analytical_context = self._analytical_context_builder.build(
                self._request.question,
                self._request.context_messages,
            )
            self._runtime.set_workspace(workspace)
            set_span_attrs(
                span,
                {
                    "analitrics.tenant_id": self._request.tenant_id,
                    "analitrics.user_id": self._request.user_id,
                    "analitrics.conversation_id": self._request.conversation_id,
                    "analitrics.message_id": self._request.message_id,
                    "analitrics.cache_path": str(workspace.cache_path) if workspace.cache_path else None,
                    "analitrics.cache_hits": workspace.cache_hits,
                    "analitrics.file_ids": [metadata.file_id for metadata in files],
                    "analitrics.filenames": [metadata.filename for metadata in files],
                    "analitrics.bytes_total": sum(metadata.bytes for metadata in files),
                    "analitrics.tables": tables,
                    "analitrics.file_count": len(files),
                    "analitrics.table_count": len(tables),
                    "analitrics.row_count_total": sum(int(p.get("row_count") or 0) for p in profiles),
                    "analitrics.catalog_feedback_count": len(catalog_feedback),
                    "analitrics.request_kind": analytical_context.get("request_kind"),
                    "analitrics.last_sql_available": bool(analytical_context.get("last_sql")),
                },
            )
            return {
                **state,
                "metadata": files[0],
                "files": files,
                "local_path": workspace.local_paths[0] if workspace.local_paths else "",
                "local_paths": workspace.local_paths,
                "tables": tables,
                "profiles": profiles,
                "catalog_feedback": catalog_feedback,
                "analytical_context": analytical_context,
                "cache_path": str(workspace.cache_path) if workspace.cache_path else "",
                "cache_hits": workspace.cache_hits,
            }

    def check_question_scope(self, state: AgentState) -> AgentState:
        with self._tracer.start_as_current_span("check_question_scope") as span:
            self._emit_progress("Validando alcance...")
            result = self._llm_client.complete_json(
                system=SCOPE_SYSTEM_PROMPT,
                payload={
                    "question": state["question"],
                    "available_data": self._schema_context_builder.build(
                        state["files"],
                        state["profiles"],
                        state.get("catalog_feedback") or [],
                    ),
                    "conversation_context": self._request.context_messages or [],
                    "analytical_context": state.get("analytical_context") or {},
                },
                model_env="ANALITRICS_SCOPE_MODEL",
                default_model="gpt-5.5",
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

    def generate_sql(self, state: AgentState) -> AgentState:
        with self._tracer.start_as_current_span("generate_sql") as span:
            self._emit_progress("Generando SQL...")
            generated = self._sql_generator.generate(
                state["question"],
                state["files"],
                state["profiles"],
                self._request.context_messages,
                state.get("catalog_feedback") or [],
                state.get("analytical_context") or {},
            )
            plan = {"sql": generated.sql, "rationale": generated.rationale, "backend": generated.backend}
            set_span_attrs(
                span,
                {
                    "analitrics.sql": generated.sql,
                    "analitrics.sql_rationale": generated.rationale,
                    "analitrics.sql_generator": generated.backend,
                },
            )
            return {**state, "plan": plan, "sql": plan["sql"]}

    def validate_sql(self, state: AgentState) -> AgentState:
        with self._tracer.start_as_current_span("validate_sql") as span:
            workspace = self._require_workspace()
            sql = state["sql"]
            for attempt in range(2):
                try:
                    self._sql_validator.validate(sql, state["tables"])
                    workspace.connection.execute(f"explain {sql}").fetchall()
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
                        repaired = self._repair_sql({**state, "sql": sql}, error)
                        sql = repaired["sql"]
                        set_span_attrs(span, {"analitrics.repaired_sql": sql})
                        continue
                    span.set_status(Status(StatusCode.ERROR, error))
                    raise
            return state

    def execute_sql(self, state: AgentState) -> AgentState:
        with self._tracer.start_as_current_span("execute_sql") as span:
            self._emit_progress("Ejecutando consulta...")
            rows_df = self._require_workspace().connection.execute(state["sql"]).fetchdf()
            rows = json.loads(rows_df.to_json(orient="records", date_format="iso"))
            set_span_attrs(
                span,
                {
                    "analitrics.row_count": len(rows),
                    "analitrics.result_columns": list(rows[0].keys()) if rows else [],
                },
            )
            return {**state, "rows": rows}

    def compose_answer(self, state: AgentState) -> AgentState:
        with self._tracer.start_as_current_span("compose_answer") as span:
            self._emit_progress("Redactando respuesta...")
            chart_intent = self._has_chart_intent(state["question"])
            answer = compose_answer(state["question"], state["sql"], state["rows"], prefer_chart=chart_intent)
            self._emit_tokens(answer)
            set_span_attrs(
                span,
                {
                    "analitrics.answer_preview": answer[:500],
                    "analitrics.chart_intent": chart_intent,
                },
            )
            return {**state, "answer": answer}

    def critique_answer(self, state: AgentState) -> AgentState:
        with self._tracer.start_as_current_span("critique_answer") as span:
            chart_intent = self._has_chart_intent(state["question"])
            critic = critique_answer(
                state["question"],
                state["sql"],
                state["rows"],
                state["answer"],
                prefer_chart=chart_intent,
            )
            answer = critic.get("revised_answer") if critic.get("approved") is False else state["answer"]
            set_span_attrs(
                span,
                {
                    "analitrics.critic_approved": critic.get("approved"),
                    "analitrics.critic_issues": critic.get("issues"),
                    "analitrics.chart_intent": chart_intent,
                },
            )
            return {**state, "critic": critic, "answer": str(answer or state["answer"])}

    def generate_chart_spec(self, state: AgentState) -> AgentState:
        with self._tracer.start_as_current_span("generate_chart_spec") as span:
            self._emit_progress("Generando gráfico...")
            rows = state.get("rows") or []
            chart_intent = self._has_chart_intent(state["question"])
            chart_type = self._chart_type(state["question"]) if chart_intent else None
            if not rows:
                result = {
                    "chart_required": False,
                    "chart_intent": chart_intent,
                    "chart_type": chart_type,
                    "renderer": "mermaid",
                    "spec": None,
                    "reason": "No hay filas para graficar.",
                }
                set_span_attrs(
                    span,
                    {
                        "analitrics.chart_required": False,
                        "analitrics.chart_intent": chart_intent,
                        "analitrics.chart_type": chart_type,
                        "analitrics.chart_renderer": "mermaid",
                    },
                )
                return {**state, "chart_spec": result}
            result = {
                "chart_required": chart_intent,
                "chart_intent": chart_intent,
                "chart_type": chart_type,
                "renderer": "mermaid",
                "spec": None,
                "reason": "El usuario pidió una visualización." if chart_intent else "El usuario no pidió visualización.",
            }
            set_span_attrs(
                span,
                {
                    "analitrics.chart_required": result.get("chart_required"),
                    "analitrics.chart_intent": chart_intent,
                    "analitrics.chart_type": chart_type,
                    "analitrics.chart_renderer": "mermaid",
                    "analitrics.chart_reason": result.get("reason"),
                },
            )
            return {**state, "chart_spec": result}

    def route_after_scope(self, state: AgentState) -> Literal["generate_sql", "__end__"]:
        return "generate_sql" if state.get("in_scope") else "__end__"

    def _repair_sql(self, state: AgentState, error: str) -> dict[str, str]:
        repaired = self._sql_generator.repair(
            question=state["question"],
            files=state["files"],
            profiles=state["profiles"],
            failed_sql=state["sql"],
            error=error,
            context_messages=self._request.context_messages,
            catalog_feedback=state.get("catalog_feedback") or [],
            analytical_context=state.get("analytical_context") or {},
        )
        return {"sql": repaired.sql, "rationale": repaired.rationale}

    def _require_workspace(self) -> DuckDbWorkspace:
        if self._runtime.workspace is None:
            raise RuntimeError("DuckDB workspace is not initialized")
        return self._runtime.workspace

    def _emit_progress(self, message: str) -> None:
        if self._progress is not None:
            self._progress(message)

    def _emit_tokens(self, text: str) -> None:
        if self._token is None:
            return
        for index in range(0, len(text), 24):
            self._token(text[index : index + 24])

    def _has_chart_intent(self, question: str) -> bool:
        normalized = question.lower()
        return any(term in normalized for term in CHART_INTENT_TERMS)

    def _chart_type(self, question: str) -> str:
        normalized = question.lower()
        if any(term in normalized for term in LINE_CHART_TERMS):
            return "line"
        return "bar"
