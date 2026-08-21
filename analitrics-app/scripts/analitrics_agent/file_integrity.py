from __future__ import annotations

import hashlib
from pathlib import Path

from nl_sql_file import FileMetadata


class FileContentHasher:
    def __init__(self, algorithm: str = "sha256", chunk_size: int = 1024 * 1024) -> None:
        self._algorithm = algorithm
        self._chunk_size = chunk_size

    def hash_path(self, path: Path) -> str:
        digest = hashlib.new(self._algorithm)
        with path.open("rb") as handle:
            while chunk := handle.read(self._chunk_size):
                digest.update(chunk)
        return f"{self._algorithm}:{digest.hexdigest()}"


class FileCacheSignatureBuilder:
    def build(self, metadata: FileMetadata) -> str:
        content_hash = getattr(metadata, "content_hash", None)
        identity = content_hash or metadata.storage_key
        return "|".join(
            [
                metadata.file_id,
                identity,
                str(metadata.bytes),
                metadata.mime_type,
            ]
        )
