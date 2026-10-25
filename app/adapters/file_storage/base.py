from abc import ABC, abstractmethod

class FileStorageError(Exception):
    pass

class StoredFileNotFound(FileStorageError):
    pass

class FileStorageAdapter(ABC):
    @abstractmethod
    def upload_file(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> str:
        pass

    @abstractmethod
    def get_download_url(self, key: str, expires_in: int = 3600) -> str:
        pass

    @abstractmethod
    def delete_file(self, key: str) -> None:
        pass