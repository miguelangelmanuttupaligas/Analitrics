from __future__ import annotations

from typing import Any

from .config import env
from .analytical_context import AnalyticalContextPromptCompactor
from .llm_client import JsonLlmClient
from .prompts import CONVERSATION_PLANNER_SYSTEM_PROMPT


VALID_REQUEST_KINDS = {"new_question", "follow_up", "correction", "clarification", "out_of_scope"}
VALID_CONFIDENCE = {"high", "medium", "low"}
VALID_CHART_TYPES = {"bar", "line", "area", "pie", "scatter", "table"}


class ConversationPlanner:
    def __init__(
        self,
        llm_client: JsonLlmClient,
        context_compactor: AnalyticalContextPromptCompactor | None = None,
    ) -> None:
        self._llm_client = llm_client
        self._context_compactor = context_compactor or AnalyticalContextPromptCompactor()

    def plan(
        self,
        question: str,
        analytical_context: dict[str, Any],
        available_data: dict[str, Any],
    ) -> dict[str, Any]:
        raw = self._llm_client.complete_json(
            system=CONVERSATION_PLANNER_SYSTEM_PROMPT,
            payload={
                "question": question,
                "analytical_context": self._context_compactor.for_planner(analytical_context),
                "available_data": self._compact_available_data(available_data),
            },
            model_env="ANALITRICS_CONVERSATION_PLANNER_MODEL",
            default_model=env("ANALITRICS_DEFAULT_MODEL", "gpt-5.5"),
        )
        return self._normalize(raw, question, analytical_context)

    def _normalize(self, raw: dict[str, Any], question: str, analytical_context: dict[str, Any]) -> dict[str, Any]:
        request_kind = str(raw.get("request_kind") or "new_question")
        if request_kind not in VALID_REQUEST_KINDS:
            request_kind = "new_question"
        confidence = str(raw.get("confidence") or "medium")
        if confidence not in VALID_CONFIDENCE:
            confidence = "medium"
        chart_type = raw.get("chart_type")
        if chart_type is not None:
            chart_type = str(chart_type)
            if chart_type not in VALID_CHART_TYPES:
                chart_type = None
        selected_id = self._selected_state_id(raw.get("selected_analysis_state_id"), analytical_context)
        needs_clarification = bool(raw.get("needs_clarification")) or confidence == "low"
        clarification_question = str(raw.get("clarification_question") or "").strip() or None
        if needs_clarification and not clarification_question:
            clarification_question = "Necesito una aclaración para continuar: ¿a qué análisis o métrica te refieres?"
        feedback_candidate = raw.get("catalog_feedback_candidate")
        if not isinstance(feedback_candidate, dict):
            feedback_candidate = None
        requires_sql = raw.get("requires_sql")
        if requires_sql is None:
            requires_sql = not (request_kind == "correction" and feedback_candidate and not bool(raw.get("chart_request")))
        return {
            "request_kind": request_kind,
            "confidence": confidence,
            "requires_sql": bool(requires_sql),
            "selected_analysis_state_id": selected_id,
            "selected_reason": str(raw.get("selected_reason") or ""),
            "effective_question": str(raw.get("effective_question") or question).strip() or question,
            "needs_clarification": needs_clarification,
            "clarification_question": clarification_question,
            "chart_request": bool(raw.get("chart_request")),
            "chart_type": chart_type,
            "catalog_feedback_candidate": self._normalize_feedback(feedback_candidate, analytical_context),
            "reason": str(raw.get("reason") or ""),
            "planner": "llm",
        }

    def _selected_state_id(self, value: Any, analytical_context: dict[str, Any]) -> int | None:
        if value is None:
            return None
        try:
            state_id = int(value)
        except (TypeError, ValueError):
            return None
        known = {
            int(state["state_id"])
            for state in analytical_context.get("previous_analysis_states") or []
            if isinstance(state, dict) and state.get("state_id") is not None
        }
        return state_id if state_id in known else None

    def _normalize_feedback(self, value: dict[str, Any] | None, analytical_context: dict[str, Any]) -> dict[str, Any] | None:
        if not value:
            return None
        source = self._default_source(analytical_context)
        requires_user_confirmation = self._bool(value.get("requires_user_confirmation"), True)
        auto_apply = self._bool(value.get("auto_apply"), False) and not requires_user_confirmation
        return {
            "suggested": True,
            "type": str(value.get("type") or "correction"),
            "label": str(value.get("label") or "Corrección sugerida"),
            "content": str(value.get("content") or "").strip()[:1200],
            "target": str(value.get("target") or "").strip()[:200],
            "source_file_id": value.get("source_file_id") or source.get("file_id"),
            "source_filename": value.get("source_filename") or source.get("filename"),
            "confidence": str(value.get("confidence") or "medium"),
            "requires_user_confirmation": requires_user_confirmation,
            "auto_apply": auto_apply,
            "reason": str(value.get("reason") or "El LLM detectó una corrección o definición de negocio."),
        }

    def _bool(self, value: Any, default: bool) -> bool:
        if isinstance(value, bool):
            return value
        if value is None:
            return default
        text = str(value).strip().lower()
        if text in {"true", "1", "yes", "si", "sí"}:
            return True
        if text in {"false", "0", "no"}:
            return False
        return default

    def _default_source(self, analytical_context: dict[str, Any]) -> dict[str, Any]:
        files = (analytical_context.get("dataset_context") or {}).get("files") or []
        return files[0] if files and isinstance(files[0], dict) else {}

    def _compact_available_data(self, available_data: dict[str, Any]) -> dict[str, Any]:
        return {
            "files": available_data.get("files") or [],
            "business_feedback": available_data.get("business_feedback") or [],
            "duckdb_schema": [
                {
                    "table": table.get("table"),
                    "row_count": table.get("row_count"),
                    "source_filename": table.get("source_filename"),
                    "columns": [
                        column.get("name")
                        for column in (table.get("columns") or [])[:18]
                        if isinstance(column, dict)
                    ],
                }
                for table in (available_data.get("duckdb_schema") or [])[:8]
                if isinstance(table, dict)
            ],
        }


def find_selected_analysis_state(analytical_context: dict[str, Any], state_id: int | None) -> dict[str, Any] | None:
    if state_id is None:
        return None
    for state in analytical_context.get("previous_analysis_states") or []:
        if not isinstance(state, dict):
            continue
        try:
            if int(state.get("state_id")) == state_id:
                return state
        except (TypeError, ValueError):
            continue
    return None
