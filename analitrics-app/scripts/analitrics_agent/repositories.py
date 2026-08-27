from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from nl_sql_file import FileMetadata, connect_mongo

from .config import bool_env, env
from .json_utils import profiles_for_storage
from .models import AgentRequest, AgentState
from .naming import file_signature
from .tracing import normalize_search_text, stable_text_hash


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class MongoDatabaseFactory:
    def __init__(self) -> None:
        self._mongo = None
        self._database = None

    def get_database(self):
        if self._database is None:
            self._mongo = connect_mongo()
            self._database = self._mongo[env("MONGO_DB", "LibreChat")]
        return self._database


class AnalysisConversationRepository:
    def __init__(self, database_factory: MongoDatabaseFactory) -> None:
        self._database_factory = database_factory

    def find_conversation(self, request: AgentRequest) -> dict[str, Any] | None:
        if not request.conversation_id:
            return None
        return self._database_factory.get_database().analitrics_analysis_sessions.find_one(
            {"tenantId": request.tenant_id, "conversationId": request.conversation_id}
        )

    def save_conversation(
        self,
        request: AgentRequest,
        files: list[FileMetadata],
        profiles: list[dict[str, Any]],
        table_map: dict[str, list[str]],
        cache_path: Path | None,
        cache_hits: int,
    ) -> None:
        if not request.conversation_id:
            return

        now = utc_now()
        db = self._database_factory.get_database()
        db.analitrics_analysis_sessions.update_one(
            {"tenantId": request.tenant_id, "conversationId": request.conversation_id},
            {
                "$set": {
                    "tenantId": request.tenant_id,
                    "userId": request.user_id,
                    "conversationId": request.conversation_id,
                    "cachePath": str(cache_path) if cache_path else None,
                    "files": [asdict(metadata) for metadata in files],
                    "profiles": profiles_for_storage(profiles, bool_env("ANALITRICS_PERSIST_PREVIEWS", False)),
                    "tableMap": table_map,
                    "lastCacheHits": cache_hits,
                    "updatedAt": now,
                },
                "$setOnInsert": {"createdAt": now},
            },
            upsert=True,
        )
        for metadata in files:
            processed_file = {
                "file_id": metadata.file_id,
                "filename": metadata.filename,
                "storageKey": metadata.storage_key,
                "mimeType": metadata.mime_type,
                "bytes": metadata.bytes,
                "contentHash": metadata.content_hash,
                "signature": file_signature(metadata),
                "tables": table_map.get(metadata.file_id, []),
                "processedAt": now,
            }
            db.analitrics_analysis_sessions.update_one(
                {"tenantId": request.tenant_id, "conversationId": request.conversation_id},
                {"$pull": {"processedFiles": {"file_id": processed_file["file_id"]}}},
            )
            db.analitrics_analysis_sessions.update_one(
                {"tenantId": request.tenant_id, "conversationId": request.conversation_id},
                {"$push": {"processedFiles": processed_file}},
            )


class AgentRunRepository:
    def __init__(self, database_factory: MongoDatabaseFactory) -> None:
        self._database_factory = database_factory

    def save_run(
        self,
        request: AgentRequest,
        result: AgentState | None,
        error: str | None = None,
        trace_id: str | None = None,
    ) -> None:
        doc: dict[str, Any] = {
            "runId": request.run_id,
            "traceId": trace_id or (result or {}).get("trace_id"),
            "tenantId": request.tenant_id,
            "userId": request.user_id,
            "conversationId": request.conversation_id,
            "messageId": request.message_id,
            "question": request.question,
            "questionNormalized": normalize_search_text(request.question),
            "questionHash": stable_text_hash(request.question),
            "status": "error" if error else "ok",
            "error": error,
            "createdAt": utc_now(),
        }
        if result:
            files = result.get("files") or []
            doc.update(
                {
                    "inScope": result.get("in_scope"),
                    "scopeReason": result.get("scope_reason"),
                    "engine": result.get("engine") or "langgraph",
                    "fileIds": [metadata.file_id for metadata in files],
                    "filenames": [metadata.filename for metadata in files],
                    "tables": profiles_for_storage(
                        result.get("profiles") or [],
                        bool_env("ANALITRICS_PERSIST_PREVIEWS", False),
                    ),
                    "sql": result.get("sql"),
                    "rowCount": len(result.get("rows") or []),
                    "answer": result.get("answer"),
                    "critic": result.get("critic"),
                    "chartSpec": result.get("chart_spec"),
                    "cachePath": result.get("cache_path"),
                    "cacheHits": result.get("cache_hits"),
                }
            )
            if bool_env("ANALITRICS_PERSIST_PREVIEWS", False):
                doc["rowsPreview"] = (result.get("rows") or [])[:20]
        self._database_factory.get_database().analitrics_agent_runs.insert_one(doc)


class ConversationAttachmentRepository:
    def __init__(self, database_factory: MongoDatabaseFactory) -> None:
        self._database_factory = database_factory

    @property
    def database(self):
        return self._database_factory.get_database()

    def find_file_ids(
        self,
        conversation_id: str | None,
        message_id: str | None,
        until_message_id: str | None = None,
    ) -> list[str]:
        if not conversation_id and not message_id:
            return []

        query: dict[str, Any] = {}
        if conversation_id:
            query["conversationId"] = conversation_id
        if message_id:
            query["messageId"] = message_id
        elif until_message_id:
            until_doc = self._database_factory.get_database().messages.find_one(
                {"conversationId": conversation_id, "messageId": until_message_id},
                {"_id": 0, "createdAt": 1},
            )
            if until_doc and until_doc.get("createdAt"):
                query["createdAt"] = {"$lte": until_doc["createdAt"]}

        db = self._database_factory.get_database()
        docs = db.messages.find(query, {"_id": 0, "files": 1, "attachments": 1}).sort("createdAt", -1).limit(20)
        file_ids: list[str] = []
        seen: set[str] = set()
        for doc in docs:
            for value in self._extract_file_ids(doc):
                if value not in seen:
                    file_ids.append(value)
                    seen.add(value)
        return file_ids

    def _extract_file_ids(self, value: Any) -> list[str]:
        if isinstance(value, list):
            file_ids: list[str] = []
            for item in value:
                file_ids.extend(self._extract_file_ids(item))
            return file_ids
        if not isinstance(value, dict):
            return []

        file_ids = []
        for key in ("file_id", "fileId"):
            candidate = value.get(key)
            if isinstance(candidate, str) and candidate:
                file_ids.append(candidate)
        for key in ("files", "attachments"):
            if key in value:
                file_ids.extend(self._extract_file_ids(value[key]))
        return file_ids


class ConversationHistoryRepository:
    def __init__(self, database_factory: MongoDatabaseFactory) -> None:
        self._database_factory = database_factory
        self._max_messages = int(env("ANALITRICS_HISTORY_MAX_MESSAGES", "8"))
        self._max_message_chars = int(env("ANALITRICS_HISTORY_MAX_MESSAGE_CHARS", "700"))
        self._max_total_chars = int(env("ANALITRICS_HISTORY_MAX_TOTAL_CHARS", "3500"))

    def find_history_text(self, conversation_id: str | None, until_message_id: str | None = None) -> str:
        if not conversation_id:
            return ""

        db = self._database_factory.get_database()
        docs = list(
            db.messages.find(
                {"conversationId": conversation_id},
                {
                    "_id": 0,
                    "messageId": 1,
                    "sender": 1,
                    "isCreatedByUser": 1,
                    "text": 1,
                    "content": 1,
                    "files": 1,
                    "attachments": 1,
                    "createdAt": 1,
                },
            ).sort("createdAt", 1)
        )
        if until_message_id:
            filtered = []
            for doc in docs:
                filtered.append(doc)
                if doc.get("messageId") == until_message_id:
                    break
            docs = filtered

        compact_docs = self._compact_docs(docs)
        lines: list[str] = []
        for index, doc in enumerate(compact_docs, start=1):
            role = "usuario" if doc.get("isCreatedByUser") else "asistente"
            sender = doc.get("sender") or role
            text = self._message_text(doc)
            files = self._file_summary(doc)
            body = self._trim_text(text or "(sin texto)", self._max_message_chars)
            if files:
                body = f"{body}\nArchivos: {files}"
            lines.append(f"[{index}] rol={role} | sender={sender}\n{body}")
        return self._trim_text("\n\n".join(lines), self._max_total_chars)

    def _compact_docs(self, docs: list[dict[str, Any]]) -> list[dict[str, Any]]:
        useful: list[dict[str, Any]] = []
        for doc in docs:
            text = self._message_text(doc)
            files = self._file_summary(doc)
            if doc.get("isCreatedByUser"):
                useful.append(doc)
                continue
            if files:
                useful.append(doc)
                continue
            if self._is_useful_assistant_text(text):
                useful.append(doc)
        return useful[-self._max_messages :]

    def _is_useful_assistant_text(self, text: str) -> bool:
        if not text:
            return False
        lowered = text.lower()
        if "an error occurred" in lowered or "something went wrong" in lowered:
            return False
        if "| --- |" in text or len(text) > self._max_message_chars:
            return False
        return True

    def _trim_text(self, text: str, limit: int) -> str:
        if len(text) <= limit:
            return text
        return text[:limit].rstrip() + "\n...(contexto recortado)"

    def _message_text(self, doc: dict[str, Any]) -> str:
        text = doc.get("text")
        if isinstance(text, str) and text.strip():
            return text.strip()
        return self._content_text(doc.get("content")).strip()

    def _content_text(self, value: Any) -> str:
        if isinstance(value, str):
            return value
        if isinstance(value, list):
            return "\n".join(self._content_text(item) for item in value if item is not None)
        if not isinstance(value, dict):
            return ""
        parts: list[str] = []
        for key in ("text", "error", "type"):
            candidate = value.get(key)
            if isinstance(candidate, str) and candidate:
                parts.append(candidate)
        return " ".join(parts)

    def _file_summary(self, doc: dict[str, Any]) -> str:
        values = []
        for key in ("files", "attachments"):
            value = doc.get(key)
            if isinstance(value, list):
                values.extend(value)
        summaries: list[str] = []
        for value in values:
            if not isinstance(value, dict):
                continue
            filename = value.get("filename") or value.get("name") or "(sin nombre)"
            file_id = value.get("file_id") or value.get("fileId") or ""
            mime_type = value.get("type") or value.get("mimeType") or ""
            summaries.append(f"{filename} file_id={file_id} type={mime_type}".strip())
        return "; ".join(summaries)
