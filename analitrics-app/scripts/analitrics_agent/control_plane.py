from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import psycopg
from psycopg.rows import dict_row

from nl_sql_file import FileMetadata

from .analytics_context import BusinessSummaryBuilder, IngestionStatusBuilder
from .config import bool_env, env
from .json_utils import profiles_for_storage
from .models import AgentRequest
from .naming import file_signature


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class PostgresControlPlaneFactory:
    def connect(self) -> psycopg.Connection:
        return psycopg.connect(
            host=env("ANALITRICS_POSTGRES_HOST", "control-postgres"),
            port=int(env("ANALITRICS_POSTGRES_PORT", "5432")),
            dbname=env("ANALITRICS_POSTGRES_DB", "analitrics"),
            user=env("ANALITRICS_POSTGRES_USER", "analitrics"),
            password=env("ANALITRICS_POSTGRES_PASSWORD"),
            row_factory=dict_row,
        )


class CatalogRepository:
    def __init__(self, connection_factory: PostgresControlPlaneFactory) -> None:
        self._connection_factory = connection_factory
        self._ingestion_status_builder = IngestionStatusBuilder()
        self._business_summary_builder = BusinessSummaryBuilder()
        self._max_analysis_states = int(env("ANALITRICS_MAX_ANALYSIS_STATES", "8"))

    def find_conversation(self, request: AgentRequest) -> dict[str, Any] | None:
        if not request.conversation_id:
            return None
        self.ensure_schema_if_allowed()
        with self._connection_factory.connect() as con:
            row = con.execute(
                """
                select tenant_id, user_id, conversation_id, cache_path, processed_files, pending_clarification, updated_at
                from analysis_catalog_sessions
                where tenant_id = %s and user_id = %s and conversation_id = %s
                """,
                (request.tenant_id, self._user_id(request), request.conversation_id),
            ).fetchone()
            if not row:
                return None
            active_rows = con.execute(
                """
                select table_name, source_file_id, profile
                from analysis_catalog_profiles
                where tenant_id = %s and user_id = %s and conversation_id = %s and active = true
                """,
                (request.tenant_id, self._user_id(request), request.conversation_id),
            ).fetchall()
            table_map: dict[str, list[str]] = {}
            for active_row in active_rows:
                source_file_id = active_row.get("source_file_id")
                if not source_file_id:
                    continue
                table_name = str(active_row["table_name"])
                table_map.setdefault(str(source_file_id), []).append(table_name)
            active_file_ids = set(table_map)
            processed_files = []
            for processed in row["processed_files"] or []:
                file_id = str(processed.get("file_id") or "")
                if file_id not in active_file_ids:
                    continue
                processed_files.append({**processed, "tables": table_map.get(file_id, [])})
            return {
                "tenantId": row["tenant_id"],
                "userId": row["user_id"],
                "conversationId": row["conversation_id"],
                "cachePath": row["cache_path"],
                "tableMap": table_map,
                "processedFiles": processed_files,
                "pendingClarification": row.get("pending_clarification"),
                "updatedAt": row["updated_at"],
            }

    def get_context(self, tenant_id: str, user_id: str, conversation_id: str) -> dict[str, Any]:
        with self._connection_factory.connect() as con:
            conversation = con.execute(
                """
                select tenant_id, user_id, conversation_id, cache_path, files,
                       table_map, processed_files, pending_clarification, last_cache_hits, created_at, updated_at
                from analysis_catalog_sessions
                where tenant_id = %s and user_id = %s and conversation_id = %s
                """,
                (tenant_id, user_id, conversation_id),
            ).fetchone()
            if not conversation:
                return {
                    "found": False,
                    "tenantId": tenant_id,
                    "userId": user_id,
                    "conversationId": conversation_id,
                    "files": [],
                    "tables": [],
                    "summary": {
                        "fileCount": 0,
                        "tableCount": 0,
                        "rowCountTotal": 0,
                        "cachePath": None,
                    },
                    "ingestionStatus": self._ingestion_status_builder.build([], [], None, catalog_found=False),
                    "businessSummary": self._business_summary_builder.build([], []),
                    "qualityWarnings": [],
                }

            profile_rows = con.execute(
                """
                select table_name, source_file_id, source_filename, profile, active, updated_at
                from analysis_catalog_profiles
                where tenant_id = %s and user_id = %s and conversation_id = %s and active = true
                order by source_filename nulls last, table_name
                """,
                (tenant_id, user_id, conversation_id),
            ).fetchall()
            feedback_rows = con.execute(
                """
                select feedback_id, source_file_id, source_filename, step, label, content, created_at, updated_at
                from analysis_catalog_feedback
                where tenant_id = %s and user_id = %s and conversation_id = %s
                order by source_filename nulls last, step, updated_at desc
                """,
                (tenant_id, user_id, conversation_id),
            ).fetchall()
            analysis_state_rows = con.execute(
                """
                select state_id, message_id, run_id, question, answer_summary, intent, metric,
                       dimensions, filters, dataset, last_sql, last_chart, row_count, state, created_at
                from analysis_conversation_states
                where tenant_id = %s and user_id = %s and conversation_id = %s
                order by state_id desc
                limit %s
                """,
                (tenant_id, user_id, conversation_id, self._max_analysis_states),
            ).fetchall()

        profiles = [row["profile"] for row in profile_rows]
        analysis_states = [self._analysis_state_row(row) for row in reversed(analysis_state_rows)]
        suggested_feedback = self._latest_feedback_proposal(analysis_states)
        tables = [
            {
                "table": row["table_name"],
                "sourceFileId": row["source_file_id"],
                "sourceFilename": row["source_filename"],
                "rowCount": int((row["profile"] or {}).get("row_count") or 0),
                "columns": (row["profile"] or {}).get("columns") or [],
                "systemTable": bool((row["profile"] or {}).get("system_table")),
                "updatedAt": row["updated_at"].isoformat() if row["updated_at"] else None,
            }
            for row in profile_rows
        ]
        files = conversation["processed_files"] or conversation["files"] or []
        data_tables = [table for table in tables if not table["systemTable"]]
        feedback = [
            {
                "feedbackId": str(row["feedback_id"]),
                "sourceFileId": row["source_file_id"],
                "sourceFilename": row["source_filename"],
                "step": int(row["step"]),
                "label": row["label"],
                "content": row["content"],
                "createdAt": row["created_at"].isoformat() if row["created_at"] else None,
                "updatedAt": row["updated_at"].isoformat() if row["updated_at"] else None,
            }
            for row in feedback_rows
        ]
        business_summary = self._business_summary_builder.build(files, tables, feedback)
        return {
            "found": True,
            "tenantId": conversation["tenant_id"],
            "userId": conversation["user_id"],
            "conversationId": conversation["conversation_id"],
            "cachePath": conversation["cache_path"],
            "cacheHits": conversation["last_cache_hits"],
            "createdAt": conversation["created_at"].isoformat() if conversation["created_at"] else None,
            "updatedAt": conversation["updated_at"].isoformat() if conversation["updated_at"] else None,
            "files": files,
            "tables": tables,
            "profiles": profiles,
            "feedback": feedback,
            "recentAnalysisStates": analysis_states,
            "suggestedFeedback": suggested_feedback,
            "pendingClarification": conversation["pending_clarification"],
            "ingestionStatus": self._ingestion_status_builder.build(
                files,
                tables,
                conversation["last_cache_hits"],
                catalog_found=True,
            ),
            "businessSummary": business_summary,
            "qualityWarnings": business_summary["qualityWarnings"],
            "summary": {
                "fileCount": len(files),
                "tableCount": len(data_tables),
                "rowCountTotal": sum(int(table["rowCount"] or 0) for table in data_tables),
                "cachePath": conversation["cache_path"],
            },
        }

    def save_feedback(
        self,
        tenant_id: str,
        user_id: str,
        conversation_id: str,
        source_file_id: str | None,
        source_filename: str | None,
        step: int,
        label: str,
        content: str,
    ) -> dict[str, Any]:
        if step < 1 or step > 6:
            raise RuntimeError("step must be between 1 and 6")
        content = content.strip()
        label = label.strip()
        if not content:
            raise RuntimeError("content is required")
        if not label:
            raise RuntimeError("label is required")
        now = utc_now()
        with self._connection_factory.connect() as con:
            row = con.execute(
                """
                select feedback_id, source_file_id, source_filename, step, label, content, created_at, updated_at
                from analysis_catalog_feedback
                where tenant_id = %s
                  and user_id = %s
                  and conversation_id = %s
                  and step = %s
                  and coalesce(source_file_id, '') = coalesce(%s, '')
                  and content = %s
                order by updated_at desc
                limit 1
                """,
                (tenant_id, user_id, conversation_id, step, source_file_id, content),
            ).fetchone()
            if row is None:
                row = con.execute(
                    """
                    insert into analysis_catalog_feedback (
                        tenant_id, user_id, conversation_id, source_file_id, source_filename,
                        step, label, content, created_at, updated_at
                    )
                    values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    returning feedback_id, source_file_id, source_filename, step, label, content, created_at, updated_at
                    """,
                    (
                        tenant_id,
                        user_id,
                        conversation_id,
                        source_file_id,
                        source_filename,
                        step,
                        label,
                        content,
                        now,
                        now,
                    ),
                ).fetchone()
        return {
            "feedbackId": str(row["feedback_id"]),
            "sourceFileId": row["source_file_id"],
            "sourceFilename": row["source_filename"],
            "step": int(row["step"]),
            "label": row["label"],
            "content": row["content"],
            "createdAt": row["created_at"].isoformat() if row["created_at"] else None,
            "updatedAt": row["updated_at"].isoformat() if row["updated_at"] else None,
        }

    def find_recent_analysis_states(self, request: AgentRequest, limit: int | None = None) -> list[dict[str, Any]]:
        if not request.conversation_id:
            return []
        user_id = self._user_id(request)
        row_limit = limit or self._max_analysis_states
        with self._connection_factory.connect() as con:
            rows = con.execute(
                """
                select state_id, message_id, run_id, question, answer_summary, intent, metric,
                       dimensions, filters, dataset, last_sql, last_chart, row_count, state, created_at
                from analysis_conversation_states
                where tenant_id = %s and user_id = %s and conversation_id = %s
                order by state_id desc
                limit %s
                """,
                (request.tenant_id, user_id, request.conversation_id, row_limit),
            ).fetchall()
        return [self._analysis_state_row(row) for row in reversed(rows)]

    def find_pending_clarification(self, request: AgentRequest) -> dict[str, Any] | None:
        if not request.conversation_id:
            return None
        with self._connection_factory.connect() as con:
            row = con.execute(
                """
                select pending_clarification
                from analysis_catalog_sessions
                where tenant_id = %s and user_id = %s and conversation_id = %s
                """,
                (request.tenant_id, self._user_id(request), request.conversation_id),
            ).fetchone()
        pending = (row or {}).get("pending_clarification")
        return pending if isinstance(pending, dict) and pending.get("pending") else None

    def save_pending_clarification(self, request: AgentRequest, pending: dict[str, Any] | None) -> None:
        if not request.conversation_id or not pending:
            return
        now = utc_now()
        with self._connection_factory.connect() as con:
            con.execute(
                """
                update analysis_catalog_sessions
                set pending_clarification = %s::jsonb,
                    updated_at = %s
                where tenant_id = %s and user_id = %s and conversation_id = %s
                """,
                (self._json(pending), now, request.tenant_id, self._user_id(request), request.conversation_id),
            )

    def clear_pending_clarification(self, request: AgentRequest) -> None:
        if not request.conversation_id:
            return
        now = utc_now()
        with self._connection_factory.connect() as con:
            con.execute(
                """
                update analysis_catalog_sessions
                set pending_clarification = null,
                    updated_at = %s
                where tenant_id = %s and user_id = %s and conversation_id = %s
                """,
                (now, request.tenant_id, self._user_id(request), request.conversation_id),
            )

    def save_analysis_state(self, request: AgentRequest, analysis_state: dict[str, Any] | None) -> dict[str, Any] | None:
        if not request.conversation_id or not analysis_state:
            return None
        self.ensure_schema_if_allowed()
        user_id = self._user_id(request)
        now = utc_now()
        with self._connection_factory.connect() as con:
            with con.transaction():
                row = con.execute(
                    """
                    insert into analysis_conversation_states (
                        tenant_id, user_id, conversation_id, message_id, run_id, question,
                        answer_summary, intent, metric, dimensions, filters, dataset,
                        last_sql, last_chart, row_count, state, created_at
                    )
                    values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb,
                            %s::jsonb, %s, %s::jsonb, %s, %s::jsonb, %s)
                    returning state_id, message_id, run_id, question, answer_summary, intent, metric,
                              dimensions, filters, dataset, last_sql, last_chart, row_count, state, created_at
                    """,
                    (
                        request.tenant_id,
                        user_id,
                        request.conversation_id,
                        analysis_state.get("message_id"),
                        analysis_state.get("run_id"),
                        analysis_state.get("question") or request.question,
                        analysis_state.get("answer_summary"),
                        analysis_state.get("intent"),
                        analysis_state.get("metric"),
                        self._json(analysis_state.get("dimensions") or []),
                        self._json(analysis_state.get("filters") or []),
                        self._json(analysis_state.get("dataset") or {}),
                        analysis_state.get("last_sql"),
                        self._json(analysis_state.get("last_chart")) if analysis_state.get("last_chart") is not None else None,
                        int(analysis_state.get("row_count") or 0),
                        self._json(analysis_state.get("state") or {}),
                        now,
                    ),
                ).fetchone()
                self._prune_analysis_states(con, request.tenant_id, user_id, request.conversation_id)
        return self._analysis_state_row(row)

    def find_feedback_for_request(
        self,
        request: AgentRequest,
        source_file_ids: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        if not request.conversation_id:
            return []
        user_id = self._user_id(request)
        file_ids = [file_id for file_id in (source_file_ids or []) if file_id]
        with self._connection_factory.connect() as con:
            if file_ids:
                rows = con.execute(
                    """
                    select source_file_id, source_filename, step, label, content, updated_at
                    from analysis_catalog_feedback
                    where tenant_id = %s
                      and user_id = %s
                      and conversation_id = %s
                      and (source_file_id = any(%s) or source_file_id is null)
                    order by step, updated_at desc
                    """,
                    (request.tenant_id, user_id, request.conversation_id, file_ids),
                ).fetchall()
            else:
                rows = con.execute(
                    """
                    select source_file_id, source_filename, step, label, content, updated_at
                    from analysis_catalog_feedback
                    where tenant_id = %s
                      and user_id = %s
                      and conversation_id = %s
                    order by step, updated_at desc
                    """,
                    (request.tenant_id, user_id, request.conversation_id),
                ).fetchall()
        return [
            {
                "source_file_id": row["source_file_id"],
                "source_filename": row["source_filename"],
                "step": int(row["step"]),
                "label": row["label"],
                "content": row["content"],
                "updated_at": row["updated_at"].isoformat() if row["updated_at"] else None,
            }
            for row in rows
        ]

    def save_conversation(
        self,
        request: AgentRequest,
        files: list[FileMetadata],
        profiles: list[dict[str, Any]],
        table_map: dict[str, list[str]],
        cache_path: Path | None,
        cache_hits: int,
    ) -> None:
        if not request.conversation_id:
            return
        self.ensure_schema_if_allowed()
        now = utc_now()
        user_id = self._user_id(request)
        persist_previews = bool_env("ANALITRICS_PERSIST_PREVIEWS", False)
        stored_profiles = profiles_for_storage(profiles, persist_previews)
        processed_files = [
            {
                "file_id": metadata.file_id,
                "filename": metadata.filename,
                "storageKey": metadata.storage_key,
                "mimeType": metadata.mime_type,
                "bytes": metadata.bytes,
                "contentHash": metadata.content_hash,
                "signature": file_signature(metadata),
                "tables": table_map.get(metadata.file_id, []),
                "processedAt": now.isoformat(),
            }
            for metadata in files
        ]
        with self._connection_factory.connect() as con:
            with con.transaction():
                con.execute(
                    """
                    insert into analysis_catalog_sessions (
                        tenant_id, user_id, conversation_id, cache_path, files,
                        table_map, processed_files, last_cache_hits, created_at, updated_at
                    )
                    values (%s, %s, %s, %s, %s::jsonb, %s::jsonb, %s::jsonb, %s, %s, %s)
                    on conflict (tenant_id, user_id, conversation_id) do update set
                        cache_path = excluded.cache_path,
                        files = excluded.files,
                        table_map = excluded.table_map,
                        processed_files = excluded.processed_files,
                        last_cache_hits = excluded.last_cache_hits,
                        updated_at = excluded.updated_at
                    """,
                    (
                        request.tenant_id,
                        user_id,
                        request.conversation_id,
                        str(cache_path) if cache_path else None,
                        self._json([asdict(metadata) for metadata in files]),
                        self._json(table_map),
                        self._json(processed_files),
                        cache_hits,
                        now,
                        now,
                    ),
                )
                for profile in stored_profiles:
                    table_name = str(profile.get("table") or "")
                    if not table_name:
                        continue
                    con.execute(
                        """
                        insert into analysis_catalog_profiles (
                            tenant_id, user_id, conversation_id, table_name, source_file_id,
                            source_filename, profile, active, deleted_at, deleted_reason, updated_at
                        )
                        values (%s, %s, %s, %s, %s, %s, %s::jsonb, true, null, null, %s)
                        on conflict (tenant_id, user_id, conversation_id, table_name) do update set
                            source_file_id = excluded.source_file_id,
                            source_filename = excluded.source_filename,
                            profile = excluded.profile,
                            active = true,
                            deleted_at = null,
                            deleted_reason = null,
                            updated_at = excluded.updated_at
                        """,
                        (
                            request.tenant_id,
                            user_id,
                            request.conversation_id,
                            table_name,
                            profile.get("source_file_id"),
                            profile.get("source_filename"),
                            self._json(profile),
                            now,
                        ),
                    )

    def count_profiles(self, request: AgentRequest) -> int:
        if not request.conversation_id:
            return 0
        self.ensure_schema_if_allowed()
        with self._connection_factory.connect() as con:
            row = con.execute(
                """
                select count(*) as count
                from analysis_catalog_profiles
                where tenant_id = %s and user_id = %s and conversation_id = %s
                """,
                (request.tenant_id, self._user_id(request), request.conversation_id),
            ).fetchone()
            return int((row or {}).get("count") or 0)

    def ensure_schema_if_allowed(self) -> None:
        if not bool_env("ANALITRICS_RUNTIME_DDL_ENABLED", False):
            return
        with self._connection_factory.connect() as con:
            with con.transaction():
                con.execute(
                    """
                    create table if not exists analysis_catalog_sessions (
                        tenant_id text not null,
                        user_id text not null,
                        conversation_id text not null,
                        cache_path text,
                        files jsonb not null default '[]'::jsonb,
                        table_map jsonb not null default '{}'::jsonb,
                        processed_files jsonb not null default '[]'::jsonb,
                        pending_clarification jsonb,
                        last_cache_hits integer not null default 0,
                        created_at timestamptz not null,
                        updated_at timestamptz not null,
                        primary key (tenant_id, user_id, conversation_id)
                    )
                    """
                )
                con.execute(
                    """
                    alter table analysis_catalog_sessions
                    add column if not exists pending_clarification jsonb
                    """
                )
                con.execute(
                    """
                    create table if not exists analysis_catalog_profiles (
                        tenant_id text not null,
                        user_id text not null,
                        conversation_id text not null,
                        table_name text not null,
                        source_file_id text,
                        source_filename text,
                        profile jsonb not null,
                        updated_at timestamptz not null,
                        primary key (tenant_id, user_id, conversation_id, table_name),
                        foreign key (tenant_id, user_id, conversation_id)
                            references analysis_catalog_sessions (tenant_id, user_id, conversation_id)
                            on delete cascade
                    )
                    """
                )
                con.execute(
                    """
                    create index if not exists idx_analysis_catalog_profiles_file
                    on analysis_catalog_profiles (tenant_id, user_id, source_file_id)
                    """
                )
                con.execute(
                    """
                    create table if not exists analysis_catalog_feedback (
                        feedback_id bigserial primary key,
                        tenant_id text not null,
                        user_id text not null,
                        conversation_id text not null,
                        source_file_id text,
                        source_filename text,
                        step integer not null check (step between 1 and 6),
                        label text not null,
                        content text not null,
                        created_at timestamptz not null,
                        updated_at timestamptz not null,
                        foreign key (tenant_id, user_id, conversation_id)
                            references analysis_catalog_sessions (tenant_id, user_id, conversation_id)
                            on delete cascade
                    )
                    """
                )
                con.execute(
                    """
                    create index if not exists idx_analysis_catalog_feedback_conversation
                    on analysis_catalog_feedback (tenant_id, user_id, conversation_id, step)
                    """
                )
                con.execute(
                    """
                    create index if not exists idx_analysis_catalog_feedback_source
                    on analysis_catalog_feedback (tenant_id, user_id, conversation_id, source_file_id, step)
                    """
                )
                con.execute(
                    """
                    create table if not exists analysis_conversation_states (
                        state_id bigserial primary key,
                        tenant_id text not null,
                        user_id text not null,
                        conversation_id text not null,
                        message_id text,
                        run_id text,
                        question text not null,
                        answer_summary text,
                        intent text,
                        metric text,
                        dimensions jsonb not null default '[]'::jsonb,
                        filters jsonb not null default '[]'::jsonb,
                        dataset jsonb not null default '{}'::jsonb,
                        last_sql text,
                        last_chart jsonb,
                        row_count integer not null default 0,
                        state jsonb not null default '{}'::jsonb,
                        created_at timestamptz not null,
                        foreign key (tenant_id, user_id, conversation_id)
                            references analysis_catalog_sessions (tenant_id, user_id, conversation_id)
                            on delete cascade
                    )
                    """
                )
                con.execute(
                    """
                    create index if not exists idx_analysis_conversation_states_recent
                    on analysis_conversation_states (tenant_id, user_id, conversation_id, state_id desc)
                    """
                )
                con.execute(
                    """
                    create index if not exists idx_analysis_conversation_states_message
                    on analysis_conversation_states (tenant_id, user_id, conversation_id, message_id)
                    """
                )

    def invalidate_file(self, tenant_id: str, user_id: str, file_id: str, reason: str) -> int:
        now = utc_now()
        with self._connection_factory.connect() as con:
            with con.transaction():
                result = con.execute(
                    """
                    update analysis_catalog_profiles
                    set active = false,
                        deleted_at = %s,
                        deleted_reason = %s,
                        updated_at = %s
                    where tenant_id = %s
                      and user_id = %s
                      and source_file_id = %s
                      and active = true
                    """,
                    (now, reason, now, tenant_id, user_id, file_id),
                )
                con.execute(
                    """
                    update analysis_catalog_sessions
                    set updated_at = %s
                    where tenant_id = %s and user_id = %s
                    """,
                    (now, tenant_id, user_id),
                )
                return int(result.rowcount or 0)

    def delete_conversation(self, tenant_id: str, user_id: str, conversation_id: str) -> dict[str, Any]:
        with self._connection_factory.connect() as con:
            with con.transaction():
                row = con.execute(
                    """
                    select cache_path
                    from analysis_catalog_sessions
                    where tenant_id = %s and user_id = %s and conversation_id = %s
                    """,
                    (tenant_id, user_id, conversation_id),
                ).fetchone()
                result = con.execute(
                    """
                    delete from analysis_catalog_sessions
                    where tenant_id = %s and user_id = %s and conversation_id = %s
                    """,
                    (tenant_id, user_id, conversation_id),
                )
        return {
            "deletedCatalogSessions": int(result.rowcount or 0),
            "cachePath": row["cache_path"] if row else None,
        }

    def active_file_refs(self, limit: int = 1000) -> list[dict[str, str]]:
        with self._connection_factory.connect() as con:
            rows = con.execute(
                """
                select distinct tenant_id, user_id, source_file_id
                from analysis_catalog_profiles
                where active = true
                  and source_file_id is not null
                order by tenant_id, user_id, source_file_id
                limit %s
                """,
                (limit,),
            ).fetchall()
            return [
                {
                    "tenantId": str(row["tenant_id"]),
                    "userId": str(row["user_id"]),
                    "fileId": str(row["source_file_id"]),
                }
                for row in rows
            ]

    def _user_id(self, request: AgentRequest) -> str:
        return request.user_id or "anonymous"

    def _json(self, value: Any) -> str:
        return json.dumps(value, ensure_ascii=False, default=str)

    def _prune_analysis_states(
        self,
        con: psycopg.Connection,
        tenant_id: str,
        user_id: str,
        conversation_id: str,
    ) -> None:
        con.execute(
            """
            delete from analysis_conversation_states
            where tenant_id = %s
              and user_id = %s
              and conversation_id = %s
              and state_id not in (
                  select state_id
                  from analysis_conversation_states
                  where tenant_id = %s and user_id = %s and conversation_id = %s
                  order by state_id desc
                  limit %s
              )
            """,
            (tenant_id, user_id, conversation_id, tenant_id, user_id, conversation_id, self._max_analysis_states),
        )

    def _analysis_state_row(self, row: dict[str, Any]) -> dict[str, Any]:
        return {
            "state_id": str(row["state_id"]),
            "message_id": row["message_id"],
            "run_id": row["run_id"],
            "question": row["question"],
            "answer_summary": row["answer_summary"],
            "intent": row["intent"],
            "metric": row["metric"],
            "dimensions": row["dimensions"] or [],
            "filters": row["filters"] or [],
            "dataset": row["dataset"] or {},
            "last_sql": row["last_sql"],
            "last_chart": row["last_chart"],
            "row_count": int(row["row_count"] or 0),
            "state": row["state"] or {},
            "created_at": row["created_at"].isoformat() if row["created_at"] else None,
        }

    def _latest_feedback_proposal(self, analysis_states: list[dict[str, Any]]) -> dict[str, Any] | None:
        for analysis_state in reversed(analysis_states):
            state = analysis_state.get("state") or {}
            proposal = state.get("feedback_proposal")
            if isinstance(proposal, dict) and proposal.get("suggested"):
                return {
                    "stateId": analysis_state.get("state_id"),
                    "step": proposal.get("step"),
                    "label": proposal.get("label"),
                    "content": proposal.get("content"),
                    "sourceFileId": proposal.get("source_file_id"),
                    "sourceFilename": proposal.get("source_filename"),
                    "reason": proposal.get("reason"),
                }
        return None
