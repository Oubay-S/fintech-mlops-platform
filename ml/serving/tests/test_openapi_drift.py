"""OpenAPI contract drift test comparing `app.openapi()` against `docs/api/ml-predict-openapi.yaml`.

Verifies:
1. All paths and HTTP methods match identically between FastAPI and the YAML specification.
2. `operationId` values match on every endpoint.
3. Required fields and enum values on all core schemas (`PredictRequest`, `TransactionFeatures`,
   `PredictResponse`, `UncertaintyEstimate`, `ModelRef`, `ModelInfoResponse`,
   `EmbeddingVizResponse`, `ErrorResponse`) match without drift.
4. All example payloads in `docs/api/ml-predict-openapi.yaml` validate cleanly against the Pydantic schemas.
"""
from __future__ import annotations

import yaml

from ml.common.paths import REPO_ROOT
from ml.serving.config import ServingSettings
from ml.serving.main import create_app
from ml.serving.schemas import (
    ErrorResponse,
    PredictRequest,
    PredictResponse,
)

OPENAPI_YAML_PATH = REPO_ROOT / "docs" / "api" / "ml-predict-openapi.yaml"


def test_openapi_paths_methods_and_operation_ids_match_yaml(
    test_settings: ServingSettings,
) -> None:
    yaml_spec = yaml.safe_load(OPENAPI_YAML_PATH.read_text(encoding="utf-8"))
    app = create_app(settings=test_settings)
    live_spec = app.openapi()

    assert set(live_spec["paths"].keys()) == set(yaml_spec["paths"].keys())

    for path, yaml_path_item in yaml_spec["paths"].items():
        live_path_item = live_spec["paths"][path]
        yaml_methods = {
            m for m in yaml_path_item if m in ("get", "post", "put", "delete", "patch")
        }
        live_methods = {
            m for m in live_path_item if m in ("get", "post", "put", "delete", "patch")
        }
        assert live_methods == yaml_methods, f"Method mismatch on {path}"

        for method in yaml_methods:
            yaml_op = yaml_path_item[method]
            live_op = live_path_item[method]
            assert live_op.get("operationId") == yaml_op.get("operationId"), (
                f"operationId mismatch on {method.upper()} {path}"
            )
            assert bool(live_op.get("deprecated", False)) == bool(
                yaml_op.get("deprecated", False)
            ), f"deprecated flag mismatch on {method.upper()} {path}"


def test_openapi_required_fields_and_enums_match_yaml(
    test_settings: ServingSettings,
) -> None:
    yaml_spec = yaml.safe_load(OPENAPI_YAML_PATH.read_text(encoding="utf-8"))
    app = create_app(settings=test_settings)
    live_spec = app.openapi()

    yaml_schemas = yaml_spec["components"]["schemas"]
    live_schemas = live_spec["components"]["schemas"]

    core_schemas = [
        "TransactionFeatures",
        "PredictRequest",
        "UncertaintyEstimate",
        "ModelRef",
        "PredictResponse",
        "HealthLiveResponse",
        "HealthReadyResponse",
        "ModelInfoResponse",
        "EmbeddingPoint",
        "EmbeddingVizResponse",
        "ErrorResponse",
    ]
    for schema_name in core_schemas:
        assert schema_name in live_schemas, f"Missing {schema_name} in app.openapi()"
        yaml_req = set(yaml_schemas[schema_name].get("required", []))
        live_req = set(live_schemas[schema_name].get("required", []))
        assert live_req == yaml_req, (
            f"Required fields drift on {schema_name}: live={live_req} vs yaml={yaml_req}"
        )

    enum_schemas = [
        "TransactionType",
        "PredictionLabel",
        "SuggestedAction",
        "UncertaintyMethod",
        "ModelStage",
        "ModelAlias",
        "VizMethod",
        "ErrorCode",
    ]
    for enum_name in enum_schemas:
        assert enum_name in live_schemas, f"Missing enum {enum_name} in app.openapi()"
        assert list(live_schemas[enum_name]["enum"]) == list(
            yaml_schemas[enum_name]["enum"]
        ), f"Enum drift on {enum_name}"


def test_yaml_examples_validate_against_pydantic_schemas() -> None:
    yaml_spec = yaml.safe_load(OPENAPI_YAML_PATH.read_text(encoding="utf-8"))
    predict_post = yaml_spec["paths"]["/predict"]["post"]

    req_examples = predict_post["requestBody"]["content"]["application/json"]["examples"]
    for ex_name, ex_obj in req_examples.items():
        validated = PredictRequest.model_validate(ex_obj["value"])
        assert validated.schema_version == "1.0", ex_name

    resp_200_examples = predict_post["responses"]["200"]["content"]["application/json"]["examples"]
    for ex_name, ex_obj in resp_200_examples.items():
        validated_resp = PredictResponse.model_validate(ex_obj["value"])
        assert validated_resp.schema_version == "1.0", ex_name

    for status_code in ("401", "422", "503"):
        err_examples = predict_post["responses"][status_code]["content"]["application/json"]["examples"]
        for ex_name, ex_obj in err_examples.items():
            validated_err = ErrorResponse.model_validate(ex_obj["value"])
            assert str(validated_err.status) == status_code, ex_name
