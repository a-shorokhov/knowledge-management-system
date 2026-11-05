import logging

from adapters.ai.yandex import AIError
from adapters.file_storage.base import FileStorageError
from services.document_extraction import extract_chunks


logger = logging.getLogger(__name__)


class IndexingService:
    def __init__(self, repository, storage, ai, bucket):
        self.repository = repository
        self.storage = storage
        self.ai = ai
        self.bucket = bucket

    def process_next(self):
        file = self.repository.claim()
        if file is None:
            return False
        try:
            if file['bucket'] != self.bucket:
                raise AIError('INDEX_BUCKET_MISMATCH', 'Хранилище файла не настроено')
            data = self.storage.read_file(file['storage_key'])
            if len(data) != file['size_bytes']:
                raise AIError('INDEX_FILE_CHANGED', 'Размер объекта не совпадает с записью файла')
            chunks = extract_chunks(data, file['original_filename'])
            for chunk in chunks:
                chunk['embedding'] = self.ai.embed(chunk['content'])
            self.repository.finish(file['id'], chunks)
            logger.info('index_finished file_id=%s chunks=%s', file['id'], len(chunks))
        except (AIError, FileStorageError) as error:
            self.repository.fail(file['id'], error.code if isinstance(error, AIError) else 'INDEX_STORAGE_ERROR')
            logger.warning('index_failed file_id=%s code=%s', file['id'], error.code if isinstance(error, AIError) else 'INDEX_STORAGE_ERROR')
        except Exception:
            self.repository.fail(file['id'], 'INDEX_INTERNAL_ERROR')
            logger.error('index_failed file_id=%s code=INDEX_INTERNAL_ERROR', file['id'])
        finally:
            self.repository.release()
        return True

    def reindex(self, file_id, user_id):
        from core.exceptions import FileNotFoundException, FileDeletionPendingException
        result = self.repository.reindex(file_id, user_id)
        if result is None:
            raise FileNotFoundException()
        if result == 'deletion_pending':
            raise FileDeletionPendingException()
        if result == 'processing':
            raise AIError('INDEX_ALREADY_PROCESSING', 'Файл уже обрабатывается', 409)
        return result
