import boto3
from botocore.config import Config
from botocore.exceptions import ClientError, BotoCoreError

from adapters.file_storage.base import FileStorageAdapter, FileStorageError, StoredFileNotFound


class S3FileStorageAdapter(FileStorageAdapter):
    def __init__(
        self,
        bucket_name: str,
        access_key: str,
        secret_key: str,
        region_name: str = "ru-central1",
        url: str = "https://storage.yandexcloud.net",
    ):
        self.bucket_name = bucket_name
        self.client = boto3.client(
            "s3",
            endpoint_url=url,
            region_name=region_name,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            config=Config(
                signature_version="s3v4",
                connect_timeout=5,
                read_timeout=30,
                retries={"max_attempts": 3, "mode": "standard"},
            ),
        )

    def upload_file(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> str:
        try:
            self.client.put_object(
                Bucket=self.bucket_name,
                Key=key,
                Body=data,
                ContentType=content_type,
            )
        except (ClientError, BotoCoreError) as error:
            raise FileStorageError("Не удалось загрузить файл в хранилище") from error

        return key

    def get_download_url(self, key: str, expires_in: int = 3600) -> str:
        try:
            self.client.head_object(Bucket=self.bucket_name, Key=key)

            return self.client.generate_presigned_url(
                "get_object",
                Params={"Bucket": self.bucket_name, "Key": key},
                ExpiresIn=expires_in,
            )

        except ClientError as error:
            if error.response["Error"]["Code"] in {"404", "NoSuchKey", "NotFound"}:
                raise StoredFileNotFound("Файл не найден в хранилище") from error

            raise FileStorageError("Не удалось получить ссылку на файл") from error

        except BotoCoreError as error:
            raise FileStorageError("Хранилище файлов недоступно") from error

    def delete_file(self, key: str) -> None:
        try:
            self.client.delete_object(Bucket=self.bucket_name, Key=key)
        except (ClientError, BotoCoreError) as error:
            raise FileStorageError("Не удалось удалить файл из хранилища") from error