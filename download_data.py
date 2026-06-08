from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import boto3


DEFAULT_SESSION_NAME = "s3-csv-downloader-session"

__all__ = ["list_csv_files", "download_csv_file"]


def list_csv_files(
    bucket_name: str | None = None,
    prefix: str = "",
    *,
    role_arn: str | None = None,
    access_key: str | None = None,
    secret_key: str | None = None,
    session_name: str | None = None,
) -> list[dict[str, Any]]:
    bucket_name = _resolve_bucket_name(bucket_name)
    s3_client = _create_s3_client(
        role_arn=role_arn,
        access_key=access_key,
        secret_key=secret_key,
        session_name=session_name,
    )
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
    bucket_name: str | None,
    prefix: str,
    file_name: str,
    local_directory: str | Path,
    *,
    role_arn: str | None = None,
    access_key: str | None = None,
    secret_key: str | None = None,
    session_name: str | None = None,
) -> Path:
    if not file_name.lower().endswith(".csv"):
        raise ValueError(f"Only CSV files can be downloaded. Got: {file_name}")

    bucket_name = _resolve_bucket_name(bucket_name)
    s3_client = _create_s3_client(
        role_arn=role_arn,
        access_key=access_key,
        secret_key=secret_key,
        session_name=session_name,
    )
    s3_key = _build_s3_key(prefix, file_name)
    local_path = _build_local_path(local_directory, file_name)

    local_path.parent.mkdir(parents=True, exist_ok=True)
    s3_client.download_file(bucket_name, s3_key, str(local_path))

    return local_path


def _create_s3_client(
    *,
    role_arn: str | None,
    access_key: str | None,
    secret_key: str | None,
    session_name: str | None,
) -> Any:
    role_arn = _get_value(role_arn, "ROLE_ARN")
    access_key = _get_value(access_key, "ACCESS_KEY", "AWS_ACCESS_KEY_ID")
    secret_key = _get_value(secret_key, "SECRET_KEY", "AWS_SECRET_ACCESS_KEY")
    session_name = _get_value(session_name, "SESSION_NAME") or DEFAULT_SESSION_NAME

    if role_arn:
        return _create_assumed_role_s3_client(
            role_arn=role_arn,
            access_key=access_key,
            secret_key=secret_key,
            session_name=session_name,
        )

    if access_key or secret_key:
        if not access_key or not secret_key:
            raise ValueError("Both ACCESS_KEY and SECRET_KEY are required.")

        return boto3.client(
            "s3",
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
        )

    return boto3.client("s3")


def _create_assumed_role_s3_client(
    *,
    role_arn: str,
    access_key: str | None,
    secret_key: str | None,
    session_name: str,
) -> Any:
    session_kwargs: dict[str, str] = {}

    if access_key or secret_key:
        if not access_key or not secret_key:
            raise ValueError("Both ACCESS_KEY and SECRET_KEY are required.")

        session_kwargs["aws_access_key_id"] = access_key
        session_kwargs["aws_secret_access_key"] = secret_key

    sts_client = boto3.Session(**session_kwargs).client("sts")
    assumed_role = sts_client.assume_role(
        RoleArn=role_arn,
        RoleSessionName=session_name,
    )
    credentials = assumed_role["Credentials"]

    return boto3.client(
        "s3",
        aws_access_key_id=credentials["AccessKeyId"],
        aws_secret_access_key=credentials["SecretAccessKey"],
        aws_session_token=credentials["SessionToken"],
    )


def _resolve_bucket_name(bucket_name: str | None) -> str:
    resolved_bucket_name = _get_value(bucket_name, "DEFAULT_BUCKET")
    if not resolved_bucket_name:
        raise ValueError("Bucket name is required. Pass bucket_name or set DEFAULT_BUCKET.")

    return resolved_bucket_name


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


def _get_value(value: str | None, *environment_names: str) -> str | None:
    if value:
        return value

    for environment_name in environment_names:
        environment_value = os.getenv(environment_name)
        if environment_value:
            return environment_value

    return None
