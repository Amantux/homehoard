"""Alembic environment for HomeHoard.

Runs the same on SQLite and Postgres. The database URL is taken from the value
the app injects on the Alembic config (``config.attributes["url"]``) when
migrations run at startup, and falls back to the app's resolved Config so the
bare ``alembic`` CLI works too. ``target_metadata`` is the app's full model
metadata, so ``--autogenerate`` diffs future migrations against the models.
"""
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

import app.models  # noqa: F401 - registers every table on db.metadata
from app import logging_setup
from app.config import Config
from app.extensions import db

config = context.config
if config.config_file_name is not None and not logging_setup.is_configured():
    # Only when the APP has not configured logging — i.e. the bare `alembic` CLI.
    #
    # disable_existing_loggers=False was not enough: fileConfig also REPLACES the
    # root logger's handlers with the ones from alembic.ini. Startup runs
    # migrations in-process, so it was detaching the app's stdout and file
    # handlers a moment after they were installed. Everything logged after boot
    # then went to Alembic's handler instead — which is why the per-process log
    # files contained the startup lines and nothing else, and the MCP tool-call
    # audit trail appeared to record nothing at all.
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = db.metadata


def _url() -> str:
    # Read from attributes (a plain dict) rather than get_main_option, which would
    # %-interpolate a URL-encoded password and crash. Falls back to the resolved
    # Config for the bare `alembic` CLI.
    return config.attributes.get("url") or Config.sqlalchemy_uri()


def run_migrations_offline() -> None:
    context.configure(
        url=_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    section = config.get_section(config.config_ini_section) or {}
    section["sqlalchemy.url"] = _url()
    connectable = engine_from_config(
        section, prefix="sqlalchemy.", poolclass=pool.NullPool
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
