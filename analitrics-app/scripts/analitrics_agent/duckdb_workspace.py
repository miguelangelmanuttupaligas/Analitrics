from __future__ import annotations

import tempfile
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd

from nl_sql_file import FileMetadata, download_from_rustfs, load_csv, load_workbook, profile_tables

from .errors import FileIngestError
from .file_integrity import FileCacheSignatureBuilder, FileContentHasher
from .models import AgentRequest
from .naming import sanitize_path_segment, table_name_for_file


@dataclass
class DuckDbWorkspace:
    connection: duckdb.DuckDBPyConnection
    tables: list[str]
    local_paths: list[str]
    table_map: dict[str, list[str]]
    cache_hit_map: dict[str, bool]
    cache_hits: int
    cache_path: Path | None
    tmpdir: tempfile.TemporaryDirectory[str]
    cache_lock: "CacheLock | None" = None

    def close(self) -> None:
        try:
            self.connection.close()
        finally:
            self.tmpdir.cleanup()
            if self.cache_lock is not None:
                self.cache_lock.release()


class CacheLock:
    def __init__(self, lock_path: Path, timeout_seconds: float = 30.0, poll_seconds: float = 0.2) -> None:
        self._lock_path = lock_path
        self._timeout_seconds = timeout_seconds
        self._poll_seconds = poll_seconds
        self._acquired = False

    def acquire(self) -> None:
        self._lock_path.parent.mkdir(parents=True, exist_ok=True)
        deadline = time.monotonic() + self._timeout_seconds
        while True:
            try:
                fd = os.open(str(self._lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                with os.fdopen(fd, "w") as handle:
                    handle.write(str(os.getpid()))
                self._acquired = True
                return
            except FileExistsError:
                if time.monotonic() >= deadline:
                    raise RuntimeError(f"Timed out waiting for DuckDB cache lock: {self._lock_path}")
                time.sleep(self._poll_seconds)

    def release(self) -> None:
        if not self._acquired:
            return
        try:
            self._lock_path.unlink(missing_ok=True)
        finally:
            self._acquired = False


class CachePathResolver:
    def resolve(self, request: AgentRequest) -> Path | None:
        if not request.conversation_id:
            return None
        if not request.user_id:
            raise RuntimeError("Analitrics requires userId to create a DuckDB cache path")

        configured_base = Path(os.getenv("ANALITRICS_CACHE_DIR", request.cache_dir)).expanduser().resolve()
        base = Path(request.cache_dir).expanduser().resolve()
        if base != configured_base:
            raise RuntimeError(f"Unsafe DuckDB cache root rejected: {base}")
        tenant = sanitize_path_segment(request.tenant_id, "tenant")
        user = sanitize_path_segment(request.user_id, "user")
        conversation = sanitize_path_segment(request.conversation_id, "conversation")
        cache_path = (base / tenant / user / f"{conversation}.duckdb").resolve()
        if cache_path.suffix != ".duckdb" or not cache_path.is_relative_to(base):
            raise RuntimeError(f"Unsafe DuckDB cache path rejected: {cache_path}")
        return cache_path


class DuckDbTableCatalog:
    def existing_tables(self, con: duckdb.DuckDBPyConnection) -> set[str]:
        try:
            return {str(row[0]) for row in con.execute("show tables").fetchall()}
        except Exception:
            return set()

    def materialize_catalog_table(
        self,
        con: duckdb.DuckDBPyConnection,
        profiles: list[dict[str, Any]],
    ) -> dict[str, Any]:
        rows = [
            {
                "table_name": profile["table"],
                "source_file_id": profile.get("source_file_id"),
                "source_filename": profile.get("source_filename"),
                "row_count": int(profile.get("row_count") or 0),
                "column_count": len(profile.get("columns") or []),
            }
            for profile in profiles
        ]
        df = pd.DataFrame(rows)
        con.register("_catalog_df", df)
        con.execute('create or replace table "__analitrics_catalog" as select * from _catalog_df')
        con.unregister("_catalog_df")
        return {
            "table": "__analitrics_catalog",
            "row_count": len(rows),
            "columns": [
                {"name": "table_name", "type": "VARCHAR"},
                {"name": "source_file_id", "type": "VARCHAR"},
                {"name": "source_filename", "type": "VARCHAR"},
                {"name": "row_count", "type": "BIGINT"},
                {"name": "column_count", "type": "BIGINT"},
            ],
            "sample": rows[:20],
            "source_file_id": None,
            "source_filename": None,
            "system_table": True,
        }


class ProfileEnricher:
    def enrich(
        self,
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


class DuckDbWorkspaceFactory:
    def __init__(
        self,
        catalog_repository: Any,
        cache_path_resolver: CachePathResolver | None = None,
        table_catalog: DuckDbTableCatalog | None = None,
        content_hasher: FileContentHasher | None = None,
        signature_builder: FileCacheSignatureBuilder | None = None,
    ) -> None:
        self._catalog_repository = catalog_repository
        self._cache_path_resolver = cache_path_resolver or CachePathResolver()
        self._table_catalog = table_catalog or DuckDbTableCatalog()
        self._content_hasher = content_hasher or FileContentHasher()
        self._signature_builder = signature_builder or FileCacheSignatureBuilder()

    def create(self, request: AgentRequest, files: list[FileMetadata]) -> DuckDbWorkspace:
        tmpdir = tempfile.TemporaryDirectory(prefix="analitrics-agent-")
        cache_path = self._cache_path_resolver.resolve(request)
        cache_lock = CacheLock(cache_path.with_suffix(".lock")) if cache_path else None
        con: duckdb.DuckDBPyConnection | None = None
        try:
            if cache_lock:
                cache_lock.acquire()
            cache_exists = cache_path.exists() if cache_path else False
            if cache_path:
                cache_path.parent.mkdir(parents=True, exist_ok=True)
                con = duckdb.connect(database=str(cache_path))
            else:
                con = duckdb.connect(database=":memory:")

            conversation_doc = self._catalog_repository.find_conversation(request) if cache_exists else None
            processed_by_signature = {
                str(item.get("signature")): item
                for item in (conversation_doc or {}).get("processedFiles", [])
                if item.get("signature")
            }
            available_tables = self._table_catalog.existing_tables(con)
            all_tables: list[str] = []
            local_paths: list[str] = []
            table_map: dict[str, list[str]] = {}
            cache_hit_map: dict[str, bool] = {}
            cache_hits = 0

            for metadata in files:
                file_dir = Path(tmpdir.name) / metadata.file_id
                file_dir.mkdir(parents=True, exist_ok=True)
                local_path = download_from_rustfs(metadata, file_dir)
                metadata.content_hash = self._content_hasher.hash_path(local_path)

                signature = self._signature_builder.build(metadata)
                cached = processed_by_signature.get(signature)
                cached_tables = [str(table) for table in (cached or {}).get("tables", [])]
                if cached_tables and all(table in available_tables for table in cached_tables):
                    table_map[metadata.file_id] = cached_tables
                    all_tables.extend(cached_tables)
                    cache_hit_map[metadata.file_id] = True
                    cache_hits += 1
                    continue

                local_paths.append(str(local_path))
                cache_hit_map[metadata.file_id] = False

                raw_tables = self._load_tables(con, local_path, metadata)

                renamed_tables: list[str] = []
                for raw_table in raw_tables:
                    final_table = table_name_for_file(metadata, raw_table)
                    if final_table != raw_table:
                        con.execute(f'create or replace table "{final_table}" as select * from "{raw_table}"')
                        con.execute(f'drop table "{raw_table}"')
                    renamed_tables.append(final_table)
                    all_tables.append(final_table)
                table_map[metadata.file_id] = renamed_tables
                available_tables.update(renamed_tables)

            return DuckDbWorkspace(con, all_tables, local_paths, table_map, cache_hit_map, cache_hits, cache_path, tmpdir, cache_lock)
        except Exception:
            if con is not None:
                con.close()
            tmpdir.cleanup()
            if cache_lock is not None:
                cache_lock.release()
            raise

    def profile(self, workspace: DuckDbWorkspace, sample_rows: int) -> list[dict[str, Any]]:
        return profile_tables(workspace.connection, workspace.tables, sample_rows)

    def _load_tables(self, con: duckdb.DuckDBPyConnection, local_path: Path, metadata: FileMetadata) -> list[str]:
        extension = local_path.suffix.lower()
        try:
            if extension == ".csv" or metadata.mime_type in {"text/csv", "application/csv"}:
                return load_csv(con, local_path, metadata.filename)
            return load_workbook(con, local_path)
        except Exception as exc:
            stage = "csv_read_csv_auto" if extension == ".csv" or metadata.mime_type in {"text/csv", "application/csv"} else "excel_openpyxl"
            raise FileIngestError(metadata, stage, exc) from exc
