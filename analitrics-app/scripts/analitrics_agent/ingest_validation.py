from __future__ import annotations

from dataclasses import asdict
import os
from pathlib import Path
from typing import Any

from nl_sql_file import owner_query_values

from .control_plane import CatalogRepository, PostgresControlPlaneFactory
from .duckdb_workspace import DuckDbTableCatalog, DuckDbWorkspaceFactory, ProfileEnricher
from .file_resolver import FileResolver
from .models import AgentRequest
from .repositories import ConversationAttachmentRepository, MongoDatabaseFactory


class ProfileSummaryBuilder:
    def build(self, profile: dict[str, Any]) -> dict[str, Any]:
        columns = profile.get("columns") or []
        return {
            "table": profile.get("table"),
            "rowCount": int(profile.get("row_count") or 0),
            "columnCount": len(columns),
            "columns": [column.get("name") for column in columns if isinstance(column, dict)],
            "sourceFileId": profile.get("source_file_id"),
            "sourceFilename": profile.get("source_filename"),
            "systemTable": bool(profile.get("system_table")),
        }


class FileContextSummaryBuilder:
    def build(
        self,
        files: list[Any],
        table_map: dict[str, list[str]],
        cache_hit_map: dict[str, bool],
    ) -> list[dict[str, Any]]:
        summaries: list[dict[str, Any]] = []
        for metadata in files:
            payload = asdict(metadata)
            summaries.append(
                {
                    "fileId": metadata.file_id,
                    "filename": metadata.filename,
                    "tenantId": metadata.tenant_id,
                    "mimeType": metadata.mime_type,
                    "bytes": metadata.bytes,
                    "source": metadata.source,
                    "storageKey": metadata.storage_key,
                    "contentHash": metadata.content_hash,
                    "tables": table_map.get(metadata.file_id, []),
                    "cacheHit": bool(cache_hit_map.get(metadata.file_id)),
                    "rawMetadata": payload,
                }
            )
        return summaries


class IngestValidationService:
    def __init__(
        self,
        file_resolver: FileResolver,
        workspace_factory: DuckDbWorkspaceFactory,
        profile_enricher: ProfileEnricher,
        table_catalog: DuckDbTableCatalog,
        catalog_repository: CatalogRepository,
        file_context_builder: FileContextSummaryBuilder | None = None,
        profile_summary_builder: ProfileSummaryBuilder | None = None,
    ) -> None:
        self._file_resolver = file_resolver
        self._workspace_factory = workspace_factory
        self._profile_enricher = profile_enricher
        self._table_catalog = table_catalog
        self._catalog_repository = catalog_repository
        self._file_context_builder = file_context_builder or FileContextSummaryBuilder()
        self._profile_summary_builder = profile_summary_builder or ProfileSummaryBuilder()

    def validate(self, request: AgentRequest) -> dict[str, Any]:
        workspace = None
        try:
            files = self._file_resolver.resolve(request)
            workspace = self._workspace_factory.create(request, files)
            profiles = self._workspace_factory.profile(workspace, request.sample_rows)
            profiles = self._profile_enricher.enrich(files, profiles, workspace.table_map)
            catalog_profile = self._table_catalog.materialize_catalog_table(workspace.connection, profiles)
            profiles = [*profiles, catalog_profile]
            tables = [*workspace.tables, "__analitrics_catalog"]
            self._catalog_repository.save_conversation(
                request,
                files,
                profiles,
                workspace.table_map,
                workspace.cache_path,
                workspace.cache_hits,
            )
            persisted_conversation = self._catalog_repository.find_conversation(request)
            return {
                "ok": True,
                "llmUsed": False,
                "runId": request.run_id,
                "tenantId": request.tenant_id,
                "userId": request.user_id,
                "conversationId": request.conversation_id,
                "messageId": request.message_id,
                "cachePath": str(workspace.cache_path) if workspace.cache_path else None,
                "cacheHits": workspace.cache_hits,
                "files": self._file_context_builder.build(files, workspace.table_map, workspace.cache_hit_map),
                "tables": tables,
                "profiles": [self._profile_summary_builder.build(profile) for profile in profiles],
                "context": {
                    "fileCount": len(files),
                    "tableCount": len(tables),
                    "rowCountTotal": sum(int(profile.get("row_count") or 0) for profile in profiles),
                    "bytesTotal": sum(metadata.bytes for metadata in files),
                    "resolvedFileIds": [metadata.file_id for metadata in files],
                    "resolvedFilenames": [metadata.filename for metadata in files],
                },
                "persistence": {
                    "fileMetadataStore": "mongodb.files",
                    "catalogStoreMvp": "postgres.analysis_catalog_sessions + postgres.analysis_catalog_profiles",
                    "postgresCatalogPersisted": True,
                    "postgresIsolationKeys": ["tenant_id", "user_id", "conversation_id"],
                    "conversationPersisted": persisted_conversation is not None,
                    "persistedProfileCount": self._catalog_repository.count_profiles(request),
                    "persistedProcessedFileCount": len((persisted_conversation or {}).get("processedFiles") or []),
                },
            }
        finally:
            if workspace is not None:
                workspace.close()

    def invalidate_file(self, tenant_id: str, user_id: str, file_id: str, reason: str) -> int:
        return self._catalog_repository.invalidate_file(tenant_id, user_id, file_id, reason)

    def get_context(self, tenant_id: str, user_id: str, conversation_id: str) -> dict[str, Any]:
        return self._catalog_repository.get_context(tenant_id, user_id, conversation_id)

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
        return self._catalog_repository.save_feedback(
            tenant_id=tenant_id,
            user_id=user_id,
            conversation_id=conversation_id,
            source_file_id=source_file_id,
            source_filename=source_filename,
            step=step,
            label=label,
            content=content,
        )

    def delete_conversation(self, tenant_id: str, user_id: str, conversation_id: str) -> dict[str, Any]:
        result = self._catalog_repository.delete_conversation(tenant_id, user_id, conversation_id)
        deleted_cache = False
        deleted_lock = False
        cache_path_value = result.get("cachePath")
        if cache_path_value:
            base = Path(os.getenv("ANALITRICS_CACHE_DIR", "/var/analitrics/analytics/cache")).resolve()
            cache_path = Path(str(cache_path_value)).resolve()
            if cache_path.suffix != ".duckdb" or not cache_path.is_relative_to(base):
                raise RuntimeError(f"Unsafe DuckDB cache deletion path rejected: {cache_path}")
            if cache_path.exists():
                cache_path.unlink()
                deleted_cache = True
            lock_path = cache_path.with_suffix(".lock")
            if lock_path.exists():
                lock_path.unlink()
                deleted_lock = True
        return {
            **result,
            "deletedDuckdb": deleted_cache,
            "deletedLock": deleted_lock,
        }

    def reconcile_deleted_files(self, limit: int = 1000) -> dict[str, Any]:
        db = self._file_resolver.database
        checked = 0
        invalidated_files = 0
        invalidated_profiles = 0
        for ref in self._catalog_repository.active_file_refs(limit=limit):
            checked += 1
            tenant_id = ref["tenantId"]
            user_id = ref["userId"]
            file_id = ref["fileId"]
            exists = db.files.find_one(
                {
                    "tenantId": tenant_id,
                    "source": "s3",
                    "file_id": file_id,
                    "user": {"$in": owner_query_values(user_id)},
                },
                {"_id": 1},
            )
            if exists:
                continue
            count = self.invalidate_file(
                tenant_id=tenant_id,
                user_id=user_id,
                file_id=file_id,
                reason="mongodb_file_missing_reconciliation",
            )
            if count:
                invalidated_files += 1
                invalidated_profiles += count
        return {
            "checkedFiles": checked,
            "invalidatedFiles": invalidated_files,
            "invalidatedProfiles": invalidated_profiles,
        }


class IngestValidationFactory:
    _instance: IngestValidationService | None = None

    @classmethod
    def get_service(cls) -> IngestValidationService:
        if cls._instance is None:
            cls._instance = cls.create_service()
        return cls._instance

    @classmethod
    def create_service(cls) -> IngestValidationService:
        database_factory = MongoDatabaseFactory()
        catalog_repository = CatalogRepository(PostgresControlPlaneFactory())
        table_catalog = DuckDbTableCatalog()
        return IngestValidationService(
            file_resolver=FileResolver(ConversationAttachmentRepository(database_factory)),
            workspace_factory=DuckDbWorkspaceFactory(catalog_repository, table_catalog=table_catalog),
            profile_enricher=ProfileEnricher(),
            table_catalog=table_catalog,
            catalog_repository=catalog_repository,
        )
