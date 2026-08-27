from __future__ import annotations

import argparse
import json
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import boto3
import duckdb
import pandas as pd
import sqlglot
from sqlglot import exp
from bson import ObjectId
from openai import OpenAI
from pymongo import MongoClient


TABULAR_TYPES = {
    "text/csv",
    "application/csv",
    "application/vnd.ms-excel",
    "application/msexcel",
    "application/x-msexcel",
    "application/x-ms-excel",
    "application/x-excel",
    "application/x-dos_ms_excel",
    "application/xls",
    "application/x-xls",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.oasis.opendocument.spreadsheet",
}

FORBIDDEN_SQL_TERMS = re.compile(
    r"\b("
    r"insert|update|delete|create|drop|alter|truncate|merge|replace|copy|attach|detach|install|load|pragma|"
    r"set|call|vacuum|export|import|grant|revoke|read_csv|read_json|read_parquet|glob|sqlite_scan|"
    r"postgres_scan|mysql_scan"
    r")\b",
    re.I,
)

CODE_BLOCK_RE = re.compile(r"```.*?```", re.S)
VISUAL_CODE_LINE_RE = re.compile(
    r"^\s*(import\s+|from\s+\w+\s+import|plt\.|fig\s*=|ax\s*=|cursos\s*=|ingresos\s*=|matplotlib|seaborn|plotly)",
    re.I,
)
MARKDOWN_TABLE_SEPARATOR_RE = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?\s*$")


@dataclass
class FileMetadata:
    file_id: str
    filename: str
    source: str
    storage_key: str
    mime_type: str
    bytes: int
    tenant_id: str


def env(name: str, default: str | None = None) -> str:
    value = os.getenv(name, default)
    if value is None or value == "":
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def normalize_identifier(value: str, fallback: str) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9_]+", "_", value.strip().lower()).strip("_")
    if not normalized:
        normalized = fallback
    if normalized[0].isdigit():
        normalized = f"_{normalized}"
    return normalized[:60]


def unique_names(values: list[str]) -> list[str]:
    seen: dict[str, int] = {}
    names: list[str] = []
    for index, value in enumerate(values):
        base = normalize_identifier(str(value), f"col_{index + 1}")
        count = seen.get(base, 0)
        seen[base] = count + 1
        names.append(base if count == 0 else f"{base}_{count + 1}")
    return names


def connect_mongo() -> MongoClient:
    return MongoClient(env("MONGO_URI", "mongodb://mongodb:27017/LibreChat"))


def owner_query_values(user_id: str) -> list[Any]:
    values: list[Any] = [user_id]
    try:
        values.append(ObjectId(user_id))
    except Exception:
        pass
    return values


def validate_storage_key_owner(storage_key: str, tenant_id: str, user_id: str | None) -> None:
    if not user_id:
        raise RuntimeError("Analitrics requires userId to resolve S3 files")

    expected_prefix = f"t/{tenant_id}/uploads/{user_id}/"
    normalized = storage_key.lstrip("/")
    if not normalized.startswith(expected_prefix):
        raise RuntimeError(
            "File storageKey does not match the authenticated tenant/user path "
            f"(expected prefix: {expected_prefix})"
        )


def safe_child_path(base: Path, filename: str, fallback: str) -> Path:
    base_resolved = base.resolve()
    safe_name = Path(filename).name
    if not safe_name or safe_name in {".", ".."}:
        safe_name = fallback

    target = (base_resolved / safe_name).resolve()
    if not target.is_relative_to(base_resolved):
        raise RuntimeError(f"Unsafe download path rejected: {target}")
    return target


def resolve_file(args: argparse.Namespace, database: Any | None = None) -> FileMetadata:
    mongo = None if database is not None else connect_mongo()
    db_name = env("MONGO_DB", "LibreChat")
    query: dict[str, Any] = {"tenantId": args.tenant_id, "source": "s3"}
    user_id = getattr(args, "user_id", None)
    if user_id:
        query["user"] = {"$in": owner_query_values(str(user_id))}
    if args.file_id:
        query["file_id"] = args.file_id
    elif args.filename:
        query["filename"] = args.filename
    else:
        raise RuntimeError("Provide --file-id or --filename")

    db = database if database is not None else mongo[db_name]
    doc = db.files.find_one(query, sort=[("createdAt", -1)])
    if not doc:
        raise RuntimeError(f"No S3 file metadata found for query: {query}")

    mime_type = doc.get("type") or ""
    filename = doc.get("filename") or ""
    extension = Path(filename).suffix.lower()
    if mime_type not in TABULAR_TYPES and extension not in {".csv", ".xls", ".xlsx", ".ods"}:
        raise RuntimeError(f"File is not a supported tabular file: {filename} ({mime_type})")

    storage_key = doc.get("storageKey")
    if not storage_key:
        raise RuntimeError(f"File {doc.get('file_id')} has no storageKey")
    validate_storage_key_owner(str(storage_key), str(doc.get("tenantId") or args.tenant_id), str(user_id) if user_id else None)

    return FileMetadata(
        file_id=str(doc["file_id"]),
        filename=filename,
        source=str(doc.get("source")),
        storage_key=str(storage_key),
        mime_type=mime_type,
        bytes=int(doc.get("bytes") or 0),
        tenant_id=str(doc.get("tenantId") or args.tenant_id),
    )


def download_from_rustfs(metadata: FileMetadata, target_dir: Path) -> Path:
    endpoint = env("AWS_ENDPOINT_URL", "http://storage-rustfs:9000")
    bucket = env("AWS_BUCKET_NAME", "librechat")
    client = boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=env("AWS_ACCESS_KEY_ID"),
        aws_secret_access_key=env("AWS_SECRET_ACCESS_KEY"),
        region_name=env("AWS_REGION", "us-east-1"),
    )
    target_dir.mkdir(parents=True, exist_ok=True)
    local_path = safe_child_path(target_dir, metadata.filename, metadata.file_id)
    client.download_file(bucket, metadata.storage_key, str(local_path))
    return local_path


def load_csv(con: duckdb.DuckDBPyConnection, path: Path, filename: str) -> list[str]:
    table = normalize_identifier(Path(filename).stem, "csv_data")
    con.execute(
        f'create or replace table "{table}" as select * from read_csv_auto(?, header=true)',
        [str(path)],
    )
    return [table]


def load_workbook(con: duckdb.DuckDBPyConnection, path: Path) -> list[str]:
    excel = pd.ExcelFile(path, engine="openpyxl")
    tables: list[str] = []
    workbook_name = normalize_identifier(path.stem, "workbook")
    for index, sheet_name in enumerate(excel.sheet_names):
        df = excel.parse(sheet_name=sheet_name, dtype=object)
        df.columns = unique_names([str(col) for col in df.columns])
        table = normalize_identifier(f"{workbook_name}_{sheet_name}", f"sheet_{index + 1}")
        con.register("_df", df)
        con.execute(f'create or replace table "{table}" as select * from _df')
        con.unregister("_df")
        tables.append(table)
    return tables


def profile_tables(con: duckdb.DuckDBPyConnection, tables: list[str], sample_rows: int) -> list[dict[str, Any]]:
    profiles: list[dict[str, Any]] = []
    numeric_type_hints = ("decimal", "double", "float", "real", "numeric", "int", "bigint", "smallint", "tinyint", "hugeint")
    for table in tables:
        columns = con.execute(f'describe "{table}"').fetchall()
        row_count = con.execute(f'select count(*) from "{table}"').fetchone()[0]
        sample = con.execute(f'select * from "{table}" limit ?', [sample_rows]).fetchdf()
        column_profiles: list[dict[str, Any]] = []
        for row in columns:
            column_name = str(row[0])
            column_type = str(row[1])
            quoted = column_name.replace('"', '""')
            null_count = con.execute(f'select count(*) from "{table}" where "{quoted}" is null').fetchone()[0]
            try:
                distinct_count = con.execute(f'select approx_count_distinct("{quoted}") from "{table}"').fetchone()[0]
            except Exception:
                distinct_count = None
            sample_values = con.execute(
                f'select distinct "{quoted}" from "{table}" where "{quoted}" is not null limit ?',
                [min(sample_rows, 5)],
            ).fetchdf()
            column_profile = {
                "name": column_name,
                "type": column_type,
                "null_count": int(null_count or 0),
                "null_ratio": float(null_count / row_count) if row_count else 0.0,
                "distinct_count": int(distinct_count) if distinct_count is not None else None,
                "sample_values": json.loads(sample_values.to_json(orient="records", date_format="iso")),
            }
            if any(hint in column_type.lower() for hint in numeric_type_hints):
                try:
                    stats = con.execute(
                        f'''
                        select
                            min("{quoted}")::double as min_value,
                            max("{quoted}")::double as max_value,
                            avg("{quoted}")::double as avg_value,
                            sum("{quoted}")::double as sum_value
                        from "{table}"
                        where "{quoted}" is not null
                        '''
                    ).fetchone()
                    column_profile.update(
                        {
                            "min": float(stats[0]) if stats and stats[0] is not None else None,
                            "max": float(stats[1]) if stats and stats[1] is not None else None,
                            "avg": float(stats[2]) if stats and stats[2] is not None else None,
                            "sum": float(stats[3]) if stats and stats[3] is not None else None,
                        }
                    )
                except Exception:
                    pass
            column_profiles.append(column_profile)
        profiles.append(
            {
                "table": table,
                "row_count": row_count,
                "columns": column_profiles,
                "sample": json.loads(sample.to_json(orient="records", date_format="iso")),
            }
        )
    return profiles


def load_file_into_duckdb(metadata: FileMetadata, path: Path) -> tuple[duckdb.DuckDBPyConnection, list[str]]:
    con = duckdb.connect(database=":memory:")
    extension = path.suffix.lower()
    if extension == ".csv" or metadata.mime_type in {"text/csv", "application/csv"}:
        tables = load_csv(con, path, metadata.filename)
    else:
        tables = load_workbook(con, path)
    return con, tables


def schema_prompt(metadata: FileMetadata, profiles: list[dict[str, Any]]) -> str:
    compact_profiles = [
        {
            "table": profile["table"],
            "row_count": profile["row_count"],
            "columns": profile["columns"],
            "sample": profile["sample"][:3],
        }
        for profile in profiles
    ]
    return json.dumps(
        {
            "file": {
                "file_id": metadata.file_id,
                "filename": metadata.filename,
                "tenantId": metadata.tenant_id,
                "mimeType": metadata.mime_type,
            },
            "duckdb_schema": compact_profiles,
        },
        ensure_ascii=False,
        indent=2,
    )


def generate_sql(question: str, metadata: FileMetadata, profiles: list[dict[str, Any]]) -> dict[str, str]:
    client = OpenAI(api_key=env("OPENAI_API_KEY"))
    model = env("ANALITRICS_NL_SQL_MODEL", "gpt-4.1-mini")
    response = client.chat.completions.create(
        model=model,
        temperature=0,
        response_format={"type": "json_object"},
        messages=[
            {
                "role": "system",
                "content": (
                    "Eres un analista de datos. Genera SQL DuckDB de solo lectura para responder "
                    "la pregunta del usuario. Responde JSON con keys: sql, rationale. "
                    "No uses INSERT, UPDATE, DELETE, CREATE, DROP, COPY, ATTACH, INSTALL, LOAD ni llamadas externas."
                ),
            },
            {
                "role": "user",
                "content": f"Schema disponible:\n{schema_prompt(metadata, profiles)}\n\nPregunta:\n{question}",
            },
        ],
    )
    content = response.choices[0].message.content or "{}"
    parsed = json.loads(content)
    return {"sql": str(parsed.get("sql", "")), "rationale": str(parsed.get("rationale", ""))}


def validate_select_sql(sql: str) -> None:
    candidate = sql.strip()
    if not candidate:
        raise RuntimeError("Generated SQL is empty")

    candidate = candidate.rstrip(";").strip()
    if ";" in candidate:
        raise RuntimeError("Only one SQL statement is allowed")

    if FORBIDDEN_SQL_TERMS.search(candidate):
        raise RuntimeError("SQL contains forbidden read/write or filesystem operation")

    expressions = sqlglot.parse(candidate, read="duckdb")
    if len(expressions) != 1:
        raise RuntimeError("Only one SQL statement is allowed")

    expression = expressions[0]
    if not isinstance(expression, (exp.Select, exp.Union)):
        raise RuntimeError(f"Only SELECT/WITH queries are allowed, got: {expression.key}")


def compose_answer(question: str, sql: str, rows: list[dict[str, Any]], prefer_chart: bool = False) -> str:
    client = OpenAI(api_key=env("OPENAI_API_KEY"))
    model = env("ANALITRICS_ANSWER_MODEL", env("ANALITRICS_NL_SQL_MODEL", "gpt-4.1-mini"))
    chart_instruction = (
        "La respuesta tendrá un gráfico interactivo con los mismos datos. "
        "No incluyas tablas markdown, rankings extensos ni listas fila por fila; el gráfico prevalece. "
        "Redacta solo 1 o 2 frases con la lectura gerencial principal."
        if prefer_chart
        else "Si el usuario pide tabla, puedes usar una tabla markdown breve."
    )
    response = client.chat.completions.create(
        model=model,
        temperature=0,
        messages=[
            {
                "role": "system",
                "content": (
                    "Redacta una respuesta breve en español basada solo en los resultados entregados. "
                    "No escribas código, pseudocódigo, Python, matplotlib, Mermaid, SQL adicional ni instrucciones "
                    "para construir gráficos. Si la pregunta pide un gráfico, responde solo el análisis textual; "
                    "el gráfico será renderizado por otro componente. "
                    + chart_instruction
                ),
            },
            {
                "role": "user",
                "content": json.dumps(
                    {"question": question, "sql": sql, "rows": rows[:50]},
                    ensure_ascii=False,
                    indent=2,
                ),
            },
        ],
    )
    return sanitize_answer_text(response.choices[0].message.content or "", remove_tables=prefer_chart)


def critique_answer(
    question: str,
    sql: str,
    rows: list[dict[str, Any]],
    answer: str,
    prefer_chart: bool = False,
) -> dict[str, Any]:
    client = OpenAI(api_key=env("OPENAI_API_KEY"))
    model = env("ANALITRICS_CRITIC_MODEL", env("ANALITRICS_NL_SQL_MODEL", "gpt-4.1-mini"))
    chart_instruction = (
        "Si habrá gráfico interactivo, no agregues tablas markdown, rankings extensos ni listas fila por fila. "
        "Deja solo una lectura ejecutiva breve."
        if prefer_chart
        else ""
    )
    response = client.chat.completions.create(
        model=model,
        temperature=0,
        response_format={"type": "json_object"},
        messages=[
            {
                "role": "system",
                "content": (
                    "Revisa si la respuesta contesta la pregunta usando el SQL y los resultados. "
                    "No agregues código, pseudocódigo, Python, matplotlib, Mermaid, SQL adicional ni instrucciones "
                    "para construir gráficos. Si revisas una solicitud con gráfico, deja solo análisis textual. "
                    + chart_instruction
                    + " "
                    "Responde JSON con keys: approved(boolean), issues(array), revised_answer(string)."
                ),
            },
            {
                "role": "user",
                "content": json.dumps(
                    {"question": question, "sql": sql, "rows": rows[:50], "answer": answer},
                    ensure_ascii=False,
                    indent=2,
                ),
            },
        ],
    )
    parsed = json.loads(response.choices[0].message.content or "{}")
    if parsed.get("revised_answer"):
        parsed["revised_answer"] = sanitize_answer_text(str(parsed["revised_answer"]), remove_tables=prefer_chart)
    return parsed


def sanitize_answer_text(answer: str, remove_tables: bool = False) -> str:
    without_blocks = CODE_BLOCK_RE.sub("", answer)
    lines = [
        line
        for line in without_blocks.splitlines()
        if not VISUAL_CODE_LINE_RE.search(line)
    ]
    cleaned = "\n".join(lines).strip()
    if remove_tables:
        cleaned = strip_markdown_tables(cleaned)
    return cleaned.strip()


def strip_markdown_tables(answer: str) -> str:
    lines = answer.splitlines()
    output: list[str] = []
    index = 0
    while index < len(lines):
        next_line = lines[index + 1] if index + 1 < len(lines) else ""
        if "|" in lines[index] and MARKDOWN_TABLE_SEPARATOR_RE.match(next_line):
            index += 2
            while index < len(lines) and "|" in lines[index]:
                index += 1
            continue
        output.append(lines[index])
        index += 1
    return "\n".join(output)


def run(args: argparse.Namespace) -> None:
    metadata = resolve_file(args)
    with tempfile.TemporaryDirectory(prefix="analitrics-file-") as tmp:
        local_path = download_from_rustfs(metadata, Path(tmp))
        con, tables = load_file_into_duckdb(metadata, local_path)
        profiles = profile_tables(con, tables, args.sample_rows)

        if args.mode == "profile":
            print(json.dumps({"file": metadata.__dict__, "tables": profiles}, ensure_ascii=False, indent=2))
            return

        plan = generate_sql(args.question, metadata, profiles)
        sql = plan["sql"]
        validate_select_sql(sql)
        rows_df = con.execute(sql).fetchdf()
        rows = json.loads(rows_df.to_json(orient="records", date_format="iso"))
        answer = compose_answer(args.question, sql, rows)
        critic = critique_answer(args.question, sql, rows, answer)
        final_answer = critic.get("revised_answer") if critic.get("approved") is False else answer
        print(
            json.dumps(
                {
                    "file": metadata.__dict__,
                    "plan": plan,
                    "sql": sql,
                    "row_count": len(rows),
                    "rows_preview": rows[:20],
                    "answer": final_answer,
                    "critic": critic,
                },
                ensure_ascii=False,
                indent=2,
            )
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Analitrics NL-SQL over a LibreChat S3 file")
    parser.add_argument("--mode", choices=["profile", "nl-sql"], default="profile")
    parser.add_argument("--file-id")
    parser.add_argument("--filename")
    parser.add_argument("--tenant-id", default="analitrics")
    parser.add_argument("--question")
    parser.add_argument("--sample-rows", type=int, default=5)
    args = parser.parse_args()
    if args.mode == "nl-sql" and not args.question:
        parser.error("--question is required when --mode nl-sql")
    return args


if __name__ == "__main__":
    run(parse_args())
