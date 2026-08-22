from __future__ import annotations

import json
import re
from typing import Any


CORRECTION_TERMS = (
    "corrige",
    "correccion",
    "corrección",
    "en vez de",
    "me referia",
    "me refería",
    "quise decir",
    "no es",
    "no era",
    "no uses",
    "usa ",
    "usando ",
)

FOLLOW_UP_TERMS = (
    "ahora",
    "tambien",
    "también",
    "lo mismo",
    "de esos",
    "filtra",
    "ordena",
    "agrega",
    "muéstrame",
    "comparado con",
    "respecto a",
)


class AnalyticalContextBuilder:
    def build(self, question: str, messages: list[dict[str, Any]] | None) -> dict[str, Any]:
        history = [message for message in (messages or []) if isinstance(message, dict)]
        previous_messages = self._previous_messages(history)
        last_answer = self._last_assistant_text(previous_messages)
        last_sql = self._last_tool_output(history, "analitrics_sql")
        return {
            "request_kind": self._request_kind(question, bool(last_answer or last_sql)),
            "correction_signals": self._matched_terms(question, CORRECTION_TERMS),
            "follow_up_signals": self._matched_terms(question, FOLLOW_UP_TERMS),
            "last_sql": last_sql,
            "last_answer": last_answer,
            "recent_messages": previous_messages[-6:],
        }

    def _request_kind(self, question: str, has_previous_analysis: bool) -> str:
        normalized = self._normalize(question)
        if has_previous_analysis and any(term in normalized for term in CORRECTION_TERMS):
            return "correction"
        if has_previous_analysis and any(term in normalized for term in FOLLOW_UP_TERMS):
            return "follow_up"
        return "new_question"

    def _matched_terms(self, question: str, terms: tuple[str, ...]) -> list[str]:
        normalized = self._normalize(question)
        return [term for term in terms if term in normalized]

    def _previous_messages(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for message in messages:
            text = str(message.get("text") or "").strip()
            if not text:
                continue
            rows.append(
                {
                    "role": "user" if message.get("isCreatedByUser") else "assistant",
                    "text": text[:1200],
                    "messageId": message.get("messageId"),
                    "createdAt": message.get("createdAt"),
                }
            )
        return rows

    def _last_assistant_text(self, messages: list[dict[str, Any]]) -> str | None:
        for message in reversed(messages):
            if message.get("role") == "assistant" and message.get("text"):
                return str(message["text"])[:1600]
        return None

    def _last_tool_output(self, messages: list[dict[str, Any]], tool_name: str) -> str | None:
        for message in reversed(messages):
            output = self._find_tool_output(message.get("content"), tool_name)
            if output:
                return output[:4000]
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

    def _normalize(self, value: str) -> str:
        text = value.lower()
        text = re.sub(r"\s+", " ", text)
        return text.strip()
