from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any


MAX_RECENT_MESSAGES = 8
MAX_MESSAGE_TEXT = 700
MAX_RECENT_STATES = 8
MAX_SQL_TOOL_STATES = 5
MAX_CONTEXT_TABLES = 8
MAX_CONTEXT_COLUMNS = 18


@dataclass(frozen=True)
class ConversationMessage:
    role: str
    text: str
    message_id: str | None
    created_at: str | None
    content: Any


class ConversationMessageNormalizer:
    def normalize(self, messages: list[dict[str, Any]] | None) -> list[ConversationMessage]:
        rows: list[ConversationMessage] = []
        for message in messages or []:
            if not isinstance(message, dict):
                continue
            text = str(message.get("text") or message.get("content") or "").strip()
            role = str(message.get("role") or "").strip().lower()
            if role not in {"user", "assistant", "system", "tool"}:
                role = "user" if message.get("isCreatedByUser") else "assistant"
            rows.append(
                ConversationMessage(
                    role=role,
                    text=text,
                    message_id=message.get("messageId") or message.get("message_id"),
                    created_at=message.get("createdAt") or message.get("created_at"),
                    content=message.get("content"),
                )
            )
        return rows


class RecentMessageCompactor:
    def compact(self, messages: list[ConversationMessage], max_messages: int = MAX_RECENT_MESSAGES) -> list[dict[str, Any]]:
        compacted: list[dict[str, Any]] = []
        for index, message in enumerate(messages, start=1):
            if not message.text:
                continue
            compacted.append(
                {
                    "turn_index": index,
                    "role": message.role,
                    "text": message.text[:MAX_MESSAGE_TEXT],
                    "messageId": message.message_id,
                    "createdAt": message.created_at,
                }
            )
        return compacted[-max_messages:]

    def last_assistant_text(self, messages: list[ConversationMessage]) -> str | None:
        for message in reversed(messages):
            if message.role == "assistant" and message.text:
                return message.text[:2000]
        return None


class ToolOutputExtractor:
    def last_output(self, messages: list[ConversationMessage], tool_name: str) -> str | None:
        for message in reversed(messages):
            output = self._find_tool_output(message.content, tool_name)
            if output:
                return output[:5000]
        return None

    def _find_tool_output(self, value: Any, tool_name: str) -> str | None:
        if isinstance(value, str):
            try:
                return self._find_tool_output(json.loads(value), tool_name)
            except Exception:
                return None
        if isinstance(value, list):
            for item in reversed(value):
                output = self._find_tool_output(item, tool_name)
                if output:
                    return output
            return None
        if not isinstance(value, dict):
            return None
        tool_call = value.get("tool_call")
        if isinstance(tool_call, dict) and tool_call.get("name") == tool_name:
            output = tool_call.get("output")
            return str(output) if output else None
        for child in value.values():
            output = self._find_tool_output(child, tool_name)
            if output:
                return output
        return None


class SqlArtifactParser:
    def parse(self, output: str | None) -> dict[str, Any] | None:
        if not output:
            return None
        sql = self._section(output, "SQL ejecutado:", "Vista previa de resultado:")
        row_count = self._line_value(output, "Filas devueltas:")
        rationale = self._section(output, "Rationale:", "SQL ejecutado:")
        return {
            "sql": sql.strip() if sql else None,
            "row_count": int(row_count) if row_count and row_count.isdigit() else None,
            "rationale": rationale.strip()[:1200] if rationale else None,
            "raw": output[:2200],
        }

    def _line_value(self, text: str, label: str) -> str | None:
        for line in text.splitlines():
            if line.startswith(label):
                return line.replace(label, "", 1).strip()
        return None

    def _section(self, text: str, start: str, end: str) -> str | None:
        start_index = text.find(start)
        if start_index < 0:
            return None
        start_index += len(start)
        end_index = text.find(end, start_index)
        if end_index < 0:
            end_index = len(text)
        return text[start_index:end_index].strip()


class JsonToolOutputParser:
    def parse(self, output: str | None) -> dict[str, Any] | None:
        if not output:
            return None
        try:
            value = json.loads(output)
        except Exception:
            return None
        return value if isinstance(value, dict) else None


class DatasetContextSelector:
    def select(self, files: list[Any], profiles: list[dict[str, Any]]) -> dict[str, Any]:
        data_profiles = [profile for profile in profiles if not profile.get("system_table")]
        active_files = self._active_files(files, data_profiles)
        active_tables = [
            {
                "table": profile.get("table"),
                "source_file_id": profile.get("source_file_id"),
                "source_filename": profile.get("source_filename"),
                "row_count": profile.get("row_count"),
                "columns": [
                    {
                        "name": column.get("name"),
                        "type": column.get("type"),
                        "sample_values": (column.get("sample_values") or column.get("examples") or [])[:5],
                    }
                    for column in (profile.get("columns") or [])[:MAX_CONTEXT_COLUMNS]
                    if isinstance(column, dict)
                ],
            }
            for profile in data_profiles[:MAX_CONTEXT_TABLES]
        ]
        return {
            "files": active_files,
            "tables": active_tables,
            "file_count": len(active_files),
            "table_count": len(active_tables),
            "row_count_total": sum(int(profile.get("row_count") or 0) for profile in data_profiles),
        }

    def _active_files(self, files: list[Any], profiles: list[dict[str, Any]]) -> list[dict[str, Any]]:
        profile_file_ids = {str(profile.get("source_file_id")) for profile in profiles if profile.get("source_file_id")}
        rows: list[dict[str, Any]] = []
        for file in files:
            file_id = str(getattr(file, "file_id", "") or "")
            if profile_file_ids and file_id not in profile_file_ids:
                continue
            rows.append(
                {
                    "file_id": file_id,
                    "filename": getattr(file, "filename", None),
                    "mime_type": getattr(file, "mime_type", None),
                    "bytes": getattr(file, "bytes", None),
                    "content_hash": getattr(file, "content_hash", None),
                }
            )
        return rows


class AnalysisStateCompactor:
    def compact(self, states: list[dict[str, Any]] | None, limit: int = MAX_RECENT_STATES) -> list[dict[str, Any]]:
        compacted: list[dict[str, Any]] = []
        for index, state in enumerate(states or [], start=1):
            if not isinstance(state, dict):
                continue
            compacted.append(
                {
                    "sequence": index,
                    "state_id": state.get("state_id"),
                    "message_id": state.get("message_id"),
                    "run_id": state.get("run_id"),
                    "question": self._trim(state.get("question"), 300),
                    "answer_summary": self._trim(state.get("answer_summary"), 280),
                    "intent": state.get("intent"),
                    "metric": state.get("metric"),
                    "dimensions": (state.get("dimensions") or [])[:6],
                    "filters": (state.get("filters") or [])[:6],
                    "dataset": self._compact_dataset(state.get("dataset") or {}),
                    "last_sql": self._trim(state.get("last_sql"), 420),
                    "last_chart": self._compact_chart(state.get("last_chart")),
                    "row_count": state.get("row_count"),
                    "created_at": state.get("created_at"),
                    "state": self._compact_state_blob(state.get("state") or {}),
                }
            )
        return compacted[-limit:]

    def _compact_dataset(self, dataset: dict[str, Any]) -> dict[str, Any]:
        tables = dataset.get("tables") or []
        files = dataset.get("files") or []
        return {
            "primary_file": dataset.get("primary_file"),
            "primary_table": dataset.get("primary_table"),
            "files": [
                {
                    "filename": file.get("filename"),
                    "file_id": file.get("file_id"),
                }
                for file in files[:5]
                if isinstance(file, dict)
            ]
            if isinstance(files, list)
            else [],
            "tables": [
                {
                    "table": table.get("table"),
                    "source_filename": table.get("source_filename"),
                    "row_count": table.get("row_count"),
                }
                for table in tables[:MAX_CONTEXT_TABLES]
                if isinstance(table, dict)
            ]
            if isinstance(tables, list)
            else [],
        }

    def _compact_state_blob(self, state: dict[str, Any]) -> dict[str, Any]:
        return {
            "semantic_summary": self._trim(state.get("semantic_summary"), 300),
            "depends_on_state_id": state.get("depends_on_state_id"),
            "confidence": state.get("confidence"),
            "assumptions": (state.get("assumptions") or [])[:3] if isinstance(state.get("assumptions"), list) else [],
            "feedback_proposal": self._compact_feedback_proposal(state.get("feedback_proposal")),
        }

    def _compact_chart(self, chart: Any) -> dict[str, Any] | None:
        if not isinstance(chart, dict):
            return None
        spec = chart.get("spec") if isinstance(chart.get("spec"), dict) else {}
        return {
            "chart_required": chart.get("chart_required"),
            "chart_type": chart.get("chart_type"),
            "renderer": chart.get("renderer"),
            "x_key": spec.get("x_key"),
            "y_keys": spec.get("y_keys"),
            "title": self._trim(spec.get("title"), 160),
        }

    def _compact_feedback_proposal(self, proposal: Any) -> dict[str, Any] | None:
        if not isinstance(proposal, dict):
            return None
        return {
            "type": proposal.get("type"),
            "label": proposal.get("label"),
            "target": proposal.get("target"),
            "content": self._trim(proposal.get("content"), 500),
            "source_filename": proposal.get("source_filename"),
            "confidence": proposal.get("confidence"),
        }

    def _compact_semantic_cache(self, value: Any) -> dict[str, Any] | None:
        if not isinstance(value, dict):
            return None
        cache = {
            "data_strategy": self._compact_data_strategy(value.get("data_strategy")),
            "compatible_groups": self._compact_compatible_groups(value.get("compatible_groups")),
            "described_tables": self._compact_described_tables(value.get("described_tables")),
            "catalog_terms": self._compact_catalog_terms(value.get("catalog_terms")),
        }
        return {key: item for key, item in cache.items() if item not in (None, [], {})} or None

    def _compact_data_strategy(self, value: Any) -> dict[str, Any] | None:
        if not isinstance(value, dict):
            return None
        return {
            "mode": value.get("mode"),
            "tables_used": [str(table) for table in (value.get("tables_used") or [])[:8] if table],
            "reason": self._trim(value.get("reason"), 180),
        }

    def _compact_compatible_groups(self, value: Any) -> list[dict[str, Any]]:
        if not isinstance(value, list):
            return []
        return [
            {
                "shared_columns": (group.get("shared_columns") or [])[:12],
                "tables": [
                    {
                        "table": table.get("table"),
                        "source_filename": table.get("source_filename"),
                        "row_count": table.get("row_count"),
                    }
                    for table in (group.get("tables") or [])[:8]
                    if isinstance(table, dict)
                ],
            }
            for group in value[:4]
            if isinstance(group, dict)
        ]

    def _compact_described_tables(self, value: Any) -> list[dict[str, Any]]:
        if not isinstance(value, list):
            return []
        return [
            {
                "table": item.get("table"),
                "source_filename": item.get("source_filename"),
                "row_count": item.get("row_count"),
                "columns": [
                    {"name": column.get("name"), "type": column.get("type")}
                    for column in (item.get("columns") or [])[:18]
                    if isinstance(column, dict)
                ],
            }
            for item in value[:6]
            if isinstance(item, dict)
        ]

    def _compact_catalog_terms(self, value: Any) -> list[dict[str, Any]]:
        if not isinstance(value, list):
            return []
        return [
            {
                "term": item.get("term"),
                "resolved": item.get("resolved"),
                "definitions": (item.get("definitions") or [])[:3],
            }
            for item in value[:8]
            if isinstance(item, dict)
        ]

    def _trim(self, value: Any, limit: int) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text if len(text) <= limit else text[:limit].rstrip() + "..."


class AnalyticalContextBuilder:
    def __init__(
        self,
        message_normalizer: ConversationMessageNormalizer | None = None,
        message_compactor: RecentMessageCompactor | None = None,
        tool_extractor: ToolOutputExtractor | None = None,
        sql_parser: SqlArtifactParser | None = None,
        json_parser: JsonToolOutputParser | None = None,
        dataset_selector: DatasetContextSelector | None = None,
        state_compactor: AnalysisStateCompactor | None = None,
    ) -> None:
        self._message_normalizer = message_normalizer or ConversationMessageNormalizer()
        self._message_compactor = message_compactor or RecentMessageCompactor()
        self._tool_extractor = tool_extractor or ToolOutputExtractor()
        self._sql_parser = sql_parser or SqlArtifactParser()
        self._json_parser = json_parser or JsonToolOutputParser()
        self._dataset_selector = dataset_selector or DatasetContextSelector()
        self._state_compactor = state_compactor or AnalysisStateCompactor()

    def build(
        self,
        question: str,
        messages: list[dict[str, Any]] | None,
        files: list[Any] | None = None,
        profiles: list[dict[str, Any]] | None = None,
        analysis_states: list[dict[str, Any]] | None = None,
        pending_clarification: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        history = self._message_normalizer.normalize(messages)
        last_sql = self._sql_parser.parse(self._tool_extractor.last_output(history, "analitrics_sql"))
        last_chart = self._json_parser.parse(self._tool_extractor.last_output(history, "analitrics_chart"))
        last_context_output = self._tool_extractor.last_output(history, "analitrics_context")
        recent_states = self._state_compactor.compact(analysis_states)
        return {
            "current_question": question,
            "effective_question": question,
            "conversation_plan": None,
            "pending_clarification": pending_clarification,
            "previous_analysis_states": recent_states,
            "recent_analysis_states": recent_states,
            "selected_analysis_state": None,
            "last_sql": last_sql or self._last_state_sql(recent_states),
            "last_answer": self._last_state_answer(recent_states) or self._message_compactor.last_assistant_text(history),
            "last_chart": self._last_state_chart(recent_states) or last_chart,
            "last_context": last_context_output[:2200] if last_context_output else None,
            "dataset_context": self._dataset_selector.select(files or [], profiles or []),
            "semantic_cache": self._latest_semantic_cache(analysis_states),
            "recent_messages": self._message_compactor.compact(history),
            "feedback_proposal": None,
            "context_policy": {
                "mode": "llm_first_compact_context",
                "decision_owner": "llm",
                "deterministic_state_selection": False,
                "full_chat_forwarded_to_llm": False,
                "max_recent_messages": MAX_RECENT_MESSAGES,
                "max_recent_analysis_states": MAX_RECENT_STATES,
                "max_context_tables": MAX_CONTEXT_TABLES,
                "max_context_columns_per_table": MAX_CONTEXT_COLUMNS,
            },
        }

    def _last_state_sql(self, states: list[dict[str, Any]]) -> dict[str, Any] | None:
        for state in reversed(states):
            if state.get("last_sql"):
                return {"sql": state.get("last_sql"), "row_count": state.get("row_count")}
        return None

    def _last_state_answer(self, states: list[dict[str, Any]]) -> str | None:
        for state in reversed(states):
            if state.get("answer_summary"):
                return state.get("answer_summary")
        return None

    def _last_state_chart(self, states: list[dict[str, Any]]) -> dict[str, Any] | None:
        for state in reversed(states):
            if isinstance(state.get("last_chart"), dict):
                return state.get("last_chart")
        return None

    def _latest_semantic_cache(self, states: list[dict[str, Any]] | None) -> dict[str, Any] | None:
        for state in reversed(states or []):
            if not isinstance(state, dict):
                continue
            cache = (state.get("state") or {}).get("semantic_cache")
            if isinstance(cache, dict) and cache:
                return self._state_compactor._compact_semantic_cache(cache)
        return None


class AnalyticalContextPromptCompactor:
    def for_planner(self, analytical_context: dict[str, Any]) -> dict[str, Any]:
        return {
            **self._conversation_context(analytical_context),
            "dataset_summary": self._dataset_summary(analytical_context),
        }

    def for_sql(self, analytical_context: dict[str, Any]) -> dict[str, Any]:
        return {
            **self._conversation_context(analytical_context),
            "conversation_plan": analytical_context.get("conversation_plan"),
            "request_kind": analytical_context.get("request_kind"),
            "chart_intent": analytical_context.get("chart_intent"),
            "selected_analysis_state": self._compact_selected_state(analytical_context.get("selected_analysis_state")),
            "feedback_proposal": self._compact_feedback_proposal(analytical_context.get("feedback_proposal")),
            "applied_feedback": self._compact_feedback_proposal(analytical_context.get("applied_feedback")),
            "dataset_summary": self._dataset_summary(analytical_context),
        }

    def for_chart(self, analytical_context: dict[str, Any]) -> dict[str, Any]:
        return {
            "conversation_plan": analytical_context.get("conversation_plan"),
            "chart_intent": analytical_context.get("chart_intent"),
            "selected_analysis_state": self._compact_selected_state(analytical_context.get("selected_analysis_state")),
        }

    def for_sql_tools(self, analytical_context: dict[str, Any]) -> dict[str, Any]:
        return {
            "current_question": analytical_context.get("current_question"),
            "effective_question": analytical_context.get("effective_question"),
            "pending_clarification": self._compact_pending_clarification(analytical_context.get("pending_clarification")),
            "previous_analysis_states": (analytical_context.get("previous_analysis_states") or [])[-MAX_SQL_TOOL_STATES:],
            "recent_messages": analytical_context.get("recent_messages") or [],
            "conversation_plan": analytical_context.get("conversation_plan"),
            "selected_analysis_state": self._compact_selected_state(analytical_context.get("selected_analysis_state")),
            "last_sql": self._compact_sql_artifact(analytical_context.get("last_sql")),
            "last_answer": self._trim(analytical_context.get("last_answer"), 280),
            "last_chart": self._compact_chart(analytical_context.get("last_chart")),
            "feedback_proposal": self._compact_feedback_proposal(analytical_context.get("feedback_proposal")),
            "applied_feedback": self._compact_feedback_proposal(analytical_context.get("applied_feedback")),
            "semantic_cache": self._semantic_cache(analytical_context),
        }

    def _conversation_context(self, analytical_context: dict[str, Any]) -> dict[str, Any]:
        return {
            "current_question": analytical_context.get("current_question"),
            "effective_question": analytical_context.get("effective_question"),
            "pending_clarification": self._compact_pending_clarification(analytical_context.get("pending_clarification")),
            "previous_analysis_states": analytical_context.get("previous_analysis_states") or [],
            "selected_analysis_state": self._compact_selected_state(analytical_context.get("selected_analysis_state")),
            "last_sql": self._compact_sql_artifact(analytical_context.get("last_sql")),
            "last_answer": self._trim(analytical_context.get("last_answer"), 280),
            "last_chart": self._compact_chart(analytical_context.get("last_chart")),
            "last_context": self._trim(analytical_context.get("last_context"), 500),
            "recent_messages": analytical_context.get("recent_messages") or [],
            "context_policy": analytical_context.get("context_policy"),
        }

    def _compact_pending_clarification(self, value: Any) -> dict[str, Any] | None:
        if not isinstance(value, dict) or not value.get("pending"):
            return None
        candidates = value.get("candidate_states") or []
        return {
            "pending": True,
            "original_question": self._trim(value.get("original_question"), 300),
            "clarification_question": self._trim(value.get("clarification_question"), 300),
            "reason": self._trim(value.get("reason"), 220),
            "candidate_state_ids": [
                state.get("state_id")
                for state in candidates[:5]
                if isinstance(state, dict) and state.get("state_id") is not None
            ],
        }

    def _compact_sql_artifact(self, value: Any) -> dict[str, Any] | None:
        if not isinstance(value, dict):
            return None
        return {
            "sql": self._trim(value.get("sql"), 420),
            "row_count": value.get("row_count"),
            "rationale": self._trim(value.get("rationale"), 220),
        }

    def _dataset_summary(self, analytical_context: dict[str, Any]) -> dict[str, Any]:
        dataset_context = analytical_context.get("dataset_context") or {}
        files = dataset_context.get("files") or []
        tables = dataset_context.get("tables") or []
        return {
            "file_count": dataset_context.get("file_count"),
            "table_count": dataset_context.get("table_count"),
            "row_count_total": dataset_context.get("row_count_total"),
            "files": [
                {
                    "file_id": file.get("file_id"),
                    "filename": file.get("filename"),
                    "bytes": file.get("bytes"),
                    "content_hash": file.get("content_hash"),
                }
                for file in files[:5]
                if isinstance(file, dict)
            ],
            "tables": [
                {
                    "table": table.get("table"),
                    "source_file_id": table.get("source_file_id"),
                    "source_filename": table.get("source_filename"),
                    "row_count": table.get("row_count"),
                    "column_count": len(table.get("columns") or []),
                }
                for table in tables[:MAX_CONTEXT_TABLES]
                if isinstance(table, dict)
            ],
        }

    def _compact_selected_state(self, state: Any) -> dict[str, Any] | None:
        if not isinstance(state, dict):
            return None
        return {
            "state_id": state.get("state_id"),
            "question": self._trim(state.get("question"), 300),
            "answer_summary": self._trim(state.get("answer_summary"), 280),
            "intent": state.get("intent"),
            "metric": state.get("metric"),
            "dimensions": (state.get("dimensions") or [])[:6] if isinstance(state.get("dimensions"), list) else [],
            "filters": (state.get("filters") or [])[:6] if isinstance(state.get("filters"), list) else [],
            "dataset": self._compact_dataset(state.get("dataset") or {}),
            "row_count": state.get("row_count"),
            "state": self._compact_state_blob(state.get("state") or {}),
        }

    def _compact_dataset(self, dataset: dict[str, Any]) -> dict[str, Any]:
        tables = dataset.get("tables") or []
        files = dataset.get("files") or []
        return {
            "primary_file": dataset.get("primary_file"),
            "primary_table": dataset.get("primary_table"),
            "files": [
                {"filename": file.get("filename"), "file_id": file.get("file_id")}
                for file in files[:5]
                if isinstance(file, dict)
            ]
            if isinstance(files, list)
            else [],
            "tables": [
                {
                    "table": table.get("table"),
                    "source_filename": table.get("source_filename"),
                    "row_count": table.get("row_count"),
                }
                for table in tables[:MAX_CONTEXT_TABLES]
                if isinstance(table, dict)
            ]
            if isinstance(tables, list)
            else [],
        }

    def _compact_state_blob(self, state: dict[str, Any]) -> dict[str, Any]:
        return {
            "semantic_summary": self._trim(state.get("semantic_summary"), 300),
            "depends_on_state_id": state.get("depends_on_state_id"),
            "confidence": state.get("confidence"),
            "assumptions": (state.get("assumptions") or [])[:3] if isinstance(state.get("assumptions"), list) else [],
            "feedback_proposal": self._compact_feedback_proposal(state.get("feedback_proposal")),
        }

    def _semantic_cache(self, analytical_context: dict[str, Any]) -> dict[str, Any] | None:
        current_cache = self._compact_semantic_cache(analytical_context.get("semantic_cache"))
        if current_cache:
            return current_cache
        selected = analytical_context.get("selected_analysis_state")
        if isinstance(selected, dict):
            selected_cache = ((selected.get("state") or {}).get("semantic_cache"))
            compacted = self._compact_semantic_cache(selected_cache)
            if compacted:
                return compacted
        states = analytical_context.get("previous_analysis_states") or []
        for state in reversed(states):
            if not isinstance(state, dict):
                continue
            compacted = self._compact_semantic_cache((state.get("state") or {}).get("semantic_cache"))
            if compacted:
                return compacted
        return None

    def _compact_semantic_cache(self, value: Any) -> dict[str, Any] | None:
        if not isinstance(value, dict):
            return None
        cache = {
            "data_strategy": self._compact_data_strategy(value.get("data_strategy")),
            "compatible_groups": self._compact_compatible_groups(value.get("compatible_groups")),
            "described_tables": self._compact_described_tables(value.get("described_tables")),
            "catalog_terms": self._compact_catalog_terms(value.get("catalog_terms")),
        }
        return {key: item for key, item in cache.items() if item not in (None, [], {})} or None

    def _compact_data_strategy(self, value: Any) -> dict[str, Any] | None:
        if not isinstance(value, dict):
            return None
        return {
            "mode": value.get("mode"),
            "tables_used": [str(table) for table in (value.get("tables_used") or [])[:8] if table],
            "reason": self._trim(value.get("reason"), 180),
        }

    def _compact_compatible_groups(self, value: Any) -> list[dict[str, Any]]:
        if not isinstance(value, list):
            return []
        groups: list[dict[str, Any]] = []
        for group in value[:4]:
            if not isinstance(group, dict):
                continue
            groups.append(
                {
                    "shared_columns": (group.get("shared_columns") or [])[:12],
                    "tables": [
                        {
                            "table": table.get("table"),
                            "source_filename": table.get("source_filename"),
                            "row_count": table.get("row_count"),
                        }
                        for table in (group.get("tables") or [])[:8]
                        if isinstance(table, dict)
                    ],
                }
            )
        return groups

    def _compact_described_tables(self, value: Any) -> list[dict[str, Any]]:
        if not isinstance(value, list):
            return []
        return [
            {
                "table": item.get("table"),
                "source_filename": item.get("source_filename"),
                "row_count": item.get("row_count"),
                "columns": [
                    {
                        "name": column.get("name"),
                        "type": column.get("type"),
                    }
                    for column in (item.get("columns") or [])[:18]
                    if isinstance(column, dict)
                ],
            }
            for item in value[:6]
            if isinstance(item, dict)
        ]

    def _compact_catalog_terms(self, value: Any) -> list[dict[str, Any]]:
        if not isinstance(value, list):
            return []
        return [
            {
                "term": item.get("term"),
                "resolved": item.get("resolved"),
                "definitions": (item.get("definitions") or [])[:3],
            }
            for item in value[:8]
            if isinstance(item, dict)
        ]

    def _compact_chart(self, chart: Any) -> dict[str, Any] | None:
        if not isinstance(chart, dict):
            return None
        spec = chart.get("spec") if isinstance(chart.get("spec"), dict) else {}
        return {
            "chart_required": chart.get("chart_required"),
            "chart_type": chart.get("chart_type"),
            "renderer": chart.get("renderer"),
            "x_key": spec.get("x_key"),
            "y_keys": spec.get("y_keys"),
            "title": self._trim(spec.get("title"), 160),
        }

    def _compact_feedback_proposal(self, proposal: Any) -> dict[str, Any] | None:
        if not isinstance(proposal, dict):
            return None
        return {
            "type": proposal.get("type"),
            "label": proposal.get("label"),
            "target": proposal.get("target"),
            "content": self._trim(proposal.get("content"), 500),
            "source_filename": proposal.get("source_filename"),
            "confidence": proposal.get("confidence"),
        }

    def _trim(self, value: Any, limit: int) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text if len(text) <= limit else text[:limit].rstrip() + "..."
