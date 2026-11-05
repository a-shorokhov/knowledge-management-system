import logging
import time

from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

import models
from adapters.ai.yandex import YandexAIAdapter
from adapters.file_storage.s3 import S3FileStorageAdapter
from core.config import DB_URL, settings
from repositories.indexing import IndexingRepository
from services.indexing import IndexingService


logger = logging.getLogger(__name__)


def main():
    logging.basicConfig(level=logging.INFO)
    engine = create_engine(DB_URL, hide_parameters=True, poolclass=NullPool)
    try:
        while True:
            if not settings.AI_ENABLED:
                time.sleep(5)
                continue
            ai = YandexAIAdapter(settings)
            storage = S3FileStorageAdapter(settings.S3_BUCKET, settings.S3_ACCESS_KEY,
                settings.S3_SECRET_KEY.get_secret_value(), settings.S3_REGION, settings.S3_ENDPOINT)
            try:
                with engine.connect() as connection, Session(bind=connection) as db:
                    service = IndexingService(IndexingRepository(db), storage, ai, settings.S3_BUCKET)
                    processed = service.process_next()
                if not processed:
                    time.sleep(2)
            except Exception:
                logger.error('worker_iteration_failed; retry in 5 seconds')
                time.sleep(5)
            finally:
                ai.close()
                storage.client.close()
    finally:
        engine.dispose()


if __name__ == '__main__':
    main()
