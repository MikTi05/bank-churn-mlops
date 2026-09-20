"""PostgreSQL persistence for prediction request logs."""

import logging

import psycopg
from psycopg.types.json import Json

from bank_churn_mlops.config import settings

logger = logging.getLogger(__name__)

DDL = """
CREATE TABLE IF NOT EXISTS predictions (
    request_id uuid PRIMARY KEY,
    ts timestamptz NOT NULL DEFAULT now(),
    model_version text NOT NULL,
    features jsonb NOT NULL,
    score double precision,
    latency_ms real,
    status_code integer NOT NULL
)
"""


def init() -> None:
    """Create the predictions table when database logging is configured."""
    if not settings.database_url:
        return

    try:
        with psycopg.connect(settings.database_url) as connection:
            connection.execute("SELECT pg_advisory_xact_lock(7001)")
            connection.execute(DDL)
    except psycopg.Error:
        logger.exception("Failed to initialize the predictions table")


def save_prediction(
    request_id: str,
    features: dict,
    score: float | None,
    model_version: str,
    latency_ms: float | None,
    status_code: int,
) -> None:
    """Insert one request log without exposing database credentials in logs."""
    if not settings.database_url:
        return

    try:
        with psycopg.connect(settings.database_url) as connection:
            connection.execute(
                "INSERT INTO predictions "
                "(request_id, model_version, features, score, latency_ms, status_code) "
                "VALUES (%s, %s, %s, %s, %s, %s)",
                (
                    request_id,
                    model_version,
                    Json(features),
                    score,
                    latency_ms,
                    status_code,
                ),
            )
    except psycopg.Error:
        logger.exception("Failed to save prediction request %s", request_id)

