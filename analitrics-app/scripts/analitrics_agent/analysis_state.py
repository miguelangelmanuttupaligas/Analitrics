from __future__ import annotations

import re
import unicodedata
from typing import Any

from .analytical_context import AnalyticalContextPromptCompactor
from .config import bool_env, env
from .llm_client import JsonLlmClient
from .prompts import ANALYSIS_STATE_SYSTEM_PROMPT
from .schema_context import SchemaContextBuilder

METRIC_ALIASES = (
    ("ingreso_total", ("ingreso", "ingresos", "venta", "ventas", "monto", "facturacion", "facturación")),
    ("alumnos_unicos", ("alumno", "alumnos", "estudiante", "estudiantes", "usuarios unicos", "usuarios únicos")),
    ("cantidad_registros", ("cantidad", "conteo", "numero", "número", "registros", "filas")),
    ("ticket_promedio", ("ticket promedio", "promedio", "media")),
)

INTENT_ALIASES = (
    ("ranking", ("top", "ranking", "mayores", "menores", "orden", "ordena")),
    ("comparison", ("compara", "comparar", "versus", "vs", "diferencia")),
    ("trend", ("tendencia", "evolucion", "evolución", "mensual", "anual", "semanal")),
    ("summary", ("total", "resumen", "cuanto", "cuánto", "cantidad")),
)

FILTER_PATTERNS = (
    r"\b20\d{2}\b",
    r"\benero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|octubre|noviembre|diciembre\b",
    r"\bsolo\s+[^,.]+",
)


class AnalysisTextNormalizer:
    def normalize(self, value: str) -> str:
        text = unicodedata.normalize("NFKD", value.lower())
        text = "".join(char for char in text if not unicodedata.combining(char))
        return re.sub(r"\s+", " ", text).strip()


class SqlDimensionExtractor:
    def extract(self, sql: str, profiles: list[dict[str, Any]]) -> list[str]:
        known_columns = self._known_columns(profiles)
        candidates = self._group_by_columns(sql)
        if not candidates:
            candidates = self._select_text_columns(sql, known_columns)
        return self._dedupe([candidate for candidate in candidates if candidate in known_columns])[:6]

    def _known_columns(self, profiles: list[dict[str, Any]]) -> set[str]:
        columns: set[str] = set()
        for profile in profiles:
            if profile.get("system_table"):
                continue
            for column in profile.get("columns") or []:
                if isinstance(column, dict) and column.get("name"):
                    columns.add(str(column["name"]))
        return columns

    def _group_by_columns(self, sql: str) -> list[str]:
        match = re.search(r"\bgroup\s+by\b(.+?)(\border\s+by\b|\blimit\b|$)", sql, flags=re.IGNORECASE | re.DOTALL)
        if not match:
            return []
        values = []
        for raw in match.group(1).split(","):
            token = raw.strip().strip('"')
            token = token.split(".")[-1].strip().strip('"')
            if re.match(r"^[a-zA-Z_][a-zA-Z0-9_]*$", token):
                values.append(token)
        return values

    def _select_text_columns(self, sql: str, known_columns: set[str]) -> list[str]:
        normalized_sql = sql.lower()
        return [column for column in known_columns if column.lower() in normalized_sql]

    def _dedupe(self, values: list[str]) -> list[str]:
        result: list[str] = []
        seen: set[str] = set()
        for value in values:
            if value in seen:
                continue
            result.append(value)
            seen.add(value)
        return result


class MetricExtractor:
    def __init__(self, normalizer: AnalysisTextNormalizer | None = None) -> None:
        self._normalizer = normalizer or AnalysisTextNormalizer()

    def extract(self, question: str, sql: str, profiles: list[dict[str, Any]]) -> str | None:
        sql_metric = self._aggregate_alias(sql)
        if sql_metric:
            return sql_metric
        normalized = self._normalizer.normalize(" ".join([question, sql]))
        for metric, aliases in METRIC_ALIASES:
            if any(self._normalizer.normalize(alias) in normalized for alias in aliases):
                return metric
        numeric_columns = self._numeric_columns(profiles)
        for column in numeric_columns:
            if column.lower() in sql.lower():
                return column
        return numeric_columns[0] if numeric_columns else None

    def _aggregate_alias(self, sql: str) -> str | None:
        match = re.search(
            r"\b(?:sum|count|avg|min|max)\s*\(.+?\)\s+as\s+\"?([a-zA-Z_][a-zA-Z0-9_]*)\"?",
            sql,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if not match:
            return None
        return match.group(1)

    def _numeric_columns(self, profiles: list[dict[str, Any]]) -> list[str]:
        columns: list[str] = []
        for profile in profiles:
            if profile.get("system_table"):
                continue
            for column in profile.get("columns") or []:
                if not isinstance(column, dict):
                    continue
                column_type = str(column.get("type") or "").lower()
                name = str(column.get("name") or "")
                if name and any(token in column_type for token in ("int", "double", "float", "decimal", "numeric", "bigint")):
                    columns.append(name)
        return columns


class IntentExtractor:
    def __init__(self, normalizer: AnalysisTextNormalizer | None = None) -> None:
        self._normalizer = normalizer or AnalysisTextNormalizer()

    def extract(self, question: str, sql: str, chart_spec: dict[str, Any] | None) -> str:
        normalized = self._normalizer.normalize(" ".join([question, sql]))
        if isinstance(chart_spec, dict) and chart_spec.get("chart_required"):
            return "visualization"
        for intent, aliases in INTENT_ALIASES:
            if any(self._normalizer.normalize(alias) in normalized for alias in aliases):
                return intent
        return "analysis"


class FilterExtractor:
    def __init__(self, normalizer: AnalysisTextNormalizer | None = None) -> None:
        self._normalizer = normalizer or AnalysisTextNormalizer()

    def extract(self, question: str, sql: str) -> list[str]:
        normalized = self._normalizer.normalize(" ".join([question, sql]))
        filters: list[str] = []
        for pattern in FILTER_PATTERNS:
            filters.extend(match.group(0).strip() for match in re.finditer(pattern, normalized))
        where_match = re.search(r"\bwhere\b(.+?)(\bgroup\s+by\b|\border\s+by\b|\blimit\b|$)", sql, flags=re.IGNORECASE | re.DOTALL)
        if where_match:
            filters.append(where_match.group(1).strip()[:500])
        return self._dedupe(filters)[:8]

    def _dedupe(self, values: list[str]) -> list[str]:
        result: list[str] = []
        seen: set[str] = set()
        for value in values:
            if value in seen:
                continue
            result.append(value)
            seen.add(value)
        return result


class DatasetStateBuilder:
    def build(self, files: list[Any], profiles: list[dict[str, Any]]) -> dict[str, Any]:
        data_profiles = [profile for profile in profiles if not profile.get("system_table")]
        return {
            "files": [
                {
                    "file_id": getattr(file, "file_id", None),
                    "filename": getattr(file, "filename", None),
                    "content_hash": getattr(file, "content_hash", None),
                }
                for file in files
            ],
            "tables": [
                {
                    "table": profile.get("table"),
                    "source_file_id": profile.get("source_file_id"),
                    "source_filename": profile.get("source_filename"),
                    "row_count": profile.get("row_count"),
                }
                for profile in data_profiles[:12]
            ],
            "primary_file": getattr(files[0], "filename", None) if files else None,
            "primary_table": data_profiles[0].get("table") if data_profiles else None,
        }


class AnswerSummarizer:
    def summarize(self, answer: str | None) -> str | None:
        if not answer:
            return None
        text = re.sub(r"\s+", " ", answer).strip()
        if len(text) <= 900:
            return text
        return text[:900].rstrip() + "..."


class AnalysisStateBuilder:
    def __init__(
        self,
        llm_client: JsonLlmClient | None = None,
        schema_context_builder: SchemaContextBuilder | None = None,
        intent_extractor: IntentExtractor | None = None,
        metric_extractor: MetricExtractor | None = None,
        dimension_extractor: SqlDimensionExtractor | None = None,
        filter_extractor: FilterExtractor | None = None,
        dataset_builder: DatasetStateBuilder | None = None,
        answer_summarizer: AnswerSummarizer | None = None,
    ) -> None:
        self._llm_client = llm_client
        self._schema_context_builder = schema_context_builder or SchemaContextBuilder()
        self._intent_extractor = intent_extractor or IntentExtractor()
        self._metric_extractor = metric_extractor or MetricExtractor()
        self._dimension_extractor = dimension_extractor or SqlDimensionExtractor()
        self._filter_extractor = filter_extractor or FilterExtractor()
        self._dataset_builder = dataset_builder or DatasetStateBuilder()
        self._answer_summarizer = answer_summarizer or AnswerSummarizer()
        self._context_compactor = AnalyticalContextPromptCompactor()

    def build(self, request: Any, state: dict[str, Any]) -> dict[str, Any] | None:
        sql = str(state.get("sql") or "").strip()
        files = state.get("files") or []
        profiles = state.get("profiles") or []
        chart_spec = state.get("chart_spec") if isinstance(state.get("chart_spec"), dict) else None
        question = str(state.get("question") or request.question or "")
        analytical_context = state.get("analytical_context") or {}
        conversation_plan = analytical_context.get("conversation_plan") or {}
        feedback_proposal = analytical_context.get("feedback_proposal")
        if not sql:
            if not isinstance(feedback_proposal, dict) or not feedback_proposal.get("content"):
                return None
            fallback_dataset = self._dataset_builder.build(files, profiles)
            analysis_state = {
                "message_id": request.message_id,
                "run_id": request.run_id,
                "question": question,
                "answer_summary": self._answer_summarizer.summarize(state.get("answer")),
                "intent": str(conversation_plan.get("request_kind") or "correction"),
                "metric": None,
                "dimensions": [],
                "filters": [],
                "dataset": fallback_dataset,
                "last_sql": "",
                "last_chart": chart_spec,
                "row_count": 0,
            }
            analysis_state["state"] = {
                "version": 1,
                "engine": state.get("engine") or "langgraph",
                "scope_reason": state.get("scope_reason"),
                "cache_path": state.get("cache_path"),
                "cache_hits": state.get("cache_hits"),
                "feedback_proposal": feedback_proposal,
                "semantic_summary": conversation_plan.get("reason"),
                "depends_on_state_id": conversation_plan.get("selected_analysis_state_id"),
                "confidence": conversation_plan.get("confidence"),
                "assumptions": [],
                "plan": state.get("plan") or {},
                "critic": state.get("critic") or {},
                "conversation_plan": conversation_plan,
            }
            return analysis_state
        semantic = (
            self._llm_semantic_state(request, state, question, sql, files, profiles, chart_spec)
            if bool_env("ANALITRICS_SYNC_ANALYSIS_STATE_LLM", False)
            else {}
        )
        fallback_dataset = self._dataset_builder.build(files, profiles)
        analysis_state = {
            "message_id": request.message_id,
            "run_id": request.run_id,
            "question": question,
            "answer_summary": self._answer_summarizer.summarize(state.get("answer")),
            "intent": semantic.get("intent") or self._intent_extractor.extract(question, sql, chart_spec),
            "metric": semantic.get("metric") or self._metric_extractor.extract(question, sql, profiles),
            "dimensions": self._list(semantic.get("dimensions")) or self._dimension_extractor.extract(sql, profiles),
            "filters": self._sanitize_filters(
                self._list(semantic.get("filters")) or self._filter_extractor.extract(question, sql),
                question,
                sql,
            ),
            "dataset": self._merge_dataset(fallback_dataset, semantic.get("dataset")),
            "last_sql": sql,
            "last_chart": chart_spec,
            "row_count": len(state.get("rows") or []),
        }
        analysis_state["state"] = {
            "version": 1,
            "engine": state.get("engine") or "langgraph",
            "scope_reason": state.get("scope_reason"),
            "cache_path": state.get("cache_path"),
            "cache_hits": state.get("cache_hits"),
            "feedback_proposal": (state.get("analytical_context") or {}).get("feedback_proposal"),
            "semantic_summary": semantic.get("semantic_summary"),
            "depends_on_state_id": semantic.get("depends_on_state_id"),
            "confidence": semantic.get("confidence"),
            "assumptions": self._list(semantic.get("assumptions"))[:8],
            "plan": state.get("plan") or {},
            "critic": state.get("critic") or {},
            "semantic_extractor": "llm" if semantic else "fast",
            "semantic_cache": self._semantic_cache(state),
        }
        return analysis_state

    def _llm_semantic_state(
        self,
        request: Any,
        state: dict[str, Any],
        question: str,
        sql: str,
        files: list[Any],
        profiles: list[dict[str, Any]],
        chart_spec: dict[str, Any] | None,
    ) -> dict[str, Any]:
        if self._llm_client is None:
            return {}
        try:
            result = self._llm_client.complete_json(
                system=ANALYSIS_STATE_SYSTEM_PROMPT,
                payload={
                    "question": question,
                    "original_question": getattr(request, "question", question),
                    "sql": sql,
                    "rows_preview": (state.get("rows") or [])[:20],
                    "answer": state.get("answer"),
                    "chart_spec": chart_spec,
                    "available_data": self._schema_context_builder.build(
                        files,
                        profiles,
                        state.get("catalog_feedback") or [],
                    ),
                    "analytical_context": self._context_compactor.for_sql_tools(state.get("analytical_context") or {}),
                },
                model_env="ANALITRICS_ANALYSIS_STATE_MODEL",
                default_model=env("ANALITRICS_DEFAULT_MODEL", "gpt-5.5"),
            )
        except Exception:
            return {}
        return result if isinstance(result, dict) else {}

    def _list(self, value: Any) -> list[Any]:
        return value if isinstance(value, list) else []

    def _sanitize_filters(self, filters: list[Any], question: str, sql: str) -> list[str]:
        sql_has_where = bool(re.search(r"\bwhere\b", sql, flags=re.IGNORECASE))
        normalized_question = self._normalize_for_filter_match(question)
        sanitized: list[str] = []
        for raw in filters:
            value = str(raw or "").strip()
            if not value:
                continue
            normalized_value = self._normalize_for_filter_match(value)
            if sql_has_where or re.search(rf"(^|\\W){re.escape(normalized_value)}($|\\W)", normalized_question):
                sanitized.append(value)
        return sanitized[:8]

    def _normalize_for_filter_match(self, value: str) -> str:
        return self._metric_extractor._normalizer.normalize(value)

    def _merge_dataset(self, fallback: dict[str, Any], semantic: Any) -> dict[str, Any]:
        if not isinstance(semantic, dict):
            return fallback
        merged = {**fallback, **{key: value for key, value in semantic.items() if value not in (None, "", [])}}
        merged.setdefault("files", fallback.get("files") or [])
        merged.setdefault("tables", fallback.get("tables") or [])
        merged.setdefault("primary_file", fallback.get("primary_file"))
        merged.setdefault("primary_table", fallback.get("primary_table"))
        return merged

    def _semantic_cache(self, state: dict[str, Any]) -> dict[str, Any]:
        plan = state.get("plan") or {}
        data_strategy = plan.get("data_strategy") if isinstance(plan, dict) else {}
        cache = {
            "data_strategy": data_strategy if isinstance(data_strategy, dict) else {},
        }
        embedded = cache["data_strategy"].get("semantic_cache") if isinstance(cache["data_strategy"], dict) else None
        if isinstance(embedded, dict):
            cache.update(embedded)
            cache["data_strategy"] = {
                key: value
                for key, value in cache["data_strategy"].items()
                if key != "semantic_cache"
            }
        return {key: value for key, value in cache.items() if value not in (None, [], {})}
