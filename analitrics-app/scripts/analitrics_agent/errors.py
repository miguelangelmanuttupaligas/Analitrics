from __future__ import annotations

from nl_sql_file import FileMetadata


class AnalitricsError(RuntimeError):
    """Base error for user-facing Analitrics failures."""


class FileIngestError(AnalitricsError):
    def __init__(self, metadata: FileMetadata, stage: str, cause: Exception) -> None:
        self.metadata = metadata
        self.stage = stage
        self.cause = cause
        super().__init__(self._build_message())

    def _build_message(self) -> str:
        return (
            "No pude leer el archivo tabular "
            f"'{self.metadata.filename}' "
            f"(file_id={self.metadata.file_id}, mime={self.metadata.mime_type}) "
            f"durante la etapa '{self.stage}'. "
            f"Causa: {self.cause}"
        )
