from __future__ import annotations

import os
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import boto3


DEFAULT_SESSION_NAME = "s3-csv-downloader-session"
OUTPUT_FILE_PREFIX = "dynamo_oam"
FILE_DATE_PATTERN = re.compile(r"\d{4}-\d{2}-\d{2}")

__all__ = ["list_csv_files", "download_csv_file", "download_csv_files_for_period"]


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
    return _list_csv_files_with_client(s3_client, bucket_name, prefix)


def _list_csv_files_with_client(
    s3_client: Any,
    bucket_name: str,
    prefix: str,
) -> list[dict[str, Any]]:
    normalized_prefix = _normalize_prefix(prefix)
    paginator = s3_client.get_paginator("list_objects_v2")
    csv_files: list[dict[str, Any]] = []

    for page in paginator.paginate(Bucket=bucket_name, Prefix=normalized_prefix):
        for s3_object in page.get("Contents", []):
            s3_key = s3_object["Key"]
            if s3_key.lower().endswith(".csv"):
                file_name = Path(s3_key).name
                csv_files.append(
                    {
                        "file_name": file_name,
                        "s3_key": s3_key,
                        "file_date": _extract_file_date(file_name),
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
    local_file_name: str | None = None,
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
    local_path = _build_local_path(local_directory, local_file_name or file_name)

    local_path.parent.mkdir(parents=True, exist_ok=True)
    s3_client.download_file(bucket_name, s3_key, str(local_path))

    return local_path


def download_csv_files_for_period(
    bucket_name: str | None,
    prefix: str,
    local_directory: str | Path,
    run_date: date | str | None = None,
    days_to_download: int = 1,
    *,
    role_arn: str | None = None,
    access_key: str | None = None,
    secret_key: str | None = None,
    session_name: str | None = None,
) -> list[Path]:
    if days_to_download < 1:
        raise ValueError("days_to_download must be 1 or greater.")

    bucket_name = _resolve_bucket_name(bucket_name)
    resolved_run_date = _resolve_run_date(run_date)
    target_dates = _get_target_dates(resolved_run_date, days_to_download)
    s3_client = _create_s3_client(
        role_arn=role_arn,
        access_key=access_key,
        secret_key=secret_key,
        session_name=session_name,
    )
    csv_files = _list_csv_files_with_client(s3_client, bucket_name, prefix)
    selected_files = _select_latest_file_per_date(csv_files, target_dates)
    downloaded_files: list[Path] = []

    for target_date in sorted(selected_files, reverse=True):
        csv_file = selected_files[target_date]
        local_file_name = _build_output_file_name(target_date)
        local_path = _build_local_path(local_directory, local_file_name)
        local_path.parent.mkdir(parents=True, exist_ok=True)
        s3_client.download_file(bucket_name, csv_file["s3_key"], str(local_path))
        downloaded_files.append(local_path)

    return downloaded_files


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


def _extract_file_date(file_name: str) -> date | None:
    date_match = FILE_DATE_PATTERN.search(file_name)
    if not date_match:
        return None

    try:
        return datetime.strptime(date_match.group(), "%Y-%m-%d").date()
    except ValueError:
        return None


def _resolve_run_date(run_date: date | str | None) -> date:
    if run_date is None:
        return date.today()

    if isinstance(run_date, date):
        return run_date

    return datetime.strptime(run_date, "%Y-%m-%d").date()


def _get_target_dates(run_date: date, days_to_download: int) -> set[date]:
    return {
        run_date - timedelta(days=day_offset)
        for day_offset in range(days_to_download)
    }


def _select_latest_file_per_date(
    csv_files: list[dict[str, Any]],
    target_dates: set[date],
) -> dict[date, dict[str, Any]]:
    selected_files: dict[date, dict[str, Any]] = {}

    for csv_file in csv_files:
        file_date = csv_file["file_date"]
        if file_date not in target_dates:
            continue

        selected_file = selected_files.get(file_date)
        if not selected_file or csv_file["last_modified"] > selected_file["last_modified"]:
            selected_files[file_date] = csv_file

    return selected_files


def _build_output_file_name(file_date: date) -> str:
    return f"{OUTPUT_FILE_PREFIX}_{file_date:%Y%m%d}.csv"


def _get_value(value: str | None, *environment_names: str) -> str | None:
    if value:
        return value

    for environment_name in environment_names:
        environment_value = os.getenv(environment_name)
        if environment_value:
            return environment_value

    return None
