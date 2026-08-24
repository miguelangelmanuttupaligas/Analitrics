from __future__ import annotations

import warnings
from typing import Any, Callable

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

from .duckdb_workspace import DuckDbTableCatalog, DuckDbWorkspaceFactory, ProfileEnricher
from .config import env
from .control_plane import CatalogRepository, PostgresControlPlaneFactory
from .file_resolver import FileResolver
from .llm_client import JsonLlmClient
from .models import AgentRequest, AgentState
from .nodes import AgentRuntime, AnalyticalAgentNodes
from .repositories import (
    AgentRunRepository,
    ConversationAttachmentRepository,
    MongoDatabaseFactory,
)
from .schema_context import SchemaContextBuilder
from .sql_generation import SqlGeneratorFactory
from .sql_validation import SqlReadOnlyValidator
from .tracing import TracingManager, current_trace_id, normalize_search_text, set_span_attrs, stable_text_hash


class AnalyticalAgent:
    def __init__(
        self,
        tracing_manager: TracingManager,
        run_repository: AgentRunRepository,
        nodes_factory: "AnalyticalAgentNodesFactory",
    ) -> None:
        self._tracing_manager = tracing_manager
        self._run_repository = run_repository
        self._nodes_factory = nodes_factory

    def run(
        self,
        request: AgentRequest,
        progress: Callable[[str], None] | None = None,
        token: Callable[[str], None] | None = None,
    ) -> AgentState:
        def emit(message: str) -> None:
            if progress is not None:
                progress(message)

        self._tracing_manager.setup()
        runtime = AgentRuntime()
        result: AgentState | None = None
        trace_id: str | None = None
        try:
            with self._tracing_manager.tracer.start_as_current_span("analitrics_agent_run") as span:
                trace_id = current_trace_id(span)
                set_span_attrs(
                    span,
                    {
                        "input.value": request.question,
                        "analitrics.question": request.question,
                        "analitrics.question_normalized": normalize_search_text(request.question),
                        "analitrics.question_hash": stable_text_hash(request.question),
                        "analitrics.trace_id": trace_id,
                        "analitrics.run_id": request.run_id,
                        "analitrics.tenant_id": request.tenant_id,
                        "analitrics.user_id": request.user_id,
                        "analitrics.conversation_id": request.conversation_id,
                        "analitrics.message_id": request.message_id,
                        "analitrics.file_id_arg": request.file_id,
                        "analitrics.file_ids_arg": request.file_ids,
                        "analitrics.filename_arg": request.filename,
                        "analitrics.filenames_arg": request.filenames,
                        "analitrics.context_message_count": len(request.context_messages or []),
                        "analitrics.engine": env("ANALITRICS_ENGINE", "langgraph"),
                    },
                )
                if env("ANALITRICS_ENGINE", "langgraph").strip().lower() != "langgraph":
                    raise RuntimeError("Only ANALITRICS_ENGINE=langgraph is supported in the active MVP runtime")
                nodes = self._nodes_factory.create(request, runtime, self._tracing_manager.tracer, progress, token)
                app = self._build_graph(nodes)
                result = app.invoke({"question": request.question, "run_id": request.run_id or ""})
                result["trace_id"] = trace_id or ""
                set_span_attrs(
                    span,
                    {
                        "output.value": result.get("answer"),
                        "analitrics.engine": result.get("engine") or "langgraph",
                        "analitrics.in_scope": result.get("in_scope"),
                        "analitrics.sql": result.get("sql"),
                        "analitrics.row_count": len(result.get("rows") or []),
                        "analitrics.chart_required": (result.get("chart_spec") or {}).get("chart_required")
                        if isinstance(result.get("chart_spec"), dict)
                        else None,
                    },
                )
            self._run_repository.save_run(request, result, trace_id=trace_id)
            return result
        except Exception as exc:
            if "conversation/message with attachments" in str(exc):
                result = {
                    "question": request.question,
                    "run_id": request.run_id or "",
                    "files": [],
                    "profiles": [],
                    "in_scope": False,
                    "scope_reason": "No tabular files were found in the current analytical context.",
                    "plan": {"backend": env("ANALITRICS_ENGINE", "langgraph"), "sql": "", "rationale": "No data file available."},
                    "sql": "",
                    "rows": [],
                    "answer": "Necesito que cargues o mantengas en la conversación al menos un archivo CSV o Excel para poder analizar datos.",
                    "critic": {"approved": True, "issues": [], "backend": env("ANALITRICS_ENGINE", "langgraph")},
                    "chart_spec": {"chart_required": False, "reason": "No data file available."},
                    "cache_path": "",
                    "cache_hits": 0,
                    "engine": env("ANALITRICS_ENGINE", "langgraph"),
                    "trace_id": trace_id or "",
                }
                self._run_repository.save_run(request, result, trace_id=trace_id)
                return result
            self._run_repository.save_run(request, result, error=str(exc), trace_id=trace_id)
            raise
        finally:
            runtime.close()
            self._tracing_manager.shutdown()

    def _build_graph(self, nodes: AnalyticalAgentNodes) -> Any:
        graph = StateGraph(AgentState)
        graph.add_node("resolve_and_profile", nodes.resolve_and_profile)
        graph.add_node("check_question_scope", nodes.check_question_scope)
        graph.add_node("generate_sql", nodes.generate_sql)
        graph.add_node("validate_sql", nodes.validate_sql)
        graph.add_node("execute_sql", nodes.execute_sql)
        graph.add_node("compose_answer", nodes.compose_answer)
        graph.add_node("critique_answer", nodes.critique_answer)
        graph.add_node("generate_chart_spec", nodes.generate_chart_spec)
        graph.add_node("persist_analysis_state", nodes.persist_analysis_state)

        graph.set_entry_point("resolve_and_profile")
        graph.add_edge("resolve_and_profile", "check_question_scope")
        graph.add_conditional_edges(
            "check_question_scope",
            nodes.route_after_scope,
            {"generate_sql": "generate_sql", "persist_analysis_state": "persist_analysis_state", "__end__": END},
        )
        graph.add_edge("generate_sql", "validate_sql")
        graph.add_edge("validate_sql", "execute_sql")
        graph.add_edge("execute_sql", "compose_answer")
        graph.add_edge("compose_answer", "critique_answer")
        graph.add_edge("critique_answer", "generate_chart_spec")
        graph.add_edge("generate_chart_spec", "persist_analysis_state")
        graph.add_edge("persist_analysis_state", END)
        return graph.compile()


class AnalyticalAgentNodesFactory:
    def __init__(
        self,
        catalog_repository: CatalogRepository,
        file_resolver: FileResolver,
        workspace_factory: DuckDbWorkspaceFactory,
        profile_enricher: ProfileEnricher,
        table_catalog: DuckDbTableCatalog,
        schema_context_builder: SchemaContextBuilder,
        sql_validator: SqlReadOnlyValidator,
    ) -> None:
        self._catalog_repository = catalog_repository
        self._file_resolver = file_resolver
        self._workspace_factory = workspace_factory
        self._profile_enricher = profile_enricher
        self._table_catalog = table_catalog
        self._schema_context_builder = schema_context_builder
        self._sql_validator = sql_validator

    def create(
        self,
        request: AgentRequest,
        runtime: AgentRuntime,
        tracer: Any,
        progress: Callable[[str], None] | None = None,
        token: Callable[[str], None] | None = None,
    ) -> AnalyticalAgentNodes:
        llm_client = JsonLlmClient(tracer)
        return AnalyticalAgentNodes(
            request=request,
            runtime=runtime,
            tracer=tracer,
            file_resolver=self._file_resolver,
            workspace_factory=self._workspace_factory,
            profile_enricher=self._profile_enricher,
            table_catalog=self._table_catalog,
            catalog_repository=self._catalog_repository,
            schema_context_builder=self._schema_context_builder,
            llm_client=llm_client,
            sql_generator=SqlGeneratorFactory.create(llm_client, self._schema_context_builder),
            sql_validator=self._sql_validator,
            progress=progress,
            token=token,
        )


class AnalyticalAgentFactory:
    _instance: AnalyticalAgent | None = None

    @classmethod
    def get_agent(cls) -> AnalyticalAgent:
        if cls._instance is None:
            cls._instance = cls.create_agent()
        return cls._instance

    @classmethod
    def create_agent(cls) -> AnalyticalAgent:
        database_factory = MongoDatabaseFactory()
        catalog_repository = CatalogRepository(PostgresControlPlaneFactory())
        run_repository = AgentRunRepository(database_factory)
        attachment_repository = ConversationAttachmentRepository(database_factory)
        table_catalog = DuckDbTableCatalog()
        file_resolver = FileResolver(attachment_repository)
        nodes_factory = AnalyticalAgentNodesFactory(
            catalog_repository=catalog_repository,
            file_resolver=file_resolver,
            workspace_factory=DuckDbWorkspaceFactory(catalog_repository, table_catalog=table_catalog),
            profile_enricher=ProfileEnricher(),
            table_catalog=table_catalog,
            schema_context_builder=SchemaContextBuilder(),
            sql_validator=SqlReadOnlyValidator(),
        )
        return AnalyticalAgent(
            tracing_manager=TracingManager(),
            run_repository=run_repository,
            nodes_factory=nodes_factory,
        )
