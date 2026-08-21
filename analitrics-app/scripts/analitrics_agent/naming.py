from __future__ import annotations

from pathlib import Path

from nl_sql_file import FileMetadata, normalize_identifier

from .file_integrity import FileCacheSignatureBuilder


def sanitize_path_segment(value: str, fallback: str) -> str:
    sanitized = normalize_identifier(value, fallback)
    return sanitized or fallback


def table_name_for_file(metadata: FileMetadata, table: str) -> str:
    file_stem = normalize_identifier(Path(metadata.filename).stem, "file")
    short_id = normalize_identifier(metadata.file_id.split("-")[0], "file")
    return normalize_identifier(f"{file_stem}_{short_id}_{table}", "table")


def file_signature(metadata: FileMetadata) -> str:
    return FileCacheSignatureBuilder().build(metadata)
