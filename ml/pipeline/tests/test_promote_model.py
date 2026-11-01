"""Tests for `ml/pipeline/promote_model.py` governance, `@previous` rotation, idempotence, and synthetic blocking."""

from __future__ import annotations

from pathlib import Path

import pytest

from ml.common.artifact_contract import (
    PREVIOUS_ALIAS,
    PRODUCTION_ALIAS,
    REGISTERED_MODEL_NAME,
    STAGING_ALIAS,
)
from ml.pipeline.mlflow_config import (
    EXIT_GATE_FAILURE,
    EXIT_SUCCESS,
)
from ml.pipeline.promote_model import main as promote_main
from ml.pipeline.promote_model import promote_model

from .conftest import create_isolated_mlflow_uri, log_test_candidate_run


def test_promote_staging_to_production_rotates_previous_and_is_idempotent(
    tmp_path: Path,
) -> None:
    mlflow = pytest.importorskip("mlflow")
    from mlflow.tracking import MlflowClient

    tracking_uri = create_isolated_mlflow_uri(tmp_path)
    mlflow.set_tracking_uri(tracking_uri)
    client = MlflowClient(tracking_uri=tracking_uri)

    # 1. Log Version 1 (data_source=paysim) -> @candidate -> @staging -> @production
    _, v1 = log_test_candidate_run(tracking_uri, data_source="paysim")
    assert (
        promote_main(
            [
                "--from-alias",
                "candidate",
                "--to-alias",
                "staging",
                "--tracking-uri",
                tracking_uri,
            ]
        )
        == EXIT_SUCCESS
    )
    assert (
        promote_main(
            [
                "--from-alias",
                "staging",
                "--to-alias",
                "production",
                "--tracking-uri",
                tracking_uri,
            ]
        )
        == EXIT_SUCCESS
    )
    assert (
        str(
            client.get_model_version_by_alias(
                REGISTERED_MODEL_NAME, PRODUCTION_ALIAS
            ).version
        )
        == v1
    )

    # 2. Log Version 2 (data_source=paysim) -> @candidate -> @staging -> @production
    _, v2 = log_test_candidate_run(tracking_uri, data_source="paysim")
    assert v2 != v1
    assert (
        promote_main(
            [
                "--from-alias",
                "candidate",
                "--to-alias",
                "staging",
                "--tracking-uri",
                tracking_uri,
            ]
        )
        == EXIT_SUCCESS
    )
    report_v2 = promote_model(
        tracking_uri=tracking_uri,
        from_alias=STAGING_ALIAS,
        to_alias=PRODUCTION_ALIAS,
    )
    assert report_v2.promoted is True
    assert report_v2.idempotent_noop is False
    assert report_v2.promoted_version == v2
    assert report_v2.previous_production_version == v1

    # Verify @production == v2 and @previous == v1
    assert (
        str(
            client.get_model_version_by_alias(
                REGISTERED_MODEL_NAME, PRODUCTION_ALIAS
            ).version
        )
        == v2
    )
    assert (
        str(
            client.get_model_version_by_alias(
                REGISTERED_MODEL_NAME, PREVIOUS_ALIAS
            ).version
        )
        == v1
    )

    # 3. Idempotence: promoting v2 to @production again must NOT overwrite @previous with v2
    noop_report = promote_model(
        tracking_uri=tracking_uri,
        from_alias=STAGING_ALIAS,
        to_alias=PRODUCTION_ALIAS,
    )
    assert noop_report.exit_code == EXIT_SUCCESS
    assert noop_report.idempotent_noop is True
    assert (
        str(
            client.get_model_version_by_alias(
                REGISTERED_MODEL_NAME, PREVIOUS_ALIAS
            ).version
        )
        == v1
    )


def test_promote_strictly_blocks_synthetic_data_source_from_production_exit_1(
    tmp_path: Path,
) -> None:
    tracking_uri = create_isolated_mlflow_uri(tmp_path)

    # Log synthetic run -> allowed in @staging (exit 0), FORBIDDEN in @production (exit 1)
    log_test_candidate_run(tracking_uri, data_source="synthetic")

    staging_code = promote_main(
        [
            "--from-alias",
            "candidate",
            "--to-alias",
            "staging",
            "--tracking-uri",
            tracking_uri,
        ]
    )
    assert staging_code == EXIT_SUCCESS

    prod_code = promote_main(
        [
            "--from-alias",
            "staging",
            "--to-alias",
            "production",
            "--tracking-uri",
            tracking_uri,
        ]
    )
    assert prod_code == EXIT_GATE_FAILURE


def test_promote_dry_run_does_not_modify_registry_aliases(tmp_path: Path) -> None:
    mlflow = pytest.importorskip("mlflow")
    from mlflow.exceptions import MlflowException
    from mlflow.tracking import MlflowClient

    tracking_uri = create_isolated_mlflow_uri(tmp_path)
    mlflow.set_tracking_uri(tracking_uri)
    client = MlflowClient(tracking_uri=tracking_uri)

    log_test_candidate_run(tracking_uri, data_source="paysim")

    code = promote_main(
        [
            "--from-alias",
            "candidate",
            "--to-alias",
            "staging",
            "--dry-run",
            "--tracking-uri",
            tracking_uri,
        ]
    )
    assert code == EXIT_SUCCESS

    # Verify @staging was NOT actually assigned in MLflow Registry
    with pytest.raises(MlflowException):
        client.get_model_version_by_alias(REGISTERED_MODEL_NAME, STAGING_ALIAS)
