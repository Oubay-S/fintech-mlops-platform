"""Export PCA / t-SNE / UMAP embeddings for the serving `/viz/{method}` endpoint.

Reads the final contract model + uncertainty config, samples the app-valid
population (default 2,000 points, matching the serving default), and writes
`pca.json`, `tsne.json`, `umap.json` in the OpenAPI `EmbeddingVizResponse`
shape.

Run from the repository root:

    python -m ml.visualization.export_embeddings
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.decomposition import PCA
from sklearn.manifold import TSNE
from sklearn.model_selection import train_test_split

from ml.common.artifact_contract import UncertaintyConfig, prediction_set
from ml.common.paths import ML_DIR, REPO_ROOT
from ml.common.preprocessing import build_features
from ml.common.schema import TARGET

DEFAULT_MODEL = ML_DIR / "data" / "processed" / "final_contract_model.joblib"
DEFAULT_POPULATION = ML_DIR / "data" / "processed" / "populations" / "app_valid.parquet"
DEFAULT_OUTPUT = ML_DIR / "visualization" / "data"
DEFAULT_SAMPLE = 2_000


def resolve(path: str | Path) -> Path:
    path = Path(path)
    return path if path.is_absolute() else REPO_ROOT / path


def _points(
    xy: np.ndarray,
    frame: pd.DataFrame,
    true_labels: np.ndarray,
    probs: np.ndarray,
    config: UncertaintyConfig,
) -> list[dict]:
    points = []
    for index, (x, y) in enumerate(xy):
        p = float(probs[index])
        labels = prediction_set(p, config)
        true_label = int(true_labels[index])
        predicted_label = int(p >= 0.5)
        points.append(
            {
                "x": float(x),
                "y": float(y),
                "true_label": true_label,
                "predicted_label": predicted_label,
                "uncertain": len(labels) != 1,
                "error": predicted_label != true_label,
                "type": str(frame.iloc[index]["type"]),
                "amount": float(frame.iloc[index]["amount"]),
                "balance_drain_ratio": float(frame.iloc[index]["balance_drain_ratio"]),
            }
        )
    return points


def export_method(
    method: str,
    transformed: np.ndarray,
    frame: pd.DataFrame,
    true_labels: np.ndarray,
    probs: np.ndarray,
    config: UncertaintyConfig,
    output_dir: Path,
) -> dict:
    if method == "pca":
        xy = PCA(n_components=2, random_state=42).fit_transform(transformed)
    elif method == "tsne":
        xy = TSNE(
            n_components=2,
            random_state=42,
            perplexity=30,
            init="pca",
            learning_rate="auto",
        ).fit_transform(transformed)
    elif method == "umap":
        import umap

        xy = umap.UMAP(
            n_components=2,
            random_state=42,
            n_neighbors=15,
            min_dist=0.1,
        ).fit_transform(transformed)
    else:
        raise ValueError(f"Unknown method: {method}")

    payload = {
        "schema_version": "1.0",
        "method": method,
        "n_points": int(len(frame)),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "points": _points(xy, frame, true_labels, probs, config),
    }
    path = output_dir / f"{method}.json"
    path.write_text(json.dumps(payload, separators=(",", ":")))
    return {"method": method, "path": str(path), "n_points": payload["n_points"]}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default=str(DEFAULT_MODEL))
    parser.add_argument(
        "--config",
        default=None,
        help="optional uncertainty config override; defaults to the artifact config",
    )
    parser.add_argument("--population", default=str(DEFAULT_POPULATION))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--sample-size", type=int, default=DEFAULT_SAMPLE)
    parser.add_argument("--methods", default="pca,tsne,umap")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    artifact = joblib.load(resolve(args.model))
    pipeline = artifact["pipeline"]
    if args.config:
        config = UncertaintyConfig.load(resolve(args.config))
    else:
        config = UncertaintyConfig.from_dict(artifact["config"])
    config.validate()

    df = pd.read_parquet(resolve(args.population))
    df["type"] = df["type"].astype("category")
    if len(df) <= args.sample_size:
        sample = df.reset_index(drop=True)
    else:
        sample, _ = train_test_split(
            df,
            train_size=args.sample_size,
            stratify=df[TARGET],
            random_state=args.seed,
        )
    sample = sample.reset_index(drop=True)

    features = build_features(sample)
    preprocessor = pipeline.named_steps["preprocessor"]
    transformed = preprocessor.transform(features)
    probs = pipeline.predict_proba(features)[:, 1]
    engineered = features.reset_index(drop=True)
    true_labels = sample[TARGET].to_numpy()

    output_dir = resolve(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    methods = [method.strip() for method in args.methods.split(",") if method.strip()]
    for method in methods:
        result = export_method(
            method, transformed, engineered, true_labels, probs, config, output_dir
        )
        print(json.dumps(result))


if __name__ == "__main__":
    main()
