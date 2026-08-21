from __future__ import annotations

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool


config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = None


def database_url() -> str:
    host = os.getenv("ANALITRICS_POSTGRES_HOST", "control-postgres")
    port = os.getenv("ANALITRICS_POSTGRES_PORT", "5432")
    db = os.getenv("ANALITRICS_POSTGRES_DB", "analitrics")
    user = os.getenv("ANALITRICS_POSTGRES_ADMIN_USER") or os.getenv("ANALITRICS_POSTGRES_USER", "analitrics")
    password = os.getenv("ANALITRICS_POSTGRES_ADMIN_PASSWORD") or os.getenv("ANALITRICS_POSTGRES_PASSWORD")
    if not password:
        raise RuntimeError("Missing required environment variable: ANALITRICS_POSTGRES_PASSWORD")
    return f"postgresql+psycopg://{user}:{password}@{host}:{port}/{db}"


def run_migrations_offline() -> None:
    context.configure(url=database_url(), target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    section = config.get_section(config.config_ini_section, {})
    section["sqlalchemy.url"] = database_url()
    connectable = engine_from_config(section, prefix="sqlalchemy.", poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
