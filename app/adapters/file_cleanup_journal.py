"""Durable local queue. Requires a shared, local POSIX filesystem."""
from contextlib import contextmanager
import fcntl
import json
import math
import os
from pathlib import Path
import re
import tempfile
import time
from uuid import uuid4


class JournalError(Exception):
    pass


class CleanupJob:
    def __init__(self, journal, data):
        self.journal = journal
        self.data = data

    def update(self, **changes):
        data = {**self.data, **changes, 'updated_at': time.time()}
        self.journal.write(data)
        self.data = data

    def attempt(self):
        now = time.time()
        attempts = self.data['attempts'] + 1
        self.update(attempts=attempts, last_attempt_at=now,
                    next_attempt_at=now + min(3600, 5 * 2 ** min(attempts, 10)))

    def complete(self):
        try:
            self.journal.path(self.data['id']).unlink(missing_ok=True)
            self.journal.sync_directory(self.journal.directory)
        except OSError as error:
            raise JournalError('Cannot finish cleanup job') from error


class FileCleanupJournal:
    def __init__(self, directory):
        self.directory = Path(directory)

    @staticmethod
    def sync_directory(directory):
        fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)

    def prepare(self):
        try:
            # Persist newly created directory entries as well as job entries.
            missing = []
            parent = self.directory
            while not parent.exists():
                missing.append(parent)
                parent = parent.parent
            for directory in reversed(missing):
                directory.mkdir(mode=0o700, exist_ok=True)
                self.sync_directory(directory.parent)
            self.sync_directory(self.directory)
        except OSError as error:
            raise JournalError('Cleanup journal is unavailable') from error

    def path(self, job_id):
        if not isinstance(job_id, str) or re.fullmatch('[0-9a-f]{32}', job_id) is None:
            raise JournalError('Invalid cleanup job ID')
        return self.directory / f'{job_id}.json'

    @contextmanager
    def lock(self, job_id, blocking):
        self.path(job_id)
        # Permanent striped lock inodes are never replaced/unlinked. Replacing
        # JSON files cannot split a lock between competing processes.
        self.prepare()
        try:
            fd = os.open(self.directory / f'.lock-{int(job_id[:2], 16) % 64:02d}',
                         os.O_CREAT | os.O_RDWR, 0o600)
        except OSError as error:
            raise JournalError('Cannot open cleanup lock') from error
        acquired = False
        try:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB))
                acquired = True
            except BlockingIOError:
                pass
            except OSError as error:
                raise JournalError('Cannot lock cleanup job') from error
            yield acquired
        finally:
            os.close(fd)

    def write(self, data):
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=self.directory,
                                             prefix='.job-', delete=False) as output:
                temporary = Path(output.name)
                json.dump(data, output, ensure_ascii=False, allow_nan=False)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, self.path(data['id']))
            self.sync_directory(self.directory)
        except OSError as error:
            raise JournalError('Cannot persist cleanup job') from error
        finally:
            if temporary is not None:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    pass  # An unrenamed temporary file cannot reference a PUT.

    @contextmanager
    def create(self, bucket, storage_key):
        job_id = uuid4().hex
        with self.lock(job_id, blocking=True):
            now = time.time()
            data = dict(version=1, id=job_id, bucket=bucket, storage_key=storage_key,
                        state='uploading', created_at=now, updated_at=now, attempts=0,
                        last_attempt_at=None, next_attempt_at=0, last_error_code=None)
            self.write(data)  # Must be durable before the first possible PUT.
            yield CleanupJob(self, data)

    @contextmanager
    def claim(self, job_id):
        with self.lock(job_id, blocking=False) as acquired:
            if not acquired:
                yield None
                return
            try:
                data = json.loads(self.path(job_id).read_text(encoding='utf-8'))
                valid = (
                    data['version'] == 1 and data['id'] == job_id
                    and data['state'] in {'uploading', 'uploaded', 'upload_uncertain'}
                    and isinstance(data['bucket'], str) and bool(data['bucket'])
                    and isinstance(data['storage_key'], str) and bool(data['storage_key'])
                    and type(data['attempts']) is int and data['attempts'] >= 0
                    and all(type(data[field]) in (int, float) and math.isfinite(data[field])
                            for field in ('created_at', 'updated_at', 'next_attempt_at'))
                )
                if not valid:
                    raise ValueError('Invalid job')
            except FileNotFoundError:
                yield None
                return
            except (OSError, ValueError, KeyError, TypeError) as error:
                raise JournalError('Unreadable cleanup job; preserved for inspection') from error
            yield CleanupJob(self, data)

    def pending(self):
        self.prepare()
        try:
            entries = []
            for path in self.directory.glob('*.json'):
                if re.fullmatch('[0-9a-f]{32}', path.stem):
                    try:
                        entries.append((path.stat().st_mtime, path.stem))
                    except FileNotFoundError:
                        continue
            return [job_id for _, job_id in sorted(entries)]
        except OSError as error:
            raise JournalError('Cannot list cleanup jobs') from error
