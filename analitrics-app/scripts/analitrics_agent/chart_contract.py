from __future__ import annotations

from typing import Any


VALID_CHART_TYPES = {"bar", "line", "pie"}
VALID_SORTS = {"preserve", "asc", "desc"}
MAX_CHART_POINTS = 50
MAX_Y_FIELDS = 3


class AnalitricsChartSpecNormalizer:
    def normalize(
        self,
        raw_spec: dict[str, Any] | None,
        rows: list[dict[str, Any]],
        fallback_title: str = "Visualizacion",
    ) -> dict[str, Any] | None:
        if not rows:
            return None
        columns = list(rows[0].keys())
        raw_spec = raw_spec or {}
        nested_spec = raw_spec.get("spec") if isinstance(raw_spec.get("spec"), dict) else None
        spec = nested_spec or raw_spec
        chart_type = str(spec.get("type") or raw_spec.get("chart_type") or spec.get("chart_type") or "bar").lower()
        if chart_type not in VALID_CHART_TYPES:
            chart_type = "bar"

        x_field = str(spec.get("xField") or spec.get("x_field") or spec.get("x_key") or self._first_text_column(rows) or columns[0])
        y_fields = spec.get("yFields") or spec.get("y_fields") or spec.get("y_keys")
        if not isinstance(y_fields, list) or not y_fields:
            y_fields = self._numeric_columns(rows)
        y_fields = [str(field) for field in y_fields if str(field) in columns][:MAX_Y_FIELDS]
        if x_field not in columns or not y_fields:
            return None

        sort = str(spec.get("sort") or "preserve").lower()
        if sort not in VALID_SORTS:
            sort = "preserve"
        limit = self._int_value(spec.get("limit"), min(len(rows), 12))
        limit = max(1, min(limit, MAX_CHART_POINTS))

        return {
            "version": 1,
            "renderer": "echarts",
            "type": chart_type,
            "title": str(spec.get("title") or fallback_title)[:120],
            "xField": x_field,
            "yFields": y_fields,
            "sort": sort,
            "limit": limit,
            "valueFormat": str(spec.get("valueFormat") or spec.get("value_format") or "number"),
            "categoryLabel": str(spec.get("categoryLabel") or spec.get("category_label") or x_field),
            "notes": str(spec.get("notes") or "")[:500],
        }

    def infer(self, rows: list[dict[str, Any]], title: str) -> dict[str, Any] | None:
        return self.normalize({"type": "bar", "title": title, "sort": "preserve"}, rows, title)

    def _first_text_column(self, rows: list[dict[str, Any]]) -> str | None:
        for key, value in rows[0].items():
            if isinstance(value, str):
                return key
        return None

    def _numeric_columns(self, rows: list[dict[str, Any]]) -> list[str]:
        columns: list[str] = []
        for key in rows[0].keys():
            values = [row.get(key) for row in rows[:20]]
            if any(isinstance(value, (int, float)) and not isinstance(value, bool) for value in values):
                columns.append(key)
        return columns

    def _int_value(self, value: Any, default: int) -> int:
        if isinstance(value, bool):
            return default
        if isinstance(value, (int, float)):
            return int(value)
        if isinstance(value, str):
            try:
                return int(value.strip())
            except ValueError:
                return default
        return default
