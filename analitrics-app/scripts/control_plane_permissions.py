from __future__ import annotations

import os

import psycopg
from psycopg import sql


def env(name: str, default: str | None = None) -> str:
    value = os.getenv(name, default)
    if value is None or value == "":
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def admin_connection() -> psycopg.Connection:
    admin_user = os.getenv("ANALITRICS_POSTGRES_ADMIN_USER") or env("ANALITRICS_POSTGRES_USER", "analitrics")
    admin_password = os.getenv("ANALITRICS_POSTGRES_ADMIN_PASSWORD") or env("ANALITRICS_POSTGRES_PASSWORD")
    return psycopg.connect(
        host=env("ANALITRICS_POSTGRES_HOST", "control-postgres"),
        port=int(env("ANALITRICS_POSTGRES_PORT", "5432")),
        dbname=env("ANALITRICS_POSTGRES_DB", "analitrics"),
        user=admin_user,
        password=admin_password,
        autocommit=True,
    )


def main() -> None:
    runtime_user = env("ANALITRICS_POSTGRES_USER", "analitrics_runtime")
    runtime_password = env("ANALITRICS_POSTGRES_PASSWORD")
    with admin_connection() as con:
        exists = con.execute("select 1 from pg_roles where rolname = %s", (runtime_user,)).fetchone()
        if exists:
            con.execute(
                sql.SQL("alter role {} with login password {} nocreatedb nocreaterole noinherit").format(
                    sql.Identifier(runtime_user),
                    sql.Literal(runtime_password),
                )
            )
        else:
            con.execute(
                sql.SQL("create role {} with login password {} nocreatedb nocreaterole noinherit").format(
                    sql.Identifier(runtime_user),
                    sql.Literal(runtime_password),
                )
            )
        con.execute(sql.SQL("grant connect on database {} to {}").format(sql.Identifier(env("ANALITRICS_POSTGRES_DB", "analitrics")), sql.Identifier(runtime_user)))
        con.execute(sql.SQL("grant usage on schema public to {}").format(sql.Identifier(runtime_user)))
        con.execute(sql.SQL("revoke create on schema public from {}").format(sql.Identifier(runtime_user)))
        con.execute(sql.SQL("grant select, insert, update, delete on all tables in schema public to {}").format(sql.Identifier(runtime_user)))
        con.execute(sql.SQL("grant usage, select on all sequences in schema public to {}").format(sql.Identifier(runtime_user)))
        con.execute(sql.SQL("alter default privileges in schema public grant select, insert, update, delete on tables to {}").format(sql.Identifier(runtime_user)))
        con.execute(sql.SQL("alter default privileges in schema public grant usage, select on sequences to {}").format(sql.Identifier(runtime_user)))
    print(f"runtime role ready: {runtime_user}")


if __name__ == "__main__":
    main()
