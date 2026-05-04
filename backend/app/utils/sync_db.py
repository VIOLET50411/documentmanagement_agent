"""Synchronous PostgreSQL connection context manager for Celery workers."""

from __future__ import annotations

import contextlib

import psycopg2

from app.config import settings


@contextlib.contextmanager
def sync_db():
    """Yield a synchronous psycopg2 connection that is auto-closed on exit.

    Usage::

        with sync_db() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
    """
    conn = psycopg2.connect(settings.postgres_dsn_sync)
    try:
        yield conn
    finally:
        conn.close()
