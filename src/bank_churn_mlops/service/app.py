"""HTTP API for serving the trained Bank Churn pipeline."""

import json
import logging
import time
import uuid
from contextlib import asynccontextmanager
from typing import Literal

import joblib
import pandas as pd
from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from fastapi.exception_handlers import (
    http_exception_handler,
    request_validation_exception_handler,
)
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute
from pydantic import BaseModel, Field
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import PlainTextResponse
from starlette.types import Receive, Scope, Send

from bank_churn_mlops import db
from bank_churn_mlops.config import settings

logger = logging.getLogger(__name__)


def request_log_features(body: bytes) -> dict:
    """Keep JSON inputs, falling back to text safe for PostgreSQL jsonb."""
    try:
        payload = json.loads(body)
        encoded = json.dumps(payload, ensure_ascii=False, allow_nan=False)
        encoded.encode("utf-8")
        if "\\u0000" in encoded:
            raise ValueError("PostgreSQL jsonb cannot store NUL characters")
    except (ValueError, RecursionError):
        return {"raw_body": body.decode("utf-8", errors="replace").replace("\x00", "\\u0000")}
    return payload if isinstance(payload, dict) else {"body": payload}


def request_latency_ms(request: Request) -> float:
    """Route entry to prediction/error creation; excludes sending and DB work."""
    return round((time.perf_counter() - request.state.started_at) * 1_000, 2)


class PredictionRoute(APIRoute):
    """Journal this route once, including failures before endpoint execution."""

    async def handle(self, scope: Scope, receive: Receive, send: Send) -> None:
        # Move the usual method check inside the timed handler to also log 405.
        await self.app(scope, receive, send)

    def get_route_handler(self):
        original_handler = super().get_route_handler()

        async def logged_handler(request: Request):
            request.state.started_at = time.perf_counter()
            request.state.request_id = str(uuid.uuid4())
            body = b""
            latency_ms = None
            try:
                try:
                    body = await request.body()
                    if self.methods and request.method not in self.methods:
                        raise StarletteHTTPException(
                            status_code=405, headers={"Allow": ", ".join(sorted(self.methods))}
                        )
                    response = await original_handler(request)
                except RequestValidationError as exc:
                    latency_ms = request_latency_ms(request)
                    response = await request_validation_exception_handler(request, exc)
                except StarletteHTTPException as exc:
                    latency_ms = request_latency_ms(request)
                    response = await http_exception_handler(request, exc)
            except Exception:
                latency_ms = request_latency_ms(request)
                logger.exception("Prediction request %s failed", request.state.request_id)
                response = PlainTextResponse("Internal Server Error", status_code=500)

            prediction = getattr(request.state, "prediction", None)
            score = None
            if response.status_code < 400 and prediction is not None:
                score = prediction.score
                latency_ms = prediction.latency_ms
            elif latency_ms is None:
                latency_ms = request_latency_ms(request)

            payload = getattr(request.state, "features", None)
            if payload is None:
                payload = request_log_features(body)
            background_tasks = BackgroundTasks()
            background_tasks.add_task(
                db.save_prediction,
                request.state.request_id,
                payload,
                score,
                getattr(request.app.state, "version", "unknown"),
                latency_ms,
                response.status_code,
            )
            if response.background is not None:
                background_tasks.add_task(response.background)
            response.background = background_tasks
            return response

        return logged_handler


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


def predict(features: Features, request: Request) -> Prediction:
    payload = features.model_dump()
    request.state.features = payload
    frame = pd.DataFrame([payload]).reindex(columns=app.state.meta["features"])

    score = float(app.state.pipeline.predict_proba(frame)[0, 1])
    churn = score >= app.state.meta["threshold"]
    prediction = Prediction(
        score=score,
        churn=churn,
        model_version=app.state.version,
        request_id=request.state.request_id,
        latency_ms=request_latency_ms(request),
    )
    request.state.prediction = prediction
    return prediction


app.router.add_api_route(
    "/v1/predict", predict, methods=["POST"], route_class_override=PredictionRoute
)
