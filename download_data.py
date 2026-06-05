from __future__ import annotations

from pathlib import Path
from typing import Any

import boto3


__all__ = ["list_csv_files", "download_csv_file"]


def list_csv_files(bucket_name: str, prefix: str = "") -> list[dict[str, Any]]:
    s3_client = _create_s3_client()
    normalized_prefix = _normalize_prefix(prefix)
    paginator = s3_client.get_paginator("list_objects_v2")
    csv_files: list[dict[str, Any]] = []

    for page in paginator.paginate(Bucket=bucket_name, Prefix=normalized_prefix):
        for s3_object in page.get("Contents", []):
            s3_key = s3_object["Key"]
            if s3_key.lower().endswith(".csv"):
                csv_files.append(
                    {
                        "file_name": Path(s3_key).name,
                        "s3_key": s3_key,
                        "last_modified": s3_object["LastModified"],
                        "size_bytes": s3_object["Size"],
                    }
                )

    return sorted(csv_files, key=lambda file: file["last_modified"], reverse=True)


def download_csv_file(
    bucket_name: str,
    prefix: str,
    file_name: str,
    local_directory: str | Path,
) -> Path:
    if not file_name.lower().endswith(".csv"):
        raise ValueError(f"Only CSV files can be downloaded. Got: {file_name}")

    s3_client = _create_s3_client()
    s3_key = _build_s3_key(prefix, file_name)
    local_path = _build_local_path(local_directory, file_name)

    local_path.parent.mkdir(parents=True, exist_ok=True)
    s3_client.download_file(bucket_name, s3_key, str(local_path))

    return local_path


def _create_s3_client() -> Any:
    return boto3.client("s3")


def _normalize_prefix(prefix: str) -> str:
    cleaned_prefix = prefix.strip().lstrip("/")
    if cleaned_prefix and not cleaned_prefix.endswith("/"):
        cleaned_prefix += "/"
    return cleaned_prefix


def _build_s3_key(prefix: str, file_name: str) -> str:
    normalized_prefix = _normalize_prefix(prefix)
    cleaned_file_name = file_name.strip().lstrip("/")

    if not normalized_prefix or cleaned_file_name.startswith(normalized_prefix):
        return cleaned_file_name

    return f"{normalized_prefix}{cleaned_file_name}"


def _build_local_path(local_directory: str | Path, file_name: str) -> Path:
    target_directory = Path(local_directory).expanduser().resolve()
    return target_directory / Path(file_name).name
