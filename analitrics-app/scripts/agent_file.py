from __future__ import annotations

import argparse
import json
import tempfile
import warnings
from pathlib import Path
from typing import Any, Literal, TypedDict

warnings.filterwarnings("ignore", message=r"The default value of `allowed_objects`.*")

try:
    from langchain_core._api.deprecation import suppress_langchain_deprecation_warning
except Exception:  # pragma: no cover - best-effort compatibility with langchain internals
    suppress_langchain_deprecation_warning = None

if suppress_langchain_deprecation_warning is None:
    from langgraph.graph import END, StateGraph
else:
    with suppress_langchain_deprecation_warning():
        from langgraph.graph import END, StateGraph
from openai import OpenAI

from nl_sql_file import (
    FileMetadata,
    compose_answer,
    critique_answer,
    download_from_rustfs,
    env,
    generate_sql,
    load_file_into_duckdb,
    profile_tables,
    resolve_file,
    schema_prompt,
    validate_select_sql,
)


class AgentState(TypedDict, total=False):
    args: argparse.Namespace
    question: str
    metadata: FileMetadata
    local_path: str
    tables: list[str]
    profiles: list[dict[str, Any]]
    in_scope: bool
    scope_reason: str
    plan: dict[str, str]
    sql: str
    rows: list[dict[str, Any]]
    answer: str
    critic: dict[str, Any]
    chart_spec: dict[str, Any]
    error: str


RUNTIME: dict[str, Any] = {}


def llm_json(system: str, payload: dict[str, Any], model_env: str, default_model: str) -> dict[str, Any]:
    client = OpenAI(api_key=env("OPENAI_API_KEY"))
    model = env(model_env, env("ANALITRICS_NL_SQL_MODEL", default_model))
    response = client.chat.completions.create(
        model=model,
        temperature=0,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False, indent=2)},
        ],
    )
    return json.loads(response.choices[0].message.content or "{}")


def resolve_and_profile(state: AgentState) -> AgentState:
    args = state["args"]
    metadata = resolve_file(args)
    tmpdir = tempfile.TemporaryDirectory(prefix="analitrics-agent-")
    local_path = download_from_rustfs(metadata, Path(tmpdir.name))
    con, tables = load_file_into_duckdb(metadata, local_path)
    profiles = profile_tables(con, tables, args.sample_rows)
    RUNTIME["tmpdir"] = tmpdir
    RUNTIME["con"] = con
    return {
        **state,
        "metadata": metadata,
        "local_path": str(local_path),
        "tables": tables,
        "profiles": profiles,
    }


def check_question_scope(state: AgentState) -> AgentState:
    payload = {
        "question": state["question"],
        "available_data": json.loads(schema_prompt(state["metadata"], state["profiles"])),
    }
    result = llm_json(
        system=(
            "Clasifica si la pregunta del usuario puede responderse usando exclusivamente la data "
            "tabular disponible, su schema, profiling, diccionario o resultados derivados. "
            "Responde JSON con keys: in_scope(boolean), reason(string). "
            "Marca false para preguntas generales, programación, historia, consejos, opiniones o cualquier "
            "tema no relacionado con los archivos disponibles."
        ),
        payload=payload,
        model_env="ANALITRICS_SCOPE_MODEL",
        default_model="gpt-4.1-mini",
    )
    in_scope = bool(result.get("in_scope"))
    reason = str(result.get("reason") or "")
    if not in_scope:
        return {
            **state,
            "in_scope": False,
            "scope_reason": reason,
            "answer": "Solo puedo responder preguntas relacionadas con la data cargada en este chat.",
        }
    return {**state, "in_scope": True, "scope_reason": reason}


def route_after_scope(state: AgentState) -> Literal["generate_sql", "__end__"]:
    return "generate_sql" if state.get("in_scope") else "__end__"


def generate_sql_node(state: AgentState) -> AgentState:
    plan = generate_sql(state["question"], state["metadata"], state["profiles"])
    return {**state, "plan": plan, "sql": plan["sql"]}


def validate_sql_node(state: AgentState) -> AgentState:
    validate_select_sql(state["sql"])
    return state


def execute_sql_node(state: AgentState) -> AgentState:
    con = RUNTIME["con"]
    rows_df = con.execute(state["sql"]).fetchdf()
    rows = json.loads(rows_df.to_json(orient="records", date_format="iso"))
    return {**state, "rows": rows}


def compose_answer_node(state: AgentState) -> AgentState:
    answer = compose_answer(state["question"], state["sql"], state["rows"])
    return {**state, "answer": answer}


def critique_answer_node(state: AgentState) -> AgentState:
    critic = critique_answer(state["question"], state["sql"], state["rows"], state["answer"])
    answer = critic.get("revised_answer") if critic.get("approved") is False else state["answer"]
    return {**state, "critic": critic, "answer": str(answer or state["answer"])}


def generate_chart_spec_node(state: AgentState) -> AgentState:
    rows = state.get("rows") or []
    if not rows:
        return {**state, "chart_spec": {"chart_required": False, "reason": "No hay filas para graficar."}}
    result = llm_json(
        system=(
            "Decide si los resultados deben tener gráfico. Si aplica, genera una especificación Vega-Lite "
            "minimalista y válida. Responde JSON con keys: chart_required(boolean), reason(string), spec(object|null). "
            "No inventes columnas; usa solo columnas presentes en rows."
        ),
        payload={
            "question": state["question"],
            "rows_preview": rows[:50],
            "columns": list(rows[0].keys()) if rows else [],
        },
        model_env="ANALITRICS_CHART_MODEL",
        default_model="gpt-4.1-mini",
    )
    return {**state, "chart_spec": result}


def cleanup_runtime() -> None:
    con = RUNTIME.pop("con", None)
    if con is not None:
        con.close()
    tmpdir = RUNTIME.pop("tmpdir", None)
    if tmpdir is not None:
        tmpdir.cleanup()


def build_graph():
    graph = StateGraph(AgentState)
    graph.add_node("resolve_and_profile", resolve_and_profile)
    graph.add_node("check_question_scope", check_question_scope)
    graph.add_node("generate_sql", generate_sql_node)
    graph.add_node("validate_sql", validate_sql_node)
    graph.add_node("execute_sql", execute_sql_node)
    graph.add_node("compose_answer", compose_answer_node)
    graph.add_node("critique_answer", critique_answer_node)
    graph.add_node("generate_chart_spec", generate_chart_spec_node)

    graph.set_entry_point("resolve_and_profile")
    graph.add_edge("resolve_and_profile", "check_question_scope")
    graph.add_conditional_edges(
        "check_question_scope",
        route_after_scope,
        {"generate_sql": "generate_sql", "__end__": END},
    )
    graph.add_edge("generate_sql", "validate_sql")
    graph.add_edge("validate_sql", "execute_sql")
    graph.add_edge("execute_sql", "compose_answer")
    graph.add_edge("compose_answer", "critique_answer")
    graph.add_edge("critique_answer", "generate_chart_spec")
    graph.add_edge("generate_chart_spec", END)
    return graph.compile()


def run(args: argparse.Namespace) -> None:
    app = build_graph()
    try:
        result = app.invoke({"args": args, "question": args.question})
        metadata = result.get("metadata")
        output = {
            "agent": "langgraph-file-analyst",
            "in_scope": result.get("in_scope"),
            "scope_reason": result.get("scope_reason"),
            "file": metadata.__dict__ if metadata else None,
            "tables": result.get("profiles"),
            "plan": result.get("plan"),
            "sql": result.get("sql"),
            "row_count": len(result.get("rows") or []),
            "rows_preview": (result.get("rows") or [])[:20],
            "answer": result.get("answer"),
            "critic": result.get("critic"),
            "chart_spec": result.get("chart_spec"),
        }
        print(json.dumps(output, ensure_ascii=False, indent=2))
    finally:
        cleanup_runtime()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Analitrics LangGraph agent over LibreChat S3 files")
    parser.add_argument("--file-id")
    parser.add_argument("--filename")
    parser.add_argument("--tenant-id", default="analitrics")
    parser.add_argument("--question", required=True)
    parser.add_argument("--sample-rows", type=int, default=5)
    return parser.parse_args()


if __name__ == "__main__":
    run(parse_args())
