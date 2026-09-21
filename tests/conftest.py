import json
import uuid

import pytest
from fastapi.testclient import TestClient

from bank_churn_mlops.service.app import app


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture()
def good_row():
    return {
        "CreditScore": 619,
        "Geography": "France",
        "Gender": "Female",
        "Age": 42,
        "Tenure": 2,
        "Balance": 0.0,
        "NumOfProducts": 1,
        "HasCrCard": 1,
        "IsActiveMember": 1,
        "EstimatedSalary": 101_348.88,
    }


@pytest.fixture(
    params=[
        "success",
        "validation",
        "malformed_json",
        "invalid_encoding",
        "inference_error",
        "method_not_allowed",
        "non_object",
        "nul_character",
    ]
)
def prediction_request(request, client, good_row, monkeypatch):
    """Real HTTP inputs shared by route tests and PostgreSQL integration tests."""
    method = "POST"
    payload = good_row.copy()
    status_code = 200
    if request.param == "validation":
        payload["log_probe"] = str(uuid.uuid4())
        status_code = 422
    elif request.param == "inference_error":
        def fail_inference(frame):
            raise RuntimeError("Injected inference failure")

        monkeypatch.setattr(client.app.state.pipeline, "predict_proba", fail_inference)
        status_code = 500
    elif request.param == "method_not_allowed":
        method = "GET"
        status_code = 405
    elif request.param == "non_object":
        payload = [good_row]
        status_code = 422
    elif request.param == "nul_character":
        payload["log_probe"] = "\x00"
        status_code = 422

    body = json.dumps(payload).encode("utf-8")
    expected_features = payload if isinstance(payload, dict) else {"body": payload}
    if request.param == "malformed_json":
        body = b'{"Age":'
        status_code = 422
    elif request.param == "invalid_encoding":
        body = b'{"Age":"\xff"}'
        status_code = 400
    if request.param in {"malformed_json", "invalid_encoding", "nul_character"}:
        expected_features = {"raw_body": body.decode("utf-8", errors="replace")}

    return method, body, status_code, expected_features
