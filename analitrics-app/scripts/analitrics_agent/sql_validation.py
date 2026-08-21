from __future__ import annotations

import sqlglot
from sqlglot import exp

from nl_sql_file import validate_select_sql


class SqlReadOnlyValidator:
    def validate(self, sql: str, known_tables: list[str]) -> None:
        validate_select_sql(sql)
        self._validate_known_tables(sql, known_tables)

    def _validate_known_tables(self, sql: str, known_tables: list[str]) -> None:
        allowed = set(known_tables)
        expressions = sqlglot.parse(sql, read="duckdb")
        used_tables = {table.name for expression in expressions for table in expression.find_all(exp.Table)}
        unknown = sorted(table for table in used_tables if table not in allowed)
        if unknown:
            raise RuntimeError(f"SQL references unavailable tables: {unknown}. Available tables: {sorted(allowed)}")
