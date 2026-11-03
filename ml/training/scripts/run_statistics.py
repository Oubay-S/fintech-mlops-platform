"""Paired statistical validation for the Phase 4 benchmark (Role 4).

Reads the tidy benchmark results (one row per population/model/protocol/fold/
seed) and runs, per population × protocol × metric:

- Friedman test across the models;
- pairwise Wilcoxon signed-rank tests;
- Holm correction;
- mean difference with a 95% paired t interval;
- matched-pairs rank-biserial effect size.

Run after the benchmark:

    python -m ml.training.scripts.run_statistics

The Markdown report is for humans; ``statistical_validation.json`` is the
machine-readable artifact consumed by the MLOps promotion gate and logged by
``run_conformal.py --log-mlflow``.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
import scipy.stats as st

from ml.common.paths import ML_DIR, REPO_ROOT

DEFAULT_RESULTS = ML_DIR / "training" / "results" / "benchmark_runs.csv"
DEFAULT_REPORT = ML_DIR / "training" / "docs" / "statistical_validation.md"
DEFAULT_JSON = ML_DIR / "training" / "results" / "statistical_validation.json"
MODEL_ORDER = ["lr", "rf", "xgb", "svm", "mlp"]
EXPECTED_PROTOCOLS = ["contract", "restricted", "rule_blind"]
EXPECTED_BLOCKS = 15  # 5 folds x 3 seeds
METRIC_LABELS = {
    "pr_auc": "PR-AUC",
    "roc_auc": "ROC-AUC",
    "f1": "F1",
    "recall": "Recall",
    "hard_recall": "Hard-subset recall",
    "consistent_hard_recall": "Serving-consistent hard-subset recall",
}


def resolve(path: str | Path) -> Path:
    path = Path(path)
    return path if path.is_absolute() else REPO_ROOT / path


def holm(pvalues: list[float]) -> list[float]:
    m = len(pvalues)
    order = np.argsort(pvalues)
    adjusted = np.empty(m, dtype=float)
    previous = 0.0
    for rank, index in enumerate(order):
        value = min(1.0, pvalues[index] * (m - rank))
        previous = max(previous, value)
        adjusted[index] = previous
    return adjusted.tolist()


def rank_biserial(diff: np.ndarray) -> float:
    nonzero = diff[diff != 0]
    if len(nonzero) == 0:
        return 0.0
    ranks = st.rankdata(np.abs(nonzero))
    positive = float(ranks[nonzero > 0].sum())
    negative = float(ranks[nonzero < 0].sum())
    total = positive + negative
    return (positive - negative) / total if total else 0.0


def paired_ci(diff: np.ndarray) -> tuple[float, float, float]:
    mean = float(np.mean(diff))
    if len(diff) < 2 or np.allclose(diff, diff[0]):
        return mean, mean, mean
    sem = float(st.sem(diff))
    low, high = st.t.interval(0.95, len(diff) - 1, loc=mean, scale=sem)
    return mean, float(low), float(high)


def validate_benchmark(
    results: pd.DataFrame,
    *,
    expected_models: list[str],
    expected_protocols: list[str],
    expected_blocks: int,
    allow_partial: bool = False,
) -> None:
    """Fail closed when the tidy results are not the full benchmark contract.

    The promotion gate consumes this artifact, so a truncated CSV (missing
    model/protocol/fold/seed) must not silently produce "valid" statistics.
    """
    required = {"population", "protocol", "model", "fold", "seed"}
    missing = required - set(results.columns)
    if missing:
        raise ValueError(f"Benchmark CSV missing columns: {sorted(missing)}")
    duplicate_keys = int(
        results.duplicated(["population", "protocol", "model", "fold", "seed"]).sum()
    )
    if duplicate_keys:
        raise ValueError(f"Benchmark CSV has {duplicate_keys} duplicate run keys")
    if allow_partial:
        return

    observed_protocols = set(results["protocol"])
    missing_protocols = set(expected_protocols) - observed_protocols
    if missing_protocols:
        raise ValueError(
            f"Benchmark CSV missing protocols: {sorted(missing_protocols)}"
        )

    for (population, protocol), frame in results.groupby(["population", "protocol"]):
        models = set(frame["model"])
        missing_models = set(expected_models) - models
        if missing_models:
            raise ValueError(
                f"{population}/{protocol}: missing models {sorted(missing_models)}"
            )
        blocks = frame[["fold", "seed"]].drop_duplicates()
        if len(blocks) != expected_blocks:
            raise ValueError(
                f"{population}/{protocol}: expected {expected_blocks} fold x seed "
                f"blocks, found {len(blocks)}"
            )
        per_model = frame.groupby("model")[["fold", "seed"]].apply(
            lambda group: len(group.drop_duplicates())
        )
        short = per_model[per_model != expected_blocks]
        if not short.empty:
            raise ValueError(
                f"{population}/{protocol}: incomplete blocks per model: "
                f"{short.to_dict()}"
            )


def analyse(
    results: pd.DataFrame,
    metrics: list[str],
) -> list[dict]:
    findings: list[dict] = []
    keys = ["population", "protocol"]
    for (population, protocol), frame in results.groupby(keys, sort=False):
        models = [model for model in MODEL_ORDER if model in set(frame["model"])]
        models += sorted(set(frame["model"]) - set(models))
        for metric in metrics:
            if metric not in frame.columns:
                continue
            pivot = (
                frame.pivot_table(
                    index=["fold", "seed"], columns="model", values=metric, aggfunc="mean"
                )
                .dropna()
            )
            models_present = [model for model in models if model in pivot.columns]
            if len(models_present) < 2 or len(pivot) < 3:
                continue
            arrays = [pivot[model].to_numpy(dtype=float) for model in models_present]
            identical = all(np.allclose(arrays[0], array) for array in arrays[1:])
            friedman_p = 1.0 if identical else float(st.friedmanchisquare(*arrays).pvalue)

            pairs = []
            raw_pvalues = []
            for i, model_a in enumerate(models_present):
                for model_b in models_present[i + 1 :]:
                    diff = pivot[model_a].to_numpy() - pivot[model_b].to_numpy()
                    if np.allclose(diff, 0):
                        pvalue = 1.0
                    else:
                        pvalue = float(
                            st.wilcoxon(diff, zero_method="wilcox", alternative="two-sided").pvalue
                        )
                    mean, low, high = paired_ci(diff)
                    pairs.append(
                        {
                            "model_a": model_a,
                            "model_b": model_b,
                            "mean_diff": mean,
                            "ci_low": low,
                            "ci_high": high,
                            "raw_p": pvalue,
                            "effect": rank_biserial(diff),
                        }
                    )
                    raw_pvalues.append(pvalue)

            adjusted = holm(raw_pvalues)
            for pair, adjusted_p in zip(pairs, adjusted):
                pair["holm_p"] = adjusted_p
            findings.append(
                {
                    "population": population,
                    "protocol": protocol,
                    "metric": metric,
                    "blocks": int(len(pivot)),
                    "models": models_present,
                    "friedman_p": friedman_p,
                    "pairs": pairs,
                }
            )
    return findings


def write_report(findings: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Statistical Validation — Role 4",
        "",
        "Generated by `ml/training/scripts/run_statistics.py` from the tidy benchmark results.",
        "Tests are **paired by fold and seed**; pairwise p-values use Holm correction.",
        "",
        "## How to read this",
        "",
        "- The **contract** protocol is near-ceiling; differences are expected to be small or",
        "  non-significant. That is the PaySim ceiling effect, not evidence that the models are equal.",
        "- The **restricted** and **rule-blind** protocols are the meaningful comparison.",
        "- The hard subset has few frauds, so its confidence intervals are wide; report power honestly.",
        "",
    ]
    for finding in findings:
        label = METRIC_LABELS.get(finding["metric"], finding["metric"])
        lines += [
            "",
            f"## {finding['population']} / {finding['protocol']} — {label}",
            "",
            f"- Blocks (fold × seed): **{finding['blocks']}**",
            f"- Models: {', '.join(finding['models'])}",
            f"- Friedman p-value: **{finding['friedman_p']:.4g}**",
            "",
            "| A | B | Mean diff (95% CI) | Raw p | Holm p | Rank-biserial |",
            "|---|---|---:|---:|---:|---:|",
        ]
        for pair in finding["pairs"]:
            lines.append(
                f"| {pair['model_a']} | {pair['model_b']} | "
                f"{pair['mean_diff']:.4f} "
                f"[{pair['ci_low']:.4f}, {pair['ci_high']:.4f}] | "
                f"{pair['raw_p']:.4g} | {pair['holm_p']:.4g} | {pair['effect']:.3f} |"
            )
    lines.append("")
    path.write_text("\n".join(lines))


def write_json(
    findings: list[dict],
    path: Path,
    *,
    results_path: Path,
    metrics: list[str],
) -> Path:
    """Machine-readable statistical validation for the MLOps gate."""
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        results_label = results_path.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        results_label = results_path.name
    payload = {
        "schema_version": "1.0",
        "results_csv": results_label,
        "metrics": metrics,
        "findings": findings,
    }
    path.write_text(json.dumps(payload, indent=2))
    return path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", default=str(DEFAULT_RESULTS))
    parser.add_argument("--report", default=str(DEFAULT_REPORT))
    parser.add_argument("--json", default=str(DEFAULT_JSON))
    parser.add_argument(
        "--expected-blocks",
        type=int,
        default=EXPECTED_BLOCKS,
        help="fold x seed blocks per population/protocol (default: 15)",
    )
    parser.add_argument(
        "--allow-partial",
        action="store_true",
        help="skip the full-benchmark validation for exploratory runs",
    )
    parser.add_argument("--metrics", default="pr_auc,hard_recall,consistent_hard_recall,f1")
    args = parser.parse_args()

    results = pd.read_csv(resolve(args.results))
    validate_benchmark(
        results,
        expected_models=MODEL_ORDER,
        expected_protocols=EXPECTED_PROTOCOLS,
        expected_blocks=args.expected_blocks,
        allow_partial=args.allow_partial,
    )
    metrics = [metric.strip() for metric in args.metrics.split(",") if metric.strip()]
    findings = analyse(results, metrics)
    if not findings:
        raise SystemExit("No complete paired blocks found; run the benchmark first.")
    write_report(findings, resolve(args.report))
    json_path = write_json(
        findings,
        resolve(args.json),
        results_path=resolve(args.results),
        metrics=metrics,
    )
    print(f"Findings: {len(findings)}")
    print(f"Report:   {resolve(args.report)}")
    print(f"JSON:     {json_path}")


if __name__ == "__main__":
    main()
