import importlib
from types import SimpleNamespace
from unittest.mock import Mock

import psycopg
import pytest

from bank_churn_mlops import db
from bank_churn_mlops.config import settings

app_module = importlib.import_module("bank_churn_mlops.service.app")


def test_prediction_is_logged_once_with_processing_time(
    client, prediction_request, monkeypatch
):
    method, body, expected_status, expected_features = prediction_request
    monkeypatch.setattr(settings, "database_url", None)
    now = [100.0]
    monkeypatch.setattr(app_module, "time", SimpleNamespace(perf_counter=lambda: now[0]))
    save_prediction = db.save_prediction
    calls = []

    def record_prediction(*args):
        calls.append(args)
        now[0] += 10.0  # Time spent in DB work must not appear in latency_ms.
        save_prediction(*args)

    def request_body():
        now[0] += 0.025  # Body reading, before validation/inference, must count.
        yield body

    monkeypatch.setattr(db, "save_prediction", record_prediction)
    response = client.request(
        method,
        "/v1/predict",
        content=request_body(),
        headers={"Content-Type": "application/json"},
    )

    assert response.status_code == expected_status
    assert len(calls) == 1
    request_id, features, score, version, latency_ms, status_code = calls[0]
    assert features == expected_features
    assert version == "1.0.0"
    assert status_code == response.status_code
    assert latency_ms == pytest.approx(25.0)
    if expected_status == 200:
        result = response.json()
        assert request_id == result["request_id"]
        assert score == result["score"]
        assert latency_ms == result["latency_ms"]
    else:
        assert score is None
        if expected_status == 400:
            assert response.json() == {"detail": "There was an error parsing the body"}
        elif expected_status == 422:
            assert isinstance(response.json()["detail"], list)
        elif expected_status == 405:
            assert response.headers["allow"] == "POST"
        elif expected_status == 500:
            assert response.text == "Internal Server Error"


@pytest.mark.parametrize("database_url", [None, "postgresql://unused"])
def test_prediction_survives_disabled_or_unavailable_database(
    client, good_row, monkeypatch, database_url
):
    monkeypatch.setattr(settings, "database_url", database_url)
    connect = Mock(side_effect=psycopg.OperationalError("Test database is unavailable"))
    monkeypatch.setattr(db.psycopg, "connect", connect)

    response = client.post("/v1/predict", json=good_row)

    assert response.status_code == 200
    assert 0.0 <= response.json()["score"] <= 1.0
    assert connect.call_count == (0 if database_url is None else 1)


def test_other_routes_do_not_create_prediction_logs(client, monkeypatch):
    save_prediction = Mock(wraps=db.save_prediction)
    monkeypatch.setattr(db, "save_prediction", save_prediction)

    for path in ["/health", "/ready", "/docs"]:
        assert client.get(path).status_code == 200

    save_prediction.assert_not_called()
