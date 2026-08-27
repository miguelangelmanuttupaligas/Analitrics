from __future__ import annotations

import argparse

from nl_sql_file import FileMetadata, resolve_file

from .models import AgentRequest
from .repositories import ConversationAttachmentRepository


def csv_list(value: str | None) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


class FileResolver:
    def __init__(self, attachment_repository: ConversationAttachmentRepository | None = None) -> None:
        self._attachment_repository = attachment_repository

    @property
    def database(self):
        if self._attachment_repository is None:
            raise RuntimeError("FileResolver has no database-backed attachment repository")
        return self._attachment_repository.database

    def resolve(self, request: AgentRequest) -> list[FileMetadata]:
        if not request.user_id:
            raise RuntimeError("Analitrics requires authenticated user_id to resolve analytical files")

        file_ids = list(request.file_id or []) + csv_list(request.file_ids)
        filenames = list(request.filename or []) + csv_list(request.filenames)

        if not file_ids and not filenames and self._attachment_repository:
            file_ids = self._attachment_repository.find_file_ids(request.conversation_id, request.message_id)
            if not file_ids and request.conversation_id and request.message_id:
                file_ids = self._attachment_repository.find_file_ids(
                    request.conversation_id,
                    None,
                    until_message_id=request.message_id,
                )

        if not file_ids and not filenames:
            raise RuntimeError(
                "Provide --file-id, --filename, --file-ids, --filenames, or a conversation/message with attachments"
            )

        files: list[FileMetadata] = []
        seen: set[str] = set()
        for file_id in file_ids:
            metadata = resolve_file(
                argparse.Namespace(file_id=file_id, filename=None, tenant_id=request.tenant_id, user_id=request.user_id),
                database=self.database,
            )
            if metadata.file_id not in seen:
                files.append(metadata)
                seen.add(metadata.file_id)

        for filename in filenames:
            metadata = resolve_file(
                argparse.Namespace(file_id=None, filename=filename, tenant_id=request.tenant_id, user_id=request.user_id),
                database=self.database,
            )
            if metadata.file_id not in seen:
                files.append(metadata)
                seen.add(metadata.file_id)

        return files
