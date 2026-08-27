from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

import duckdb

from .config import env
from .control_plane import CatalogRepository, PostgresControlPlaneFactory
from .chart_contract import AnalitricsChartSpecNormalizer
from .repositories import AgentRunRepository
from .sql_validation import SqlReadOnlyValidator


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class DashboardRepository:
    def __init__(
        self,
        connection_factory: PostgresControlPlaneFactory,
        catalog_repository: CatalogRepository,
        run_repository: AgentRunRepository,
        sql_validator: SqlReadOnlyValidator | None = None,
        chart_spec_normalizer: AnalitricsChartSpecNormalizer | None = None,
    ) -> None:
        self._connection_factory = connection_factory
        self._catalog_repository = catalog_repository
        self._run_repository = run_repository
        self._sql_validator = sql_validator or SqlReadOnlyValidator()
        self._chart_spec_normalizer = chart_spec_normalizer or AnalitricsChartSpecNormalizer()

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

    def create_from_latest_analysis(
        self,
        tenant_id: str,
        user_id: str,
        conversation_id: str,
        title: str | None = None,
    ) -> dict[str, Any]:
        run = self._run_repository.find_latest_success(tenant_id, user_id, conversation_id)
        if not run:
            raise RuntimeError("No successful analytical run with SQL was found for this conversation")

        context = self._catalog_repository.get_context(tenant_id, user_id, conversation_id)
        if not context.get("found"):
            raise RuntimeError("No active analytical catalog was found for this conversation")

        sql = str(run.get("sql") or "").strip()
        if not sql:
            raise RuntimeError("The latest analytical run has no SQL")

        known_tables = [str(table.get("table")) for table in context.get("tables") or [] if table.get("table")]
        self._sql_validator.validate(sql, known_tables)

        dashboard_id = f"dash_{uuid4().hex}"
        view_id = f"view_{uuid4().hex}"
        now = utc_now()
        seed_question = str(run.get("question") or "")
        source_file_ids = [str(item) for item in (run.get("fileIds") or []) if item]
        dashboard_title = (title or self._title_from_question(seed_question)).strip()

        preview = self._execute_seed_preview(sql, known_tables, str(context.get("cachePath") or ""))
        chart_spec = self._chart_spec_normalizer.normalize(run.get("chartSpec"), preview, dashboard_title)
        if chart_spec is None:
            raise RuntimeError(
                "The latest analytical run has no valid chart proposal. Ask Analitrics for a chart/dashboard first."
            )

        with self._connection_factory.connect() as con:
            with con.transaction():
                con.execute(
                    """
                    delete from analysis_dashboards
                    where tenant_id = %s and user_id = %s and conversation_id = %s
                    """,
                    (tenant_id, user_id, conversation_id),
                )
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
                        "Dashboard grafico creado desde un análisis del chat.",
                        seed_question,
                        sql,
                        run.get("messageId"),
                        run.get("runId"),
                        self._json(source_file_ids),
                        context.get("cachePath"),
                        self._json(
                            {
                                "summary": context.get("summary"),
                                "files": context.get("files") or [],
                                "tables": context.get("tables") or [],
                            }
                        ),
                        self._json(
                            {
                                "feedback": context.get("feedback") or [],
                                "recentAnalysisStates": context.get("recentAnalysisStates") or [],
                            }
                        ),
                        now,
                        now,
                    ),
                ).fetchone()
                con.execute(
                    """
                    insert into analysis_dashboard_views (
                        view_id, dashboard_id, tenant_id, user_id, title, view_type,
                        question, sql, chart_spec, position, created_at, updated_at
                    )
                    values (%s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s)
                    """,
                    (
                        view_id,
                        dashboard_id,
                        tenant_id,
                        user_id,
                        chart_spec["title"] or "Grafico principal",
                        chart_spec["type"],
                        seed_question,
                        sql,
                        self._json(chart_spec),
                        1,
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
            views = con.execute(
                """
                select view_id, title, view_type, question, sql, chart_spec, position,
                       created_at, updated_at
                from analysis_dashboard_views
                where tenant_id = %s and user_id = %s and dashboard_id = %s
                order by position, created_at
                """,
                (tenant_id, user_id, dashboard_id),
            ).fetchall()
        return {**self._dashboard_detail(dashboard), "views": [self._view(row) for row in views]}

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
