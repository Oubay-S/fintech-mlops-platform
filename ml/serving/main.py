"""Production FastAPI application for the FinTech ML Serving microservice.

Implements:
- `POST /predict` (synchronous `def` executed in FastAPI worker threadpool)
- `GET /health/live` & `GET /health/ready` (plus deprecated aliases `/health` & `/ready`)
- `GET /model-info`
- `GET /viz/{method}` (reads from `VIZ_DATA_DIR`, capped at `VIZ_MAX_POINTS` = 2,000)
- `GET /metrics` (Prometheus exposition)
- Constant-time `X-Internal-Api-Key` verification (`secrets.compare_digest`), exempting probes & `/metrics`
- Unified `ErrorResponse` for 401, 404, 422 (`VALIDATION_FAILED` & `UNSUPPORTED_SCHEMA_VERSION`), 500, 503 (`MODEL_NOT_READY`)
- Structured JSON request logging (never logs raw feature payloads or secrets)
- Route-template Prometheus HTTP metrics (no raw path cardinality explosion)
"""
from __future__ import annotations

import json
import logging
import secrets
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, PlainTextResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.routing import Match

from .config import ServingSettings
from .metrics import (
    ML_HTTP_REQUEST_DURATION_SECONDS,
    ML_HTTP_REQUESTS_TOTAL,
    record_prediction_metrics,
)
from .model_loader import ModelRegistryHolder
from .predictor import ModelNotReadyError
from .schemas import (
    EmbeddingPoint,
    EmbeddingVizResponse,
    ErrorCode,
    ErrorResponse,
    HealthLiveResponse,
    HealthReadyResponse,
    ModelInfoResponse,
    PredictRequest,
    PredictResponse,
    VizMethod,
)

logger = logging.getLogger("ml.serving.app")

AUTH_EXEMPT_PATHS = frozenset(
    {
        "/health",
        "/health/live",
        "/health/ready",
        "/ready",
        "/metrics",
        "/openapi.json",
        "/docs",
        "/redoc",
    }
)


def _configure_logging(level_name: str) -> None:
    level = getattr(logging, level_name.upper(), logging.INFO)
    logging.basicConfig(level=level, format="%(message)s")


def _try_parse_uuid(raw: Any) -> UUID | None:
    if isinstance(raw, UUID):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            return UUID(raw.strip())
        except ValueError:
            return None
    return None


def _resolve_request_id(request: Request, body_dict: dict[str, Any] | None = None) -> UUID:
    """Resolve `request_id` in priority order: JSON body -> X-Request-ID -> X-Correlation-Id -> new UUID4."""
    if isinstance(body_dict, dict):
        from_body = _try_parse_uuid(body_dict.get("request_id"))
        if from_body is not None:
            request.state.request_id = from_body
            return from_body

    cached = getattr(request.state, "request_id", None)
    if isinstance(cached, UUID):
        return cached

    for header_name in ("X-Request-ID", "X-Correlation-Id"):
        from_header = _try_parse_uuid(request.headers.get(header_name))
        if from_header is not None:
            request.state.request_id = from_header
            return from_header

    generated = uuid4()
    request.state.request_id = generated
    return generated


def _resolve_route_template(request: Request) -> str:
    """Return the matched route template (e.g., `/viz/{method}`) to avoid raw-path metric cardinality."""
    for route in request.app.routes:
        match, _ = route.matches(request.scope)
        if match == Match.FULL and hasattr(route, "path"):
            return str(route.path)
    return "unmatched"


def _build_error_json_response(
    *,
    request: Request,
    code: ErrorCode,
    message: str,
    status_code: int,
    detail: list[dict[str, Any]] | None = None,
) -> JSONResponse:
    req_id = _resolve_request_id(request)
    err = ErrorResponse.build(
        code=code,
        message=message,
        request_id=req_id,
        status=status_code,
        detail=detail,
    )
    headers = {"X-Request-ID": str(req_id)}
    corr_header = request.headers.get("X-Correlation-Id")
    if corr_header:
        headers["X-Correlation-Id"] = corr_header
    return JSONResponse(
        status_code=status_code,
        content=err.model_dump(mode="json"),
        headers=headers,
    )


def create_app(
    settings: ServingSettings | None = None,
    holder: ModelRegistryHolder | None = None,
) -> FastAPI:
    """Application factory supporting dependency injection for unit and integration tests."""
    resolved_settings = settings or ServingSettings.from_env()
    _configure_logging(resolved_settings.log_level)
    resolved_holder = holder or ModelRegistryHolder(resolved_settings)

    @asynccontextmanager
    async def lifespan(app_instance: FastAPI) -> AsyncIterator[None]:
        app_instance.state.settings = resolved_settings
        app_instance.state.holder = resolved_holder
        resolved_holder.start_background_load()
        try:
            yield
        finally:
            resolved_holder.stop_background_load()

    app = FastAPI(
        title="FinTech ML Serving API",
        version="1.0.0",
        description=(
            "Real-time fraud classification, Mondrian split-conformal uncertainty quantification, "
            "model metadata, and embedding visualization service."
        ),
        lifespan=lifespan,
    )
    app.state.settings = resolved_settings
    app.state.holder = resolved_holder

    # -----------------------------------------------------------------------
    # Middleware: Request ID, Constant-Time API Key Auth, Metrics & JSON Logs
    # -----------------------------------------------------------------------
    @app.middleware("http")
    async def observability_and_security_middleware(
        request: Request, call_next: Any
    ) -> Response:
        start_ns = time.perf_counter_ns()
        req_id = _resolve_request_id(request)
        route_template = _resolve_route_template(request)

        # Enforce X-Internal-Api-Key when configured (exempting health probes and /metrics)
        current_settings: ServingSettings = request.app.state.settings
        expected_key = current_settings.internal_api_key
        if expected_key and request.url.path not in AUTH_EXEMPT_PATHS:
            supplied_key = request.headers.get("X-Internal-Api-Key", "")
            if not supplied_key or not secrets.compare_digest(
                supplied_key.encode("utf-8"), expected_key.encode("utf-8")
            ):
                response = _build_error_json_response(
                    request=request,
                    code=ErrorCode.UNAUTHORIZED,
                    message="Invalid or missing X-Internal-Api-Key header.",
                    status_code=401,
                )
                elapsed_s = (time.perf_counter_ns() - start_ns) / 1_000_000_000.0
                ML_HTTP_REQUESTS_TOTAL.labels(
                    method=request.method,
                    route=route_template,
                    status="401",
                ).inc()
                ML_HTTP_REQUEST_DURATION_SECONDS.labels(
                    method=request.method,
                    route=route_template,
                ).observe(elapsed_s)
                return response

        response = await call_next(request)

        elapsed_s = (time.perf_counter_ns() - start_ns) / 1_000_000_000.0
        elapsed_ms = elapsed_s * 1000.0

        # Ensure correlation headers are echoed on every response
        final_req_id = getattr(request.state, "request_id", req_id)
        response.headers["X-Request-ID"] = str(final_req_id)
        corr_id = request.headers.get("X-Correlation-Id")
        if corr_id:
            response.headers["X-Correlation-Id"] = corr_id

        ML_HTTP_REQUESTS_TOTAL.labels(
            method=request.method,
            route=route_template,
            status=str(response.status_code),
        ).inc()
        ML_HTTP_REQUEST_DURATION_SECONDS.labels(
            method=request.method,
            route=route_template,
        ).observe(elapsed_s)

        # Structured JSON log (never logs feature values or secrets)
        log_entry = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": "INFO" if response.status_code < 400 else "WARNING",
            "service": "ml-serving",
            "request_id": str(final_req_id),
            "method": request.method,
            "route": route_template,
            "status": response.status_code,
            "latency_ms": round(elapsed_ms, 3),
            "model_version": getattr(request.state, "model_version", None),
            "action": getattr(request.state, "prediction_action", None),
        }
        logger.info(json.dumps(log_entry))
        return response

    # -----------------------------------------------------------------------
    # Custom Exception Handlers (Unified ErrorResponse for 401, 404, 422, 500, 503)
    # -----------------------------------------------------------------------
    @app.exception_handler(ModelNotReadyError)
    async def handle_model_not_ready(
        request: Request, exc: ModelNotReadyError
    ) -> JSONResponse:
        return _build_error_json_response(
            request=request,
            code=ErrorCode.MODEL_NOT_READY,
            message=str(exc),
            status_code=503,
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        if isinstance(exc.body, dict):
            _resolve_request_id(request, exc.body)
        raw_errors = exc.errors()
        sanitized_details: list[dict[str, Any]] = []
        is_schema_version_error = False

        for err in raw_errors:
            loc_tuple = err.get("loc", ())
            loc_strs = [str(part) for part in loc_tuple]
            msg_str = str(err.get("msg", "Invalid value"))
            err_type = str(err.get("type", "value_error"))
            if "schema_version" in loc_strs or "Unsupported schema_version" in msg_str:
                is_schema_version_error = True
            sanitized_details.append(
                {
                    "loc": loc_strs,
                    "msg": msg_str,
                    "type": err_type,
                }
            )

        if is_schema_version_error:
            return _build_error_json_response(
                request=request,
                code=ErrorCode.UNSUPPORTED_SCHEMA_VERSION,
                message="Unsupported schema_version. Expected pattern '^1\\.[0-9]+$'.",
                status_code=422,
                detail=sanitized_details,
            )

        return _build_error_json_response(
            request=request,
            code=ErrorCode.VALIDATION_FAILED,
            message=f"Request validation failed on {len(sanitized_details)} field(s).",
            status_code=422,
            detail=sanitized_details,
        )

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_exception(
        request: Request, exc: StarletteHTTPException
    ) -> JSONResponse:
        status = exc.status_code
        if status == 401:
            code = ErrorCode.UNAUTHORIZED
        elif status == 404:
            code = ErrorCode.NOT_FOUND
        elif status == 503:
            code = ErrorCode.MODEL_NOT_READY
        elif status == 422:
            code = ErrorCode.VALIDATION_FAILED
        else:
            code = ErrorCode.INTERNAL_ERROR

        return _build_error_json_response(
            request=request,
            code=code,
            message=str(exc.detail),
            status_code=status,
        )

    @app.exception_handler(Exception)
    async def handle_unexpected_exception(
        request: Request, exc: Exception
    ) -> JSONResponse:
        logger.error(
            json.dumps(
                {
                    "timestamp": datetime.now(UTC).isoformat(),
                    "level": "ERROR",
                    "service": "ml-serving",
                    "request_id": str(_resolve_request_id(request)),
                    "error_type": type(exc).__name__,
                }
            )
        )
        # Never leak stack traces or internal details in 500 responses
        return _build_error_json_response(
            request=request,
            code=ErrorCode.INTERNAL_ERROR,
            message="An unexpected internal error occurred during request processing.",
            status_code=500,
        )

    # -----------------------------------------------------------------------
    # Endpoints (Sync `def` for CPU/IO routes -> runs in FastAPI threadpool)
    # -----------------------------------------------------------------------
    @app.post(
        "/predict",
        response_model=PredictResponse,
        tags=["Prediction"],
        operation_id="predictTransaction",
        responses={
            401: {"model": ErrorResponse},
            422: {"model": ErrorResponse},
            503: {"model": ErrorResponse},
        },
    )
    def predict(payload: PredictRequest, request: Request) -> PredictResponse:
        request.state.request_id = payload.request_id
        current_holder: ModelRegistryHolder = request.app.state.holder
        predictor = current_holder.get_predictor()

        outcome = predictor.predict(payload)
        record_prediction_metrics(outcome)

        request.state.model_version = outcome.response.model.version
        request.state.prediction_action = outcome.response.action.value
        return outcome.response

    @app.get(
        "/health/live",
        response_model=HealthLiveResponse,
        tags=["Health & Probes"],
        operation_id="healthLive",
    )
    def health_live(request: Request) -> HealthLiveResponse:
        current_holder: ModelRegistryHolder = request.app.state.holder
        version: str | None = None
        if current_holder.is_ready:
            try:
                version = current_holder.get_predictor().get_model_ref().version
            except ModelNotReadyError:
                version = None
        return HealthLiveResponse(
            status="ok",
            service="ml-serving",
            model_version=version,
        )

    @app.get(
        "/health/ready",
        response_model=HealthReadyResponse,
        tags=["Health & Probes"],
        operation_id="healthReady",
        responses={503: {"model": ErrorResponse}},
    )
    def health_ready(request: Request) -> HealthReadyResponse:
        current_holder: ModelRegistryHolder = request.app.state.holder
        predictor = current_holder.get_predictor()
        return HealthReadyResponse(
            status="ready",
            ready=True,
            model=predictor.get_model_ref(),
        )

    @app.get(
        "/health",
        response_model=HealthLiveResponse,
        deprecated=True,
        tags=["Health & Probes"],
        operation_id="healthAlias",
    )
    def health_alias(request: Request) -> HealthLiveResponse:
        return health_live(request)

    @app.get(
        "/ready",
        response_model=HealthReadyResponse,
        deprecated=True,
        tags=["Health & Probes"],
        operation_id="readyAlias",
        responses={503: {"model": ErrorResponse}},
    )
    def ready_alias(request: Request) -> HealthReadyResponse:
        return health_ready(request)

    @app.get(
        "/model-info",
        response_model=ModelInfoResponse,
        tags=["Model Metadata & Analytics"],
        operation_id="getModelInfo",
        responses={
            401: {"model": ErrorResponse},
            503: {"model": ErrorResponse},
        },
    )
    def get_model_info(request: Request) -> ModelInfoResponse:
        current_holder: ModelRegistryHolder = request.app.state.holder
        predictor = current_holder.get_predictor()
        info = predictor.get_model_info()
        request.state.model_version = info.model.version
        return info

    @app.get(
        "/viz/{method}",
        response_model=EmbeddingVizResponse,
        tags=["Model Metadata & Analytics"],
        operation_id="getVisualizationEmbeddings",
        responses={
            401: {"model": ErrorResponse},
            404: {"model": ErrorResponse},
            503: {"model": ErrorResponse},
        },
    )
    def get_visualization_embeddings(
        method: VizMethod, request: Request
    ) -> EmbeddingVizResponse:
        current_settings: ServingSettings = request.app.state.settings
        viz_dir = current_settings.viz_data_dir
        if not viz_dir.exists():
            raise HTTPException(
                status_code=404,
                detail=f"Visualization artifact directory not found for method '{method.value}'.",
            )

        file_path = viz_dir / f"{method.value}.json"
        if not file_path.exists():
            raise HTTPException(
                status_code=404,
                detail=f"Embedding artifact '{method.value}.json' has not been generated yet.",
            )

        try:
            raw_data = json.loads(file_path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise HTTPException(
                status_code=503,
                detail=f"Failed to read visualization artifact '{method.value}.json': {exc}",
            ) from exc

        raw_points = raw_data.get("points", [])
        capped_points = raw_points[: current_settings.viz_max_points]
        validated_points = [EmbeddingPoint.model_validate(pt) for pt in capped_points]

        return EmbeddingVizResponse(
            schema_version=str(raw_data.get("schema_version", "1.0")),
            method=method,
            n_points=len(validated_points),
            generated_at=raw_data.get("generated_at"),
            points=validated_points,
        )

    @app.get(
        "/metrics",
        response_class=PlainTextResponse,
        tags=["Observability"],
        operation_id="getPrometheusMetrics",
    )
    def get_prometheus_metrics() -> Response:
        payload = generate_latest()
        return Response(content=payload, media_type=CONTENT_TYPE_LATEST)

    return app


app = create_app()
