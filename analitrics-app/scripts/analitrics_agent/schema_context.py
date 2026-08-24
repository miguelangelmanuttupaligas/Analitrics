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

    def build_for_sql(
        self,
        files: list[FileMetadata],
        profiles: list[dict[str, Any]],
        catalog_feedback: list[dict[str, Any]] | None = None,
        analytical_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        plan = (analytical_context or {}).get("conversation_plan") or {}
        if plan.get("confidence") == "low":
            return self.build(files, profiles, catalog_feedback)
        compact_profiles = [
            {
                "table": profile["table"],
                "row_count": profile["row_count"],
                "columns": [self._compact_column(column) for column in profile.get("columns", [])],
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
                    "mimeType": metadata.mime_type,
                    "bytes": metadata.bytes,
                }
                for metadata in files
            ],
            "duckdb_schema": compact_profiles,
            "business_feedback": self._compact_feedback(catalog_feedback or []),
            "context_policy": {
                "mode": "planner_compact",
                "fallback": "full_context_when_confidence_low",
            },
        }

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

    def _compact_column(self, column: dict[str, Any]) -> dict[str, Any]:
        sample_values = column.get("sample_values") or []
        return {
            "name": column.get("name"),
            "type": column.get("type"),
            "null_ratio": column.get("null_ratio"),
            "distinct_count": column.get("distinct_count"),
            "sample_values": sample_values[:2] if isinstance(sample_values, list) else [],
        }
