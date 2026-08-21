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

    def find_conversation(self, request: AgentRequest) -> dict[str, Any] | None:
        if not request.conversation_id:
            return None
        self.ensure_schema_if_allowed()
        with self._connection_factory.connect() as con:
            row = con.execute(
                """
                select tenant_id, user_id, conversation_id, cache_path, processed_files, updated_at
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
                "updatedAt": row["updated_at"],
            }

    def get_context(self, tenant_id: str, user_id: str, conversation_id: str) -> dict[str, Any]:
        with self._connection_factory.connect() as con:
            conversation = con.execute(
                """
                select tenant_id, user_id, conversation_id, cache_path, files,
                       table_map, processed_files, last_cache_hits, created_at, updated_at
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

        profiles = [row["profile"] for row in profile_rows]
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
                        last_cache_hits integer not null default 0,
                        created_at timestamptz not null,
                        updated_at timestamptz not null,
                        primary key (tenant_id, user_id, conversation_id)
                    )
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
