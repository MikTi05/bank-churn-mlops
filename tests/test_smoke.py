def test_valid_request_returns_prediction(client, good_row):
    response = client.post("/v1/predict", json=good_row)

    assert response.status_code == 200
    body = response.json()
    assert 0.0 <= body["score"] <= 1.0
    assert isinstance(body["score"], float)
    assert isinstance(body["churn"], bool)
    assert isinstance(body["model_version"], str)
    assert isinstance(body["request_id"], str)
    assert isinstance(body["latency_ms"], float)
    assert body["latency_ms"] >= 0.0


def test_identical_requests_have_identical_predictions(client, good_row):
    first = client.post("/v1/predict", json=good_row)
    second = client.post("/v1/predict", json=good_row)

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["score"] == second.json()["score"]
    assert first.json()["churn"] == second.json()["churn"]

