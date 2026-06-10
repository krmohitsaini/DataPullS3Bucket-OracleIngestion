from __future__ import annotations

import re
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable

import oracledb
import pandas as pd

from process_data import (
    COLUMN_RENAME_MAPPING,
    DATE_COLUMNS_TO_NORMALIZE,
    EFFECTIVE_DT_COLUMN,
    process_csv_file,
)


ORACLE_IDENTIFIER = re.compile(r"^[A-Za-z][A-Za-z0-9_$#]*$")
PROCESSED_FILE_PATTERN = re.compile(r"^(?P<table_name>.+_\d{8})\.csv$")
UPLOAD_LOG_FILE = "upload_log.txt"
ACTION_CREATED_TABLE = "Created table"
ACTION_APPENDED = "Appended"
ACTION_SKIPPED = "Skipped"
ACTION_INVALID_NAME = "Invalid name"

COLUMN_NAME_REPLACEMENTS = {
    "DATE": "EVENT_DATE",
}
COLUMN_TYPE_OVERRIDES = {
    "BP_STATUS": "VARCHAR2(65)",
}
ORACLE_DATE_COLUMNS = [
    EFFECTIVE_DT_COLUMN,
    *DATE_COLUMNS_TO_NORMALIZE,
]


@dataclass(frozen=True)
class ProcessedFile:
    source_path: Path
    processed_path: Path
    table_name: str
    data: pd.DataFrame


def push_files(
    file_paths: str | Path | Iterable[str | Path],
    oracle_user: str,
    oracle_password: str,
    oracle_dsn: str,
    processed_directory: str | Path,
    uploaded_directory: str | Path | None = None,
    log_directory: str | Path | None = None,
    invalid_directory: str | Path | None = None,
) -> None:
    source_files = _get_file_paths(file_paths)
    skipped_log_entries = []

    source_files, invalid_files = _split_invalid_files(source_files)
    invalid_log_entries = _get_invalid_log_entries(invalid_files)

    if invalid_directory:
        archive_files(invalid_files, invalid_directory, force_rename=True)

    if log_directory:
        append_upload_log(invalid_log_entries, log_directory)

    if uploaded_directory:
        source_files, skipped_files = _split_archived_files(
            source_files,
            uploaded_directory,
        )
        archive_files(skipped_files, uploaded_directory, force_rename=True)
        skipped_log_entries.extend(_get_skipped_log_entries(skipped_files))

    if log_directory:
        source_files, skipped_files = _split_logged_files(source_files, log_directory)

        if uploaded_directory:
            archive_files(skipped_files, uploaded_directory, force_rename=True)

        skipped_log_entries.extend(_get_skipped_log_entries(skipped_files))
        append_upload_log(skipped_log_entries, log_directory)

    processed_files = process_files(source_files, processed_directory)
    if not processed_files:
        return

    with oracledb.connect(
        user=oracle_user,
        password=oracle_password,
        dsn=oracle_dsn,
    ) as connection:
        upload_log_entries = push_processed_files(connection, processed_files)

    if log_directory:
        append_upload_log(upload_log_entries, log_directory)

    if uploaded_directory:
        archive_processed_files(processed_files, uploaded_directory)


def find_files(directory: str | Path) -> list[Path]:
    return sorted(
        file_path
        for file_path in Path(directory).expanduser().resolve().iterdir()
        if file_path.is_file() and file_path.suffix.lower() == ".csv"
    )


def get_file_details(file_path: str | Path) -> tuple[str, str]:
    file_name = Path(file_path).name
    match = PROCESSED_FILE_PATTERN.fullmatch(file_name)

    if not match:
        raise ValueError("expected file name format: table_name_YYYYMMDD.csv")

    table_name = _sanitize_column_name(match.group("table_name"))
    file_date = match.group("table_name")[-8:]
    return table_name, file_date


def process_files(
    file_paths: Iterable[str | Path],
    processed_directory: str | Path,
) -> dict[str, list[ProcessedFile]]:
    processed_files: dict[str, list[ProcessedFile]] = {}

    for file_path in file_paths:
        source_path = Path(file_path)
        table_name, _file_date = get_file_details(source_path)
        processed_path = process_csv_file(
            source_path.parent,
            source_path.name,
            processed_directory,
        )
        dataframe = pd.read_csv(processed_path, dtype=str)
        _convert_date_columns(dataframe)
        processed_files.setdefault(table_name, []).append(
            ProcessedFile(
                source_path=source_path,
                processed_path=processed_path,
                table_name=table_name,
                data=dataframe,
            )
        )

    return processed_files


def _convert_date_columns(dataframe: pd.DataFrame) -> None:
    for column_name in ORACLE_DATE_COLUMNS:
        output_column_name = COLUMN_RENAME_MAPPING.get(column_name, column_name)
        if output_column_name in dataframe.columns:
            dataframe[output_column_name] = pd.to_datetime(
                dataframe[output_column_name],
                errors="coerce",
            )


def push_processed_files(
    connection,
    processed_files: dict[str, list[ProcessedFile]],
) -> list[tuple[str, int | None, str, int | None, str | None]]:
    upload_log_entries = []

    try:
        for table_name, files_for_table in processed_files.items():
            for processed_file in files_for_table:
                rows_read = len(processed_file.data)
                action = push_dataframe(connection, table_name, processed_file.data)
                if action:
                    upload_log_entries.append(
                        (
                            processed_file.source_path.name,
                            rows_read,
                            action,
                            rows_read,
                            table_name,
                        )
                    )
                print(
                    f"Inserted {rows_read} rows from "
                    f"{processed_file.source_path.name} into {table_name}"
                )

        connection.commit()
        return upload_log_entries
    except Exception:
        connection.rollback()
        raise


def push_dataframe(connection, table_name: str, dataframe: pd.DataFrame) -> str | None:
    if dataframe.empty:
        return None

    _validate_identifier(table_name)
    columns = _sanitize_column_names(dataframe.columns)

    if not table_exists(connection, table_name):
        create_table(connection, table_name, dataframe)
        action = ACTION_CREATED_TABLE
    else:
        action = ACTION_APPENDED

    column_list = ", ".join(columns)
    bind_variables = ", ".join(f":{number}" for number in range(1, len(columns) + 1))
    insert_sql = f"INSERT INTO {table_name} ({column_list}) VALUES ({bind_variables})"
    rows = [
        tuple(_to_oracle_value(value) for value in row)
        for row in dataframe.itertuples(index=False, name=None)
    ]

    with connection.cursor() as cursor:
        cursor.executemany(insert_sql, rows)

    return action


def table_exists(connection, table_name: str) -> bool:
    _validate_identifier(table_name)

    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT COUNT(*) FROM user_tables WHERE table_name = :1",
            [table_name.upper()],
        )
        return cursor.fetchone()[0] > 0


def create_table(connection, table_name: str, dataframe: pd.DataFrame) -> None:
    _validate_identifier(table_name)
    column_definitions = []
    column_names = _sanitize_column_names(dataframe.columns)

    for column, column_name in zip(dataframe.columns, column_names):
        oracle_type = _get_column_oracle_type(column_name, dataframe[column])
        column_definitions.append(f"{column_name} {oracle_type}")

    create_sql = f"CREATE TABLE {table_name} ({', '.join(column_definitions)})"

    with connection.cursor() as cursor:
        cursor.execute(create_sql)

    print(f"Created table {table_name}")


def archive_processed_files(
    processed_files: dict[str, list[ProcessedFile]],
    uploaded_directory: str | Path,
) -> None:
    file_paths = [
        processed_file.source_path
        for files_for_table in processed_files.values()
        for processed_file in files_for_table
    ]
    archive_files(file_paths, uploaded_directory)


def archive_files(
    file_paths: Iterable[str | Path],
    uploaded_directory: str | Path,
    force_rename: bool = False,
) -> None:
    uploaded_path = Path(uploaded_directory)
    uploaded_path.mkdir(parents=True, exist_ok=True)

    for file_path in file_paths:
        source_path = Path(file_path)
        destination = _get_archive_destination(
            uploaded_path,
            source_path.name,
            force_rename=force_rename,
        )
        shutil.move(str(source_path), str(destination))
        print(f"Moved {source_path.name} to {destination}")


def read_logged_file_names(log_directory: str | Path) -> set[str]:
    log_path = _get_upload_log_path(log_directory)
    if not log_path.exists():
        return set()

    uploaded_file_names = set()

    for line in log_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue

        file_name = _get_logged_file_name(line)
        if file_name:
            uploaded_file_names.add(file_name)

    return uploaded_file_names


def append_upload_log(
    upload_log_entries: list[tuple[str, int | None, str, int | None, str | None]],
    log_directory: str | Path,
) -> None:
    if not upload_log_entries:
        return

    log_path = _get_upload_log_path(log_directory)
    log_path.parent.mkdir(parents=True, exist_ok=True)

    with log_path.open("a", encoding="utf-8") as log_file:
        for file_name, rows_read, action, rows_added, table_name in upload_log_entries:
            log_file.write(
                _format_upload_log_entry(
                    file_name,
                    rows_read,
                    action,
                    rows_added,
                    table_name,
                )
            )


def _get_file_paths(
    file_paths: str | Path | Iterable[str | Path],
) -> list[Path]:
    if isinstance(file_paths, (str, Path)):
        path = Path(file_paths)

        if path.is_dir():
            return find_files(path)

        return [path]

    return [Path(path) for path in file_paths]


def _split_invalid_files(file_paths: list[Path]) -> tuple[list[Path], list[Path]]:
    valid_files = []
    invalid_files = []

    for file_path in file_paths:
        try:
            get_file_details(file_path)
        except ValueError as error:
            print(f"Skipped {file_path.name}: invalid file name ({error})")
            invalid_files.append(file_path)
        else:
            valid_files.append(file_path)

    return valid_files, invalid_files


def _split_archived_files(
    file_paths: list[Path],
    uploaded_directory: str | Path,
) -> tuple[list[Path], list[Path]]:
    uploaded_path = Path(uploaded_directory)
    uploaded_path.mkdir(parents=True, exist_ok=True)
    new_files = []
    skipped_files = []

    for file_path in file_paths:
        if _is_inside_directory(file_path, uploaded_path):
            continue

        if (uploaded_path / file_path.name).exists():
            print(f"Skipped {file_path.name}: already uploaded to Oracle")
            skipped_files.append(file_path)
        else:
            new_files.append(file_path)

    return new_files, skipped_files


def _split_logged_files(
    file_paths: list[Path],
    log_directory: str | Path,
) -> tuple[list[Path], list[Path]]:
    uploaded_file_names = read_logged_file_names(log_directory)
    new_files = []
    skipped_files = []

    for file_path in file_paths:
        if file_path.name in uploaded_file_names:
            print(f"Skipped {file_path.name}: already found in upload log")
            skipped_files.append(file_path)
        else:
            new_files.append(file_path)

    return new_files, skipped_files


def _get_skipped_log_entries(
    file_paths: Iterable[Path],
) -> list[tuple[str, int | None, str, int | None, str | None]]:
    return [
        (file_path.name, None, ACTION_SKIPPED, None, None)
        for file_path in file_paths
    ]


def _get_invalid_log_entries(
    file_paths: Iterable[Path],
) -> list[tuple[str, int | None, str, int | None, str | None]]:
    return [
        (file_path.name, None, ACTION_INVALID_NAME, None, None)
        for file_path in file_paths
    ]


def _get_logged_file_name(line: str) -> str:
    log_entry = line.strip()
    if " : " in log_entry:
        log_entry = log_entry.split(" : ", maxsplit=1)[1].strip()

    return log_entry.split(" -> ", maxsplit=1)[0].strip()


def _format_upload_log_entry(
    file_name: str,
    rows_read: int | None,
    action: str,
    rows_added: int | None,
    table_name: str | None,
) -> str:
    logged_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_entry = f"{logged_at} : {file_name}"

    if rows_read is not None:
        log_entry = f"{log_entry} -> {rows_read} rows read"

    log_entry = f"{log_entry} -> {action}"

    if rows_added is not None:
        log_entry = f"{log_entry} -> {rows_added} rows added"

    if table_name:
        log_entry = f"{log_entry} -> {table_name}"

    return f"{log_entry}\n"


def _get_upload_log_path(log_directory: str | Path) -> Path:
    return Path(log_directory) / UPLOAD_LOG_FILE


def _get_archive_destination(
    uploaded_directory: Path,
    file_name: str,
    force_rename: bool = False,
) -> Path:
    destination = uploaded_directory / file_name
    if not force_rename and not destination.exists():
        return destination

    file_path = Path(file_name)
    uploaded_at = datetime.now().strftime("%Y%m%d_%H%M%S")
    destination = uploaded_directory / f"{file_path.stem}_{uploaded_at}{file_path.suffix}"
    duplicate_number = 1

    while destination.exists():
        destination = uploaded_directory / (
            f"{file_path.stem}_{uploaded_at}_{duplicate_number}{file_path.suffix}"
        )
        duplicate_number += 1

    return destination


def _is_inside_directory(file_path: Path, directory: Path) -> bool:
    try:
        file_path.resolve().relative_to(directory.resolve())
        return True
    except ValueError:
        return False


def _get_oracle_type(series: pd.Series) -> str:
    if pd.api.types.is_bool_dtype(series):
        return "CHAR(1)"

    if pd.api.types.is_datetime64_any_dtype(series):
        return "DATE"

    max_length = series.dropna().astype(str).str.len().max()
    max_length = 1 if pd.isna(max_length) else int(max_length)

    if max_length > 4000:
        return "CLOB"

    max_length = max(255, max_length)
    return f"VARCHAR2({max_length})"


def _get_column_oracle_type(column_name: str, series: pd.Series) -> str:
    override_type = COLUMN_TYPE_OVERRIDES.get(column_name)
    if override_type:
        _validate_column_type_override(column_name, override_type)
        return override_type

    return _get_oracle_type(series)


def _validate_column_type_override(column_name: str, oracle_type: str) -> None:
    if ";" in oracle_type or "--" in oracle_type or "/*" in oracle_type:
        raise ValueError(f"Invalid Oracle type override for {column_name}: {oracle_type}")


def _sanitize_column_names(columns) -> list[str]:
    sanitized_columns = [_sanitize_column_name(column) for column in columns]

    if len(sanitized_columns) != len(set(sanitized_columns)):
        raise ValueError(
            "Two or more source columns become the same Oracle column name after "
            f"sanitization: {sanitized_columns}"
        )

    return sanitized_columns


def _sanitize_column_name(column) -> str:
    column_name = re.sub(r"[^A-Za-z0-9_$#]+", "_", str(column))
    column_name = column_name.strip("_").upper()

    if not column_name:
        raise ValueError(f"Could not create an Oracle column name from: {column}")

    if not column_name[0].isalpha():
        column_name = f"COLUMN_{column_name}"

    column_name = COLUMN_NAME_REPLACEMENTS.get(column_name, column_name)

    _validate_identifier(column_name)
    return column_name


def _validate_identifier(identifier: str) -> None:
    if not ORACLE_IDENTIFIER.fullmatch(identifier):
        raise ValueError(f"Invalid Oracle identifier: {identifier}")


def _to_oracle_value(value):
    if pd.isna(value):
        return None

    if isinstance(value, pd.Timestamp):
        return value.to_pydatetime()

    return value
