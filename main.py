import os

from download_data import download_csv_file, list_csv_files


BUCKET_NAME = os.getenv("DEFAULT_BUCKET")
S3_FOLDER_PREFIX = "replace-with-your-folder-prefix/"
LOCAL_DIRECTORY = "./downloaded_csv"
FILE_NAME_TO_DOWNLOAD = "replace-with-file-name.csv"


def main() -> None:
    csv_files = list_csv_files(BUCKET_NAME, S3_FOLDER_PREFIX)

    print(f"Available CSV files in s3://{BUCKET_NAME}/{S3_FOLDER_PREFIX}")
    for csv_file in csv_files:
        print(
            f"- {csv_file['file_name']} "
            f"(modified: {csv_file['last_modified']}, "
            f"size: {csv_file['size_bytes']} bytes)"
        )

    downloaded_file = download_csv_file(
        BUCKET_NAME,
        S3_FOLDER_PREFIX,
        FILE_NAME_TO_DOWNLOAD,
        LOCAL_DIRECTORY,
    )

    print(f"\nDownloaded: {downloaded_file}")


if __name__ == "__main__":
    main()
