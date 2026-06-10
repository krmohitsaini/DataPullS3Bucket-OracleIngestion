# S3 CSV Downloader

Simple Python utility to list CSV files from an S3 bucket folder/prefix and download date-based CSV files to a local directory.

## Requirements

- Python 3.9+
- AWS access to the S3 bucket
- `boto3`
- `pandas`
- `oracledb`

Install the dependency:

```bash
pip install boto3 pandas oracledb
```

## AWS Credentials

The script can assume an AWS role using these environment variables:

```bash
export ROLE_ARN="arn:aws:iam::123456789012:role/your-role"
export ACCESS_KEY="your-access-key"
export SECRET_KEY="your-secret-key"
export SESSION_NAME="s3-csv-downloader-session"
export DEFAULT_BUCKET="your-bucket-name"
```

PowerShell:

```powershell
$env:ROLE_ARN="arn:aws:iam::123456789012:role/your-role"
$env:ACCESS_KEY="your-access-key"
$env:SECRET_KEY="your-secret-key"
$env:SESSION_NAME="s3-csv-downloader-session"
$env:DEFAULT_BUCKET="your-bucket-name"
```

Do not hardcode real access keys in the Python files.

If `ROLE_ARN` is present, the script uses `ACCESS_KEY` and `SECRET_KEY` to assume that role through AWS STS, then uses the temporary role credentials to access S3.

If `ROLE_ARN` is not present, the script can still use:

- `ACCESS_KEY` and `SECRET_KEY` directly
- Standard `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY`
- AWS CLI credentials from `aws configure`
- IAM role credentials when running on AWS

## Oracle Credentials

Set these environment variables before running `main.py`:

```bash
export ORACLE_USER="your-oracle-user"
export ORACLE_PASSWORD="your-oracle-password"
export ORACLE_DSN="host:port/service"
```

PowerShell:

```powershell
$env:ORACLE_USER="your-oracle-user"
$env:ORACLE_PASSWORD="your-oracle-password"
$env:ORACLE_DSN="host:port/service"
```

## Configure `main.py`

Update these values in `main.py`:

```python
S3_FOLDER_PREFIX = "your/folder/prefix/"
LOCAL_DIRECTORY = "./downloaded_csv"
PROCESSED_DIRECTORY = "Processed"
UPLOADED_DIRECTORY = "Uploaded"
LOG_DIRECTORY = "Logs"
INVALID_DIRECTORY = "Invalid"
RUN_DATE = date.today()
DAYS_TO_DOWNLOAD = 1
```

`BUCKET_NAME` is read from the `DEFAULT_BUCKET` environment variable.

`DAYS_TO_DOWNLOAD = 1` downloads only the file for `RUN_DATE`. Use a larger value for backfills. For example, `DAYS_TO_DOWNLOAD = 7` downloads files for `RUN_DATE` and the previous six days.

Then run:

```bash
python3 main.py
```

The script downloads matching CSV files, then calls `push_files.py`. That flow processes each downloaded file into `PROCESSED_DIRECTORY`, inserts it into Oracle, writes upload logs, and archives successfully uploaded source files.

## Available Functions

### List CSV files

```python
from download_data import list_csv_files

csv_files = list_csv_files(
    bucket_name="your-bucket-name",
    prefix="your/folder/prefix/",
)

for csv_file in csv_files:
    print(csv_file["file_name"])
```

Each item contains:

- `file_name`
- `s3_key`
- `file_date`
- `last_modified`
- `size_bytes`

### Download files for a date period

```python
from datetime import date

from download_data import download_csv_files_for_period

downloaded_paths = download_csv_files_for_period(
    bucket_name="your-bucket-name",
    prefix="your/folder/prefix/",
    local_directory="./downloaded_csv",
    run_date=date.today(),
    days_to_download=1,
)

for downloaded_path in downloaded_paths:
    print(downloaded_path)
```

This finds CSV files that contain a date in the filename, such as:

```text
dynamo-oam-user-data-2026-06-08-040006.csv
```

Downloaded files are renamed locally to:

```text
dynamo_oam_YYYYMMDD.csv
```

For example:

```text
dynamo_oam_20260608.csv
```

### Download one CSV file

```python
from download_data import download_csv_file

downloaded_path = download_csv_file(
    bucket_name="your-bucket-name",
    prefix="your/folder/prefix/",
    file_name="your-file.csv",
    local_directory="./downloaded_csv",
)

print(downloaded_path)
```

The local directory is created automatically if it does not exist.

### Process a downloaded CSV file

```python
from process_data import process_csv_file

processed_path = process_csv_file(
    source_directory="./downloaded_csv",
    file_name="dynamo_oam_20260609.csv",
    processed_directory="Processed",
)

print(processed_path)
```

The processed file keeps the same filename and adds these columns immediately after `Created Date`:

- `BP_STATUS`, left blank
- `EFFECTIVE_DT`, filled for every row from the date in the filename

For `dynamo_oam_20260609.csv`, `EFFECTIVE_DT` is written as `2026-06-09`.

Date columns are also normalized to `YYYY-MM-DD` with the time removed. Add or remove column names in `process_data.py`:

```python
DATE_COLUMNS_TO_NORMALIZE = [
    "Last Login",
    "Created Date",
    "mob_first_login",
    "mob_last_login",
]
```

Values like `3/31/2025 10:29 AM`, `2026-03-13 11:36:08 PM CST`, and `2025-11-14 10:11:12 AM CDT` become `YYYY-MM-DD`. Values like `N/A`, blank, and `NULL` become blank in the processed CSV, then become Oracle `NULL` when pushed.

Columns can be renamed in `process_data.py`. Missing source columns are ignored automatically:

```python
COLUMN_RENAME_MAPPING = {
    "Old BpId": "BP_ID",
    "SubId": "SUB_ID",
}
```

After renaming, selected columns can be left-padded with zeroes:

```python
LEFT_PAD_COLUMNS = (
    ("BP_ID", 10),
    ("SUB_ID", 8),
)
```

For example, `12345` in `BP_ID` becomes `0000012345` when the configured length is `10`.

### Push files to Oracle

```python
from push_files import push_files

push_files(
    file_paths="./downloaded_csv",
    oracle_user="your-oracle-user",
    oracle_password="your-oracle-password",
    oracle_dsn="host:port/service",
    processed_directory="Processed",
    uploaded_directory="Uploaded",
    log_directory="Logs",
    invalid_directory="Invalid",
)
```

`push_files(...)` accepts one file path, one directory, or multiple file paths.

It skips invalid file names, skips files already archived or logged, processes valid files with `process_data.py`, creates Oracle tables when needed, appends rows with `executemany(...)`, writes `upload_log.txt`, and moves successfully uploaded source files into `UPLOADED_DIRECTORY`.

The Oracle table name is created from the full CSV filename without `.csv`. For example, `dynamo_oam_20260609.csv` is loaded into table `DYNAMO_OAM_20260609`.

Specific Oracle column types can be configured in `push_files.py`. Any column not listed here uses automatic type inference:

```python
COLUMN_TYPE_OVERRIDES = {
    "BP_STATUS": "VARCHAR2(65)",
}
```

You can also pass credentials directly if needed:

```python
csv_files = list_csv_files(
    bucket_name="your-bucket-name",
    prefix="your/folder/prefix/",
    role_arn="arn:aws:iam::123456789012:role/your-role",
    access_key="your-access-key",
    secret_key="your-secret-key",
    session_name="s3-csv-downloader-session",
)
```

## Notes

- `prefix` is the S3 folder path, for example `reports/daily/`.
- Date-based downloads look for the first `YYYY-MM-DD` value found in each CSV filename.
- Date-based downloads save files as `dynamo_oam_YYYYMMDD.csv`.
- Single-file downloads save using the original CSV filename unless you pass `local_file_name`.
- Processed files are saved with the same filename in `PROCESSED_DIRECTORY`.
- Successfully uploaded source files are moved to `UPLOADED_DIRECTORY`.
- Upload and skip entries are written to `upload_log.txt` when `LOG_DIRECTORY` is provided.
- Only files ending with `.csv` are listed or downloaded.
