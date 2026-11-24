"""Validation tests for Role 5 Grafana dashboard JSON and PrometheusRule YAML (Issues #32 & #33).

Ensures:
1. `k8s/monitoring/dashboards/ml-serving.json` is valid Grafana JSON covering all
   required panels (latency p50/p90/p95/p99, RPS throughput, prediction distribution,
   uncertainty score distribution, active model info) and references only real metrics
   defined in `ml/serving/metrics.py`.
2. `k8s/monitoring/alert-rules/ml-uncertainty-alert.yaml` is valid Prometheus Operator
   `PrometheusRule` YAML defining `HighMLUncertaintyRate` (> 25% over 5m, warning) and
   companion ML serving SLA/availability alerts referencing only real metrics.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import yaml
from prometheus_client import REGISTRY

import ml.serving.metrics  # noqa: F401 — registers all ML Prometheus metrics

REPO_ROOT = Path(__file__).resolve().parents[3]
DASHBOARD_PATH = REPO_ROOT / "k8s" / "monitoring" / "dashboards" / "ml-serving.json"
ALERT_RULE_PATH = (
    REPO_ROOT / "k8s" / "monitoring" / "alert-rules" / "ml-uncertainty-alert.yaml"
)

_METRIC_RE = re.compile(r"\b(ml_[a-z0-9_]+)\b")


def _registered_ml_metric_sample_names() -> frozenset[str]:
    """Dynamically collect all real `ml_*` Prometheus sample names from `ml.serving.metrics`."""
    names: set[str] = set()
    for metric_family in REGISTRY.collect():
        if not metric_family.name.startswith("ml_"):
            continue
        names.add(metric_family.name)
        if metric_family.type == "counter":
            names.add(f"{metric_family.name}_total")
        elif metric_family.type == "histogram":
            names.update(
                {
                    f"{metric_family.name}_bucket",
                    f"{metric_family.name}_sum",
                    f"{metric_family.name}_count",
                }
            )
    return frozenset(names)


def test_grafana_ml_serving_dashboard_is_valid_and_aligned_with_metrics() -> None:
    assert DASHBOARD_PATH.exists(), f"Missing Grafana dashboard at {DASHBOARD_PATH}"
    dashboard = json.loads(DASHBOARD_PATH.read_text(encoding="utf-8"))

    assert dashboard["uid"] == "fintech-ml-serving"
    assert dashboard["schemaVersion"] >= 36
    assert isinstance(dashboard["panels"], list) and len(dashboard["panels"]) >= 8

    allowed_metrics = _registered_ml_metric_sample_names()
    all_exprs: list[str] = []
    for panel in dashboard["panels"]:
        assert "id" in panel and "title" in panel and "type" in panel
        targets = panel.get("targets", [])
        assert targets, f"Panel '{panel['title']}' has no Prometheus targets"
        for target in targets:
            expr = target.get("expr", "").strip()
            assert expr, f"Empty PromQL expr in panel '{panel['title']}'"
            all_exprs.append(expr)
            referenced = set(_METRIC_RE.findall(expr))
            assert referenced, f"No ml_* metric found in expr: {expr}"
            unknown = referenced - allowed_metrics
            assert not unknown, (
                f"Unknown ml_* metrics in dashboard panel '{panel['title']}': {unknown}"
            )

    joined = "\n".join(all_exprs)
    # Verify all Issue #32 required metrics are plotted
    for required_metric in (
        "ml_inference_duration_seconds_bucket",
        "ml_http_requests_total",
        "ml_predictions_total",
        "ml_uncertainty_score_bucket",
        "ml_model_info",
        "ml_ready",
        "ml_human_review_requests_total",
    ):
        assert required_metric in joined, (
            f"Dashboard missing required metric '{required_metric}'"
        )

    # Verify p50, p90, p95, p99 latency quantiles are present
    for quantile in ("0.50", "0.90", "0.95", "0.99"):
        assert f"histogram_quantile({quantile}" in joined


def test_prometheus_uncertainty_alert_rule_is_valid_and_aligned_with_metrics() -> None:
    assert ALERT_RULE_PATH.exists(), f"Missing PrometheusRule at {ALERT_RULE_PATH}"
    manifest = yaml.safe_load(ALERT_RULE_PATH.read_text(encoding="utf-8"))

    assert manifest["apiVersion"] == "monitoring.coreos.com/v1"
    assert manifest["kind"] == "PrometheusRule"
    assert manifest["metadata"]["name"] == "fintech-ml-serving-alerts"

    groups = manifest["spec"]["groups"]
    assert isinstance(groups, list) and len(groups) >= 1
    rules_by_name = {
        rule["alert"]: rule for group in groups for rule in group.get("rules", [])
    }

    # Issue #33 mandatory alert: HighMLUncertaintyRate (> 25% over 5m, severity: warning)
    assert "HighMLUncertaintyRate" in rules_by_name
    unc_rule = rules_by_name["HighMLUncertaintyRate"]
    assert unc_rule["labels"]["severity"] == "warning"
    assert unc_rule["for"] == "5m"
    assert 'action="HUMAN_REVIEW"' in unc_rule["expr"]
    assert "0.25" in unc_rule["expr"]
    assert "[5m]" in unc_rule["expr"]

    # Companion SLA & availability alerts
    assert "MLInferenceLatencyHigh" in rules_by_name
    assert "0.3" in rules_by_name["MLInferenceLatencyHigh"]["expr"]
    assert "MLServingErrorRateHigh" in rules_by_name
    assert "0.05" in rules_by_name["MLServingErrorRateHigh"]["expr"]
    assert "MLServingModelNotReady" in rules_by_name
    assert "ml_ready == 0" in rules_by_name["MLServingModelNotReady"]["expr"]

    # Every alert expression must only reference real metrics from ml/serving/metrics.py
    allowed_metrics = _registered_ml_metric_sample_names()
    for alert_name, rule in rules_by_name.items():
        expr = str(rule["expr"])
        referenced = set(_METRIC_RE.findall(expr))
        assert referenced, f"Alert '{alert_name}' references no ml_* metric"
        unknown = referenced - allowed_metrics
        assert not unknown, (
            f"Alert '{alert_name}' references unknown ml_* metrics: {unknown}"
        )
