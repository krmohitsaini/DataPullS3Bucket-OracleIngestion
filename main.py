import os
from datetime import date

from download_data import download_csv_files_for_period, list_csv_files
from push_files import push_files


BUCKET_NAME = os.getenv("DEFAULT_BUCKET")
ORACLE_USER = os.getenv("ORACLE_USER")
ORACLE_PASSWORD = os.getenv("ORACLE_PASSWORD")
ORACLE_DSN = os.getenv("ORACLE_DSN")
S3_FOLDER_PREFIX = "replace-with-your-folder-prefix/"
LOCAL_DIRECTORY = "./downloaded_csv"
PROCESSED_DIRECTORY = "Processed"
UPLOADED_DIRECTORY = "Uploaded"
LOG_DIRECTORY = "Logs"
INVALID_DIRECTORY = "Invalid"
RUN_DATE = date.today()
DAYS_TO_DOWNLOAD = 1


def main() -> None:
    csv_files = list_csv_files(BUCKET_NAME, S3_FOLDER_PREFIX)

    print(f"Available CSV files in s3://{BUCKET_NAME}/{S3_FOLDER_PREFIX}")
    for csv_file in csv_files:
        print(
            f"- {csv_file['file_name']} "
            f"(file date: {csv_file['file_date']}, "
            f"modified: {csv_file['last_modified']}, "
            f"size: {csv_file['size_bytes']} bytes)"
        )

    downloaded_files = download_csv_files_for_period(
        BUCKET_NAME,
        S3_FOLDER_PREFIX,
        LOCAL_DIRECTORY,
        RUN_DATE,
        DAYS_TO_DOWNLOAD,
    )

    if not downloaded_files:
        print("\nNo CSV files matched the requested date range.")
        return

    print("\nDownloaded files:")
    for downloaded_file in downloaded_files:
        print(f"- {downloaded_file}")

    _validate_oracle_config()
    push_files(
        downloaded_files,
        ORACLE_USER,
        ORACLE_PASSWORD,
        ORACLE_DSN,
        processed_directory=PROCESSED_DIRECTORY,
        uploaded_directory=UPLOADED_DIRECTORY,
        log_directory=LOG_DIRECTORY,
        invalid_directory=INVALID_DIRECTORY,
    )

    print("\nPushed downloaded files to Oracle.")


def _validate_oracle_config() -> None:
    missing_values = [
        name
        for name, value in {
            "ORACLE_USER": ORACLE_USER,
            "ORACLE_PASSWORD": ORACLE_PASSWORD,
            "ORACLE_DSN": ORACLE_DSN,
        }.items()
        if not value
    ]

    if missing_values:
        raise ValueError(
            "Missing Oracle environment variables: "
            + ", ".join(missing_values)
        )


if __name__ == "__main__":
    main()
