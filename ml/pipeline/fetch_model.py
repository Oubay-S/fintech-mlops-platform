"""Fetch and cryptographically verify the official trained model from GitHub Releases.

Queries the GitHub Releases API dynamically (defaulting to the latest published
release, or an explicit `--tag` if provided) with zero hardcoded version tags,
filenames, or checksums:
1. Resolves the release metadata from GitHub API (`/releases/latest` or `/releases/tags/<tag>`).
2. Locates the `.zip` archive asset and its companion `.sha256` checksum asset.
3. Downloads both into memory and verifies the archive SHA-256 digest.
4. Verifies the inner `model/final_contract_model.joblib` SHA-256 against `SHA256SUMS`
    inside the archive.
5. Extracts only `final_contract_model.joblib` to `ml/data/processed/final_contract_model.joblib`
   (without creating any extra directories) and validates the fitted scikit-learn Pipeline.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import sys
import tempfile
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from typing import Any

from ml.pipeline.mlflow_config import (
    EXIT_INFRA_ERROR,
    EXIT_SUCCESS,
    REPO_ROOT,
    PipelineInfraError,
)
from ml.pipeline.populate_mlflow import LOCAL_MODEL_PATH, load_champion_pipeline

DEFAULT_GITHUB_REPO = "Oubay-S/fintech-mlops-platform"
MODEL_ZIP_SUFFIX = "model/final_contract_model.joblib"
SHA256SUMS_SUFFIX = "SHA256SUMS"


def _http_get_bytes(url: str, *, accept: str = "application/octet-stream") -> bytes:
    """Perform an HTTP GET request and return raw response bytes, or raise PipelineInfraError."""
    headers = {
        "User-Agent": "fintech-mlops-pipeline",
        "Accept": accept,
    }
    github_token = os.environ.get("GITHUB_TOKEN", "").strip()
    if github_token:
        headers["Authorization"] = f"Bearer {github_token}"

    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return resp.read()
    except urllib.error.HTTPError as exc:
        raise PipelineInfraError(
            f"HTTP {exc.code} when fetching '{url}': {exc.reason}"
        ) from exc
    except urllib.error.URLError as exc:
        raise PipelineInfraError(f"Network error when fetching '{url}': {exc}") from exc


def resolve_release_assets(
    *,
    repo: str = DEFAULT_GITHUB_REPO,
    tag: str = "latest",
) -> tuple[str, str, str]:
    """Return `(resolved_tag, zip_download_url, sha256_download_url)` from GitHub Releases API."""
    clean_tag = tag.strip()
    if not clean_tag:
        raise PipelineInfraError("Release tag must be a non-empty string.")

    endpoint = (
        f"https://api.github.com/repos/{repo}/releases/latest"
        if clean_tag == "latest"
        else f"https://api.github.com/repos/{repo}/releases/tags/{clean_tag}"
    )
    raw_json = _http_get_bytes(endpoint, accept="application/vnd.github+json")
    try:
        release_data: dict[str, Any] = json.loads(raw_json.decode("utf-8"))
    except Exception as exc:
        raise PipelineInfraError(
            f"Malformed JSON response from GitHub Releases API '{endpoint}': {exc}"
        ) from exc

    resolved_tag = str(release_data.get("tag_name", "")).strip()
    assets = release_data.get("assets")
    if not resolved_tag or not isinstance(assets, list) or not assets:
        raise PipelineInfraError(
            f"Release '{clean_tag}' in '{repo}' has no downloadable assets."
        )

    zip_asset: dict[str, Any] | None = None
    sha_asset: dict[str, Any] | None = None

    for asset in assets:
        if not isinstance(asset, dict):
            continue
        name = str(asset.get("name", ""))
        if name.endswith(".zip"):
            zip_asset = asset
        elif name.endswith((".zip.sha256", ".sha256")):
            sha_asset = asset

    if zip_asset is None or not zip_asset.get("browser_download_url"):
        raise PipelineInfraError(
            f"Release '{resolved_tag}' in '{repo}' is missing a '.zip' model archive asset."
        )
    if sha_asset is None or not sha_asset.get("browser_download_url"):
        raise PipelineInfraError(
            f"Release '{resolved_tag}' in '{repo}' is missing a '.sha256' checksum asset."
        )

    return (
        resolved_tag,
        str(zip_asset["browser_download_url"]),
        str(sha_asset["browser_download_url"]),
    )


def _parse_sha256_file(content: str) -> str:
    """Extract and validate a 64-character hex SHA-256 digest from a `.sha256` file."""
    tokens = content.strip().split()
    if not tokens:
        raise PipelineInfraError("Downloaded .sha256 checksum file is empty.")
    digest = tokens[0].strip().lower()
    if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
        raise PipelineInfraError(
            f"Invalid SHA-256 digest format in checksum file: '{digest}'."
        )
    return digest


def _parse_inner_model_sha256(sha256sums_text: str) -> str:
    """Extract the expected SHA-256 for `model/final_contract_model.joblib` from `SHA256SUMS`."""
    for line in sha256sums_text.splitlines():
        parts = line.strip().split()
        if len(parts) >= 2 and parts[1].replace("\\", "/").endswith(MODEL_ZIP_SUFFIX):
            return _parse_sha256_file(parts[0])
    raise PipelineInfraError(
        f"Archive SHA256SUMS is missing an entry for '{MODEL_ZIP_SUFFIX}'."
    )


def extract_and_verify_archive(
    *,
    zip_bytes: bytes,
    expected_zip_sha256: str,
    output_path: Path = LOCAL_MODEL_PATH,
) -> Path:
    """Verify outer and inner SHA-256 checksums, extract `.joblib`, and validate the Pipeline."""
    actual_zip_sha256 = hashlib.sha256(zip_bytes).hexdigest().lower()
    if actual_zip_sha256 != expected_zip_sha256.lower():
        raise PipelineInfraError(
            f"Archive SHA-256 mismatch: expected {expected_zip_sha256}, "
            f"got {actual_zip_sha256}."
        )

    try:
        zf = zipfile.ZipFile(io.BytesIO(zip_bytes))
        names = zf.namelist()
    except Exception as exc:
        raise PipelineInfraError(
            f"Downloaded release asset is not a valid ZIP archive: {exc}"
        ) from exc

    model_entries = [
        n for n in names if n.replace("\\", "/").endswith(MODEL_ZIP_SUFFIX)
    ]
    if not model_entries:
        raise PipelineInfraError(
            f"Release archive does not contain '{MODEL_ZIP_SUFFIX}'."
        )
    model_entry = model_entries[0]

    # Verify inner model checksum against SHA256SUMS in the archive
    sha_entries = [n for n in names if n.replace("\\", "/").endswith(SHA256SUMS_SUFFIX)]
    if not sha_entries:
        raise PipelineInfraError(
            f"Release archive is missing '{SHA256SUMS_SUFFIX}' manifest for inner file verification."
        )

    try:
        model_bytes = zf.read(model_entry)
        sha256sums_text = zf.read(sha_entries[0]).decode("utf-8")
    except Exception as exc:
        raise PipelineInfraError(
            f"Failed to read or decode entries from release ZIP archive: {exc}"
        ) from exc

    expected_model_sha256 = _parse_inner_model_sha256(sha256sums_text)
    actual_model_sha256 = hashlib.sha256(model_bytes).hexdigest().lower()
    if actual_model_sha256 != expected_model_sha256:
        raise PipelineInfraError(
            f"Inner model SHA-256 mismatch for '{model_entry}': "
            f"expected {expected_model_sha256}, got {actual_model_sha256}."
        )

    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            dir=str(output_path.parent),
            prefix=".tmp_model_",
            suffix=".joblib",
            delete=False,
        ) as tmp_file:
            tmp_path = Path(tmp_file.name)
            tmp_file.write(model_bytes)
    except Exception as exc:
        raise PipelineInfraError(
            f"Failed to write temporary model artifact in '{output_path.parent}': {exc}"
        ) from exc

    try:
        # Validate that the extracted file is a genuine fitted contract Pipeline before replacing target
        load_champion_pipeline(local_model_path=tmp_path)
        os.replace(tmp_path, output_path)
    except PipelineInfraError:
        if tmp_path.exists():
            tmp_path.unlink(missing_ok=True)
        raise
    except Exception as exc:
        if tmp_path.exists():
            tmp_path.unlink(missing_ok=True)
        raise PipelineInfraError(
            f"Failed to install validated model artifact at '{output_path}': {exc}"
        ) from exc

    return output_path


def fetch_model(
    *,
    repo: str = DEFAULT_GITHUB_REPO,
    tag: str = "latest",
    output_path: Path = LOCAL_MODEL_PATH,
) -> dict[str, str]:
    """Download, verify, and extract the trained model artifact from GitHub Releases."""
    resolved_tag, zip_url, sha_url = resolve_release_assets(repo=repo, tag=tag)
    raw_sha = _http_get_bytes(sha_url, accept="text/plain")
    try:
        sha_text = raw_sha.decode("utf-8")
    except Exception as exc:
        raise PipelineInfraError(
            f"Failed to decode .sha256 checksum asset from '{sha_url}': {exc}"
        ) from exc

    expected_zip_sha256 = _parse_sha256_file(sha_text)
    zip_bytes = _http_get_bytes(zip_url)

    saved_path = extract_and_verify_archive(
        zip_bytes=zip_bytes,
        expected_zip_sha256=expected_zip_sha256,
        output_path=output_path,
    )
    model_sha256 = hashlib.sha256(saved_path.read_bytes()).hexdigest()
    try:
        display_path = str(saved_path.relative_to(REPO_ROOT))
    except ValueError:
        display_path = str(saved_path)

    return {
        "status": "SUCCESS",
        "repo": repo,
        "tag": resolved_tag,
        "archive_sha256": expected_zip_sha256,
        "model_sha256": model_sha256,
        "output_path": display_path,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--tag",
        default="latest",
        help="GitHub Release tag to fetch (default: 'latest' automatically resolves the newest release)",
    )
    parser.add_argument(
        "--repo",
        default=DEFAULT_GITHUB_REPO,
        help=f"GitHub repository in 'owner/name' format (default: {DEFAULT_GITHUB_REPO})",
    )
    parser.add_argument(
        "--output",
        default=str(LOCAL_MODEL_PATH),
        help="Destination path for final_contract_model.joblib",
    )
    args = parser.parse_args(argv)

    try:
        report = fetch_model(
            repo=args.repo,
            tag=args.tag,
            output_path=Path(args.output),
        )
        print(json.dumps(report, indent=2))
        return EXIT_SUCCESS
    except Exception as exc:  # noqa: BLE001
        infra_exc = (
            exc
            if isinstance(exc, PipelineInfraError)
            else PipelineInfraError(f"Unexpected fetch_model failure: {exc}")
        )
        print(
            json.dumps(
                {
                    "status": "INFRA_ERROR",
                    "exit_code": EXIT_INFRA_ERROR,
                    "error": str(infra_exc),
                },
                indent=2,
            ),
            file=sys.stderr,
        )
        return EXIT_INFRA_ERROR


if __name__ == "__main__":
    raise SystemExit(main())
