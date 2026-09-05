from __future__ import annotations

import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

from analitrics_agent import AgentRequest, AnalyticalAgentFactory
from analitrics_agent.config import bool_env
from analitrics_agent.dashboards import DashboardRepositoryFactory
from analitrics_agent.ingest_validation import IngestValidationFactory
from analitrics_agent.models import state_output
from analitrics_agent.repositories import AgentRunRepository, MongoDatabaseFactory


_database_factory = MongoDatabaseFactory()
_run_repository = AgentRunRepository(_database_factory)


def start_reconciliation_worker() -> None:
    interval_seconds = int(os.getenv("ANALITRICS_RECONCILE_INTERVAL_SECONDS", str(6 * 60 * 60)))
    if interval_seconds <= 0:
        print("Analitrics reconciliation worker disabled")
        return

    def worker() -> None:
        while True:
            time.sleep(interval_seconds)
            try:
                reconciled = IngestValidationFactory.get_service().reconcile_deleted_files()
                print(f"Analitrics reconciliation worker: interval_seconds={interval_seconds} reconciled={reconciled}")
            except Exception as exc:
                print(f"Analitrics reconciliation worker failed: {exc}", file=os.sys.stderr)

    thread = threading.Thread(target=worker, name="analitrics-reconciliation", daemon=True)
    thread.start()
    print(f"Analitrics reconciliation worker scheduled every {interval_seconds}s")


class AgentHttpHandler(BaseHTTPRequestHandler):
    server_version = "AnalitricsAgentHTTP/0.1"

    def do_GET(self) -> None:
        if self.path == "/health":
            self._send_json(200, {"ok": True, "service": "analitrics-agent"})
            return
        parsed = urlparse(self.path)
        if parsed.path == "/agent/context":
            self._handle_context(parsed.query)
            return
        if parsed.path == "/agent/dashboards":
            self._handle_dashboard_list(parsed.query)
            return
        if parsed.path.startswith("/agent/dashboards/"):
            self._handle_dashboard_get(parsed.path, parsed.query)
            return
        self._send_json(404, {"error": "Not found"})

    def do_POST(self) -> None:
        if self.path == "/agent/run/stream":
            self._handle_stream_run()
            return

        if self.path == "/agent/ingest/validate":
            self._handle_ingest_validate()
            return

        if self.path == "/agent/files/invalidate":
            self._handle_file_invalidate()
            return

        if self.path == "/agent/conversations/delete":
            self._handle_conversation_delete()
            return

        if self.path == "/agent/catalog/feedback":
            self._handle_catalog_feedback()
            return

        if self.path == "/agent/dashboards":
            self._handle_dashboard_create()
            return

        if self.path.startswith("/agent/dashboards/") and self.path.endswith("/run"):
            self._handle_dashboard_view_run()
            return

        if self.path.startswith("/agent/dashboards/") and self.path.endswith("/instructions"):
            self._handle_dashboard_instruction()
            return

        if self.path != "/agent/run":
            self._send_json(404, {"error": "Not found"})
            return
        try:
            payload = self._read_json()
            request = self._request_from_payload(payload)
            result = AnalyticalAgentFactory.get_agent().run(request)
            self._send_json(200, state_output(request, result))
        except Exception as exc:
            if bool_env("ANALITRICS_DEBUG_ERRORS", False):
                raise
            self._send_json(422, {"error": str(exc)})

    def _handle_ingest_validate(self) -> None:
        service = IngestValidationFactory.get_service()
        try:
            payload = self._read_json()
            request = self._request_from_payload(payload)
            result = service.validate(request)
            self._send_json(200, result)
        except Exception as exc:
            if bool_env("ANALITRICS_DEBUG_ERRORS", False):
                raise
            self._send_json(422, service.error_payload(exc))

    def _handle_file_invalidate(self) -> None:
        try:
            payload = self._read_json()
            tenant_id = str(payload.get("tenantId") or payload.get("tenant_id") or "analitrics")
            user_id = payload.get("userId") or payload.get("user_id")
            file_id = payload.get("fileId") or payload.get("file_id")
            if not isinstance(user_id, str) or not user_id.strip():
                raise RuntimeError("userId is required")
            if not isinstance(file_id, str) or not file_id.strip():
                raise RuntimeError("fileId is required")
            reason = str(payload.get("reason") or "file_deleted")
            invalidated = IngestValidationFactory.get_service().invalidate_file(
                tenant_id=tenant_id,
                user_id=user_id,
                file_id=file_id,
                reason=reason,
            )
            self._send_json(
                200,
                {
                    "ok": True,
                    "tenantId": tenant_id,
                    "userId": user_id,
                    "fileId": file_id,
                    "invalidatedProfiles": invalidated,
                    "duckdbDeleted": False,
                    "cleanupMode": "logical_invalidation_immediate_physical_on_chat_delete",
                },
            )
        except Exception as exc:
            if bool_env("ANALITRICS_DEBUG_ERRORS", False):
                raise
            self._send_json(422, {"ok": False, "error": str(exc)})

    def _handle_conversation_delete(self) -> None:
        try:
            payload = self._read_json()
            tenant_id = str(payload.get("tenantId") or payload.get("tenant_id") or "analitrics")
            user_id = payload.get("userId") or payload.get("user_id")
            conversation_id = payload.get("conversationId") or payload.get("conversation_id")
            if not isinstance(user_id, str) or not user_id.strip():
                raise RuntimeError("userId is required")
            if not isinstance(conversation_id, str) or not conversation_id.strip():
                raise RuntimeError("conversationId is required")
            result = IngestValidationFactory.get_service().delete_conversation(
                tenant_id=tenant_id,
                user_id=user_id,
                conversation_id=conversation_id,
            )
            self._send_json(200, {"ok": True, **result})
        except Exception as exc:
            if bool_env("ANALITRICS_DEBUG_ERRORS", False):
                raise
            self._send_json(422, {"ok": False, "error": str(exc)})

    def _handle_context(self, query: str) -> None:
        try:
            values = parse_qs(query)
            tenant_id = str((values.get("tenantId") or values.get("tenant_id") or ["analitrics"])[0])
            user_id = (values.get("userId") or values.get("user_id") or [""])[0]
            conversation_id = (values.get("conversationId") or values.get("conversation_id") or [""])[0]
            if not user_id:
                raise RuntimeError("userId is required")
            if not conversation_id:
                raise RuntimeError("conversationId is required")
            result = IngestValidationFactory.get_service().get_context(
                tenant_id=tenant_id,
                user_id=user_id,
                conversation_id=conversation_id,
            )
            self._send_json(200, {"ok": True, **result})
        except Exception as exc:
            if bool_env("ANALITRICS_DEBUG_ERRORS", False):
                raise
            self._send_json(422, {"ok": False, "error": str(exc)})

    def _handle_dashboard_list(self, query: str) -> None:
        try:
            tenant_id, user_id, _ = self._identity_from_query(query, require_conversation=False)
            dashboards = DashboardRepositoryFactory.get_repository(_run_repository).list_dashboards(tenant_id, user_id)
            self._send_json(200, {"ok": True, "dashboards": dashboards})
        except Exception as exc:
            if bool_env("ANALITRICS_DEBUG_ERRORS", False):
                raise
            self._send_json(422, {"ok": False, "error": str(exc)})

    def _handle_dashboard_get(self, path: str, query: str) -> None:
        try:
            dashboard_id = self._path_part(path, 2)
            tenant_id, user_id, _ = self._identity_from_query(query, require_conversation=False)
            dashboard = DashboardRepositoryFactory.get_repository(_run_repository).get_dashboard(
                tenant_id,
                user_id,
                dashboard_id,
            )
            self._send_json(200, {"ok": True, "dashboard": dashboard})
        except Exception as exc:
            if bool_env("ANALITRICS_DEBUG_ERRORS", False):
                raise
            self._send_json(422, {"ok": False, "error": str(exc)})

    def _handle_dashboard_create(self) -> None:
        try:
            payload = self._read_json()
            tenant_id = str(payload.get("tenantId") or payload.get("tenant_id") or "analitrics")
            user_id = self._required_str(payload.get("userId") or payload.get("user_id"), "userId")
            conversation_id = self._required_str(
                payload.get("conversationId") or payload.get("conversation_id"),
                "conversationId",
            )
            title = self._optional_str(payload.get("title"))
            dashboard = DashboardRepositoryFactory.get_repository(_run_repository).create_from_conversation(
                tenant_id=tenant_id,
                user_id=user_id,
                conversation_id=conversation_id,
                title=title,
            )
            self._send_json(200, {"ok": True, "dashboard": dashboard})
        except Exception as exc:
            if bool_env("ANALITRICS_DEBUG_ERRORS", False):
                raise
            self._send_json(422, {"ok": False, "error": str(exc)})

    def _handle_dashboard_view_run(self) -> None:
        try:
            payload = self._read_json()
            parts = urlparse(self.path).path.strip("/").split("/")
            if (
                len(parts) != 6
                or parts[0] != "agent"
                or parts[1] != "dashboards"
                or parts[3] != "views"
                or parts[5] != "run"
            ):
                raise RuntimeError("Invalid dashboard view path")
            dashboard_id = parts[2]
            view_id = parts[4]
            tenant_id = str(payload.get("tenantId") or payload.get("tenant_id") or "analitrics")
            user_id = self._required_str(payload.get("userId") or payload.get("user_id"), "userId")
            limit = int(payload.get("limit") or 200)
            result = DashboardRepositoryFactory.get_repository(_run_repository).run_view(
                tenant_id=tenant_id,
                user_id=user_id,
                dashboard_id=dashboard_id,
                view_id=view_id,
                limit=limit,
            )
            self._send_json(200, {"ok": True, **result})
        except Exception as exc:
            if bool_env("ANALITRICS_DEBUG_ERRORS", False):
                raise
            self._send_json(422, {"ok": False, "error": str(exc)})

    def _handle_dashboard_instruction(self) -> None:
        try:
            payload = self._read_json()
            parts = urlparse(self.path).path.strip("/").split("/")
            if (
                len(parts) != 4
                or parts[0] != "agent"
                or parts[1] != "dashboards"
                or parts[3] != "instructions"
            ):
                raise RuntimeError("Invalid dashboard instruction path")
            dashboard_id = parts[2]
            tenant_id = str(payload.get("tenantId") or payload.get("tenant_id") or "analitrics")
            user_id = self._required_str(payload.get("userId") or payload.get("user_id"), "userId")
            instruction = self._required_str(payload.get("instruction"), "instruction")
            dashboard = DashboardRepositoryFactory.get_repository(_run_repository).apply_instruction(
                tenant_id=tenant_id,
                user_id=user_id,
                dashboard_id=dashboard_id,
                instruction=instruction,
            )
            self._send_json(200, {"ok": True, "dashboard": dashboard, "lastOperation": dashboard.get("lastOperation")})
        except Exception as exc:
            if bool_env("ANALITRICS_DEBUG_ERRORS", False):
                raise
            self._send_json(422, {"ok": False, "error": str(exc)})

    def _handle_catalog_feedback(self) -> None:
        try:
            payload = self._read_json()
            tenant_id = str(payload.get("tenantId") or payload.get("tenant_id") or "analitrics")
            user_id = payload.get("userId") or payload.get("user_id")
            conversation_id = payload.get("conversationId") or payload.get("conversation_id")
            if not isinstance(user_id, str) or not user_id.strip():
                raise RuntimeError("userId is required")
            if not isinstance(conversation_id, str) or not conversation_id.strip():
                raise RuntimeError("conversationId is required")
            result = IngestValidationFactory.get_service().save_feedback(
                tenant_id=tenant_id,
                user_id=user_id,
                conversation_id=conversation_id,
                source_file_id=self._optional_str(payload.get("sourceFileId") or payload.get("source_file_id")),
                source_filename=self._optional_str(payload.get("sourceFilename") or payload.get("source_filename")),
                step=int(payload.get("step") or 0),
                label=str(payload.get("label") or ""),
                content=str(payload.get("content") or ""),
            )
            self._send_json(200, {"ok": True, "tenantId": tenant_id, "userId": user_id, "conversationId": conversation_id, "feedback": result})
        except Exception as exc:
            if bool_env("ANALITRICS_DEBUG_ERRORS", False):
                raise
            self._send_json(422, {"ok": False, "error": str(exc)})

    def _handle_stream_run(self) -> None:
        headers_sent = False
        try:
            payload = self._read_json()
            request = self._request_from_payload(payload)
            self._send_stream_headers()
            headers_sent = True

            def progress(message: str) -> None:
                self._send_sse({"type": "progress", "message": message})

            def token(chunk: str) -> None:
                if chunk:
                    self._send_sse({"type": "token", "delta": chunk})

            result = AnalyticalAgentFactory.get_agent().run(request, progress=progress, token=token)
            self._send_sse({"type": "final", "payload": state_output(request, result)})
            self._send_sse("[DONE]")
            self.close_connection = True
        except Exception as exc:
            if bool_env("ANALITRICS_DEBUG_ERRORS", False):
                raise
            if not headers_sent:
                self._send_json(422, {"error": str(exc)})
                return
            if not self.wfile.closed:
                try:
                    self._send_sse({"type": "error", "error": str(exc)})
                    self._send_sse("[DONE]")
                    self.close_connection = True
                except Exception:
                    pass

    def log_message(self, fmt: str, *args: Any) -> None:
        print(f"{self.address_string()} - {fmt % args}")

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("content-length", "0"))
        if length <= 0:
            raise RuntimeError("JSON body is required")
        payload = json.loads(self.rfile.read(length).decode("utf-8"))
        if not isinstance(payload, dict):
            raise RuntimeError("JSON body must be an object")
        return payload

    def _request_from_payload(self, payload: dict[str, Any]) -> AgentRequest:
        question = payload.get("question")
        if not isinstance(question, str) or not question.strip():
            raise RuntimeError("question is required")
        conversation_id = payload.get("conversationId") or payload.get("conversation_id")
        if not isinstance(conversation_id, str) or not conversation_id.strip():
            raise RuntimeError("conversationId is required")
        return AgentRequest(
            question=question,
            tenant_id=str(payload.get("tenantId") or payload.get("tenant_id") or "analitrics"),
            user_id=payload.get("userId") or payload.get("user_id"),
            conversation_id=conversation_id,
            message_id=payload.get("messageId") or payload.get("message_id"),
            file_id=self._list_or_none(payload.get("file_id")),
            filename=self._list_or_none(payload.get("filename")),
            file_ids=payload.get("fileIds") or payload.get("file_ids"),
            filenames=payload.get("filenames"),
            cache_dir=str(payload.get("cacheDir") or payload.get("cache_dir") or "/var/analitrics/analytics/cache"),
            sample_rows=int(payload.get("sampleRows") or payload.get("sample_rows") or 5),
            run_id=str(payload.get("runId") or payload.get("run_id") or uuid4()),
            context_messages=self._messages_or_none(payload.get("messages")),
        )

    def _list_or_none(self, value: Any) -> list[str] | None:
        if value is None:
            return None
        if isinstance(value, list):
            return [str(item) for item in value]
        return [str(value)]

    def _optional_str(self, value: Any) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    def _required_str(self, value: Any, name: str) -> str:
        text = self._optional_str(value)
        if not text:
            raise RuntimeError(f"{name} is required")
        return text

    def _identity_from_query(self, query: str, require_conversation: bool = True) -> tuple[str, str, str | None]:
        values = parse_qs(query)
        tenant_id = str((values.get("tenantId") or values.get("tenant_id") or ["analitrics"])[0])
        user_id = (values.get("userId") or values.get("user_id") or [""])[0]
        conversation_id = (values.get("conversationId") or values.get("conversation_id") or [""])[0]
        if not user_id:
            raise RuntimeError("userId is required")
        if require_conversation and not conversation_id:
            raise RuntimeError("conversationId is required")
        return tenant_id, user_id, conversation_id or None

    def _path_part(self, path: str, index: int) -> str:
        parts = path.strip("/").split("/")
        try:
            value = parts[index]
        except IndexError as exc:
            raise RuntimeError("Invalid path") from exc
        if not value:
            raise RuntimeError("Invalid path")
        return value

    def _messages_or_none(self, value: Any) -> list[dict[str, Any]] | None:
        if not isinstance(value, list):
            return None
        messages: list[dict[str, Any]] = []
        for item in value:
            if isinstance(item, dict):
                messages.append(item)
        return messages

    def _send_json(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("content-type", "application/json; charset=utf-8")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_stream_headers(self) -> None:
        self.send_response(200)
        self.send_header("content-type", "text/event-stream; charset=utf-8")
        self.send_header("cache-control", "no-cache")
        self.send_header("connection", "keep-alive")
        self.end_headers()

    def _send_sse(self, payload: dict[str, Any] | str) -> None:
        if isinstance(payload, str):
            data = payload
        else:
            data = json.dumps(payload, ensure_ascii=False)
        self.wfile.write(f"data: {data}\n\n".encode("utf-8"))
        self.wfile.flush()


def main() -> None:
    port = int(os.getenv("ANALITRICS_AGENT_PORT", "8090"))
    start_reconciliation_worker()
    server = HTTPServer(("0.0.0.0", port), AgentHttpHandler)
    print(f"Analitrics agent HTTP server listening on port {port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
