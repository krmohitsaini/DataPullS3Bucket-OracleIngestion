import os
from datetime import date

from download_data import download_csv_files_for_period, list_csv_files
from process_data import process_csv_file


BUCKET_NAME = os.getenv("DEFAULT_BUCKET")
S3_FOLDER_PREFIX = "replace-with-your-folder-prefix/"
LOCAL_DIRECTORY = "./downloaded_csv"
PROCESSED_DIRECTORY = "Processed"
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

    processed_files = [
        process_csv_file(
            downloaded_file.parent,
            downloaded_file.name,
            PROCESSED_DIRECTORY,
        )
        for downloaded_file in downloaded_files
    ]

    print("\nProcessed files:")
    for processed_file in processed_files:
        print(f"- {processed_file}")


if __name__ == "__main__":
    main()
