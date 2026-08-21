from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from nl_sql_file import TABULAR_TYPES, connect_mongo, env

from analitrics_agent.ingest_validation import IngestValidationFactory
from analitrics_agent.models import AgentRequest


TEST_PREFIX = "analitrics-ingest-suite"


@dataclass(frozen=True)
class FileRef:
    file_id: str
    filename: str
    mime_type: str
    bytes: int
    owner_id: str


@dataclass(frozen=True)
class Scenario:
    name: str
    description: str
    request: AgentRequest
    expected_file_ids: list[str] = field(default_factory=list)
    expected_error: str | None = None
    min_cache_hits: int = 0
    invalidate_before: str | None = None
    assert_cache_path_exists_after_invalidation: bool = False


class FileInventory:
    def __init__(self, tenant_id: str, limit: int) -> None:
        self._tenant_id = tenant_id
        self._limit = limit

    def load(self) -> list[FileRef]:
        mongo = connect_mongo()
        db = mongo[env("MONGO_DB", "LibreChat")]
        docs = db.files.find(
            {"tenantId": self._tenant_id, "source": "s3"},
            {"_id": 0, "file_id": 1, "filename": 1, "type": 1, "bytes": 1, "user": 1, "createdAt": 1},
        ).sort("createdAt", -1)
        files: list[FileRef] = []
        seen: set[str] = set()
        for doc in docs:
            filename = str(doc.get("filename") or "")
            extension = Path(filename).suffix.lower()
            mime_type = str(doc.get("type") or "")
            if mime_type not in TABULAR_TYPES and extension not in {".csv", ".xls", ".xlsx", ".ods"}:
                continue
            file_id = str(doc.get("file_id") or "")
            if not file_id or file_id in seen:
                continue
            files.append(
                FileRef(
                    file_id=file_id,
                    filename=filename,
                    mime_type=mime_type,
                    bytes=int(doc.get("bytes") or 0),
                    owner_id=str(doc.get("user") or ""),
                )
            )
            seen.add(file_id)
            if len(files) >= self._limit:
                break
        return files


class TemporaryMessageSeeder:
    def __init__(self, tenant_id: str, user_id: str) -> None:
        self._tenant_id = tenant_id
        self._user_id = user_id
        self._mongo = connect_mongo()
        self._db = self._mongo[env("MONGO_DB", "LibreChat")]
        self._conversation_ids: list[str] = []

    def cleanup(self) -> None:
        self._db.messages.delete_many({"conversationId": {"$regex": f"^{TEST_PREFIX}-"}})

    def seed(self, files: list[FileRef]) -> dict[str, dict[str, str]]:
        self.cleanup()
        now = datetime.now(timezone.utc).replace(microsecond=0)
        a = files[0]
        b = files[1] if len(files) > 1 else files[0]
        c = files[2] if len(files) > 2 else b
        conversations = {
            "single": f"{TEST_PREFIX}-single",
            "carry": f"{TEST_PREFIX}-carry",
            "multi": f"{TEST_PREFIX}-multi",
            "duplicates": f"{TEST_PREFIX}-duplicates",
            "three": f"{TEST_PREFIX}-three",
        }
        message_ids = {
            "single_file": f"{TEST_PREFIX}-single-file",
            "carry_before": f"{TEST_PREFIX}-carry-before",
            "carry_file": f"{TEST_PREFIX}-carry-file",
            "carry_after": f"{TEST_PREFIX}-carry-after",
            "multi_a": f"{TEST_PREFIX}-multi-a",
            "multi_b": f"{TEST_PREFIX}-multi-b",
            "duplicates": f"{TEST_PREFIX}-duplicates",
            "three_a": f"{TEST_PREFIX}-three-a",
            "three_b": f"{TEST_PREFIX}-three-b",
            "three_c": f"{TEST_PREFIX}-three-c",
        }
        self._conversation_ids = list(conversations.values())
        docs = [
            self._message(conversations["single"], message_ids["single_file"], "archivo A", [a], now),
            self._message(conversations["carry"], message_ids["carry_before"], "pregunta sin archivo antes de adjuntar", [], now + timedelta(seconds=1)),
            self._message(conversations["carry"], message_ids["carry_file"], "archivo A + texto", [a], now + timedelta(seconds=2)),
            self._message(conversations["carry"], message_ids["carry_after"], "pregunta posterior sin archivo", [], now + timedelta(seconds=3)),
            self._message(conversations["multi"], message_ids["multi_a"], "archivo A", [a], now + timedelta(seconds=4)),
            self._message(conversations["multi"], message_ids["multi_b"], "archivo B", [b], now + timedelta(seconds=5)),
            self._message(conversations["duplicates"], message_ids["duplicates"], "archivo A duplicado", [a, a], now + timedelta(seconds=6)),
            self._message(conversations["three"], message_ids["three_a"], "archivo A", [a], now + timedelta(seconds=7)),
            self._message(conversations["three"], message_ids["three_b"], "archivo B", [b], now + timedelta(seconds=8)),
            self._message(conversations["three"], message_ids["three_c"], "archivo C", [c], now + timedelta(seconds=9)),
        ]
        self._db.messages.insert_many(docs)
        return {
            key: {
                "conversationId": conversation_id,
                "single_file": message_ids["single_file"],
                "carry_before": message_ids["carry_before"],
                "carry_file": message_ids["carry_file"],
                "carry_after": message_ids["carry_after"],
                "multi_a": message_ids["multi_a"],
                "multi_b": message_ids["multi_b"],
                "duplicates": message_ids["duplicates"],
                "three_a": message_ids["three_a"],
                "three_b": message_ids["three_b"],
                "three_c": message_ids["three_c"],
            }
            for key, conversation_id in conversations.items()
        }

    def _message(
        self,
        conversation_id: str,
        message_id: str,
        text: str,
        files: list[FileRef],
        created_at: datetime,
    ) -> dict[str, Any]:
        return {
            "tenantId": self._tenant_id,
            "user": self._user_id,
            "userId": self._user_id,
            "conversationId": conversation_id,
            "messageId": message_id,
            "isCreatedByUser": True,
            "sender": "Analitrics Test",
            "text": text,
            "files": [
                {
                    "file_id": file.file_id,
                    "filename": file.filename,
                    "type": file.mime_type,
                    "bytes": file.bytes,
                }
                for file in files
            ],
            "createdAt": created_at,
            "updatedAt": created_at,
            "testSource": TEST_PREFIX,
        }


class ScenarioBuilder:
    def __init__(self, tenant_id: str, user_id: str, cache_dir: str) -> None:
        self._tenant_id = tenant_id
        self._user_id = user_id
        self._cache_dir = cache_dir

    def build(self, files: list[FileRef], seeded: dict[str, dict[str, str]]) -> list[Scenario]:
        a = files[0]
        b = files[1] if len(files) > 1 else files[0]
        c = files[2] if len(files) > 2 else b
        cache_conversation = f"{TEST_PREFIX}-cache-conversation"

        scenarios = [
            self._scenario("01_no_context", "sin archivo ni conversación", {}, [], "Provide"),
            self._scenario("02_file_id_a", "archivo explícito por file_id", {"file_id": [a.file_id]}, [a.file_id]),
            self._scenario("03_filename_a", "archivo explícito por filename", {"filename": [a.filename]}, [a.file_id]),
            self._scenario(
                "04_duplicate_file_id_a",
                "file_id duplicado debe deduplicarse",
                {"file_id": [a.file_id, a.file_id]},
                [a.file_id],
            ),
            self._scenario(
                "05_file_id_and_filename_same",
                "mismo archivo por id y nombre debe deduplicarse",
                {"file_id": [a.file_id], "filename": [a.filename]},
                [a.file_id],
            ),
            self._scenario("06_two_file_ids", "dos archivos por file_id", {"file_id": [a.file_id, b.file_id]}, [a.file_id, b.file_id]),
            self._scenario("07_two_filenames", "dos archivos por filename", {"filename": [a.filename, b.filename]}, [a.file_id, b.file_id]),
            self._scenario("08_mixed_id_filename", "archivo por id + archivo por nombre", {"file_id": [a.file_id], "filename": [b.filename]}, [a.file_id, b.file_id]),
            self._scenario("09_csv_file_ids_arg", "lista CSV file_ids", {"file_ids": f"{a.file_id},{b.file_id}"}, [a.file_id, b.file_id]),
            self._scenario("10_csv_filenames_arg", "lista CSV filenames", {"filenames": f"{a.filename},{b.filename}"}, [a.file_id, b.file_id]),
            self._scenario(
                "11_conversation_message_with_file",
                "resuelve adjunto del messageId exacto",
                {"conversation_id": seeded["single"]["conversationId"], "message_id": seeded["single"]["single_file"]},
                [a.file_id],
            ),
            self._scenario(
                "12_conversation_only_with_file",
                "resuelve adjuntos de conversación",
                {"conversation_id": seeded["single"]["conversationId"]},
                [a.file_id],
            ),
            self._scenario("13_message_only_with_file", "resuelve solo por messageId", {"message_id": seeded["single"]["single_file"]}, [a.file_id]),
            self._scenario(
                "14_no_file_before_attachment",
                "mensaje sin archivo antes de adjuntos no debe ver futuro",
                {"conversation_id": seeded["carry"]["conversationId"], "message_id": seeded["carry"]["carry_before"]},
                [],
                "Provide",
            ),
            self._scenario(
                "15_file_plus_text_message",
                "mensaje con archivo + texto",
                {"conversation_id": seeded["carry"]["conversationId"], "message_id": seeded["carry"]["carry_file"]},
                [a.file_id],
            ),
            self._scenario(
                "16_followup_without_file_uses_prior_context",
                "mensaje posterior sin archivo usa contexto previo",
                {"conversation_id": seeded["carry"]["conversationId"], "message_id": seeded["carry"]["carry_after"]},
                [a.file_id],
            ),
            self._scenario(
                "17_exact_message_b_not_full_context",
                "messageId con archivo B no arrastra A si el mensaje trae adjunto",
                {"conversation_id": seeded["multi"]["conversationId"], "message_id": seeded["multi"]["multi_b"]},
                [b.file_id],
            ),
            self._scenario(
                "18_conversation_accumulates_a_b",
                "conversación completa acumula A+B",
                {"conversation_id": seeded["multi"]["conversationId"]},
                [a.file_id, b.file_id],
            ),
            self._scenario(
                "19_conversation_first_ingest",
                "primera ingesta con conversationId explícito",
                {"file_id": [a.file_id], "conversation_id": cache_conversation},
                [a.file_id],
            ),
            self._scenario(
                "20_conversation_reuses_cache",
                "segunda ingesta reusa DuckDB por hash",
                {"file_id": [a.file_id], "conversation_id": cache_conversation},
                [a.file_id],
                min_cache_hits=1,
            ),
            self._scenario(
                "21_conversation_adds_second_file",
                "misma conversación agrega otro archivo y conserva cache",
                {"file_id": [a.file_id, b.file_id], "conversation_id": cache_conversation},
                [a.file_id, b.file_id],
                min_cache_hits=1,
            ),
            self._scenario(
                "22_logical_invalidation_keeps_duckdb",
                "invalidar un archivo no borra DuckDB y excluye sus tablas del contexto",
                {"file_id": [b.file_id], "conversation_id": cache_conversation},
                [b.file_id],
                invalidate_before=a.file_id,
                assert_cache_path_exists_after_invalidation=True,
            ),
            self._scenario("23_sample_rows_one", "profile con sampleRows=1", {"file_id": [a.file_id], "sample_rows": 1}, [a.file_id]),
            self._scenario("24_missing_file_id", "file_id inexistente debe fallar", {"file_id": ["missing-file-id"]}, [], "No S3 file metadata"),
            self._scenario("25_missing_filename", "filename inexistente debe fallar", {"filename": ["missing.xlsx"]}, [], "No S3 file metadata"),
            self._scenario(
                "26_other_user_cannot_read_file",
                "otro usuario no puede resolver file_id ajeno",
                {"file_id": [a.file_id], "user_id": f"{self._user_id}-other"},
                [],
                "No S3 file metadata",
            ),
            self._scenario(
                "27_other_tenant_cannot_read_file",
                "otro tenant no puede resolver file_id ajeno",
                {"file_id": [a.file_id], "tenant_id": f"{self._tenant_id}-other"},
                [],
                "No S3 file metadata",
            ),
            self._scenario(
                "28_other_user_same_conversation_cannot_reuse_cache",
                "otro usuario no puede reutilizar cache/conversación ajena",
                {"file_id": [a.file_id], "conversation_id": cache_conversation, "user_id": f"{self._user_id}-other"},
                [],
                "No S3 file metadata",
            ),
        ]

        if len({a.file_id, b.file_id, c.file_id}) >= 3:
            scenarios.append(
                self._scenario(
                    "29_three_files_conversation",
                    "conversación con tres archivos",
                    {"conversation_id": seeded["three"]["conversationId"]},
                    [a.file_id, b.file_id, c.file_id],
                )
            )
        return scenarios

    def _scenario(
        self,
        name: str,
        description: str,
        overrides: dict[str, Any],
        expected_file_ids: list[str],
        expected_error: str | None = None,
        min_cache_hits: int = 0,
        invalidate_before: str | None = None,
        assert_cache_path_exists_after_invalidation: bool = False,
    ) -> Scenario:
        request = AgentRequest(
            question="Validar ingesta sin LLM",
            tenant_id=overrides.get("tenant_id") or self._tenant_id,
            user_id=overrides.get("user_id") or self._user_id,
            conversation_id=overrides.get("conversation_id"),
            message_id=overrides.get("message_id"),
            file_id=overrides.get("file_id"),
            filename=overrides.get("filename"),
            file_ids=overrides.get("file_ids"),
            filenames=overrides.get("filenames"),
            cache_dir=self._cache_dir,
            sample_rows=int(overrides.get("sample_rows") or 5),
            run_id=str(uuid4()),
        )
        return Scenario(
            name,
            description,
            request,
            expected_file_ids,
            expected_error,
            min_cache_hits,
            invalidate_before,
            assert_cache_path_exists_after_invalidation,
        )


class ScenarioExecutor:
    def __init__(self) -> None:
        self._service = IngestValidationFactory.get_service()

    def execute(self, scenario: Scenario) -> dict[str, Any]:
        try:
            if scenario.invalidate_before:
                self._service.invalidate_file(
                    tenant_id=scenario.request.tenant_id,
                    user_id=scenario.request.user_id or "",
                    file_id=scenario.invalidate_before,
                    reason="ingest_suite_logical_delete",
                )
            result = self._service.validate(scenario.request)
            return self._success_result(scenario, result)
        except Exception as exc:
            return self._error_result(scenario, exc)

    def _success_result(self, scenario: Scenario, result: dict[str, Any]) -> dict[str, Any]:
        actual_file_ids = [str(file.get("fileId")) for file in result.get("files", [])]
        expected = set(scenario.expected_file_ids)
        actual = set(actual_file_ids)
        failures: list[str] = []
        if scenario.expected_error:
            failures.append(f"se esperaba error con texto '{scenario.expected_error}'")
        if expected != actual:
            failures.append(f"contexto esperado={sorted(expected)} actual={sorted(actual)}")
        if int(result.get("cacheHits") or 0) < scenario.min_cache_hits:
            failures.append(f"cacheHits esperado>={scenario.min_cache_hits} actual={result.get('cacheHits')}")
        if result.get("llmUsed") is not False:
            failures.append("llmUsed debe ser false")
        if scenario.assert_cache_path_exists_after_invalidation:
            cache_path = result.get("cachePath")
            if not cache_path or not Path(cache_path).exists():
                failures.append("DuckDB físico debe seguir existiendo tras invalidación lógica")
        if (
            scenario.request.session_id
            and not (result.get("persistence") or {}).get("sessionPersisted")
            and scenario.expected_file_ids
        ):
            failures.append("sessionPersisted debe ser true")
        return {
            "name": scenario.name,
            "description": scenario.description,
            "status": "passed" if not failures else "failed",
            "expectedFileIds": scenario.expected_file_ids,
            "actualFileIds": actual_file_ids,
            "cacheHits": result.get("cacheHits"),
            "cachePath": result.get("cachePath"),
            "tableCount": (result.get("context") or {}).get("tableCount"),
            "rowCountTotal": (result.get("context") or {}).get("rowCountTotal"),
            "llmUsed": result.get("llmUsed"),
            "failures": failures,
            "result": result,
        }

    def _error_result(self, scenario: Scenario, exc: Exception) -> dict[str, Any]:
        error = str(exc)
        expected_error = scenario.expected_error
        passed = bool(expected_error and expected_error in error)
        return {
            "name": scenario.name,
            "description": scenario.description,
            "status": "passed" if passed else "failed",
            "expectedFileIds": scenario.expected_file_ids,
            "actualFileIds": [],
            "cacheHits": None,
            "cachePath": None,
            "tableCount": None,
            "rowCountTotal": None,
            "llmUsed": False,
            "failures": [] if passed else [f"error inesperado: {error}"],
            "error": error,
        }


class SuiteReporter:
    def write(self, results: list[dict[str, Any]], output_path: Path | None) -> None:
        self._print_table(results)
        if output_path:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(json.dumps({"results": results}, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"\nJSON report: {output_path}")

    def _print_table(self, results: list[dict[str, Any]]) -> None:
        headers = ["#", "STATUS", "SCENARIO", "FILES", "TABLES", "CACHE", "ROWS", "LLM"]
        rows = []
        for index, result in enumerate(results, start=1):
            rows.append(
                [
                    str(index),
                    result["status"],
                    result["name"],
                    str(len(result.get("actualFileIds") or [])),
                    str(result.get("tableCount") if result.get("tableCount") is not None else "-"),
                    str(result.get("cacheHits") if result.get("cacheHits") is not None else "-"),
                    str(result.get("rowCountTotal") if result.get("rowCountTotal") is not None else "-"),
                    str(result.get("llmUsed")),
                ]
            )
        widths = [max(len(row[column]) for row in [headers, *rows]) for column in range(len(headers))]
        print("  ".join(headers[index].ljust(widths[index]) for index in range(len(headers))))
        print("  ".join("-" * width for width in widths))
        for row in rows:
            print("  ".join(row[index].ljust(widths[index]) for index in range(len(row))))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run no-LLM Analitrics ingest validation scenarios")
    parser.add_argument("--tenant-id", default="analitrics")
    parser.add_argument("--user-id")
    parser.add_argument("--cache-dir", default="/var/analitrics/analytics/cache")
    parser.add_argument("--file-limit", type=int, default=4)
    parser.add_argument("--output", default="/var/analitrics/analytics/validation/ingest-suite-latest.json")
    parser.add_argument("--keep-test-messages", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    files = FileInventory(args.tenant_id, args.file_limit).load()
    if not files:
        print("ERROR: no hay archivos tabulares S3 para validar", file=sys.stderr)
        raise SystemExit(2)

    user_id = args.user_id or files[0].owner_id
    if not user_id:
        print("ERROR: no se pudo determinar owner user_id de los archivos", file=sys.stderr)
        raise SystemExit(2)

    seeder = TemporaryMessageSeeder(args.tenant_id, user_id)
    seeded = seeder.seed(files)
    try:
        scenarios = ScenarioBuilder(args.tenant_id, user_id, args.cache_dir).build(files, seeded)
        executor = ScenarioExecutor()
        results = [executor.execute(scenario) for scenario in scenarios]
        SuiteReporter().write(results, Path(args.output) if args.output else None)
        failed = [result for result in results if result["status"] != "passed"]
        if failed:
            print("\nFailures:")
            for result in failed:
                print(f"- {result['name']}: {'; '.join(result.get('failures') or [result.get('error', '')])}")
            raise SystemExit(1)
    finally:
        if not args.keep_test_messages:
            seeder.cleanup()


if __name__ == "__main__":
    main()
