def test_health_returns_200(client):
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "model_version": "1.0.0"}


def test_ready_returns_200_when_model_is_loaded(client):
    response = client.get("/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ready"}


def test_invalid_numeric_value_returns_422(client, good_row):
    response = client.post("/v1/predict", json={**good_row, "Age": 17})

    assert response.status_code == 422


def test_extra_field_returns_422(client, good_row):
    response = client.post(
        "/v1/predict",
        json={**good_row, "unexpected_field": "not allowed"},
    )

    assert response.status_code == 422


def test_missing_required_field_returns_422(client, good_row):
    row = dict(good_row)
    del row["Geography"]

    response = client.post("/v1/predict", json=row)

    assert response.status_code == 422

