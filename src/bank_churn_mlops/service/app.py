"""HTTP API for serving the trained Bank Churn pipeline."""

import time
import uuid
from contextlib import asynccontextmanager
from typing import Literal

import joblib
import pandas as pd
from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, Field

from bank_churn_mlops import db
from bank_churn_mlops.config import settings


class Features(BaseModel):
    model_config = {"extra": "forbid"}

    CreditScore: int = Field(strict=True, ge=350, le=850)
    Geography: Literal["France", "Germany", "Spain"]
    Gender: Literal["Female", "Male"]
    Age: int = Field(strict=True, ge=18, le=92)
    Tenure: int = Field(strict=True, ge=0, le=10)
    Balance: float = Field(strict=True, ge=0.0, le=250_898.09)
    NumOfProducts: int = Field(strict=True, ge=1, le=4)
    HasCrCard: int = Field(strict=True, ge=0, le=1)
    IsActiveMember: int = Field(strict=True, ge=0, le=1)
    EstimatedSalary: float = Field(strict=True, ge=11.58, le=199_992.48)


class Prediction(BaseModel):
    score: float = Field(ge=0.0, le=1.0)
    churn: bool
    model_version: str
    request_id: str
    latency_ms: float = Field(ge=0.0)


@asynccontextmanager
async def lifespan(app: FastAPI):
    bundle = joblib.load(settings.model_path)
    app.state.pipeline = bundle["pipeline"]
    app.state.meta = bundle["metadata"]
    app.state.version = bundle["metadata"]["version"]
    db.init()
    yield
    app.state.pipeline = None


app = FastAPI(title="bank-churn-service", version="1.0", lifespan=lifespan)


@app.exception_handler(RequestValidationError)
async def log_validation_error(request: Request, exc: RequestValidationError):
    response = await request_validation_exception_handler(request, exc)
    if request.url.path == "/v1/predict":
        try:
            payload = await request.json()
        except ValueError:
            body = await request.body()
            payload = {"raw_body": body.decode("utf-8", errors="replace")}

        background_tasks = BackgroundTasks()
        background_tasks.add_task(
            db.save_prediction,
            str(uuid.uuid4()),
            payload,
            None,
            getattr(app.state, "version", "unknown"),
            None,
            422,
        )
        response.background = background_tasks
    return response


@app.get("/health")
def health():
    return {
        "status": "ok",
        "model_version": getattr(app.state, "version", "unknown"),
    }


@app.get("/ready")
def ready():
    if getattr(app.state, "pipeline", None) is None:
        raise HTTPException(status_code=503, detail="Model not loaded")
    return {"status": "ready"}


@app.post("/v1/predict")
def predict(features: Features, background_tasks: BackgroundTasks) -> Prediction:
    started_at = time.perf_counter()
    request_id = str(uuid.uuid4())
    payload = features.model_dump()
    frame = pd.DataFrame([payload]).reindex(columns=app.state.meta["features"])

    score = float(app.state.pipeline.predict_proba(frame)[0, 1])
    churn = score >= app.state.meta["threshold"]
    latency_ms = round((time.perf_counter() - started_at) * 1_000, 2)

    background_tasks.add_task(
        db.save_prediction,
        request_id,
        payload,
        score,
        app.state.version,
        latency_ms,
        200,
    )

    return Prediction(
        score=score,
        churn=churn,
        model_version=app.state.version,
        request_id=request_id,
        latency_ms=latency_ms,
    )
