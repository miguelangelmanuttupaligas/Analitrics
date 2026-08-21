from __future__ import annotations

from typing import Any


NUMERIC_TYPE_HINTS = ("int", "decimal", "double", "float", "real", "numeric", "hugeint", "bigint", "utinyint", "smallint")
DATE_TYPE_HINTS = ("date", "time", "timestamp")


class IngestionStatusBuilder:
    def build(
        self,
        files: list[dict[str, Any]],
        tables: list[dict[str, Any]],
        cache_hits: int | None,
        catalog_found: bool,
    ) -> dict[str, Any]:
        file_count = len(files)
        data_tables = [table for table in tables if not table.get("systemTable")]
        stages = [
            self._stage("files_resolved", file_count > 0, f"{file_count} archivo(s) resuelto(s)."),
            self._stage("rustfs_available", self._all_have(files, "storageKey"), "Archivos fuente disponibles en RustFS."),
            self._stage("duckdb_ready", bool(data_tables), f"{len(data_tables)} tabla(s) disponibles en DuckDB."),
            self._stage("catalog_persisted", catalog_found and bool(data_tables), "Catálogo disponible en Postgres control plane."),
        ]
        return {
            "status": "ready" if all(stage["ok"] for stage in stages) else "pending",
            "stages": stages,
            "cache": {
                "hitCount": int(cache_hits or 0),
                "mode": "reused" if int(cache_hits or 0) > 0 else "built_or_refreshed",
            },
        }

    def _stage(self, code: str, ok: bool, label: str) -> dict[str, Any]:
        return {"code": code, "ok": ok, "label": label}

    def _all_have(self, rows: list[dict[str, Any]], key: str) -> bool:
        return bool(rows) and all(bool(row.get(key)) for row in rows)


class BusinessSummaryBuilder:
    def build(
        self,
        files: list[dict[str, Any]],
        tables: list[dict[str, Any]],
        feedback: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        data_tables = [table for table in tables if not table.get("systemTable")]
        metrics: list[dict[str, Any]] = []
        dimensions: list[dict[str, Any]] = []
        dates: list[dict[str, Any]] = []
        quality_warnings: list[dict[str, Any]] = []

        for table in data_tables:
            row_count = int(table.get("rowCount") or 0)
            if row_count == 0:
                quality_warnings.append(
                    {
                        "severity": "warning",
                        "code": "empty_table",
                        "message": f"La tabla {table.get('table')} no tiene filas.",
                        "table": table.get("table"),
                    }
                )
            for column in table.get("columns") or []:
                column_type = str(column.get("type") or "")
                item = {
                    "name": column.get("name"),
                    "type": column_type,
                    "table": table.get("table"),
                    "sourceFileId": table.get("sourceFileId"),
                    "sourceFilename": table.get("sourceFilename"),
                    "distinctCount": column.get("distinct_count"),
                    "nullRatio": round(float(column.get("null_ratio") or 0.0), 4),
                    "sampleValues": self._sample_values(column.get("sample_values") or []),
                }
                if self._is_numeric(column_type):
                    metrics.append(item)
                elif self._is_date(column_type):
                    dates.append(item)
                else:
                    dimensions.append(item)
                if float(column.get("null_ratio") or 0.0) >= 0.5:
                    quality_warnings.append(
                        {
                            "severity": "warning",
                            "code": "high_null_ratio",
                            "message": f"La columna {column.get('name')} tiene muchos valores vacíos.",
                            "table": table.get("table"),
                            "column": column.get("name"),
                            "nullRatio": item["nullRatio"],
                        }
                    )

        return {
            "title": "Resumen ejecutivo",
            "sourceCount": len(files),
            "tableCount": len(data_tables),
            "rowCountTotal": sum(int(table.get("rowCount") or 0) for table in data_tables),
            "candidateMetrics": metrics[:12],
            "candidateDimensions": dimensions[:12],
            "candidateDates": dates[:8],
            "qualityWarnings": quality_warnings[:12],
            "feedbackCount": len(feedback or []),
            "catalogMaturity": self._catalog_maturity(feedback or []),
        }

    def _is_numeric(self, column_type: str) -> bool:
        lowered = column_type.lower()
        return any(hint in lowered for hint in NUMERIC_TYPE_HINTS)

    def _is_date(self, column_type: str) -> bool:
        lowered = column_type.lower()
        return any(hint in lowered for hint in DATE_TYPE_HINTS)

    def _sample_values(self, rows: list[Any]) -> list[Any]:
        values: list[Any] = []
        for row in rows:
            if isinstance(row, dict) and row:
                values.append(next(iter(row.values())))
            else:
                values.append(row)
        return values[:5]

    def _catalog_maturity(self, feedback: list[dict[str, Any]]) -> dict[str, Any]:
        completed_steps = sorted({int(item.get("step") or 0) for item in feedback if item.get("content")})
        return {
            "completedSteps": completed_steps,
            "completedCount": len(completed_steps),
            "recommendedNextStep": next((step for step in range(1, 7) if step not in completed_steps), None),
        }
