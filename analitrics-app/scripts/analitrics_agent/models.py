from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, TypedDict

from nl_sql_file import FileMetadata


@dataclass(frozen=True)
class AgentRequest:
    question: str
    tenant_id: str = "analitrics"
    user_id: str | None = None
    conversation_id: str | None = None
    message_id: str | None = None
    file_id: list[str] | None = None
    filename: list[str] | None = None
    file_ids: str | None = None
    filenames: str | None = None
    cache_dir: str = "/var/analitrics/analytics/cache"
    sample_rows: int = 5
    run_id: str | None = None
    context_messages: list[dict[str, Any]] | None = None


class AgentState(TypedDict, total=False):
    run_id: str
    trace_id: str
    question: str
    metadata: FileMetadata
    files: list[FileMetadata]
    local_path: str
    local_paths: list[str]
    tables: list[str]
    profiles: list[dict[str, Any]]
    catalog_feedback: list[dict[str, Any]]
    analytical_context: dict[str, Any]
    analysis_state: dict[str, Any]
    in_scope: bool
    scope_reason: str
    plan: dict[str, str]
    sql: str
    sql_validation_attempt: int
    sql_repaired: bool
    rows: list[dict[str, Any]]
    answer: str
    critic: dict[str, Any]
    chart_spec: dict[str, Any]
    cache_path: str
    cache_hits: int
    engine: str
    error: str


def state_output(request: AgentRequest, state: AgentState) -> dict[str, Any]:
    metadata = state.get("metadata")
    files = state.get("files") or []
    return {
        "agent": state.get("engine") or "langgraph-file-analyst",
        "runId": state.get("run_id") or request.run_id,
        "traceId": state.get("trace_id"),
        "tenantId": request.tenant_id,
        "userId": request.user_id,
        "conversationId": request.conversation_id,
        "messageId": request.message_id,
        "cachePath": state.get("cache_path"),
        "cacheHits": state.get("cache_hits"),
        "in_scope": state.get("in_scope"),
        "scope_reason": state.get("scope_reason"),
        "file": asdict(metadata) if metadata else None,
        "files": [asdict(file) for file in files],
        "tables": state.get("profiles"),
        "catalog_feedback": state.get("catalog_feedback") or [],
        "analytical_context": state.get("analytical_context") or {},
        "analysis_state": state.get("analysis_state") or {},
        "feedback_proposal": (state.get("analytical_context") or {}).get("feedback_proposal"),
        "plan": state.get("plan"),
        "sql": state.get("sql"),
        "row_count": len(state.get("rows") or []),
        "rows_preview": (state.get("rows") or [])[:20],
        "answer": state.get("answer"),
        "critic": state.get("critic"),
        "chart_spec": state.get("chart_spec"),
    }
