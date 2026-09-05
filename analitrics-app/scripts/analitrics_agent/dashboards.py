from __future__ import annotations

import json
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

import duckdb
from opentelemetry import trace

from .config import env
from .control_plane import CatalogRepository, PostgresControlPlaneFactory
from .chart_contract import AnalitricsChartSpecNormalizer
from .llm_client import JsonLlmClient
from .repositories import AgentRunRepository
from .sql_validation import SqlReadOnlyValidator


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class DashboardFeedbackPreferences:
    def __init__(
        self,
        preferred_metrics: list[str] | None = None,
        preferred_dimensions: list[str] | None = None,
        avoid_dimensions: list[str] | None = None,
        applied_feedback_ids: list[str] | None = None,
        reasons: list[str] | None = None,
    ) -> None:
        self.preferred_metrics = preferred_metrics or []
        self.preferred_dimensions = preferred_dimensions or []
        self.avoid_dimensions = avoid_dimensions or []
        self.applied_feedback_ids = applied_feedback_ids or []
        self.reasons = reasons or []

    def as_dict(self) -> dict[str, Any]:
        return {
            "preferredMetrics": self.preferred_metrics,
            "preferredDimensions": self.preferred_dimensions,
            "avoidDimensions": self.avoid_dimensions,
            "appliedFeedbackIds": self.applied_feedback_ids,
            "reasons": self.reasons,
        }


class DashboardFeedbackIntentSelector:
    NEGATIVE_HINTS = ("no usar", "no uses", "evitar", "excluir", "no considerar", "no lo uses")
    POSITIVE_HINTS = (
        "usar",
        "usa",
        "priorizar",
        "prioriza",
        "corte principal",
        "agrupación",
        "agrupacion",
        "segmentar",
        "desglosar",
        "por ",
        "columna",
    )
    METRIC_HINTS = ("métrica", "metrica", "indicador", "monto", "venta", "ingreso", "ticket", "cantidad", "suma")

    def select(self, context: dict[str, Any]) -> DashboardFeedbackPreferences:
        feedback = [item for item in context.get("feedback") or [] if isinstance(item, dict)]
        tables = [table for table in context.get("tables") or [] if isinstance(table, dict)]
        column_names = self._column_names(tables)
        metrics = self._column_names(tables, numeric=True)
        dimensions = [name for name in column_names if name not in metrics]

        preferred_metrics: list[str] = []
        preferred_dimensions: list[str] = []
        avoid_dimensions: list[str] = []
        applied_feedback_ids: list[str] = []
        reasons: list[str] = []

        for item in feedback:
            text = self._normalize(" ".join([str(item.get("label") or ""), str(item.get("content") or "")]))
            matched = False
            for name in dimensions:
                normalized = self._normalize(name)
                if normalized not in text:
                    continue
                if self._has_negative_hint(text, normalized):
                    self._append_unique(avoid_dimensions, name)
                    matched = True
                elif self._has_positive_hint(text):
                    self._append_unique(preferred_dimensions, name)
                    matched = True
            for name in metrics:
                normalized = self._normalize(name)
                if normalized in text and (self._has_positive_hint(text) or self._has_metric_hint(text)):
                    self._append_unique(preferred_metrics, name)
                    matched = True
            if matched:
                feedback_id = item.get("feedbackId") or item.get("feedback_id")
                if feedback_id is not None:
                    self._append_unique(applied_feedback_ids, str(feedback_id))
                content = str(item.get("content") or "").strip()
                if content:
                    reasons.append(content[:240])

        return DashboardFeedbackPreferences(
            preferred_metrics=preferred_metrics,
            preferred_dimensions=[name for name in preferred_dimensions if name not in avoid_dimensions],
            avoid_dimensions=avoid_dimensions,
            applied_feedback_ids=applied_feedback_ids,
            reasons=reasons,
        )

    def _column_names(self, tables: list[dict[str, Any]], numeric: bool | None = None) -> list[str]:
        names: list[str] = []
        for table in tables:
            if table.get("systemTable"):
                continue
            for column in table.get("columns") or []:
                if not isinstance(column, dict):
                    continue
                name = str(column.get("name") or "").strip()
                if not name:
                    continue
                is_numeric = any(
                    token in str(column.get("type") or "").lower()
                    for token in ("decimal", "double", "float", "real", "numeric", "int", "bigint")
                )
                if numeric is not None and is_numeric is not numeric:
                    continue
                self._append_unique(names, name)
        return names

    def _has_negative_hint(self, text: str, normalized_column: str) -> bool:
        for hint in self.NEGATIVE_HINTS:
            index = text.find(hint)
            if index < 0:
                continue
            window = text[index : index + 120]
            if normalized_column in window:
                return True
        return False

    def _has_positive_hint(self, text: str) -> bool:
        return any(hint in text for hint in self.POSITIVE_HINTS)

    def _has_metric_hint(self, text: str) -> bool:
        return any(hint in text for hint in self.METRIC_HINTS)

    def _normalize(self, value: str) -> str:
        return " ".join(value.lower().replace("_", " ").replace("-", " ").split())

    def _append_unique(self, values: list[str], value: str) -> None:
        if value and value not in values:
            values.append(value)


class DashboardCatalogHasher:
    GENERATION_VERSION = "2026-08-30-feedback-v2"

    def hash(self, context: dict[str, Any], preferences: DashboardFeedbackPreferences) -> str:
        payload = {
            "generationVersion": self.GENERATION_VERSION,
            "summary": context.get("summary") or {},
            "files": self._stable_files(context.get("files") or []),
            "tables": self._stable_tables(context.get("tables") or []),
            "feedback": self._stable_feedback(context.get("feedback") or []),
            "derivedMetrics": context.get("derivedMetrics") or [],
            "preferences": preferences.as_dict(),
        }
        raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
        return "sha256:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def _stable_files(self, files: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return sorted(
            [
                {
                    "fileId": item.get("file_id") or item.get("fileId"),
                    "filename": item.get("filename") or item.get("name"),
                    "signature": item.get("signature"),
                    "contentHash": item.get("contentHash") or item.get("content_hash"),
                    "bytes": item.get("bytes"),
                }
                for item in files
                if isinstance(item, dict)
            ],
            key=lambda item: str(item.get("fileId") or item.get("filename") or ""),
        )

    def _stable_tables(self, tables: list[dict[str, Any]]) -> list[dict[str, Any]]:
        stable = []
        for table in tables:
            if not isinstance(table, dict):
                continue
            stable.append(
                {
                    "table": table.get("table"),
                    "sourceFileId": table.get("sourceFileId") or table.get("source_file_id"),
                    "sourceFilename": table.get("sourceFilename") or table.get("source_filename"),
                    "rowCount": table.get("rowCount") or table.get("row_count"),
                    "systemTable": table.get("systemTable") or table.get("system_table"),
                    "columns": [
                        {
                            "name": column.get("name"),
                            "type": column.get("type"),
                            "distinctCount": column.get("distinct_count") or column.get("distinctCount"),
                            "nullRatio": column.get("null_ratio") or column.get("nullRatio"),
                        }
                        for column in table.get("columns") or []
                        if isinstance(column, dict)
                    ],
                }
            )
        return sorted(stable, key=lambda item: str(item.get("table") or ""))

    def _stable_feedback(self, feedback: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return sorted(
            [
                {
                    "feedbackId": item.get("feedbackId") or item.get("feedback_id"),
                    "sourceFileId": item.get("sourceFileId") or item.get("source_file_id"),
                    "step": item.get("step"),
                    "label": item.get("label"),
                    "content": item.get("content"),
                    "updatedAt": item.get("updatedAt") or item.get("updated_at"),
                }
                for item in feedback
                if isinstance(item, dict)
            ],
            key=lambda item: str(item.get("feedbackId") or ""),
        )


class DashboardReadiness:
    def validate(self, context: dict[str, Any]) -> None:
        pending_clarification = context.get("pendingClarification") or context.get("pending_clarification")
        if pending_clarification:
            raise RuntimeError(
                "Dashboard cannot be created while the analytical agent is waiting for a clarification"
            )

        if not self._latest_sql_state(context):
            raise RuntimeError(
                "Dashboard requires at least one completed analytical answer with validated SQL"
            )

    def _latest_sql_state(self, context: dict[str, Any]) -> dict[str, Any] | None:
        for state in reversed(context.get("recentAnalysisStates") or []):
            if not isinstance(state, dict):
                continue
            sql = str(state.get("last_sql") or "").strip()
            if not sql:
                continue
            if self._is_low_confidence_or_non_analytical(state):
                continue
            return state
        return None

    def _is_low_confidence_or_non_analytical(self, state: dict[str, Any]) -> bool:
        nested = state.get("state") if isinstance(state.get("state"), dict) else {}
        confidence = str(nested.get("confidence") or "").strip().lower()
        conversation_plan = nested.get("conversation_plan") if isinstance(nested.get("conversation_plan"), dict) else {}
        intent = str(state.get("intent") or conversation_plan.get("request_kind") or "").strip().lower()
        return confidence == "low" or intent in {"metadata_literal", "out_of_scope"}


DASHBOARD_INSTRUCTION_SYSTEM_PROMPT = (
    "Eres planificador de edición de dashboard analítico. Convierte la instrucción del usuario en una operación "
    "sobre gráficos existentes, sin responder narrativa. Usa solo tablas, columnas, feedback y métricas derivadas "
    "disponibles. Si el usuario pide una métrica derivada, define su cálculo de forma estructurada. "
    "Devuelve solo JSON compacto con keys: operation(add_chart|replace_chart|remove_chart|change_dimension|"
    "change_metric|change_chart_type), target_view_id(string|null), title(string|null), chart_type(bar|line|pie|null), "
    "table(string|null), metric(string|null), dimensions(array), filters(array), derived_metric(object|null), "
    "reason(string). derived_metric si aplica: name,label,kind(sum|avg|count|count_distinct|share_of_sum), "
    "value_column, distinct_column, base_metric, description. No inventes columnas; si no hay base suficiente, "
    "usa operation=add_chart con campos nulos y explica en reason."
)


class DashboardInstructionPlanner:
    def __init__(self, llm_client: JsonLlmClient | None = None) -> None:
        self._llm_client = llm_client or JsonLlmClient(trace.get_tracer(__name__))

    def plan(self, instruction: str, dashboard: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        payload = {
            "instruction": instruction,
            "dashboard": {
                "dashboard_id": dashboard.get("dashboardId") or dashboard.get("dashboard_id"),
                "title": dashboard.get("title"),
                "views": [
                    {
                        "view_id": view.get("viewId") or view.get("view_id"),
                        "title": view.get("title"),
                        "view_type": view.get("viewType") or view.get("view_type"),
                        "metric": view.get("metric"),
                        "dimensions": view.get("dimensions") or [],
                    }
                    for view in dashboard.get("views", [])
                    if isinstance(view, dict)
                ],
            },
            "available_data": {
                "files": [
                    {
                        "file_id": item.get("file_id") or item.get("fileId"),
                        "filename": item.get("filename") or item.get("name"),
                    }
                    for item in context.get("files") or []
                    if isinstance(item, dict)
                ],
                "tables": [
                    {
                        "table": table.get("table"),
                        "source_file_id": table.get("sourceFileId"),
                        "source_filename": table.get("sourceFilename"),
                        "row_count": table.get("rowCount"),
                        "columns": [
                            {
                                "name": column.get("name"),
                                "type": column.get("type"),
                                "distinct_count": column.get("distinct_count") or column.get("distinctCount"),
                            }
                            for column in table.get("columns") or []
                            if isinstance(column, dict)
                        ],
                    }
                    for table in context.get("tables") or []
                    if isinstance(table, dict) and table.get("table") and not table.get("systemTable")
                ],
                "feedback": context.get("feedback") or [],
                "derived_metrics": context.get("derivedMetrics") or [],
            },
        }
        result = self._llm_client.complete_json(
            system=DASHBOARD_INSTRUCTION_SYSTEM_PROMPT,
            payload=payload,
            model_env="ANALITRICS_DASHBOARD_PLANNER_MODEL",
            default_model=env("ANALITRICS_DEFAULT_MODEL", "gpt-5.5"),
        )
        return result if isinstance(result, dict) else {}


class DashboardRepository:
    def __init__(
        self,
        connection_factory: PostgresControlPlaneFactory,
        catalog_repository: CatalogRepository,
        run_repository: AgentRunRepository,
        sql_validator: SqlReadOnlyValidator | None = None,
        chart_spec_normalizer: AnalitricsChartSpecNormalizer | None = None,
        intent_selector: DashboardFeedbackIntentSelector | None = None,
        catalog_hasher: DashboardCatalogHasher | None = None,
        readiness: DashboardReadiness | None = None,
        instruction_planner: DashboardInstructionPlanner | None = None,
    ) -> None:
        self._connection_factory = connection_factory
        self._catalog_repository = catalog_repository
        self._run_repository = run_repository
        self._sql_validator = sql_validator or SqlReadOnlyValidator()
        self._chart_spec_normalizer = chart_spec_normalizer or AnalitricsChartSpecNormalizer()
        self._intent_selector = intent_selector or DashboardFeedbackIntentSelector()
        self._catalog_hasher = catalog_hasher or DashboardCatalogHasher()
        self._readiness = readiness or DashboardReadiness()
        self._instruction_planner = instruction_planner or DashboardInstructionPlanner()

    def list_dashboards(self, tenant_id: str, user_id: str) -> list[dict[str, Any]]:
        with self._connection_factory.connect() as con:
            rows = con.execute(
                """
                select dashboard_id, conversation_id, title, description, seed_question,
                       source_file_ids, created_at, updated_at
                from analysis_dashboards
                where tenant_id = %s and user_id = %s
                order by updated_at desc
                limit 100
                """,
                (tenant_id, user_id),
            ).fetchall()
        return [self._dashboard_summary(row) for row in rows]

    def create_from_conversation(
        self,
        tenant_id: str,
        user_id: str,
        conversation_id: str,
        title: str | None = None,
    ) -> dict[str, Any]:
        context = self._catalog_repository.get_context(tenant_id, user_id, conversation_id)
        if not context.get("found"):
            raise RuntimeError("No active analytical catalog was found for this conversation")
        files = context.get("files") or []
        if not files:
            raise RuntimeError("At least one active file is required to create a dashboard")
        self._readiness.validate(context)

        known_tables = [str(table.get("table")) for table in context.get("tables") or [] if table.get("table")]
        preferences = self._intent_selector.select(context)
        catalog_hash = self._catalog_hasher.hash(context, preferences)
        now = utc_now()
        source_file_ids = [str(item.get("file_id") or item.get("fileId")) for item in files if item.get("file_id") or item.get("fileId")]
        dashboard_title = (title or self._title_from_context(context)).strip()
        existing_dashboard = self._get_dashboard_by_conversation(tenant_id, user_id, conversation_id)
        if existing_dashboard and self._dashboard_catalog_hash(existing_dashboard) == catalog_hash:
            return self.get_dashboard(tenant_id, user_id, str(existing_dashboard["dashboard_id"]))

        dashboard_id = str(existing_dashboard["dashboard_id"]) if existing_dashboard else f"dash_{uuid4().hex}"
        chart_views = self._build_initial_chart_views(context, known_tables, dashboard_title, preferences)
        if not chart_views:
            raise RuntimeError("No chartable dataset was found in the active analytical catalog")

        with self._connection_factory.connect() as con:
            with con.transaction():
                if existing_dashboard:
                    con.execute(
                        """
                        delete from analysis_dashboard_views
                        where tenant_id = %s and user_id = %s and dashboard_id = %s
                        """,
                        (tenant_id, user_id, dashboard_id),
                    )
                    dashboard = con.execute(
                        """
                        update analysis_dashboards
                        set title = %s,
                            description = %s,
                            seed_question = %s,
                            seed_sql = %s,
                            seed_message_id = %s,
                            seed_run_id = %s,
                            source_file_ids = %s::jsonb,
                            duckdb_path = %s,
                            catalog_snapshot = %s::jsonb,
                            business_context = %s::jsonb,
                            updated_at = %s
                        where tenant_id = %s and user_id = %s and conversation_id = %s
                        returning dashboard_id, conversation_id, title, description, seed_question,
                                  source_file_ids, created_at, updated_at
                        """,
                        (
                            dashboard_title,
                            "Dashboard gráfico de Analitrics.",
                            self._seed_question_from_context(context),
                            chart_views[0]["sql"],
                            None,
                            None,
                            self._json(source_file_ids),
                            context.get("cachePath"),
                            self._json(self._catalog_snapshot(context, catalog_hash)),
                            self._json(self._business_context(context, preferences, catalog_hash, regenerated=True)),
                            now,
                            tenant_id,
                            user_id,
                            conversation_id,
                        ),
                    ).fetchone()
                else:
                    dashboard = con.execute(
                        """
                        insert into analysis_dashboards (
                            dashboard_id, tenant_id, user_id, conversation_id, title, description,
                            seed_question, seed_sql, seed_message_id, seed_run_id, source_file_ids,
                            duckdb_path, catalog_snapshot, business_context, created_at, updated_at
                        )
                        values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb,
                                %s, %s::jsonb, %s::jsonb, %s, %s)
                        returning dashboard_id, conversation_id, title, description, seed_question,
                                  source_file_ids, created_at, updated_at
                        """,
                        (
                            dashboard_id,
                            tenant_id,
                            user_id,
                            conversation_id,
                            dashboard_title,
                            "Dashboard gráfico de Analitrics.",
                            self._seed_question_from_context(context),
                            chart_views[0]["sql"],
                            None,
                            None,
                            self._json(source_file_ids),
                            context.get("cachePath"),
                            self._json(self._catalog_snapshot(context, catalog_hash)),
                            self._json(self._business_context(context, preferences, catalog_hash, regenerated=False)),
                            now,
                            now,
                        ),
                    ).fetchone()
                for position, view in enumerate(chart_views, start=1):
                    con.execute(
                        """
                        insert into analysis_dashboard_views (
                            view_id, dashboard_id, tenant_id, user_id, title, view_type,
                            question, sql, chart_spec, metric, dimensions, filters, source_file_ids,
                            catalog_hash, generation_metadata, position, created_at, updated_at
                        )
                        values (%s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s::jsonb, %s::jsonb,
                                %s::jsonb, %s, %s::jsonb, %s, %s, %s)
                        """,
                        (
                            f"view_{uuid4().hex}",
                            dashboard_id,
                            tenant_id,
                            user_id,
                            view["title"],
                            view["type"],
                            view["question"],
                            view["sql"],
                            self._json(self._chart_spec_with_metadata(view["chart_spec"], view)),
                            view.get("metric"),
                            self._json(view.get("dimensions") or []),
                            self._json(view.get("filters") or []),
                            self._json(view.get("source_file_ids") or source_file_ids),
                            catalog_hash,
                            self._json(view.get("generation_metadata") or self._view_generation_metadata(view, "create_dashboard")),
                            position,
                            now,
                            now,
                        ),
                    )
        return self.get_dashboard(tenant_id, user_id, str(dashboard["dashboard_id"]))

    def get_dashboard(self, tenant_id: str, user_id: str, dashboard_id: str) -> dict[str, Any]:
        with self._connection_factory.connect() as con:
            dashboard = con.execute(
                """
                select dashboard_id, conversation_id, title, description, seed_question,
                       seed_sql, seed_message_id, seed_run_id, source_file_ids, duckdb_path,
                       catalog_snapshot, business_context, created_at, updated_at
                from analysis_dashboards
                where tenant_id = %s and user_id = %s and dashboard_id = %s
                """,
                (tenant_id, user_id, dashboard_id),
            ).fetchone()
            if not dashboard:
                raise RuntimeError("Dashboard not found")
            if self._dashboard_is_stale(tenant_id, user_id, dashboard):
                return self.create_from_conversation(
                    tenant_id,
                    user_id,
                    str(dashboard["conversation_id"]),
                    title=str(dashboard["title"] or ""),
                )
            views = con.execute(
                """
                select view_id, title, view_type, question, sql, chart_spec, metric, dimensions,
                       filters, source_file_ids, catalog_hash, generation_metadata, position, created_at, updated_at
                from analysis_dashboard_views
                where tenant_id = %s and user_id = %s and dashboard_id = %s
                order by position, created_at
                """,
                (tenant_id, user_id, dashboard_id),
            ).fetchall()
        return {**self._dashboard_detail(dashboard), "views": [self._view(row) for row in views]}

    def apply_instruction(
        self,
        tenant_id: str,
        user_id: str,
        dashboard_id: str,
        instruction: str,
    ) -> dict[str, Any]:
        instruction = " ".join(str(instruction or "").split())
        if not instruction:
            raise RuntimeError("instruction is required")
        self._reject_unsafe_instruction(instruction)

        dashboard = self.get_dashboard(tenant_id, user_id, dashboard_id)
        self._reject_ambiguous_target_instruction(instruction, dashboard)
        conversation_id = str(dashboard.get("conversationId") or "")
        context = self._catalog_repository.get_context(tenant_id, user_id, conversation_id)
        if not context.get("found"):
            raise RuntimeError("No active analytical catalog was found for this dashboard")
        preferences = self._intent_selector.select(context)
        catalog_hash = self._catalog_hasher.hash(context, preferences)
        plan = self._instruction_planner.plan(instruction, dashboard, context)
        operation = self._operation(plan)
        target_view_id = self._optional_str(plan.get("target_view_id"))
        if operation != "add_chart" and not target_view_id:
            target_view_id = self._infer_target_view_id(dashboard, plan, instruction)
        if operation != "add_chart" and not target_view_id:
            raise RuntimeError("A target chart is required for dashboard change operations")
        if operation == "remove_chart":
            explanation = self._delete_view(tenant_id, user_id, dashboard_id, target_view_id, instruction, plan)
            return {**self.get_dashboard(tenant_id, user_id, dashboard_id), "lastOperation": explanation}

        view = self._build_view_from_plan(context, plan, instruction, preferences, catalog_hash)
        catalog_hash = str((view.get("generation_metadata") or {}).get("catalogHash") or catalog_hash)
        now = utc_now()
        with self._connection_factory.connect() as con:
            with con.transaction():
                if operation in {"replace_chart", "change_dimension", "change_metric", "change_chart_type"} and target_view_id:
                    result = con.execute(
                        """
                        update analysis_dashboard_views
                        set title = %s,
                            view_type = %s,
                            question = %s,
                            sql = %s,
                            chart_spec = %s::jsonb,
                            metric = %s,
                            dimensions = %s::jsonb,
                            filters = %s::jsonb,
                            source_file_ids = %s::jsonb,
                            catalog_hash = %s,
                            generation_metadata = %s::jsonb,
                            updated_at = %s
                        where tenant_id = %s and user_id = %s and dashboard_id = %s and view_id = %s
                        """,
                        (
                            view["title"],
                            view["type"],
                            view["question"],
                            view["sql"],
                            self._json(self._chart_spec_with_metadata(view["chart_spec"], view)),
                            view.get("metric"),
                            self._json(view.get("dimensions") or []),
                            self._json(view.get("filters") or []),
                            self._json(view.get("source_file_ids") or []),
                            catalog_hash,
                            self._json(view.get("generation_metadata") or {}),
                            now,
                            tenant_id,
                            user_id,
                            dashboard_id,
                            target_view_id,
                        ),
                    )
                    if int(result.rowcount or 0) == 0:
                        raise RuntimeError("Dashboard view not found")
                else:
                    row = con.execute(
                        """
                        select coalesce(max(position), 0) + 1 as next_position
                        from analysis_dashboard_views
                        where tenant_id = %s and user_id = %s and dashboard_id = %s
                        """,
                        (tenant_id, user_id, dashboard_id),
                    ).fetchone()
                    con.execute(
                        """
                        insert into analysis_dashboard_views (
                            view_id, dashboard_id, tenant_id, user_id, title, view_type,
                            question, sql, chart_spec, metric, dimensions, filters, source_file_ids,
                            catalog_hash, generation_metadata, position, created_at, updated_at
                        )
                        values (%s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s::jsonb, %s::jsonb,
                                %s::jsonb, %s, %s::jsonb, %s, %s, %s)
                        """,
                        (
                            f"view_{uuid4().hex}",
                            dashboard_id,
                            tenant_id,
                            user_id,
                            view["title"],
                            view["type"],
                            view["question"],
                            view["sql"],
                            self._json(self._chart_spec_with_metadata(view["chart_spec"], view)),
                            view.get("metric"),
                            self._json(view.get("dimensions") or []),
                            self._json(view.get("filters") or []),
                            self._json(view.get("source_file_ids") or []),
                            catalog_hash,
                            self._json(view.get("generation_metadata") or {}),
                            int((row or {}).get("next_position") or 1),
                            now,
                            now,
                        ),
                    )
                con.execute(
                    """
                    update analysis_dashboards
                    set business_context = coalesce(business_context, '{}'::jsonb) || %s::jsonb,
                        updated_at = %s
                    where tenant_id = %s and user_id = %s and dashboard_id = %s
                    """,
                    (
                        self._json({
                            "lastOperation": view.get("generation_metadata") or {},
                            "catalogHash": (view.get("generation_metadata") or {}).get("catalogHash") or catalog_hash,
                        }),
                        now,
                        tenant_id,
                        user_id,
                        dashboard_id,
                    ),
                )
        return {**self.get_dashboard(tenant_id, user_id, dashboard_id), "lastOperation": view.get("generation_metadata") or {}}

    def run_view(
        self,
        tenant_id: str,
        user_id: str,
        dashboard_id: str,
        view_id: str,
        limit: int = 200,
    ) -> dict[str, Any]:
        dashboard = self.get_dashboard(tenant_id, user_id, dashboard_id)
        view = next((item for item in dashboard.get("views", []) if item.get("viewId") == view_id), None)
        if not view:
            raise RuntimeError("Dashboard view not found")

        tables = ((dashboard.get("catalogSnapshot") or {}).get("tables") or [])
        known_tables = [str(table.get("table")) for table in tables if table.get("table")]
        sql = str(view.get("sql") or "").strip()
        self._sql_validator.validate(sql, known_tables)

        cache_path = self._validated_cache_path(str(dashboard.get("duckdbPath") or ""))
        if not cache_path.exists():
            raise RuntimeError("Dashboard data cache was not found")

        safe_limit = max(1, min(int(limit or 200), 500))
        query = f"select * from ({sql.rstrip(';')}) as analitrics_dashboard_view limit ?"
        con = duckdb.connect(database=str(cache_path), read_only=True)
        try:
            cursor = con.execute(query, [safe_limit])
            columns = [column[0] for column in cursor.description or []]
            rows = [dict(zip(columns, row)) for row in cursor.fetchall()]
        finally:
            con.close()
        return {"columns": columns, "rows": rows, "rowCount": len(rows), "limit": safe_limit}

    def _delete_view(
        self,
        tenant_id: str,
        user_id: str,
        dashboard_id: str,
        view_id: str,
        instruction: str,
        plan: dict[str, Any],
    ) -> dict[str, Any]:
        now = utc_now()
        explanation = {
            "operation": "remove_chart",
            "userInstruction": instruction,
            "changed": "Se eliminó un gráfico del dashboard.",
            "sql": None,
            "usedCatalogFeedback": False,
            "reason": str(plan.get("reason") or ""),
            "updatedAt": now.isoformat(),
        }
        with self._connection_factory.connect() as con:
            with con.transaction():
                result = con.execute(
                    """
                    delete from analysis_dashboard_views
                    where tenant_id = %s and user_id = %s and dashboard_id = %s and view_id = %s
                    """,
                    (tenant_id, user_id, dashboard_id, view_id),
                )
                if int(result.rowcount or 0) == 0:
                    raise RuntimeError("Dashboard view not found")
                con.execute(
                    """
                    update analysis_dashboards
                    set business_context = coalesce(business_context, '{}'::jsonb) || %s::jsonb,
                        updated_at = %s
                    where tenant_id = %s and user_id = %s and dashboard_id = %s
                    """,
                    (self._json({"lastOperation": explanation}), now, tenant_id, user_id, dashboard_id),
                )
        return explanation

    def _build_view_from_plan(
        self,
        context: dict[str, Any],
        plan: dict[str, Any],
        instruction: str,
        preferences: DashboardFeedbackPreferences,
        catalog_hash: str,
    ) -> dict[str, Any]:
        tables = [table for table in context.get("tables") or [] if table.get("table") and not table.get("systemTable")]
        known_tables = [str(table.get("table")) for table in context.get("tables") or [] if table.get("table")]
        table = self._select_table_for_plan(tables, plan)
        if not table:
            raise RuntimeError("No compatible table was found for the dashboard instruction")
        table_name = str(table.get("table"))
        columns = [column for column in table.get("columns") or [] if isinstance(column, dict)]
        column_names = {str(column.get("name")) for column in columns if column.get("name")}
        dimension = self._first_existing(plan.get("dimensions") or [], column_names)
        if not dimension:
            raise RuntimeError("A valid dashboard dimension is required")

        derived_metric = self._normalize_derived_metric(plan.get("derived_metric"), column_names)
        metric_name = str(plan.get("metric") or "").strip()
        metric_expr = ""
        metric_alias = self._safe_alias(metric_name or (derived_metric or {}).get("name") or "valor")
        saved_metric = None
        if derived_metric:
            metric_name = derived_metric["name"]
            metric_alias = self._safe_alias(metric_name)
            metric_expr = self._metric_expression(derived_metric)
            saved_metric = self._catalog_repository.save_derived_metric(
                tenant_id=str(context["tenantId"]),
                user_id=str(context["userId"]),
                conversation_id=str(context["conversationId"]),
                source_file_id=self._optional_str(table.get("sourceFileId")),
                source_filename=self._optional_str(table.get("sourceFilename")),
                name=metric_name,
                label=str(derived_metric.get("label") or metric_name),
                definition=derived_metric,
                created_from={
                    "source": "dashboard_instruction",
                    "instruction": instruction,
                    "plannerReason": plan.get("reason"),
                },
            )
            context = {
                **context,
                "derivedMetrics": [*(context.get("derivedMetrics") or []), saved_metric],
            }
            catalog_hash = self._catalog_hasher.hash(context, preferences)
        else:
            if metric_name not in column_names:
                metric = self._first_existing([metric.get("name") for metric in self._metric_columns(columns)], column_names)
                if not metric:
                    raise RuntimeError("A valid dashboard metric is required")
                metric_name = metric
            metric_alias = f"total_{self._safe_alias(metric_name)}"
            metric_expr = f'sum("{self._quote_name(metric_name)}")::double'

        chart_type = self._chart_type_from_plan(plan)
        sql = self._grouped_metric_sql(table_name, dimension, metric_expr, metric_alias, chart_type)
        preview = self._execute_seed_preview(sql, known_tables, str(context.get("cachePath") or ""))
        title = str(plan.get("title") or "").strip() or f"{self._label(metric_name)} por {self._label(dimension)}"
        spec = self._chart_spec_normalizer.normalize(
            {
                "type": chart_type,
                "title": title,
                "xField": dimension,
                "yFields": [metric_alias],
                "sort": "preserve",
                "limit": 12,
                "categoryLabel": self._label(dimension),
            },
            preview,
            title,
        )
        if spec is None:
            raise RuntimeError("Generated dashboard chart spec could not be normalized")
        source_file_ids = [
            str(value)
            for value in [table.get("sourceFileId")]
            if value is not None and str(value).strip()
        ]
        generation_metadata = {
            "operation": self._operation(plan),
            "userInstruction": instruction,
            "changed": self._change_summary(plan, metric_name, dimension, chart_type),
            "sql": sql,
            "usedCatalogFeedback": bool((context.get("feedback") or []) or (context.get("derivedMetrics") or []) or saved_metric),
            "usedDerivedMetric": saved_metric,
            "catalogHash": catalog_hash,
            "reason": str(plan.get("reason") or ""),
            "updatedAt": utc_now().isoformat(),
        }
        return {
            "title": title,
            "type": chart_type,
            "question": instruction,
            "sql": sql,
            "chart_spec": spec,
            "metric": metric_name,
            "dimensions": [dimension],
            "filters": plan.get("filters") if isinstance(plan.get("filters"), list) else [],
            "source_file_ids": source_file_ids,
            "generation_reason": generation_metadata["reason"],
            "applied_feedback_ids": [
                str(item.get("feedbackId") or item.get("feedback_id"))
                for item in context.get("feedback") or []
                if isinstance(item, dict) and (item.get("feedbackId") or item.get("feedback_id"))
            ],
            "generation_metadata": generation_metadata,
        }

    def _select_table_for_plan(self, tables: list[dict[str, Any]], plan: dict[str, Any]) -> dict[str, Any] | None:
        requested_table = str(plan.get("table") or "").strip()
        if requested_table:
            for table in tables:
                if str(table.get("table") or "") == requested_table:
                    return table
        requested_columns = {
            str(value)
            for value in [plan.get("metric"), *(plan.get("dimensions") or [])]
            if value is not None and str(value).strip()
        }
        derived_metric = plan.get("derived_metric") if isinstance(plan.get("derived_metric"), dict) else {}
        for key in ("value_column", "distinct_column", "base_metric"):
            value = derived_metric.get(key)
            if value is not None and str(value).strip():
                requested_columns.add(str(value))
        best: tuple[int, int, dict[str, Any]] | None = None
        for table in tables:
            column_names = {str(column.get("name")) for column in table.get("columns") or [] if isinstance(column, dict)}
            matches = len(requested_columns.intersection(column_names))
            rows = int(table.get("rowCount") or 0)
            if best is None or matches > best[0] or (matches == best[0] and rows > best[1]):
                best = (matches, rows, table)
        return best[2] if best else None

    def _normalize_derived_metric(self, value: Any, column_names: set[str]) -> dict[str, Any] | None:
        if not isinstance(value, dict):
            return None
        kind = str(value.get("kind") or "").strip().lower()
        if kind not in {"sum", "avg", "count", "count_distinct", "share_of_sum"}:
            return None
        name = self._safe_alias(str(value.get("name") or value.get("label") or kind))
        if not name:
            return None
        normalized = {
            "name": name,
            "label": str(value.get("label") or name.replace("_", " ")).strip()[:120],
            "kind": kind,
            "description": str(value.get("description") or "").strip()[:500],
        }
        for key in ("value_column", "distinct_column", "base_metric"):
            raw = str(value.get(key) or "").strip()
            if raw and raw in column_names:
                normalized[key] = raw
        if kind in {"sum", "avg", "share_of_sum"} and not normalized.get("value_column"):
            return None
        if kind == "count_distinct" and not normalized.get("distinct_column"):
            return None
        return normalized

    def _metric_expression(self, metric: dict[str, Any]) -> str:
        kind = str(metric.get("kind") or "")
        if kind == "avg":
            return f'avg("{self._quote_name(str(metric["value_column"]))}")::double'
        if kind == "count":
            return "count(*)::double"
        if kind == "count_distinct":
            return f'count(distinct "{self._quote_name(str(metric["distinct_column"]))}")::double'
        if kind == "share_of_sum":
            value_column = self._quote_name(str(metric["value_column"]))
            return f'(sum("{value_column}") / nullif(sum(sum("{value_column}")) over (), 0))::double'
        return f'sum("{self._quote_name(str(metric["value_column"]))}")::double'

    def _grouped_metric_sql(
        self,
        table_name: str,
        dimension: str,
        metric_expr: str,
        metric_alias: str,
        chart_type: str,
    ) -> str:
        limit = 12 if chart_type != "line" else 24
        order = "1" if chart_type == "line" else "2 desc"
        return f"""
        select "{self._quote_name(dimension)}"::varchar as "{self._quote_name(dimension)}",
               {metric_expr} as "{self._quote_name(metric_alias)}"
        from "{self._quote_name(table_name)}"
        where "{self._quote_name(dimension)}" is not null
        group by 1
        order by {order}
        limit {limit}
        """.strip()

    def _operation(self, plan: dict[str, Any]) -> str:
        operation = str(plan.get("operation") or "add_chart").strip().lower()
        if operation not in {"add_chart", "replace_chart", "remove_chart", "change_dimension", "change_metric", "change_chart_type"}:
            return "add_chart"
        return operation

    def _infer_target_view_id(
        self,
        dashboard: dict[str, Any],
        plan: dict[str, Any],
        instruction: str,
    ) -> str | None:
        views = [view for view in dashboard.get("views") or [] if isinstance(view, dict)]
        if len(views) == 1:
            return str(views[0].get("viewId") or "")
        needles = [
            str(plan.get("metric") or ""),
            str(plan.get("chart_type") or ""),
            *[str(item) for item in plan.get("dimensions") or []],
            instruction,
        ]
        normalized_needles = [self._normalize_text(value) for value in needles if value]
        scored: list[tuple[int, str]] = []
        for view in views:
            view_id = str(view.get("viewId") or "")
            haystack = self._normalize_text(
                " ".join(
                    [
                        str(view.get("title") or ""),
                        str(view.get("viewType") or ""),
                        str(view.get("metric") or ""),
                        " ".join(str(item) for item in view.get("dimensions") or []),
                    ]
                )
            )
            score = sum(1 for needle in normalized_needles if needle and needle in haystack)
            if score > 0 and view_id:
                scored.append((score, view_id))
        scored.sort(key=lambda item: item[0], reverse=True)
        if len(scored) == 1 or (len(scored) > 1 and scored[0][0] > scored[1][0]):
            return scored[0][1]
        return None

    def _reject_unsafe_instruction(self, instruction: str) -> None:
        normalized = self._normalize_text(instruction)
        dangerous_terms = (
            "drop table",
            "delete from",
            "truncate",
            "insert into",
            "update ",
            "create table",
            "copy ",
            "attach ",
            "install ",
            "load ",
            "pragma ",
            "rm ",
            "borrar archivos",
            "borra archivos",
            "borra todos los archivos",
            "eliminar archivos",
            "elimina archivos",
            "borrar tablas",
            "borra tablas",
            "eliminar tablas",
            "elimina tablas",
            "duckdb",
            "rustfs",
            "postgres",
            "s3",
        )
        if any(term in normalized for term in dangerous_terms):
            raise RuntimeError("Dashboard instructions can only add, remove or modify charts.")

    def _reject_ambiguous_target_instruction(self, instruction: str, dashboard: dict[str, Any]) -> None:
        views = [view for view in dashboard.get("views") or [] if isinstance(view, dict)]
        if len(views) < 2:
            return

        normalized = f" {self._normalize_text(instruction)} "
        mutation_terms = (" cambia ", " cambiar ", " modifica ", " modificar ", " reemplaza ", " reemplazar ", " quita ", " quitar ", " elimina ", " eliminar ")
        ambiguous_refs = (
            " eso ",
            " esto ",
            " aquello ",
            " lo otro ",
            " el otro ",
            " la otra ",
            " ese grafico ",
            " ese gráfico ",
            " este grafico ",
            " este gráfico ",
            " el grafico ",
            " el gráfico ",
        )
        if not any(term in normalized for term in mutation_terms):
            return
        if not any(term in normalized for term in ambiguous_refs):
            return

        view_terms: set[str] = set()
        for view in views:
            values = [
                view.get("title"),
                view.get("metric"),
                view.get("viewType") or view.get("view_type"),
                *list(view.get("dimensions") or []),
            ]
            for value in values:
                term = self._normalize_text(str(value or ""))
                if len(term) >= 3:
                    view_terms.add(term)
        if any(f" {term} " in normalized for term in view_terms):
            return

        raise RuntimeError("Please specify which dashboard chart should be modified.")

    def _chart_type_from_plan(self, plan: dict[str, Any]) -> str:
        chart_type = str(plan.get("chart_type") or "bar").strip().lower()
        return chart_type if chart_type in {"bar", "line", "pie"} else "bar"

    def _first_existing(self, values: list[Any], candidates: set[str]) -> str | None:
        for value in values:
            text = str(value or "").strip()
            if text in candidates:
                return text
        return None

    def _change_summary(self, plan: dict[str, Any], metric: str, dimension: str, chart_type: str) -> str:
        operation = self._operation(plan).replace("_", " ")
        return f"{operation}: {self._label(metric)} por {self._label(dimension)} como {chart_type}."

    def _normalize_text(self, value: str) -> str:
        return " ".join(value.lower().replace("_", " ").replace("-", " ").split())

    def _optional_str(self, value: Any) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    def _get_dashboard_by_conversation(
        self,
        tenant_id: str,
        user_id: str,
        conversation_id: str,
    ) -> dict[str, Any] | None:
        with self._connection_factory.connect() as con:
            return con.execute(
                """
                select dashboard_id, conversation_id, title, description, seed_question,
                       seed_sql, seed_message_id, seed_run_id, source_file_ids, duckdb_path,
                       catalog_snapshot, business_context, created_at, updated_at
                from analysis_dashboards
                where tenant_id = %s and user_id = %s and conversation_id = %s
                """,
                (tenant_id, user_id, conversation_id),
            ).fetchone()

    def _dashboard_is_stale(self, tenant_id: str, user_id: str, dashboard: dict[str, Any]) -> bool:
        conversation_id = str(dashboard.get("conversation_id") or "")
        if not conversation_id:
            return False
        try:
            context = self._catalog_repository.get_context(tenant_id, user_id, conversation_id)
        except Exception:
            return False
        if not context.get("found"):
            return False
        preferences = self._intent_selector.select(context)
        current_hash = self._catalog_hasher.hash(context, preferences)
        return self._dashboard_catalog_hash(dashboard) != current_hash

    def _dashboard_catalog_hash(self, dashboard: dict[str, Any]) -> str | None:
        business_context = dashboard.get("business_context") or dashboard.get("businessContext") or {}
        catalog_snapshot = dashboard.get("catalog_snapshot") or dashboard.get("catalogSnapshot") or {}
        if isinstance(business_context, dict) and business_context.get("catalogHash"):
            return str(business_context["catalogHash"])
        if isinstance(catalog_snapshot, dict) and catalog_snapshot.get("catalogHash"):
            return str(catalog_snapshot["catalogHash"])
        return None

    def _catalog_snapshot(self, context: dict[str, Any], catalog_hash: str) -> dict[str, Any]:
        return {
            "catalogHash": catalog_hash,
            "summary": context.get("summary"),
            "files": context.get("files") or [],
            "tables": context.get("tables") or [],
        }

    def _business_context(
        self,
        context: dict[str, Any],
        preferences: DashboardFeedbackPreferences,
        catalog_hash: str,
        regenerated: bool,
    ) -> dict[str, Any]:
        return {
            "catalogHash": catalog_hash,
            "regeneratedFromCatalogChange": regenerated,
            "dashboardIntent": preferences.as_dict(),
            "feedback": context.get("feedback") or [],
            "recentAnalysisStates": context.get("recentAnalysisStates") or [],
        }

    def _chart_spec_with_metadata(self, chart_spec: dict[str, Any], view: dict[str, Any]) -> dict[str, Any]:
        metadata = {
            "generationReason": view.get("generation_reason"),
            "appliedFeedbackIds": view.get("applied_feedback_ids") or [],
        }
        return {**chart_spec, "analitrics": metadata}

    def _view_generation_metadata(self, view: dict[str, Any], operation: str) -> dict[str, Any]:
        return {
            "operation": operation,
            "changed": view.get("generation_reason") or "Vista generada desde el catálogo analítico.",
            "sql": view.get("sql"),
            "usedCatalogFeedback": bool(view.get("applied_feedback_ids")),
            "reason": view.get("generation_reason") or "",
            "updatedAt": utc_now().isoformat(),
        }

    def _execute_seed_preview(self, sql: str, known_tables: list[str], cache_path_value: str) -> list[dict[str, Any]]:
        self._sql_validator.validate(sql, known_tables)
        cache_path = self._validated_cache_path(cache_path_value)
        if not cache_path.exists():
            return []
        con = duckdb.connect(database=str(cache_path), read_only=True)
        try:
            cursor = con.execute(f"select * from ({sql.rstrip(';')}) as analitrics_dashboard_seed limit ?", [50])
            columns = [column[0] for column in cursor.description or []]
            return [dict(zip(columns, row)) for row in cursor.fetchall()]
        finally:
            con.close()

    def _build_initial_chart_views(
        self,
        context: dict[str, Any],
        known_tables: list[str],
        dashboard_title: str,
        preferences: DashboardFeedbackPreferences,
    ) -> list[dict[str, Any]]:
        tables = [table for table in context.get("tables") or [] if table.get("table") and not table.get("systemTable")]
        cache_path = str(context.get("cachePath") or "")
        views: list[dict[str, Any]] = []
        for table in tables:
            table_name = str(table.get("table"))
            columns = [column for column in table.get("columns") or [] if isinstance(column, dict)]
            metrics = self._metric_columns(columns, preferences)
            dimensions = self._dimension_columns(columns, int(table.get("rowCount") or 0), preferences)
            date_columns = self._date_columns(columns)
            for metric in metrics[:2]:
                if not dimensions:
                    continue
                for dimension in dimensions[:2]:
                    views.append(
                        self._ranking_view(
                            table_name=table_name,
                            source_filename=str(table.get("sourceFilename") or ""),
                            dimension=str(dimension["name"]),
                            metric=str(metric["name"]),
                            known_tables=known_tables,
                            cache_path=cache_path,
                            preferences=preferences,
                        )
                    )
                    if len(views) >= 4:
                        return views
            if date_columns and metrics:
                views.append(
                    self._trend_view(
                        table_name=table_name,
                        source_filename=str(table.get("sourceFilename") or ""),
                        date_column=str(date_columns[0]["name"]),
                        metric=str(metrics[0]["name"]),
                        known_tables=known_tables,
                        cache_path=cache_path,
                        preferences=preferences,
                    )
                )
                if len(views) >= 4:
                    return views
        if not views:
            views.extend(self._fallback_rowcount_views(context, known_tables, dashboard_title))
        return views[:4]

    def _ranking_view(
        self,
        table_name: str,
        source_filename: str,
        dimension: str,
        metric: str,
        known_tables: list[str],
        cache_path: str,
        preferences: DashboardFeedbackPreferences,
    ) -> dict[str, Any]:
        metric_alias = f"total_{self._safe_alias(metric)}"
        title = f"{self._label(metric)} por {self._label(dimension)}"
        sql = f"""
        select "{self._quote_name(dimension)}"::varchar as "{self._quote_name(dimension)}",
               sum("{self._quote_name(metric)}")::double as "{self._quote_name(metric_alias)}"
        from "{self._quote_name(table_name)}"
        where "{self._quote_name(dimension)}" is not null
          and "{self._quote_name(metric)}" is not null
        group by 1
        order by 2 desc
        limit 12
        """.strip()
        preview = self._execute_seed_preview(sql, known_tables, cache_path)
        spec = self._chart_spec_normalizer.normalize(
            {
                "type": "bar",
                "title": title,
                "xField": dimension,
                "yFields": [metric_alias],
                "sort": "preserve",
                "limit": 12,
                "categoryLabel": self._label(dimension),
            },
            preview,
            title,
        )
        if spec is None:
            raise RuntimeError("Generated dashboard chart spec could not be normalized")
        return {
            "title": title,
            "type": "bar",
            "question": f"Ranking inicial de {self._label(metric)} por {self._label(dimension)} en {source_filename or table_name}.",
            "sql": sql,
            "chart_spec": spec,
            "metric": metric,
            "dimensions": [dimension],
            "filters": [],
            "generation_reason": self._generation_reason(metric, dimension, preferences),
            "applied_feedback_ids": preferences.applied_feedback_ids,
        }

    def _trend_view(
        self,
        table_name: str,
        source_filename: str,
        date_column: str,
        metric: str,
        known_tables: list[str],
        cache_path: str,
        preferences: DashboardFeedbackPreferences,
    ) -> dict[str, Any]:
        period_alias = "periodo"
        metric_alias = f"total_{self._safe_alias(metric)}"
        title = f"Tendencia de {self._label(metric)}"
        sql = f"""
        select date_trunc('month', "{self._quote_name(date_column)}")::varchar as "{period_alias}",
               sum("{self._quote_name(metric)}")::double as "{self._quote_name(metric_alias)}"
        from "{self._quote_name(table_name)}"
        where "{self._quote_name(date_column)}" is not null
          and "{self._quote_name(metric)}" is not null
        group by 1
        order by 1
        limit 24
        """.strip()
        preview = self._execute_seed_preview(sql, known_tables, cache_path)
        spec = self._chart_spec_normalizer.normalize(
            {
                "type": "line",
                "title": title,
                "xField": period_alias,
                "yFields": [metric_alias],
                "sort": "preserve",
                "limit": 24,
                "categoryLabel": "Periodo",
            },
            preview,
            title,
        )
        if spec is None:
            raise RuntimeError("Generated dashboard trend spec could not be normalized")
        return {
            "title": title,
            "type": "line",
            "question": f"Tendencia inicial de {self._label(metric)} en {source_filename or table_name}.",
            "sql": sql,
            "chart_spec": spec,
            "metric": metric,
            "dimensions": [date_column],
            "filters": [],
            "generation_reason": self._generation_reason(metric, date_column, preferences),
            "applied_feedback_ids": preferences.applied_feedback_ids,
        }

    def _fallback_rowcount_views(
        self,
        context: dict[str, Any],
        known_tables: list[str],
        dashboard_title: str,
    ) -> list[dict[str, Any]]:
        cache_path = str(context.get("cachePath") or "")
        sql = """
        select source_filename::varchar as archivo,
               sum(row_count)::double as filas
        from "__analitrics_catalog"
        where source_filename is not null
        group by 1
        order by 2 desc
        limit 12
        """.strip()
        preview = self._execute_seed_preview(sql, known_tables, cache_path)
        spec = self._chart_spec_normalizer.normalize(
            {
                "type": "bar",
                "title": "Volumen de registros por archivo",
                "xField": "archivo",
                "yFields": ["filas"],
                "sort": "preserve",
                "limit": 12,
                "categoryLabel": "Archivo",
            },
            preview,
            dashboard_title,
        )
        if spec is None:
            return []
        return [
            {
                "title": "Volumen de registros por archivo",
                "type": "bar",
                "question": "Distribución inicial del volumen de registros por archivo cargado.",
                "sql": sql,
                "chart_spec": spec,
                "metric": "filas",
                "dimensions": ["archivo"],
                "filters": [],
            }
        ]

    def _metric_columns(
        self,
        columns: list[dict[str, Any]],
        preferences: DashboardFeedbackPreferences | None = None,
    ) -> list[dict[str, Any]]:
        candidates = [column for column in columns if self._is_numeric(column) and not self._is_identifier(column)]
        priority_terms = ("monto", "ingreso", "venta", "total", "importe", "precio", "ticket", "cantidad")
        preferred = set((preferences or DashboardFeedbackPreferences()).preferred_metrics)
        return sorted(
            candidates,
            key=lambda column: (
                str(column.get("name") or "") not in preferred,
                not any(term in str(column.get("name") or "").lower() for term in priority_terms),
                str(column.get("name") or ""),
            ),
        )

    def _dimension_columns(
        self,
        columns: list[dict[str, Any]],
        row_count: int,
        preferences: DashboardFeedbackPreferences | None = None,
    ) -> list[dict[str, Any]]:
        preferences = preferences or DashboardFeedbackPreferences()
        preferred = set(preferences.preferred_dimensions)
        avoided = set(preferences.avoid_dimensions)
        candidates = []
        for column in columns:
            name = str(column.get("name") or "")
            if name in avoided:
                continue
            if self._is_numeric(column) or self._is_date(column):
                continue
            distinct = column.get("distinct_count")
            if isinstance(distinct, int) and row_count > 0 and distinct > max(80, row_count * 0.8):
                continue
            candidates.append(column)
        priority_terms = ("producto", "curso", "categoria", "categoría", "pais", "país", "canal", "sede", "cliente")
        return sorted(
            candidates,
            key=lambda column: (
                str(column.get("name") or "") not in preferred,
                not any(term in str(column.get("name") or "").lower() for term in priority_terms),
                str(column.get("name") or ""),
            ),
        )

    def _date_columns(self, columns: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [column for column in columns if self._is_date(column)]

    def _generation_reason(
        self,
        metric: str,
        dimension: str,
        preferences: DashboardFeedbackPreferences,
    ) -> str:
        reasons = []
        if metric in preferences.preferred_metrics:
            reasons.append(f"métrica priorizada por catálogo: {self._label(metric)}")
        if dimension in preferences.preferred_dimensions:
            reasons.append(f"dimensión priorizada por catálogo: {self._label(dimension)}")
        if preferences.avoid_dimensions:
            avoided = ", ".join(self._label(item) for item in preferences.avoid_dimensions)
            reasons.append(f"se evitaron dimensiones indicadas por catálogo: {avoided}")
        if not reasons:
            reasons.append("vista sugerida desde el profiling técnico del archivo")
        return "; ".join(reasons)

    def _is_numeric(self, column: dict[str, Any]) -> bool:
        data_type = str(column.get("type") or "").lower()
        return any(token in data_type for token in ("decimal", "double", "float", "real", "numeric", "int", "bigint"))

    def _is_identifier(self, column: dict[str, Any]) -> bool:
        name = str(column.get("name") or "").lower().replace("-", "_").replace(" ", "_")
        return (
            name == "id"
            or name.endswith("_id")
            or name.startswith("id_")
            or any(token in name for token in ("codigo", "código", "documento", "dni", "ruc", "telefono", "teléfono"))
        )

    def _is_date(self, column: dict[str, Any]) -> bool:
        data_type = str(column.get("type") or "").lower()
        return "date" in data_type or "time" in data_type

    def _title_from_context(self, context: dict[str, Any]) -> str:
        files = context.get("files") or []
        if len(files) == 1:
            filename = str(files[0].get("filename") or files[0].get("name") or "").strip()
            if filename:
                return f"Dashboard {filename}"
        if len(files) > 1:
            return f"Dashboard de {len(files)} archivos"
        return "Dashboard Analitrics"

    def _seed_question_from_context(self, context: dict[str, Any]) -> str:
        files = context.get("files") or []
        filenames = [str(item.get("filename") or item.get("name") or "") for item in files if item.get("filename") or item.get("name")]
        if filenames:
            return "Dashboard generado desde archivos cargados: " + ", ".join(filenames[:4])
        return "Dashboard generado desde el catálogo analítico del chat."

    def _label(self, value: str) -> str:
        return value.replace("_", " ").strip()

    def _safe_alias(self, value: str) -> str:
        clean = "".join(char.lower() if char.isalnum() else "_" for char in value).strip("_")
        return clean or "valor"

    def _quote_name(self, value: str) -> str:
        return value.replace('"', '""')

    def _validated_cache_path(self, value: str) -> Path:
        base = Path(env("ANALITRICS_CACHE_DIR", "/var/analitrics/analytics/cache")).expanduser().resolve()
        cache_path = Path(value).expanduser().resolve()
        if cache_path.suffix != ".duckdb" or not cache_path.is_relative_to(base):
            raise RuntimeError("Unsafe dashboard cache path rejected")
        return cache_path

    def _title_from_question(self, question: str) -> str:
        clean = " ".join(question.split())
        if not clean:
            return "Dashboard Analitrics"
        return clean[:72] + ("..." if len(clean) > 72 else "")

    def _dashboard_summary(self, row: dict[str, Any]) -> dict[str, Any]:
        return {
            "dashboardId": row["dashboard_id"],
            "conversationId": row["conversation_id"],
            "title": row["title"],
            "description": row["description"],
            "seedQuestion": row["seed_question"],
            "sourceFileIds": row["source_file_ids"] or [],
            "createdAt": row["created_at"].isoformat() if row["created_at"] else None,
            "updatedAt": row["updated_at"].isoformat() if row["updated_at"] else None,
        }

    def _dashboard_detail(self, row: dict[str, Any]) -> dict[str, Any]:
        return {
            **self._dashboard_summary(row),
            "seedSql": row["seed_sql"],
            "seedMessageId": row["seed_message_id"],
            "seedRunId": row["seed_run_id"],
            "duckdbPath": row["duckdb_path"],
            "catalogSnapshot": row["catalog_snapshot"] or {},
            "businessContext": row["business_context"] or {},
        }

    def _view(self, row: dict[str, Any]) -> dict[str, Any]:
        return {
            "viewId": row["view_id"],
            "title": row["title"],
            "viewType": row["view_type"],
            "question": row["question"],
            "sql": row["sql"],
            "chartSpec": row["chart_spec"] or {},
            "metric": row.get("metric"),
            "dimensions": row.get("dimensions") or [],
            "filters": row.get("filters") or [],
            "sourceFileIds": row.get("source_file_ids") or [],
            "catalogHash": row.get("catalog_hash"),
            "generationMetadata": row.get("generation_metadata") or {},
            "position": int(row["position"] or 0),
            "createdAt": row["created_at"].isoformat() if row["created_at"] else None,
            "updatedAt": row["updated_at"].isoformat() if row["updated_at"] else None,
        }

    def _json(self, value: Any) -> str:
        return json.dumps(value, ensure_ascii=False, default=str)


class DashboardRepositoryFactory:
    _instance: DashboardRepository | None = None

    @classmethod
    def get_repository(cls, run_repository: AgentRunRepository) -> DashboardRepository:
        if cls._instance is None:
            connection_factory = PostgresControlPlaneFactory()
            cls._instance = DashboardRepository(
                connection_factory=connection_factory,
                catalog_repository=CatalogRepository(connection_factory),
                run_repository=run_repository,
            )
        return cls._instance
