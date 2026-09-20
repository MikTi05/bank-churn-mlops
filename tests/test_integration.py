import os
import uuid

import psycopg
import pytest

DATABASE_URL = os.getenv("DATABASE_URL")

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not DATABASE_URL,
        reason="A test PostgreSQL database must be provided in DATABASE_URL",
    ),
]


def test_successful_prediction_is_logged(client, good_row):
    response = client.post("/v1/predict", json=good_row)
    body = response.json()

    with psycopg.connect(DATABASE_URL) as connection:
        row = connection.execute(
            "SELECT model_version, score, features->>'Geography', "
            "latency_ms, status_code "
            "FROM predictions WHERE request_id = %s",
            (body["request_id"],),
        ).fetchone()

    assert row is not None
    assert row[0] == body["model_version"]
    assert row[1] == pytest.approx(body["score"])
    assert row[2] == good_row["Geography"]
    assert row[3] == pytest.approx(body["latency_ms"])
    assert row[4] == 200


def test_validation_error_is_logged(client, good_row):
    log_probe = str(uuid.uuid4())
    invalid_row = {**good_row, "log_probe": log_probe}

    response = client.post("/v1/predict", json=invalid_row)

    assert response.status_code == 422
    with psycopg.connect(DATABASE_URL) as connection:
        row = connection.execute(
            "SELECT score, latency_ms, status_code "
            "FROM predictions WHERE features->>'log_probe' = %s "
            "ORDER BY ts DESC LIMIT 1",
            (log_probe,),
        ).fetchone()

    assert row is not None
    assert row[0] is None
    assert row[1] is None
    assert row[2] == 422

