# S3 CSV Downloader

Simple Python utility to list CSV files from an S3 bucket folder/prefix and download a selected CSV file to a local directory.

## Requirements

- Python 3.9+
- AWS access to the S3 bucket
- `boto3`

Install the dependency:

```bash
pip install boto3
```

## AWS Credentials

The script uses the default AWS credential lookup from `boto3`.

Any of these will work:

- AWS CLI credentials from `aws configure`
- Environment variables such as `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY`
- AWS SSO/profile login
- IAM role credentials when running on AWS

## Configure `main.py`

Update these values in `main.py`:

```python
BUCKET_NAME = "your-bucket-name"
S3_FOLDER_PREFIX = "your/folder/prefix/"
LOCAL_DIRECTORY = "./downloaded_csv"
FILE_NAME_TO_DOWNLOAD = "your-file.csv"
```

Then run:

```bash
python3 main.py
```

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
- `last_modified`
- `size_bytes`

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

## Notes

- `prefix` is the S3 folder path, for example `reports/daily/`.
- The downloaded file is saved using only the CSV filename, not the full S3 folder path.
- Only files ending with `.csv` are listed or downloaded.
