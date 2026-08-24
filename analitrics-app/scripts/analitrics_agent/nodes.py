from __future__ import annotations

import json
from typing import Any, Callable, Literal

from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode

from nl_sql_file import sanitize_answer_text

from .analysis_state import AnalysisStateBuilder
from .analytical_context import AnalyticalContextBuilder
from .catalog_feedback import CatalogFeedbackApplier
from .chart_spec import ChartSpecGenerator
from .conversation_planner import ConversationPlanner, find_selected_analysis_state
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

ANSWER_ROW_LIMIT = 15
CHART_ROW_LIMIT = 12
CRITIC_ROW_LIMIT = 12
COMPACT_SQL_CHARS = 1200


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
        analysis_state_builder: AnalysisStateBuilder | None = None,
        conversation_planner: ConversationPlanner | None = None,
        chart_spec_generator: ChartSpecGenerator | None = None,
        catalog_feedback_applier: CatalogFeedbackApplier | None = None,
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
        self._analysis_state_builder = analysis_state_builder or AnalysisStateBuilder(llm_client, schema_context_builder)
        self._conversation_planner = conversation_planner or ConversationPlanner(llm_client)
        self._chart_spec_generator = chart_spec_generator or ChartSpecGenerator(llm_client)
        self._catalog_feedback_applier = catalog_feedback_applier or CatalogFeedbackApplier(catalog_repository)
        self._progress = progress
        self._token = token

    def resolve_and_profile(self, state: AgentState) -> AgentState:
        with self._tracer.start_as_current_span("resolve_and_profile") as span:
            self._emit_progress("Buscando archivos adjuntos en el contexto del chat...")
            files = self._file_resolver.resolve(self._request)
            file_names = ", ".join(metadata.filename for metadata in files[:3])
            suffix = "..." if len(files) > 3 else ""
            self._emit_progress(f"Encontré {len(files)} archivo(s) tabulares: {file_names}{suffix}.")
            self._emit_progress("Preparando el espacio analítico aislado de esta conversación...")
            workspace = self._workspace_factory.create(self._request, files)
            self._runtime.set_workspace(workspace)
            if workspace.cache_hits:
                self._emit_progress("Reutilizando DuckDB ya construido para este chat.")
            else:
                self._emit_progress("Construyendo DuckDB desde los archivos fuente.")
            profiles = self._workspace_factory.profile(workspace, self._request.sample_rows)
            profiles = self._profile_enricher.enrich(files, profiles, workspace.table_map)
            catalog_profile = self._table_catalog.materialize_catalog_table(workspace.connection, profiles)
            profiles = [*profiles, catalog_profile]
            tables = [*workspace.tables, "__analitrics_catalog"]
            data_tables = [profile for profile in profiles if not profile.get("system_table")]
            row_count = sum(int(profile.get("row_count") or 0) for profile in data_tables)
            self._emit_progress(f"Perfilé {len(data_tables)} tabla(s) con {row_count:,} fila(s) disponibles.")
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
            if catalog_feedback:
                self._emit_progress(f"Cargando {len(catalog_feedback)} definición(es) del catálogo enriquecido.")
            recent_analysis_states = self._catalog_repository.find_recent_analysis_states(self._request)
            pending_clarification = self._catalog_repository.find_pending_clarification(self._request)
            if recent_analysis_states:
                self._emit_progress(f"Revisando {len(recent_analysis_states)} estado(s) analíticos anteriores del chat.")
            analytical_context = self._analytical_context_builder.build(
                self._request.question,
                self._request.context_messages,
                files,
                profiles,
                recent_analysis_states,
                pending_clarification,
            )
            available_data = self._schema_context_builder.build(files, profiles, catalog_feedback)
            self._emit_progress("Interpretando si la pregunta es nueva, seguimiento, corrección o aclaración...")
            conversation_plan = self._conversation_planner.plan(
                self._request.question,
                analytical_context,
                available_data,
            )
            self._emit_progress(self._planner_progress(conversation_plan))
            selected_state = find_selected_analysis_state(
                analytical_context,
                conversation_plan.get("selected_analysis_state_id"),
            )
            feedback_proposal = conversation_plan.get("catalog_feedback_candidate")
            applied_feedback = self._catalog_feedback_applier.apply_if_confirmed(self._request, feedback_proposal)
            if applied_feedback:
                self._emit_progress("Registré una definición de negocio explícita en el catálogo.")
                feedback_proposal = applied_feedback
                conversation_plan = {**conversation_plan, "catalog_feedback_candidate": applied_feedback}
                catalog_feedback = self._catalog_repository.find_feedback_for_request(
                    self._request,
                    [metadata.file_id for metadata in files],
                )
            analytical_context = {
                **analytical_context,
                "conversation_plan": conversation_plan,
                "request_kind": conversation_plan.get("request_kind"),
                "effective_question": conversation_plan.get("effective_question") or self._request.question,
                "chart_intent": bool(conversation_plan.get("chart_request")),
                "selected_analysis_state": selected_state,
                "feedback_proposal": feedback_proposal,
                "applied_feedback": applied_feedback,
            }
            effective_question = str(analytical_context.get("effective_question") or self._request.question)
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
                    "analitrics.analysis_state_count": len(recent_analysis_states),
                    "analitrics.selected_analysis_state_id": conversation_plan.get("selected_analysis_state_id"),
                    "analitrics.conversation_plan_confidence": conversation_plan.get("confidence"),
                    "analitrics.conversation_plan_reason": conversation_plan.get("reason"),
                    "analitrics.last_sql_available": bool((analytical_context.get("last_sql") or {}).get("sql")),
                    "analitrics.last_chart_available": bool(analytical_context.get("last_chart")),
                    "analitrics.feedback_proposal": bool(analytical_context.get("feedback_proposal")),
                    "analitrics.feedback_auto_applied": bool(applied_feedback),
                    "analitrics.pending_clarification": bool(pending_clarification),
                    "analitrics.needs_clarification": bool(conversation_plan.get("needs_clarification")),
                },
            )
            return {
                **state,
                "question": effective_question,
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
            self._emit_progress("Verificando que la solicitud pertenezca a los datos cargados...")
            analytical_context = state.get("analytical_context") or {}
            conversation_plan = analytical_context.get("conversation_plan") or {}
            if conversation_plan.get("request_kind") == "out_of_scope":
                self._emit_progress("La solicitud no corresponde al análisis de los archivos del chat.")
                answer = str(
                    conversation_plan.get("reason")
                    or "Solo puedo responder preguntas relacionadas con la data cargada en este chat."
                )
                self._emit_tokens(answer)
                set_span_attrs(
                    span,
                    {
                        "analitrics.in_scope": False,
                        "analitrics.scope_reason": "conversation_plan_out_of_scope",
                        "analitrics.request_kind": "out_of_scope",
                        "analitrics.requires_sql": False,
                    },
                )
                return {
                    **state,
                    "analytical_context": analytical_context,
                    "in_scope": False,
                    "scope_reason": "conversation_plan_out_of_scope",
                    "answer": answer,
                    "rows": [],
                    "sql": "",
                    "chart_spec": {"chart_required": False, "chart_intent": False, "renderer": "recharts", "spec": None},
                }
            if conversation_plan.get("needs_clarification") and not analytical_context.get("feedback_proposal"):
                self._emit_progress("La pregunta admite más de una lectura; pediré una aclaración antes de consultar.")
                pending = {
                    "pending": True,
                    "original_question": self._request.question,
                    "created_message_id": self._request.message_id,
                    "created_run_id": self._request.run_id,
                    "conversation_plan": conversation_plan,
                    "candidate_states": (analytical_context.get("previous_analysis_states") or [])[-5:],
                    "clarification_question": conversation_plan.get("clarification_question"),
                    "reason": conversation_plan.get("reason") or "El LLM pidió aclaración por baja confianza.",
                }
                self._catalog_repository.save_pending_clarification(self._request, pending)
                answer = str(pending.get("clarification_question") or "Necesito una aclaración para continuar.")
                self._emit_tokens(answer)
                set_span_attrs(
                    span,
                    {
                        "analitrics.pending_clarification_saved": True,
                        "analitrics.pending_clarification_reason": pending.get("reason"),
                    },
                )
                return {
                    **state,
                    "analytical_context": {
                        **analytical_context,
                        "pending_clarification_request": pending,
                    },
                    "in_scope": False,
                    "scope_reason": "clarification_required",
                    "answer": answer,
                }
            if analytical_context.get("pending_clarification"):
                self._catalog_repository.clear_pending_clarification(self._request)
            if conversation_plan.get("requires_sql") is False:
                self._emit_progress("No necesito ejecutar SQL para esta respuesta; aplicaré la decisión conversacional.")
                answer = self._direct_plan_answer(conversation_plan)
                self._emit_tokens(answer)
                set_span_attrs(
                    span,
                    {
                        "analitrics.in_scope": True,
                        "analitrics.scope_reason": "conversation_plan_requires_no_sql",
                        "analitrics.requires_sql": False,
                    },
                )
                return {
                    **state,
                    "analytical_context": analytical_context,
                    "in_scope": True,
                    "scope_reason": "conversation_plan_requires_no_sql",
                    "answer": answer,
                    "rows": [],
                    "sql": "",
                        "chart_spec": {"chart_required": False, "chart_intent": False, "renderer": "recharts", "spec": None},
                }
            if conversation_plan.get("requires_sql") is True and not conversation_plan.get("needs_clarification"):
                reason = str(conversation_plan.get("reason") or "conversation_plan_in_scope")
                self._emit_progress("La pregunta está dentro del alcance; prepararé una consulta segura.")
                set_span_attrs(
                    span,
                    {
                        "analitrics.in_scope": True,
                        "analitrics.scope_reason": reason,
                        "analitrics.scope_decision_source": "conversation_plan",
                    },
                )
                return {
                    **state,
                    "analytical_context": analytical_context,
                    "in_scope": True,
                    "scope_reason": reason,
                }
            result = self._llm_client.complete_json(
                system=SCOPE_SYSTEM_PROMPT,
                payload={
                    "question": state["question"],
                    "available_data": self._schema_context_builder.build(
                        state["files"],
                        state["profiles"],
                        state.get("catalog_feedback") or [],
                    ),
                    "analytical_context": analytical_context,
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
                    "analytical_context": analytical_context,
                    "in_scope": False,
                    "scope_reason": reason,
                    "answer": "Solo puedo responder preguntas relacionadas con la data cargada en este chat.",
                }
            return {**state, "analytical_context": analytical_context, "in_scope": True, "scope_reason": reason}

    def generate_sql(self, state: AgentState) -> AgentState:
        with self._tracer.start_as_current_span("generate_sql") as span:
            self._emit_progress("Traduciendo la intención analítica a SQL de solo lectura...")
            generated = self._sql_generator.generate(
                state["question"],
                state["files"],
                state["profiles"],
                None,
                state.get("catalog_feedback") or [],
                state.get("analytical_context") or {},
                self._require_workspace(),
                self._emit_progress,
            )
            plan = {
                "sql": generated.sql,
                "rationale": generated.rationale,
                "backend": generated.backend,
                "data_strategy": generated.data_strategy or {},
            }
            self._emit_progress("SQL generado; ahora verifico que solo lea tablas permitidas.")
            set_span_attrs(
                span,
                {
                    "analitrics.sql": generated.sql,
                    "analitrics.sql_rationale": generated.rationale,
                    "analitrics.sql_generator": generated.backend,
                    "analitrics.data_strategy": generated.data_strategy or {},
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
                    self._emit_progress("SQL validado con sqlglot, allowlist de tablas y EXPLAIN de DuckDB.")
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
                        return {
                            **state,
                            "sql": sql,
                            "plan": plan,
                            "sql_validation_attempt": attempt + 1,
                            "sql_repaired": True,
                        }
                    return {**state, "sql_validation_attempt": attempt + 1, "sql_repaired": attempt > 0}
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
                        self._emit_progress("El SQL necesita reparación; pediré una versión corregida manteniendo solo lectura.")
                        repaired = self._repair_sql({**state, "sql": sql}, error)
                        sql = repaired["sql"]
                        set_span_attrs(span, {"analitrics.repaired_sql": sql})
                        continue
                    span.set_status(Status(StatusCode.ERROR, error))
                    raise
            return state

    def execute_sql(self, state: AgentState) -> AgentState:
        with self._tracer.start_as_current_span("execute_sql") as span:
            self._emit_progress("Ejecutando la consulta dentro del DuckDB aislado del chat...")
            rows_df = self._require_workspace().connection.execute(state["sql"]).fetchdf()
            rows = json.loads(rows_df.to_json(orient="records", date_format="iso"))
            self._emit_progress(f"La consulta devolvió {len(rows):,} fila(s); prepararé una lectura ejecutiva.")
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
            self._emit_progress("Sintetizando la respuesta con los resultados principales...")
            chart_intent = self._chart_intent(state)
            chart_instruction = (
                "La respuesta tendrá un gráfico interactivo con los mismos datos. "
                "No incluyas tablas markdown, rankings extensos ni listas fila por fila; el gráfico prevalece. "
                "Redacta solo 1 o 2 frases con la lectura gerencial principal."
                if chart_intent
                else "Si el usuario pide tabla, puedes usar una tabla markdown breve."
            )
            answer = self._llm_client.complete_text(
                system=(
                    "Responde en español, breve y gerencial, usando solo los resultados entregados. "
                    "No menciones data_strategy ni nombres técnicos de tablas. "
                    "Solo explica consolidación o limitación si se usaron varias tablas o no se pudo combinar. "
                    "No afirmes que faltan campos si solo no aparecen en rows. "
                    "No escribas código, SQL, Mermaid ni instrucciones para graficar; el gráfico lo renderiza otro componente. "
                    + chart_instruction
                ),
                payload={
                    "question": state["question"],
                    "sql": self._compact_sql(state.get("sql") or ""),
                    "data_strategy": (state.get("plan") or {}).get("data_strategy") or {},
                    "rows": self._rows_for_answer(state),
                    "row_count": len(state.get("rows") or []),
                },
                model_env="ANALITRICS_ANSWER_MODEL",
                default_model="gpt-5.5",
            )
            answer = sanitize_answer_text(answer, remove_tables=chart_intent)
            answer = self._append_feedback_proposal(answer, state.get("analytical_context") or {})
            self._emit_tokens(answer)
            set_span_attrs(
                span,
                {
                    "analitrics.answer_preview": answer[:500],
                    "analitrics.chart_intent": chart_intent,
                    "analitrics.feedback_proposal": bool((state.get("analytical_context") or {}).get("feedback_proposal")),
                },
            )
            return {**state, "answer": answer}

    def critique_answer(self, state: AgentState) -> AgentState:
        with self._tracer.start_as_current_span("critique_answer") as span:
            chart_intent = self._chart_intent(state)
            if self._should_skip_critic(state):
                self._emit_progress("La consulta fue simple y validada; omito revisión profunda para responder más rápido.")
                critic = {
                    "approved": True,
                    "issue": None,
                    "revised_answer": None,
                    "skipped": True,
                    "reason": "Simple validated response; critic skipped.",
                }
                set_span_attrs(
                    span,
                    {
                        "analitrics.critic_skipped": True,
                        "analitrics.critic_skip_reason": critic["reason"],
                    },
                )
                return {**state, "critic": critic}
            self._emit_progress("Revisando consistencia entre pregunta, SQL y respuesta antes de cerrar.")
            chart_instruction = (
                "Si habrá gráfico interactivo, no agregues tablas markdown, rankings extensos ni listas fila por fila. "
                "Deja solo una lectura ejecutiva breve."
                if chart_intent
                else ""
            )
            critic = self._llm_client.complete_json(
                system=(
                    "Valida respuesta contra pregunta, SQL, rows y data_strategy. "
                    "Falla solo si no responde, contradice resultados/estrategia o inventa campos. "
                    "No agregues código, SQL ni instrucciones de gráfico. "
                    + chart_instruction
                    + " Responde JSON compacto: approved(boolean), issue(string|null), revised_answer(string|null). "
                    "Si approved=true, issue=null y revised_answer=null."
                ),
                payload={
                    "question": state["question"],
                    "sql": self._compact_sql(state.get("sql") or ""),
                    "data_strategy": (state.get("plan") or {}).get("data_strategy") or {},
                    "rows": self._rows_for_critic(state),
                    "row_count": len(state.get("rows") or []),
                    "answer": state["answer"],
                },
                model_env="ANALITRICS_CRITIC_MODEL",
                default_model="gpt-5.5",
            )
            answer = critic.get("revised_answer") if critic.get("approved") is False and critic.get("revised_answer") else state["answer"]
            set_span_attrs(
                span,
                {
                    "analitrics.critic_approved": critic.get("approved"),
                    "analitrics.critic_issue": critic.get("issue") or critic.get("issues"),
                    "analitrics.chart_intent": chart_intent,
                },
            )
            return {**state, "critic": critic, "answer": str(answer or state["answer"])}

    def generate_chart_spec(self, state: AgentState) -> AgentState:
        with self._tracer.start_as_current_span("generate_chart_spec") as span:
            chart_intent = self._chart_intent(state)
            if not chart_intent:
                self._emit_progress("No se solicitó gráfico; cerraré con respuesta textual.")
                result = {
                    "chart_required": False,
                    "chart_intent": False,
                    "chart_type": None,
                    "renderer": "recharts",
                    "spec": None,
                    "reason": "El usuario no pidió gráfico.",
                }
                set_span_attrs(
                    span,
                    {
                        "analitrics.chart_required": False,
                        "analitrics.chart_intent": False,
                        "analitrics.chart_skipped": True,
                    },
                )
                return {**state, "chart_spec": result}
            deterministic = self._deterministic_chart_spec(state)
            if deterministic is not None:
                self._emit_progress("El gráfico es directo; generaré la especificación visual sin otra llamada al LLM.")
                set_span_attrs(
                    span,
                    {
                        "analitrics.chart_required": deterministic.get("chart_required"),
                        "analitrics.chart_intent": deterministic.get("chart_intent"),
                        "analitrics.chart_type": deterministic.get("chart_type"),
                        "analitrics.chart_renderer": deterministic.get("renderer"),
                        "analitrics.chart_deterministic": True,
                    },
                )
                return {**state, "chart_spec": deterministic}
            self._emit_progress("El gráfico requiere una especificación más cuidadosa; prepararé la visualización.")
            result = self._chart_spec_generator.generate(
                state["question"],
                self._compact_sql(state.get("sql") or ""),
                self._rows_for_chart(state),
                state.get("analytical_context") or {},
            )
            set_span_attrs(
                span,
                {
                    "analitrics.chart_required": result.get("chart_required"),
                    "analitrics.chart_intent": result.get("chart_intent"),
                    "analitrics.chart_type": result.get("chart_type"),
                    "analitrics.chart_renderer": result.get("renderer"),
                    "analitrics.chart_reason": result.get("reason"),
                },
            )
            return {**state, "chart_spec": result}

    def persist_analysis_state(self, state: AgentState) -> AgentState:
        with self._tracer.start_as_current_span("persist_analysis_state") as span:
            self._emit_progress("Guardando el estado analítico para futuras preguntas del chat.")
            analysis_state = self._analysis_state_builder.build(self._request, state)
            saved_state = self._catalog_repository.save_analysis_state(self._request, analysis_state)
            set_span_attrs(
                span,
                {
                    "analitrics.analysis_state_saved": bool(saved_state),
                    "analitrics.analysis_state_id": (saved_state or {}).get("state_id"),
                    "analitrics.analysis_state_intent": (saved_state or analysis_state or {}).get("intent"),
                    "analitrics.analysis_state_metric": (saved_state or analysis_state or {}).get("metric"),
                },
            )
            return {**state, "analysis_state": saved_state or analysis_state or {}}

    def route_after_scope(self, state: AgentState) -> Literal["generate_sql", "persist_analysis_state", "__end__"]:
        plan = (state.get("analytical_context") or {}).get("conversation_plan") or {}
        if state.get("in_scope") and plan.get("requires_sql") is not False:
            return "generate_sql"
        if state.get("in_scope") and (state.get("analytical_context") or {}).get("feedback_proposal"):
            return "persist_analysis_state"
        return "__end__"

    def _repair_sql(self, state: AgentState, error: str) -> dict[str, str]:
        repaired = self._sql_generator.repair(
            question=state["question"],
            files=state["files"],
            profiles=state["profiles"],
            failed_sql=state["sql"],
            error=error,
            context_messages=None,
            catalog_feedback=state.get("catalog_feedback") or [],
            analytical_context=state.get("analytical_context") or {},
            workspace=self._require_workspace(),
            progress=self._emit_progress,
        )
        return {"sql": repaired.sql, "rationale": repaired.rationale}

    def _require_workspace(self) -> DuckDbWorkspace:
        if self._runtime.workspace is None:
            raise RuntimeError("DuckDB workspace is not initialized")
        return self._runtime.workspace

    def _emit_progress(self, message: str) -> None:
        span = trace.get_current_span()
        if span is not None:
            span.add_event("analitrics.progress", {"message": message})
        if self._progress is not None:
            self._progress(message)

    def _emit_tokens(self, text: str) -> None:
        if self._token is None:
            return
        for index in range(0, len(text), 24):
            self._token(text[index : index + 24])

    def _chart_intent(self, state: AgentState) -> bool:
        plan = (state.get("analytical_context") or {}).get("conversation_plan") or {}
        if isinstance(plan, dict) and plan.get("chart_request") is not None:
            return bool(plan.get("chart_request"))
        return self._has_chart_intent(state.get("question") or "")

    def _planner_progress(self, conversation_plan: dict[str, Any]) -> str:
        request_kind = str(conversation_plan.get("request_kind") or "analysis")
        confidence = str(conversation_plan.get("confidence") or "media")
        selected_state_id = conversation_plan.get("selected_analysis_state_id")
        if request_kind == "out_of_scope":
            return "Detecté que la solicitud está fuera del alcance de los datos cargados."
        if conversation_plan.get("needs_clarification"):
            return "Detecté ambigüedad suficiente para pedir una aclaración antes de consultar."
        if request_kind == "correction":
            return "Detecté una corrección o definición de negocio y la contrasto con el catálogo."
        if request_kind == "follow_up":
            suffix = (
                f" usando el estado analítico {selected_state_id}"
                if selected_state_id
                else " usando el contexto reciente"
            )
            return f"Detecté una pregunta de seguimiento{suffix}; confianza {confidence}."
        if conversation_plan.get("chart_request"):
            return f"Detecté una solicitud analítica con visualización; confianza {confidence}."
        return f"Detecté una pregunta analítica nueva; confianza {confidence}."

    def _has_chart_intent(self, question: str) -> bool:
        normalized = question.lower()
        return any(term in normalized for term in CHART_INTENT_TERMS)

    def _chart_type(self, question: str) -> str:
        normalized = question.lower()
        if any(term in normalized for term in LINE_CHART_TERMS):
            return "line"
        return "bar"

    def _rows_for_answer(self, state: AgentState) -> list[dict[str, Any]]:
        return (state.get("rows") or [])[:ANSWER_ROW_LIMIT]

    def _rows_for_critic(self, state: AgentState) -> list[dict[str, Any]]:
        return (state.get("rows") or [])[:CRITIC_ROW_LIMIT]

    def _rows_for_chart(self, state: AgentState) -> list[dict[str, Any]]:
        return (state.get("rows") or [])[:CHART_ROW_LIMIT]

    def _compact_sql(self, sql: str) -> str:
        compact = " ".join(str(sql or "").split())
        if len(compact) <= COMPACT_SQL_CHARS:
            return compact
        return compact[:COMPACT_SQL_CHARS].rstrip() + " ..."

    def _should_skip_critic(self, state: AgentState) -> bool:
        plan = (state.get("analytical_context") or {}).get("conversation_plan") or {}
        if self._chart_intent(state):
            return False
        if state.get("sql_repaired"):
            return False
        if int(state.get("sql_validation_attempt") or 0) != 1:
            return False
        if not state.get("rows"):
            return False
        if plan.get("confidence") not in {"high", "medium"}:
            return False
        return True

    def _deterministic_chart_spec(self, state: AgentState) -> dict[str, Any] | None:
        rows = self._rows_for_chart(state)
        if not rows:
            return None
        plan = (state.get("analytical_context") or {}).get("conversation_plan") or {}
        chart_type = str(plan.get("chart_type") or "bar")
        if chart_type not in {"bar", "line"}:
            return None
        columns = list(rows[0].keys())
        text_columns = [
            key
            for key in columns
            if any(isinstance(row.get(key), str) for row in rows[:5])
        ]
        numeric_columns = [
            key
            for key in columns
            if any(isinstance(row.get(key), (int, float)) and not isinstance(row.get(key), bool) for row in rows[:5])
        ]
        if len(text_columns) != 1 or not numeric_columns:
            return None
        x_key = text_columns[0]
        y_key = numeric_columns[0]
        return {
            "chart_required": True,
            "chart_intent": True,
            "chart_type": chart_type,
            "renderer": "recharts",
            "spec": {
                "title": str(plan.get("effective_question") or state.get("question") or "")[:120],
                "x_key": x_key,
                "y_keys": [y_key],
                "series": rows,
                "sort": "preserve",
                "limit": len(rows),
                "value_format": "number",
                "category_label": x_key,
                "notes": "Grafico simple generado sin llamada LLM adicional.",
            },
            "reason": "Grafico simple detectado desde columnas resultantes.",
        }

    def _append_feedback_proposal(self, answer: str, analytical_context: dict[str, Any]) -> str:
        proposal = analytical_context.get("feedback_proposal")
        if not isinstance(proposal, dict) or not proposal.get("suggested"):
            return answer
        filename = proposal.get("source_filename")
        target = f" para {filename}" if filename else ""
        if proposal.get("applied"):
            note = (
                "\n\nRegistré esta definición en el catálogo"
                f"{target}. Puedes revisarla o editarla desde el panel derecho."
            )
            return answer.rstrip() + note
        note = (
            "\n\nDetecté una corrección que podría enriquecer el catálogo"
            f"{target}. Puedes guardarla desde el panel derecho si quieres que afecte futuras consultas."
        )
        return answer.rstrip() + note

    def _direct_plan_answer(self, conversation_plan: dict[str, Any]) -> str:
        feedback = conversation_plan.get("catalog_feedback_candidate")
        if isinstance(feedback, dict) and feedback.get("content"):
            if feedback.get("applied"):
                return (
                    "Registré esta definición de negocio en el catálogo:\n\n"
                    f"{feedback.get('content')}\n\n"
                    "Puedes revisarla o editarla desde el panel derecho."
                )
            return (
                "Detecté una corrección o definición de negocio para enriquecer el catálogo:\n\n"
                f"{feedback.get('content')}\n\n"
                "Puedes confirmarla desde el panel derecho para que afecte futuras consultas."
            )
        clarification = conversation_plan.get("clarification_question")
        if clarification:
            return str(clarification)
        return str(conversation_plan.get("reason") or "Entendido. No necesito ejecutar una consulta para esta actualización.")
