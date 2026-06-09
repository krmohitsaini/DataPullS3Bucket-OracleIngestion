from __future__ import annotations

import csv
import re
from datetime import datetime
from pathlib import Path


CREATED_DATE_COLUMN = "Created Date"
BP_STATUS_COLUMN = "BP_STATUS"
EFFECTIVE_DT_COLUMN = "EFFECTIVE_DT"
DATE_WITH_DASHES_PATTERN = re.compile(r"\d{4}-\d{2}-\d{2}")
DATE_WITHOUT_DASHES_PATTERN = re.compile(r"\d{8}")
DATE_WITH_SLASHES_PATTERN = re.compile(r"\d{1,2}/\d{1,2}/\d{4}")
DATE_COLUMNS_TO_NORMALIZE = [
    "Last Login",
    "Created Date",
    "mob_first_login",
    "mob_last_login",
]
EMPTY_DATE_VALUES = {"", "N/A", "NA", "NULL", "NONE"}

__all__ = ["process_csv_file"]


def process_csv_file(
    source_directory: str | Path,
    file_name: str,
    processed_directory: str | Path,
) -> Path:
    source_path = Path(source_directory).expanduser().resolve() / file_name
    processed_path = Path(processed_directory).expanduser().resolve() / file_name
    effective_date = _extract_effective_date(file_name)

    with source_path.open("r", encoding="utf-8-sig", newline="") as source_file:
        reader = csv.DictReader(source_file)
        fieldnames = _build_processed_fieldnames(reader.fieldnames)
        rows = [
            _build_processed_row(row, fieldnames, effective_date)
            for row in reader
        ]

    processed_path.parent.mkdir(parents=True, exist_ok=True)
    with processed_path.open("w", encoding="utf-8", newline="") as processed_file:
        writer = csv.DictWriter(processed_file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    return processed_path


def _build_processed_fieldnames(fieldnames: list[str] | None) -> list[str]:
    if not fieldnames:
        raise ValueError("CSV file does not have a header row.")

    if CREATED_DATE_COLUMN not in fieldnames:
        raise ValueError(f"CSV file is missing required column: {CREATED_DATE_COLUMN}")

    cleaned_fieldnames = [
        fieldname
        for fieldname in fieldnames
        if fieldname not in {BP_STATUS_COLUMN, EFFECTIVE_DT_COLUMN}
    ]

    created_date_index = cleaned_fieldnames.index(CREATED_DATE_COLUMN)
    return (
        cleaned_fieldnames[: created_date_index + 1]
        + [BP_STATUS_COLUMN, EFFECTIVE_DT_COLUMN]
        + cleaned_fieldnames[created_date_index + 1 :]
    )


def _build_processed_row(
    row: dict[str, str],
    fieldnames: list[str],
    effective_date: str,
) -> dict[str, str]:
    processed_row = {fieldname: row.get(fieldname, "") for fieldname in fieldnames}
    _normalize_date_columns(processed_row)
    processed_row[BP_STATUS_COLUMN] = ""
    processed_row[EFFECTIVE_DT_COLUMN] = effective_date
    return processed_row


def _normalize_date_columns(row: dict[str, str]) -> None:
    for column_name in DATE_COLUMNS_TO_NORMALIZE:
        if column_name in row:
            row[column_name] = _normalize_date_value(row[column_name])


def _normalize_date_value(value: str) -> str:
    cleaned_value = value.strip()
    if cleaned_value.upper() in EMPTY_DATE_VALUES:
        return cleaned_value

    date_with_dashes = DATE_WITH_DASHES_PATTERN.search(cleaned_value)
    if date_with_dashes:
        return date_with_dashes.group()

    date_with_slashes = DATE_WITH_SLASHES_PATTERN.search(cleaned_value)
    if date_with_slashes:
        parsed_date = datetime.strptime(date_with_slashes.group(), "%m/%d/%Y")
        return parsed_date.strftime("%Y-%m-%d")

    return cleaned_value


def _extract_effective_date(file_name: str) -> str:
    date_with_dashes = DATE_WITH_DASHES_PATTERN.search(file_name)
    if date_with_dashes:
        return date_with_dashes.group()

    date_without_dashes = DATE_WITHOUT_DASHES_PATTERN.search(file_name)
    if date_without_dashes:
        parsed_date = datetime.strptime(date_without_dashes.group(), "%Y%m%d")
        return parsed_date.strftime("%Y-%m-%d")

    raise ValueError(f"Could not find date in file name: {file_name}")
