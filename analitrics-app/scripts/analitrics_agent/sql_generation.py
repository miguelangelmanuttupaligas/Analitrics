from __future__ import annotations

from dataclasses import dataclass
import json
import re
import unicodedata
from typing import Any, Callable, Protocol

import sqlglot
from sqlglot import exp

from .analytical_context import AnalyticalContextPromptCompactor
from .config import env
from .llm_client import JsonLlmClient
from .prompts import GENERATE_SQL_SYSTEM_PROMPT, REPAIR_SQL_SYSTEM_PROMPT, TOOL_ASSISTED_SQL_SYSTEM_PROMPT
from .schema_context import SchemaContextBuilder
from .sql_validation import SqlReadOnlyValidator


@dataclass(frozen=True)
class SqlGenerationResult:
    sql: str
    rationale: str
    backend: str
    data_strategy: dict[str, Any] | None = None


class SqlGenerator(Protocol):
    def generate(
        self,
        question: str,
        files: list[Any],
        profiles: list[dict[str, Any]],
        context_messages: list[dict[str, Any]] | None = None,
        catalog_feedback: list[dict[str, Any]] | None = None,
        analytical_context: dict[str, Any] | None = None,
        workspace: Any | None = None,
        progress: Callable[[str], None] | None = None,
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
        analytical_context: dict[str, Any] | None = None,
        workspace: Any | None = None,
        progress: Callable[[str], None] | None = None,
    ) -> SqlGenerationResult:
        ...


class LlmSqlGenerator:
    def __init__(
        self,
        llm_client: JsonLlmClient,
        schema_context_builder: SchemaContextBuilder,
        context_compactor: AnalyticalContextPromptCompactor | None = None,
    ) -> None:
        self._llm_client = llm_client
        self._schema_context_builder = schema_context_builder
        self._context_compactor = context_compactor or AnalyticalContextPromptCompactor()

    def generate(
        self,
        question: str,
        files: list[Any],
        profiles: list[dict[str, Any]],
        context_messages: list[dict[str, Any]] | None = None,
        catalog_feedback: list[dict[str, Any]] | None = None,
        analytical_context: dict[str, Any] | None = None,
        workspace: Any | None = None,
        progress: Callable[[str], None] | None = None,
    ) -> SqlGenerationResult:
        plan = self._llm_client.complete_json(
            system=GENERATE_SQL_SYSTEM_PROMPT,
            payload={
                "question": question,
                "available_data": self._schema_context_builder.build_for_sql(
                    files,
                    profiles,
                    catalog_feedback,
                    analytical_context,
                ),
                "conversation_context": context_messages or [],
                "analytical_context": self._context_compactor.for_sql(analytical_context or {}),
            },
            model_env="ANALITRICS_NL_SQL_MODEL",
            default_model=env("ANALITRICS_DEFAULT_MODEL", "gpt-5.5"),
        )
        return SqlGenerationResult(
            sql=str(plan.get("sql", "")),
            rationale=self._trim_text(plan.get("rationale"), 240),
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
        analytical_context: dict[str, Any] | None = None,
        workspace: Any | None = None,
        progress: Callable[[str], None] | None = None,
    ) -> SqlGenerationResult:
        repaired = self._llm_client.complete_json(
            system=REPAIR_SQL_SYSTEM_PROMPT,
            payload={
                "question": question,
                "available_data": self._schema_context_builder.build_for_sql(
                    files,
                    profiles,
                    catalog_feedback,
                    analytical_context,
                ),
                "conversation_context": context_messages or [],
                "analytical_context": self._context_compactor.for_sql(analytical_context or {}),
                "failed_sql": failed_sql,
                "error": error,
            },
            model_env="ANALITRICS_SQL_REPAIR_MODEL",
            default_model=env("ANALITRICS_DEFAULT_MODEL", "gpt-5.5"),
        )
        return SqlGenerationResult(
            sql=str(repaired.get("sql", "")),
            rationale=self._trim_text(repaired.get("rationale"), 240),
            backend="llm",
        )

    def _trim_text(self, value: Any, limit: int) -> str:
        text = str(value or "").strip()
        return text if len(text) <= limit else text[:limit].rstrip() + "..."


class SqlExplorationTools:
    def __init__(
        self,
        workspace: Any,
        profiles: list[dict[str, Any]],
        catalog_feedback: list[dict[str, Any]] | None = None,
        validator: SqlReadOnlyValidator | None = None,
    ) -> None:
        self._workspace = workspace
        self._profiles = [profile for profile in profiles if not profile.get("system_table")]
        self._catalog_feedback = [item for item in (catalog_feedback or []) if str(item.get("content") or "").strip()]
        self._validator = validator or SqlReadOnlyValidator()
        self._known_tables = [str(profile.get("table")) for profile in profiles if profile.get("table")]

    def seed(self, files: list[Any]) -> dict[str, Any]:
        return {
            "files": [
                {
                    "filename": getattr(file, "filename", None),
                    "bytes": getattr(file, "bytes", None),
                }
                for file in files[:8]
            ],
            "table_count": len(self._profiles),
            "table_inventory": [self._table_summary(profile) for profile in self._profiles[:8]],
            "catalog_summary": self._catalog_summary(),
            "tool_policy": {
                "max_tool_calls": int(env("ANALITRICS_SQL_TOOL_MAX_CALLS", "8")),
                "sample_rows_limit": 5,
                "preview_rows_limit": 5,
                "catalog_search_limit": 5,
                "read_only": True,
                "known_tables_only": True,
                "table_inventory": "use table_inventory first; call list_tables only if more tables are needed",
                "business_catalog": "call search_catalog, resolve_business_term, or get_business_rules when business definitions are needed",
            },
        }

    def run(self, action: str, args: dict[str, Any]) -> dict[str, Any]:
        if action == "list_tables":
            return {"tables": [self._table_summary(profile) for profile in self._profiles[:20]]}
        if action == "describe_table":
            return self._describe_table(str(args.get("table") or ""))
        if action == "find_compatible_tables":
            return self.find_compatible_tables(str(args.get("table") or "") or None)
        if action == "sample_rows":
            return self._sample_rows(str(args.get("table") or ""), self._int(args.get("limit"), 3, 1, 5))
        if action == "preview_sql":
            return self._preview_sql(str(args.get("sql") or ""))
        if action == "search_catalog":
            return self._search_catalog(str(args.get("query") or ""), self._int(args.get("limit"), 5, 1, 10))
        if action == "resolve_business_term":
            return self._resolve_business_term(str(args.get("term") or ""))
        if action == "get_business_rules":
            return self._get_business_rules()
        raise RuntimeError(f"Unsupported SQL exploration action: {action}")

    def _catalog_summary(self) -> dict[str, Any]:
        by_step: dict[str, int] = {}
        sources: set[str] = set()
        for item in self._catalog_feedback:
            by_step[str(item.get("step") or "unknown")] = by_step.get(str(item.get("step") or "unknown"), 0) + 1
            if item.get("source_filename"):
                sources.add(str(item.get("source_filename")))
        return {
            "available": bool(self._catalog_feedback),
            "entry_count": len(self._catalog_feedback),
            "sources": sorted(sources)[:8],
            "entries_by_step": by_step,
        }

    def _search_catalog(self, query: str, limit: int) -> dict[str, Any]:
        normalized_query = self._normalize(query)
        terms = [term for term in normalized_query.split() if len(term) > 2]
        scored: list[tuple[int, dict[str, Any]]] = []
        for item in self._catalog_feedback:
            haystack = self._normalize(
                " ".join(
                    str(value or "")
                    for value in [
                        item.get("label"),
                        item.get("content"),
                        item.get("source_filename"),
                        self._step_label(item.get("step")),
                    ]
                )
            )
            score = sum(1 for term in terms if term in haystack)
            if normalized_query and normalized_query in haystack:
                score += 3
            if score > 0:
                scored.append((score, item))
        scored.sort(key=lambda row: row[0], reverse=True)
        return {
            "query": query,
            "matches": [self._catalog_entry(item, score) for score, item in scored[:limit]],
        }

    def _resolve_business_term(self, term: str) -> dict[str, Any]:
        result = self._search_catalog(term, 8)
        matches = result.get("matches") or []
        return {
            "term": term,
            "resolved": bool(matches),
            "definitions": matches,
            "instruction": "Use matching definitions as priority business context. If no match exists, do not invent definitions.",
        }

    def _get_business_rules(self) -> dict[str, Any]:
        rules = [
            self._catalog_entry(item)
            for item in self._catalog_feedback
            if int(item.get("step") or 0) == 4
        ]
        return {
            "rules": rules[:12],
            "rule_count": len(rules),
        }

    def _catalog_entry(self, item: dict[str, Any], score: int | None = None) -> dict[str, Any]:
        entry = {
            "source_file_id": item.get("source_file_id"),
            "source_filename": item.get("source_filename"),
            "step": item.get("step"),
            "step_label": self._step_label(item.get("step")),
            "label": item.get("label"),
            "content": self._trim_text(item.get("content"), 900),
            "updated_at": item.get("updated_at"),
        }
        if score is not None:
            entry["score"] = score
        return entry

    def _step_label(self, step: Any) -> str:
        labels = {
            1: "conceptos de negocio",
            2: "indicadores o métricas",
            3: "dimensiones",
            4: "reglas de negocio",
            5: "correcciones",
            6: "definiciones aprobadas",
        }
        try:
            return labels.get(int(step), "catálogo enriquecido")
        except (TypeError, ValueError):
            return "catálogo enriquecido"

    def _normalize(self, value: str) -> str:
        text = unicodedata.normalize("NFKD", value or "")
        text = "".join(char for char in text if not unicodedata.combining(char))
        text = re.sub(r"\s+", " ", text.lower()).strip()
        return text

    def find_compatible_tables(self, table: str | None = None) -> dict[str, Any]:
        groups: list[dict[str, Any]] = []
        profiles = self._profiles
        if table:
            base = self._profile_for_table(table)
            base_columns = self._column_names(base)
            candidates = []
            for profile in profiles:
                shared = sorted(base_columns.intersection(self._column_names(profile)))
                compatibility = len(shared) / max(1, len(base_columns))
                if compatibility >= 0.6:
                    candidates.append(
                        {
                            **self._table_summary(profile),
                            "shared_columns": shared[:16],
                            "compatibility": round(compatibility, 2),
                        }
                    )
            return {"base_table": table, "compatible_tables": candidates[:12]}

        buckets: dict[tuple[str, ...], list[dict[str, Any]]] = {}
        for profile in profiles:
            key = tuple(sorted(self._column_names(profile)))
            buckets.setdefault(key, []).append(profile)
        for columns, bucket in buckets.items():
            if len(bucket) < 2:
                continue
            groups.append(
                {
                    "shared_columns": list(columns)[:16],
                    "tables": [self._table_summary(profile) for profile in bucket[:8]],
                }
            )
        return {"compatible_groups": groups[:8]}

    def _table_summary(self, profile: dict[str, Any]) -> dict[str, Any]:
        columns = profile.get("columns") or []
        return {
            "table": profile.get("table"),
            "source_filename": profile.get("source_filename"),
            "row_count": profile.get("row_count"),
            "column_count": len(columns),
        }

    def _describe_table(self, table: str) -> dict[str, Any]:
        profile = self._profile_for_table(table)
        columns = []
        for column in profile.get("columns") or []:
            if not isinstance(column, dict):
                continue
            sample_values = column.get("sample_values") or column.get("examples") or []
            columns.append(
                {
                    "name": column.get("name"),
                    "type": column.get("type"),
                    "distinct_count": column.get("distinct_count"),
                    "sample_values": sample_values[:1] if isinstance(sample_values, list) else [],
                }
            )
        return {**self._table_summary(profile), "columns": columns}

    def _sample_rows(self, table: str, limit: int) -> dict[str, Any]:
        self._profile_for_table(table)
        rows = self._workspace.connection.execute(f'select * from "{table}" limit {limit}').fetchdf()
        return {
            "table": table,
            "limit": limit,
            "rows": json.loads(rows.to_json(orient="records", date_format="iso")),
        }

    def _preview_sql(self, sql: str) -> dict[str, Any]:
        compact_sql = " ".join(sql.strip().rstrip(";").split())
        self._validator.validate(compact_sql, self._known_tables)
        rows = self._workspace.connection.execute(f"select * from ({compact_sql}) as analitrics_preview limit 5").fetchdf()
        return {
            "valid": True,
            "row_count_preview": len(rows),
            "columns": list(rows.columns),
            "rows": json.loads(rows.to_json(orient="records", date_format="iso")),
        }

    def _profile_for_table(self, table: str) -> dict[str, Any]:
        for profile in self._profiles:
            if profile.get("table") == table:
                return profile
        raise RuntimeError(f"Unknown table requested: {table}")

    def _column_names(self, profile: dict[str, Any]) -> set[str]:
        return {
            str(column.get("name"))
            for column in profile.get("columns") or []
            if isinstance(column, dict) and column.get("name")
        }

    def _int(self, value: Any, default: int, minimum: int, maximum: int) -> int:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            parsed = default
        return max(minimum, min(maximum, parsed))

    def _trim_text(self, value: Any, limit: int) -> str:
        text = str(value or "").strip()
        return text if len(text) <= limit else text[:limit].rstrip() + "..."


class ToolAssistedSqlGenerator:
    def __init__(
        self,
        llm_client: JsonLlmClient,
        context_compactor: AnalyticalContextPromptCompactor | None = None,
        validator: SqlReadOnlyValidator | None = None,
    ) -> None:
        self._llm_client = llm_client
        self._context_compactor = context_compactor or AnalyticalContextPromptCompactor()
        self._validator = validator or SqlReadOnlyValidator()
        self._max_tool_calls = int(env("ANALITRICS_SQL_TOOL_MAX_CALLS", "8"))

    def generate(
        self,
        question: str,
        files: list[Any],
        profiles: list[dict[str, Any]],
        context_messages: list[dict[str, Any]] | None = None,
        catalog_feedback: list[dict[str, Any]] | None = None,
        analytical_context: dict[str, Any] | None = None,
        workspace: Any | None = None,
        progress: Callable[[str], None] | None = None,
    ) -> SqlGenerationResult:
        if workspace is None:
            raise RuntimeError("Tool-assisted SQL generation requires an initialized DuckDB workspace")
        tools = SqlExplorationTools(workspace, profiles, catalog_feedback, self._validator)
        tool_results: list[dict[str, Any]] = self._seed_tool_results_from_cache(analytical_context or {})
        consolidation_requested = self._consolidation_requested(question, analytical_context or {})
        final_sql_failures = 0
        for step in range(self._max_tool_calls + 1):
            action = self._next_action(
                question=question,
                seed=tools.seed(files),
                analytical_context=analytical_context or {},
                tool_results=tool_results,
                force_final=step >= self._max_tool_calls,
            )
            action_name = str(action.get("action") or "").strip()
            if action_name == "final_sql":
                args = action.get("args") if isinstance(action.get("args"), dict) else {}
                sql = str(action.get("sql") or args.get("sql") or "").strip()
                rationale = self._trim_text(action.get("rationale"), 240)
                data_strategy = action.get("data_strategy") if isinstance(action.get("data_strategy"), dict) else {}
                if not sql:
                    tool_results.append(
                        {
                            "step": step + 1,
                            "action": "final_sql",
                            "args": {},
                            "error": "final_sql was returned without sql. Return final_sql with sql populated.",
                        }
                    )
                    continue
                try:
                    self._validate_data_strategy(
                        sql=sql,
                        data_strategy=data_strategy,
                        tools=tools,
                        tool_results=tool_results,
                        consolidation_requested=consolidation_requested,
                    )
                    tools.run("preview_sql", {"sql": sql})
                except Exception as exc:
                    final_sql_failures += 1
                    if step >= self._max_tool_calls:
                        raise
                    tool_results.append(
                        {
                            "step": step + 1,
                            "action": "final_sql",
                            "args": {"sql": sql},
                            "error": f"Final SQL failed validation/preview: {exc}",
                        }
                    )
                    if progress is not None:
                        progress("La consulta final necesita ajuste; devuelvo el error al generador SQL.")
                    if final_sql_failures >= 2:
                        raise RuntimeError(f"Final SQL failed validation twice; stopping to avoid excessive LLM/tool retries: {exc}") from exc
                    continue
                return SqlGenerationResult(
                    sql=sql,
                    rationale=rationale,
                    backend="llm-tools",
                    data_strategy={
                        **self._compact_data_strategy(data_strategy),
                        "semantic_cache": self._semantic_cache(data_strategy, tool_results),
                    },
                )
            if step >= self._max_tool_calls:
                raise RuntimeError(f"Tool-assisted SQL generation exceeded {self._max_tool_calls} tool calls")
            args = action.get("args") if isinstance(action.get("args"), dict) else {}
            if progress is not None:
                progress(self._progress_message(action_name, args, step + 1))
            try:
                result = tools.run(action_name, args)
                tool_results.append(
                    {
                        "step": step + 1,
                        "action": action_name,
                        "args": args,
                        "result": self._compact_tool_result(action_name, result),
                    }
                )
            except Exception as exc:
                tool_results.append(
                    {
                        "step": step + 1,
                        "action": action_name,
                        "args": args,
                        "error": str(exc),
                    }
                )
        raise RuntimeError("Tool-assisted SQL generation did not produce final_sql")

    def _seed_tool_results_from_cache(self, analytical_context: dict[str, Any]) -> list[dict[str, Any]]:
        cache = analytical_context.get("semantic_cache")
        if not isinstance(cache, dict):
            return []
        seeded: list[dict[str, Any]] = []
        compatible_groups = cache.get("compatible_groups")
        if isinstance(compatible_groups, list) and compatible_groups:
            seeded.append(
                {
                    "step": 0,
                    "action": "find_compatible_tables",
                    "args": {"source": "semantic_cache"},
                    "result": {"compatible_groups": compatible_groups[:4]},
                    "cached": True,
                }
            )
        for table in (cache.get("described_tables") or [])[:4] if isinstance(cache.get("described_tables"), list) else []:
            if not isinstance(table, dict) or not table.get("table"):
                continue
            seeded.append(
                {
                    "step": 0,
                    "action": "describe_table",
                    "args": {"table": table.get("table"), "source": "semantic_cache"},
                    "result": table,
                    "cached": True,
                }
            )
        for term in (cache.get("catalog_terms") or [])[:4] if isinstance(cache.get("catalog_terms"), list) else []:
            if not isinstance(term, dict):
                continue
            seeded.append(
                {
                    "step": 0,
                    "action": "resolve_business_term",
                    "args": {"source": "semantic_cache"},
                    "result": term,
                    "cached": True,
                }
            )
        return seeded[:8]

    def repair(
        self,
        question: str,
        files: list[Any],
        profiles: list[dict[str, Any]],
        failed_sql: str,
        error: str,
        context_messages: list[dict[str, Any]] | None = None,
        catalog_feedback: list[dict[str, Any]] | None = None,
        analytical_context: dict[str, Any] | None = None,
        workspace: Any | None = None,
        progress: Callable[[str], None] | None = None,
    ) -> SqlGenerationResult:
        repair_context = {
            **(analytical_context or {}),
            "failed_sql": failed_sql,
            "validation_error": error,
        }
        return self.generate(
            question=f"{question}\n\nRepara esta consulta fallida manteniendo la intención: {failed_sql}\nError: {error}",
            files=files,
            profiles=profiles,
            context_messages=context_messages,
            catalog_feedback=catalog_feedback,
            analytical_context=repair_context,
            workspace=workspace,
            progress=progress,
        )

    def _next_action(
        self,
        question: str,
        seed: dict[str, Any],
        analytical_context: dict[str, Any],
        tool_results: list[dict[str, Any]],
        force_final: bool,
    ) -> dict[str, Any]:
        payload = {
            "question": question,
            "available_data_seed": seed,
            "analytical_context": self._context_compactor.for_sql_tools(analytical_context),
            "tool_results": tool_results[-self._max_tool_calls :],
            "force_final_sql": force_final,
        }
        return self._llm_client.complete_json(
            system=TOOL_ASSISTED_SQL_SYSTEM_PROMPT,
            payload=payload,
            model_env="ANALITRICS_NL_SQL_MODEL",
            default_model=env("ANALITRICS_DEFAULT_MODEL", "gpt-5.5"),
        )

    def _validate_data_strategy(
        self,
        sql: str,
        data_strategy: dict[str, Any],
        tools: SqlExplorationTools,
        tool_results: list[dict[str, Any]],
        consolidation_requested: bool,
    ) -> None:
        used_tables = self._used_tables(sql)
        mode = str(data_strategy.get("mode") or "").strip()
        if mode not in {"single_table", "union_compatible_tables", "join_tables", "cannot_combine"}:
            if len(used_tables) <= 1:
                mode = "single_table"
            elif re.search(r"\bunion\b", sql, flags=re.IGNORECASE):
                mode = "union_compatible_tables"
            else:
                mode = "join_tables"
            data_strategy["mode"] = mode
            data_strategy["reason"] = self._trim_text(
                data_strategy.get("reason") or "Modo técnico inferido desde el SQL porque el modelo omitió data_strategy.mode.",
                180,
            )
        declared_used = {str(value) for value in data_strategy.get("tables_used") or [] if value}
        if declared_used and declared_used != used_tables:
            data_strategy["tables_used_declared"] = sorted(declared_used)
            data_strategy["tables_used_corrected"] = True
        data_strategy["tables_used"] = sorted(used_tables)
        if len(used_tables) > 1 and mode == "single_table":
            raise RuntimeError("data_strategy.mode=single_table but SQL uses multiple tables")
        if not consolidation_requested:
            return
        if not self._has_action(tool_results, "find_compatible_tables"):
            raise RuntimeError("The user requested consolidated/historical data; call find_compatible_tables before final_sql")
        compatible_groups = tools.find_compatible_tables().get("compatible_groups") or []
        compatible_sets = [
            {str(table.get("table")) for table in group.get("tables") or [] if table.get("table")}
            for group in compatible_groups
        ]
        relevant_groups = [group for group in compatible_sets if len(group.intersection(used_tables)) == 1 and len(group) > 1]
        if relevant_groups and len(used_tables) == 1 and mode != "cannot_combine":
            raise RuntimeError(
                "The user requested consolidated/historical data and compatible tables exist, but final SQL uses one table. "
                "Use union_compatible_tables/join_tables or return cannot_combine with a verifiable reason."
            )
        if mode == "cannot_combine" and not str(data_strategy.get("reason") or "").strip():
            raise RuntimeError("cannot_combine requires data_strategy.reason")

    def _compact_data_strategy(self, data_strategy: dict[str, Any]) -> dict[str, Any]:
        compacted: dict[str, Any] = {
            "mode": data_strategy.get("mode"),
            "tables_used": data_strategy.get("tables_used") or [],
            "reason": self._trim_text(data_strategy.get("reason"), 180),
        }
        tables_considered = data_strategy.get("tables_considered")
        if isinstance(tables_considered, list) and tables_considered:
            compacted["tables_considered"] = [str(value) for value in tables_considered if value][:8]
        if data_strategy.get("tables_used_corrected"):
            compacted["tables_used_corrected"] = True
        declared = data_strategy.get("tables_used_declared")
        if isinstance(declared, list) and declared:
            compacted["tables_used_declared"] = [str(value) for value in declared if value][:8]
        return compacted

    def _semantic_cache(self, data_strategy: dict[str, Any], tool_results: list[dict[str, Any]]) -> dict[str, Any]:
        compatible_groups: list[dict[str, Any]] = []
        described_tables: list[dict[str, Any]] = []
        catalog_terms: list[dict[str, Any]] = []
        for item in tool_results:
            action = item.get("action")
            result = item.get("result")
            if not isinstance(result, dict):
                continue
            if action == "find_compatible_tables":
                groups = result.get("compatible_groups") or []
                if groups:
                    compatible_groups.extend(groups[:4])
                compatible = result.get("compatible_tables") or []
                if compatible:
                    compatible_groups.append(
                        {
                            "shared_columns": compatible[0].get("shared_columns") or [],
                            "tables": compatible[:8],
                        }
                    )
            elif action == "describe_table":
                described_tables.append(result)
            elif action == "resolve_business_term":
                catalog_terms.append(result)
            elif action == "search_catalog":
                catalog_terms.append({"term": result.get("query"), "resolved": bool(result.get("matches")), "definitions": result.get("matches") or []})
        return {
            "data_strategy": {
                "mode": data_strategy.get("mode"),
                "tables_used": data_strategy.get("tables_used") or [],
                "reason": self._trim_text(data_strategy.get("reason"), 180),
            },
            "compatible_groups": compatible_groups[:4],
            "described_tables": described_tables[:6],
            "catalog_terms": catalog_terms[:8],
        }

    def _trim_text(self, value: Any, limit: int) -> str:
        text = str(value or "").strip()
        return text if len(text) <= limit else text[:limit].rstrip() + "..."

    def _used_tables(self, sql: str) -> set[str]:
        expressions = sqlglot.parse(sql, read="duckdb")
        cte_names = {
            str(cte.alias)
            for expression in expressions
            for cte in expression.find_all(exp.CTE)
            if cte.alias
        }
        return {
            table.name
            for expression in expressions
            for table in expression.find_all(exp.Table)
            if table.name not in cte_names
        }

    def _has_successful_preview(self, tool_results: list[dict[str, Any]]) -> bool:
        for item in reversed(tool_results):
            if item.get("action") != "preview_sql":
                continue
            result = item.get("result")
            if isinstance(result, dict) and result.get("valid"):
                return True
        return False

    def _has_action(self, tool_results: list[dict[str, Any]], action: str) -> bool:
        return any(item.get("action") == action and not item.get("error") for item in tool_results)

    def _consolidation_requested(self, question: str, analytical_context: dict[str, Any]) -> bool:
        text = " ".join(
            str(value or "")
            for value in [
                question,
                (analytical_context.get("conversation_plan") or {}).get("effective_question"),
                (analytical_context.get("conversation_plan") or {}).get("reason"),
            ]
        ).lower()
        terms = (
            "consolida",
            "consolidado",
            "consolidada",
            "base histórica",
            "base historica",
            "histórica",
            "historica",
            "todos los archivos",
            "archivos cargados",
            "como una sola base",
            "periodo completo",
            "período completo",
        )
        return any(term in text for term in terms)

    def _compact_tool_result(self, action: str, result: dict[str, Any]) -> dict[str, Any]:
        if action == "list_tables":
            return {
                "table_count": len(result.get("tables") or []),
                "tables": (result.get("tables") or [])[:12],
            }
        if action == "describe_table":
            return {
                "table": result.get("table"),
                "source_filename": result.get("source_filename"),
                "row_count": result.get("row_count"),
                "columns": (result.get("columns") or [])[:24],
            }
        if action in {"sample_rows", "preview_sql"}:
            return {
                **{key: value for key, value in result.items() if key != "rows"},
                "rows": (result.get("rows") or [])[:3],
            }
        if action == "find_compatible_tables":
            return {
                "base_table": result.get("base_table"),
                "compatible_tables": (result.get("compatible_tables") or [])[:8],
                "compatible_groups": (result.get("compatible_groups") or [])[:6],
            }
        if action == "search_catalog":
            return {
                "query": result.get("query"),
                "matches": (result.get("matches") or [])[:5],
            }
        if action == "resolve_business_term":
            return {
                "term": result.get("term"),
                "resolved": result.get("resolved"),
                "definitions": (result.get("definitions") or [])[:5],
                "instruction": result.get("instruction"),
            }
        if action == "get_business_rules":
            return {
                "rule_count": result.get("rule_count"),
                "rules": (result.get("rules") or [])[:8],
            }
        return result

    def _progress_message(self, action: str, args: dict[str, Any], step: int) -> str:
        table = args.get("table")
        query = args.get("query") or args.get("term")
        if action == "list_tables":
            return f"Explorando tablas disponibles ({step}/{self._max_tool_calls})."
        if action == "describe_table" and table:
            return f"Revisando columnas de {table} ({step}/{self._max_tool_calls})."
        if action == "find_compatible_tables":
            return f"Buscando tablas compatibles para consolidar datos ({step}/{self._max_tool_calls})."
        if action == "search_catalog":
            suffix = f": {query}" if query else ""
            return f"Buscando definiciones de negocio en el catálogo{suffix} ({step}/{self._max_tool_calls})."
        if action == "resolve_business_term":
            suffix = f": {query}" if query else ""
            return f"Resolviendo término de negocio{suffix} ({step}/{self._max_tool_calls})."
        if action == "get_business_rules":
            return f"Consultando reglas de negocio activas ({step}/{self._max_tool_calls})."
        if action == "sample_rows" and table:
            return f"Inspeccionando una muestra de {table} ({step}/{self._max_tool_calls})."
        if action == "preview_sql":
            return f"Validando una consulta preliminar ({step}/{self._max_tool_calls})."
        return f"Ejecutando herramienta analítica {action} ({step}/{self._max_tool_calls})."


class VannaSqlGenerator:
    def __init__(self) -> None:
        raise RuntimeError(
            "ANALITRICS_SQL_GENERATOR=vanna is reserved but not enabled yet. "
            "Vanna 2.x must be validated against the Analitrics DuckDB workspace before becoming the SQL backend."
        )


class SqlGeneratorFactory:
    @staticmethod
    def create(llm_client: JsonLlmClient, schema_context_builder: SchemaContextBuilder) -> SqlGenerator:
        backend = env("ANALITRICS_SQL_GENERATOR", "llm-tools").strip().lower()
        if backend in {"llm-tools", "tools", "tool-assisted"}:
            return ToolAssistedSqlGenerator(llm_client)
        if backend == "llm":
            return LlmSqlGenerator(llm_client, schema_context_builder)
        if backend == "vanna":
            return VannaSqlGenerator()
        raise RuntimeError(f"Unsupported ANALITRICS_SQL_GENERATOR={backend!r}")
