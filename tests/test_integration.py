import os
from unittest.mock import Mock

import psycopg
import pytest

from bank_churn_mlops import db

DATABASE_URL = os.getenv("DATABASE_URL")

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not DATABASE_URL,
        reason="A test PostgreSQL database must be provided in DATABASE_URL",
    ),
]


def test_prediction_is_logged_once_in_postgres(client, prediction_request, monkeypatch):
    method, body, expected_status, expected_features = prediction_request
    # Spy on attempts while still executing the real PostgreSQL INSERT.
    save_prediction = Mock(wraps=db.save_prediction)
    monkeypatch.setattr(db, "save_prediction", save_prediction)

    try:
        response = client.request(
            method,
            "/v1/predict",
            content=body,
            headers={"Content-Type": "application/json"},
        )

        assert response.status_code == expected_status
        assert save_prediction.call_count == 1
        request_id = save_prediction.call_args.args[0]
        with psycopg.connect(DATABASE_URL) as connection:
            rows = connection.execute(
                "SELECT model_version, score, features, latency_ms, status_code "
                "FROM predictions WHERE request_id = %s",
                (request_id,),
            ).fetchall()

        assert len(rows) == 1
        version, score, features, latency_ms, status_code = rows[0]
        assert version == "1.0.0"
        assert features == expected_features
        assert isinstance(latency_ms, float)
        assert latency_ms >= 0.0
        assert status_code == response.status_code
        if expected_status == 200:
            result = response.json()
            assert request_id == result["request_id"]
            assert version == result["model_version"]
            assert score == pytest.approx(result["score"])
            assert latency_ms == pytest.approx(result["latency_ms"])
        else:
            assert score is None
    finally:
        request_ids = [call.args[0] for call in save_prediction.call_args_list]
        if request_ids:
            with psycopg.connect(DATABASE_URL) as connection:
                connection.execute(
                    "DELETE FROM predictions WHERE request_id = ANY(%s::uuid[])",
                    (request_ids,),
                )
