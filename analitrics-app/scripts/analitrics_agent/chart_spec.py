from __future__ import annotations

from typing import Any

from .analytical_context import AnalyticalContextPromptCompactor
from .config import env
from .llm_client import JsonLlmClient
from .prompts import CHART_SPEC_SYSTEM_PROMPT


VALID_CHART_TYPES = {"bar", "line", "pie"}


class ChartSpecGenerator:
    def __init__(
        self,
        llm_client: JsonLlmClient,
        context_compactor: AnalyticalContextPromptCompactor | None = None,
    ) -> None:
        self._llm_client = llm_client
        self._context_compactor = context_compactor or AnalyticalContextPromptCompactor()

    def generate(
        self,
        question: str,
        sql: str,
        rows: list[dict[str, Any]],
        analytical_context: dict[str, Any],
    ) -> dict[str, Any]:
        result = self._llm_client.complete_json(
            system=CHART_SPEC_SYSTEM_PROMPT,
            payload={
                "question": question,
                "sql": sql,
                "rows": rows[:12],
                "row_count": len(rows),
                "analytical_context": self._context_compactor.for_chart(analytical_context),
            },
            model_env="ANALITRICS_CHART_SPEC_MODEL",
            default_model=env("ANALITRICS_DEFAULT_MODEL", "gpt-5.5"),
        )
        return self._normalize(result, rows, analytical_context)

    def _normalize(
        self,
        result: dict[str, Any],
        rows: list[dict[str, Any]],
        analytical_context: dict[str, Any],
    ) -> dict[str, Any]:
        conversation_plan = analytical_context.get("conversation_plan") or {}
        chart_intent = bool(result.get("chart_intent")) or bool(conversation_plan.get("chart_request"))
        chart_required = bool(result.get("chart_required")) or chart_intent
        if conversation_plan.get("chart_request") is False:
            chart_intent = False
            chart_required = False
        chart_type = str(result.get("chart_type") or conversation_plan.get("chart_type") or "bar")
        if chart_type not in VALID_CHART_TYPES:
            chart_type = "bar"
        if not rows:
            return {
                "chart_required": False,
                "chart_intent": chart_intent,
                "chart_type": chart_type,
                "renderer": "echarts",
                "spec": None,
                "reason": "No hay filas para graficar.",
            }
        spec = result.get("spec") if isinstance(result.get("spec"), dict) else {}
        columns = list(rows[0].keys()) if rows else []
        x_key = str(spec.get("x_key") or self._first_text_column(rows) or (columns[0] if columns else "categoria"))
        y_keys = spec.get("y_keys")
        if not isinstance(y_keys, list) or not y_keys:
            numeric = self._numeric_columns(rows)
            y_keys = numeric[:2] if numeric else [columns[1]] if len(columns) > 1 else []
        y_keys = [str(key) for key in y_keys if str(key) in columns][:3]
        if x_key not in columns or not y_keys:
            chart_required = False
        points = rows[:12]
        return {
            "chart_required": chart_required,
            "chart_intent": chart_intent,
            "chart_type": chart_type,
            "renderer": "echarts",
            "spec": {
                "title": str(spec.get("title") or result.get("title") or ""),
                "x_key": x_key,
                "y_keys": y_keys,
                "series": points,
                "sort": spec.get("sort") or "preserve",
                "limit": min(self._int_value(spec.get("limit"), len(points)), 12),
                "value_format": spec.get("value_format") or "number",
                "category_label": spec.get("category_label") or x_key,
                "notes": spec.get("notes") or result.get("reason") or "",
            }
            if chart_required
            else None,
            "reason": str(result.get("reason") or ("El usuario pidió una visualización." if chart_required else "No se requiere gráfico.")),
        }

    def _first_text_column(self, rows: list[dict[str, Any]]) -> str | None:
        if not rows:
            return None
        for key, value in rows[0].items():
            if isinstance(value, str):
                return key
        return None

    def _numeric_columns(self, rows: list[dict[str, Any]]) -> list[str]:
        if not rows:
            return []
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
