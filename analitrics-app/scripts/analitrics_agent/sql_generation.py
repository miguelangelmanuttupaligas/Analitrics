from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from .config import env
from .llm_client import JsonLlmClient
from .prompts import GENERATE_SQL_SYSTEM_PROMPT, REPAIR_SQL_SYSTEM_PROMPT
from .schema_context import SchemaContextBuilder


@dataclass(frozen=True)
class SqlGenerationResult:
    sql: str
    rationale: str
    backend: str


class SqlGenerator(Protocol):
    def generate(
        self,
        question: str,
        files: list[Any],
        profiles: list[dict[str, Any]],
        context_messages: list[dict[str, Any]] | None = None,
        catalog_feedback: list[dict[str, Any]] | None = None,
    ) -> SqlGenerationResult:
        ...

    def repair(
        self,
        question: str,
        files: list[Any],
        profiles: list[dict[str, Any]],
        failed_sql: str,
        error: str,
        context_messages: list[dict[str, Any]] | None = None,
        catalog_feedback: list[dict[str, Any]] | None = None,
    ) -> SqlGenerationResult:
        ...


class LlmSqlGenerator:
    def __init__(self, llm_client: JsonLlmClient, schema_context_builder: SchemaContextBuilder) -> None:
        self._llm_client = llm_client
        self._schema_context_builder = schema_context_builder

    def generate(
        self,
        question: str,
        files: list[Any],
        profiles: list[dict[str, Any]],
        context_messages: list[dict[str, Any]] | None = None,
        catalog_feedback: list[dict[str, Any]] | None = None,
    ) -> SqlGenerationResult:
        plan = self._llm_client.complete_json(
            system=GENERATE_SQL_SYSTEM_PROMPT,
            payload={
                "question": question,
                "available_data": self._schema_context_builder.build(files, profiles, catalog_feedback),
                "conversation_context": context_messages or [],
            },
            model_env="ANALITRICS_NL_SQL_MODEL",
            default_model=env("ANALITRICS_DEFAULT_MODEL", "gpt-5.5"),
        )
        return SqlGenerationResult(
            sql=str(plan.get("sql", "")),
            rationale=str(plan.get("rationale", "")),
            backend="llm",
        )

    def repair(
        self,
        question: str,
        files: list[Any],
        profiles: list[dict[str, Any]],
        failed_sql: str,
        error: str,
        context_messages: list[dict[str, Any]] | None = None,
        catalog_feedback: list[dict[str, Any]] | None = None,
    ) -> SqlGenerationResult:
        repaired = self._llm_client.complete_json(
            system=REPAIR_SQL_SYSTEM_PROMPT,
            payload={
                "question": question,
                "available_data": self._schema_context_builder.build(files, profiles, catalog_feedback),
                "conversation_context": context_messages or [],
                "failed_sql": failed_sql,
                "error": error,
            },
            model_env="ANALITRICS_SQL_REPAIR_MODEL",
            default_model=env("ANALITRICS_DEFAULT_MODEL", "gpt-5.5"),
        )
        return SqlGenerationResult(
            sql=str(repaired.get("sql", "")),
            rationale=str(repaired.get("rationale", "")),
            backend="llm",
        )


class VannaSqlGenerator:
    def __init__(self) -> None:
        raise RuntimeError(
            "ANALITRICS_SQL_GENERATOR=vanna is reserved but not enabled yet. "
            "Vanna 2.x must be validated against the Analitrics DuckDB workspace before becoming the SQL backend."
        )


class SqlGeneratorFactory:
    @staticmethod
    def create(llm_client: JsonLlmClient, schema_context_builder: SchemaContextBuilder) -> SqlGenerator:
        backend = env("ANALITRICS_SQL_GENERATOR", "llm").strip().lower()
        if backend == "llm":
            return LlmSqlGenerator(llm_client, schema_context_builder)
        if backend == "vanna":
            return VannaSqlGenerator()
        raise RuntimeError(f"Unsupported ANALITRICS_SQL_GENERATOR={backend!r}")
