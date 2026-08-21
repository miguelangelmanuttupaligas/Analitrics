from __future__ import annotations

import json
from typing import Any

from nl_sql_file import FileMetadata


class SchemaContextBuilder:
    def build(
        self,
        files: list[FileMetadata],
        profiles: list[dict[str, Any]],
        catalog_feedback: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        compact_profiles = [
            {
                "table": profile["table"],
                "row_count": profile["row_count"],
                "columns": profile["columns"],
                "sample": profile["sample"][:3],
                "source_file_id": profile.get("source_file_id"),
                "source_filename": profile.get("source_filename"),
            }
            for profile in profiles
        ]
        return {
            "files": [
                {
                    "file_id": metadata.file_id,
                    "filename": metadata.filename,
                    "tenantId": metadata.tenant_id,
                    "mimeType": metadata.mime_type,
                    "bytes": metadata.bytes,
                }
                for metadata in files
            ],
            "duckdb_schema": compact_profiles,
            "business_feedback": self._compact_feedback(catalog_feedback or []),
        }

    def build_json(
        self,
        files: list[FileMetadata],
        profiles: list[dict[str, Any]],
        catalog_feedback: list[dict[str, Any]] | None = None,
    ) -> str:
        return json.dumps(self.build(files, profiles, catalog_feedback), ensure_ascii=False, indent=2)

    def _compact_feedback(self, feedback: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [
            {
                "source_file_id": item.get("source_file_id"),
                "source_filename": item.get("source_filename"),
                "step": item.get("step"),
                "label": item.get("label"),
                "content": item.get("content"),
            }
            for item in feedback
            if str(item.get("content") or "").strip()
        ]
