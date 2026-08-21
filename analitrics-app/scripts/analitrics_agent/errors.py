from __future__ import annotations

from nl_sql_file import FileMetadata


class AnalitricsError(RuntimeError):
    """Base error for user-facing Analitrics failures."""

    code = "analitrics_error"
    user_message = "No se pudo completar el flujo analítico."

    def to_payload(self) -> dict[str, object]:
        return {
            "code": self.code,
            "message": str(self),
            "userMessage": self.user_message,
            "recoverable": True,
        }


class FileIngestError(AnalitricsError):
    code = "file_ingest_failed"

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

    @property
    def user_message(self) -> str:
        if self.stage == "csv_read_csv_auto":
            return (
                f"No pude leer el CSV '{self.metadata.filename}'. "
                "Revisa que tenga encabezados, delimitador consistente y filas tabulares."
            )
        if self.stage == "excel_openpyxl":
            return (
                f"No pude leer el Excel '{self.metadata.filename}'. "
                "Revisa que tenga al menos una hoja tabular con encabezados claros."
            )
        return f"No pude leer el archivo '{self.metadata.filename}'."

    def to_payload(self) -> dict[str, object]:
        return {
            **super().to_payload(),
            "stage": self.stage,
            "file": {
                "fileId": self.metadata.file_id,
                "filename": self.metadata.filename,
                "mimeType": self.metadata.mime_type,
                "bytes": self.metadata.bytes,
            },
            "cause": str(self.cause),
        }
