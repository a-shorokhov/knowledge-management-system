import asyncio
import io
import json
import logging
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from pydantic import SecretStr, ValidationError
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, declarative_base
from sqlalchemy.pool import StaticPool
from sqlalchemy.schema import CreateTable
from file_samples import SAMPLES

APP = Path(__file__).resolve().parents[1] / 'app'
sys.path.insert(0, str(APP))
engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
@event.listens_for(engine, 'connect')
def enable_foreign_keys(connection, record):
    connection.execute('PRAGMA foreign_keys=ON')

database = types.ModuleType('core.database')
database.Base = declarative_base()
database.engine = engine
database.get_db = lambda: None
sys.modules['core.database'] = database
config = types.ModuleType('core.config')
config.settings = types.SimpleNamespace(S3_BUCKET='fake-test-bucket', SECRET_KEY=SecretStr('test-secret-key-that-is-only-used-in-tests'), TOKEN_ALGORITHM='HS256', TOKEN_LIFETIME_MINUTES=30, CORS_ORIGINS=[])
sys.modules['core.config'] = config

import models
from models.users import User
from models.modules import Module
from models.launches import Launch
from models.sections import RunSection
from models.stored_files import StoredFile
from models.materials import Material
from models.notes import Note
from models.enums import MaterialKind
from repositories.modules import ModuleRepository
from repositories.launches import LaunchRepository
from repositories.sections import SectionRepository
from repositories.materials import MaterialRepository
from repositories.notes import NoteRepository
from repositories.stored_files import StoredFileRepository
from services.modules import ModuleService
from services.launches import LaunchService
from services.sections import SectionService
from services.materials import MaterialService
from services.notes import NoteService
from services.stored_files import StoredFileService
from schemas.launches import CreateLaunchRequest, UpdateLaunchRequest
from schemas.modules import CreateModuleRequest, UpdateModuleRequest
from schemas.sections import CreateSectionRequest, UpdateSectionRequest
from schemas.materials import CopyMaterialRequest, MaterialUpload, UpdateMaterialRequest
from schemas.notes import CreateNoteRequest, UpdateNoteRequest
from adapters.file_storage.base import FileStorageError, StoredFileNotFound
from core.depends import get_current_user, get_file_storage
from main import app

logging.disable(logging.CRITICAL)


class FakeStorage:
    def __init__(self):
        self.objects = {}
        self.upload_error = False
        self.delete_error = False
        self.download_error = False

    def upload_file(self, key, data, content_type='application/octet-stream'):
        if self.upload_error:
            raise FileStorageError('fake upload failure')
        self.objects[key] = (data, content_type)
        return key

    def delete_file(self, key):
        if self.delete_error:
            raise FileStorageError('fake delete failure')
        self.objects.pop(key, None)

    def get_download_url(self, key, expires_in=3600):
        if self.download_error:
            raise FileStorageError('fake download failure')
        if key not in self.objects:
            raise StoredFileNotFound('fake missing file')
        return f'https://fake.invalid/{key}?expires={expires_in}'


def upload(name='test.txt', mime='text/plain', data=b'a', declared_size=None):
    return MaterialUpload(io.BytesIO(data), name, mime, len(data) if declared_size is None else declared_size)


class ERDTests(unittest.TestCase):
    def setUp(self):
        database.Base.metadata.create_all(engine)
        self.db = Session(engine)
        self.db.add_all([User(id=i, username=f'user{i}', email=f'user{i}@example.com', hashed_password='unused') for i in (1, 2)])
        self.db.commit()
        self.modules = ModuleRepository(self.db)
        self.launches = LaunchRepository(self.db)
        self.sections = SectionRepository(self.db)
        self.materials = MaterialRepository(self.db)
        self.notes = NoteRepository(self.db)
        self.files = StoredFileRepository(self.db)
        self.storage = FakeStorage()
        self.file_service = StoredFileService(self.files, self.materials, self.storage)
        self.module_service = ModuleService(self.modules, self.file_service)
        self.launch_service = LaunchService(self.launches, self.modules, self.file_service)
        self.section_service = SectionService(self.sections, self.launches, self.file_service)
        self.note_service = NoteService(self.notes, self.launches, self.materials, self.sections)
        self.material_service = MaterialService(self.materials, self.launches, self.sections, self.storage, self.file_service, self.notes)
                # Поддержка старого и нового контрактов ошибок в тестах.
        from fastapi import HTTPException

        class ServiceErrorAdapter:
            def __init__(self, service):
                self._service = service

            def __getattr__(self, name):
                original = getattr(self._service, name)
                if not callable(original):
                    return original

                def call(*args, **kwargs):
                    try:
                        return original(*args, **kwargs)
                    except HTTPException as exc:
                        detail = exc.detail
                        if not (
                            isinstance(detail, dict)
                            and isinstance(detail.get("ErrorCode"), str)
                            and isinstance(detail.get("ErrorMessage"), str)
                            and detail["ErrorMessage"]
                            and 400 <= exc.status_code < 600
                        ):
                            raise AssertionError(
                                "Некорректный формат исключения"
                            ) from exc

                        return {
                            "success": False,
                            "status_code": exc.status_code,
                            "message": detail["ErrorMessage"],
                        }

                return call

        for name in (
            "file_service",
            "module_service",
            "launch_service",
            "section_service",
            "note_service",
            "material_service",
        ):
            setattr(
                self,
                name,
                ServiceErrorAdapter(getattr(self, name)),
            )
        self.module = self.modules.create_module(1, {'title': 'Module', 'description': ''})
        self.other_module = self.modules.create_module(2, {'title': 'Other', 'description': ''})
        self.run = self.launches.create_launch(self.module['id'], self.run_data('2026'))
        self.target = self.launches.create_launch(self.module['id'], self.run_data('2027'))
        self.other_run = self.launches.create_launch(self.other_module['id'], self.run_data('Other'))
        app.dependency_overrides[database.get_db] = lambda: self.db
        app.dependency_overrides[get_current_user] = lambda: {'id': 1}
        app.dependency_overrides[get_file_storage] = lambda: self.storage

    def tearDown(self):
        app.dependency_overrides.clear()
        self.db.rollback()
        self.db.close()
        database.Base.metadata.drop_all(engine)

    @staticmethod
    def run_data(title):
        return {'title': title, 'description': '', 'year': 2026, 'semester': 'Осень'}

    def material(self, section_id=None):
        result = self.material_service.create_material(self.run['id'], 1, 'Material', None, upload(), section_id)
        self.assertTrue(result['success'], result)
        return result

    def section(self, launch=None, position=0):
        return self.sections.create_section(launch or self.run['id'], {'title': 'Section', 'position': position})

    def request(self, method, path, body=None, headers=None, raw=None):
        async def invoke():
            data = raw if raw is not None else json.dumps(body).encode() if body is not None else b''
            request_headers = [(b'content-type', b'application/json')] if raw is None else []
            request_headers += [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()]
            sent = False
            messages = []
            async def receive():
                nonlocal sent
                if sent:
                    return {'type': 'http.disconnect'}
                sent = True
                return {'type': 'http.request', 'body': data, 'more_body': False}
            async def send(message):
                messages.append(message)
            await app({'type': 'http', 'asgi': {'version': '3.0'}, 'http_version': '1.1', 'method': method, 'scheme': 'http', 'path': path, 'raw_path': path.encode(), 'query_string': b'', 'root_path': '', 'headers': request_headers, 'server': ('test', 80), 'client': ('test', 1)}, receive, send)
            status = next(m['status'] for m in messages if m['type'] == 'http.response.start')
            data = b''.join(m.get('body', b'') for m in messages if m['type'] == 'http.response.body')
            return status, json.loads(data) if data else None
        return asyncio.run(invoke())

    def test_delete_original_launch_preserves_copied_launch(self):
        section = self.section()
        material = self.material(section['id'])
        copied_run = self.launch_service.copy_launch(self.run['id'], 1, CreateLaunchRequest(**self.run_data('Copy')))
        self.assertTrue(copied_run['success'])
        self.assertTrue(self.launch_service.delete_launch(self.run['id'], 1)['success'])
        copy = self.launches.get_launch_by_id(copied_run['id'], 1)
        self.assertIsNone(copy['copied_from_launch_id'])
        copied_material = next(iter(self.materials.get_all_materials(copy['id'], 1).values()))
        self.assertIsNone(copied_material['copied_from_material_id'])
        self.assertEqual(copied_material['stored_file_id'], material['stored_file_id'])
        self.assertTrue(self.file_service.get_material_download_url(copied_material['id'], 1)['success'])

    def test_http_section_note_and_cascade(self):
        section = self.section()
        status, note = self.request('POST', f"/launches/{self.run['id']}/notes", {'title': 'Week note', 'content': 'Text', 'section_id': section['id']})
        self.assertEqual(status, 201)
        self.assertEqual(note['section_id'], section['id'])
        self.assertEqual(self.request('DELETE', f"/sections/{section['id']}")[0], 200)
        self.assertEqual(self.request('GET', f"/notes/{note['id']}")[0], 404)

    def test_note_section_foreign_key_rejects_other_launch_in_database(self):
        section = self.section(self.target['id'])
        self.db.add(Note(launch_id=self.run['id'], section_id=section['id'], author_id=1, title='Bad', content='Text'))
        with self.assertRaises(IntegrityError):
            self.db.commit()
        self.db.rollback()

    def test_module_delete_preserves_file_used_outside_module(self):
        original = self.material()
        another = self.modules.create_module(1, {'title': 'Second module', 'description': ''})
        run = self.launches.create_launch(another['id'], self.run_data('Another launch'))
        shared = Material(launch_id=run['id'], stored_file_id=original['stored_file_id'], title='Existing shared file')
        self.db.add(shared)
        self.db.commit()
        shared_id = shared.id
        with patch.object(self.storage, 'delete_file', wraps=self.storage.delete_file) as deletion:
            self.assertTrue(self.module_service.delete_module(self.module['id'], 1)['success'])
            deletion.assert_not_called()
        self.assertTrue(self.file_service.get_material_download_url(shared_id, 1)['success'])
        self.assertTrue(self.module_service.delete_module(another['id'], 1)['success'])
        self.assertFalse(self.storage.objects)
        self.assertEqual(self.db.scalar(select(func.count()).select_from(User)), 2)

    def test_note_can_link_to_section_only(self):
        section = self.section()
        result = self.note_service.create_note(self.run['id'], 1, CreateNoteRequest(title='Week note', content='Text', section_id=section['id']))
        self.assertTrue(result['success'])
        self.assertEqual(result['section_id'], section['id'])
        self.assertIsNone(result['material_id'])
        self.assertFalse(self.note_service.create_note(self.target['id'], 1, CreateNoteRequest(title='Wrong run', content='Text', section_id=section['id']))['success'])

    def test_note_material_must_belong_to_selected_section(self):
        section = self.section()
        other = self.section()
        material = self.material(section['id'])
        bad = self.note_service.create_note(self.run['id'], 1, CreateNoteRequest(title='Mismatch', content='Text', material_id=material['id'], section_id=other['id']))
        self.assertEqual(bad['status_code'], 400)
        good = self.note_service.create_note(self.run['id'], 1, CreateNoteRequest(title='Match', content='Text', material_id=material['id'], section_id=section['id']))
        self.assertTrue(good['success'])
        bad = self.note_service.edit_note(good['id'], 1, UpdateNoteRequest(section_id=other['id']))
        self.assertEqual(bad['status_code'], 400)
        good = self.note_service.edit_note(good['id'], 1, UpdateNoteRequest(section_id=None))
        self.assertTrue(good['success'])
        self.assertIsNone(good['section_id'])

    def test_partial_note_patch_validates_existing_section_and_new_material(self):
        section = self.section()
        material = self.material()
        note = self.note_service.create_note(self.run['id'], 1, CreateNoteRequest(title='Section note', content='Text', section_id=section['id']))
        self.assertEqual(self.note_service.edit_note(note['id'], 1, UpdateNoteRequest(material_id=material['id']))['status_code'], 400)
        self.assertTrue(self.note_service.edit_note(note['id'], 1, UpdateNoteRequest(material_id=material['id'], section_id=None))['success'])

    def test_material_move_does_not_break_note_section_link(self):
        first = self.section()
        second = self.section()
        material = self.material(first['id'])
        note = self.note_service.create_note(self.run['id'], 1, CreateNoteRequest(title='Linked', content='Text', material_id=material['id'], section_id=first['id']))
        self.assertEqual(self.material_service.edit_material(material['id'], 1, UpdateMaterialRequest(section_id=second['id']))['status_code'], 409)
        self.assertEqual(self.material_service.edit_material(material['id'], 1, UpdateMaterialRequest(section_id=None))['status_code'], 409)
        self.assertTrue(self.note_service.edit_note(note['id'], 1, UpdateNoteRequest(section_id=None))['success'])
        self.assertTrue(self.material_service.edit_material(material['id'], 1, UpdateMaterialRequest(section_id=second['id']))['success'])

    def test_material_delete_cascades_notes_and_cleans_last_file(self):
        material = self.material()
        self.note_service.create_note(self.run['id'], 1, CreateNoteRequest(title='Note', content='Text', material_id=material['id']))
        self.assertTrue(self.material_service.delete_material(material['id'], 1)['success'])
        self.assertEqual(self.notes.get_all_notes(self.run['id'], 1), {})
        self.assertFalse(self.storage.objects)

    def test_section_delete_cascades_but_preserves_other_section(self):
        first = self.section()
        second = self.section()
        material = self.material(first['id'])
        survivor = self.material(second['id'])
        self.note_service.create_note(self.run['id'], 1, CreateNoteRequest(title='Section note', content='Text', section_id=first['id']))
        self.note_service.create_note(self.run['id'], 1, CreateNoteRequest(title='Material note', content='Text', material_id=material['id']))
        run_note = self.note_service.create_note(self.run['id'], 1, CreateNoteRequest(title='Run note', content='Text'))
        self.assertTrue(self.section_service.delete_section(first['id'], 1)['success'])
        self.assertEqual(list(self.notes.get_all_notes(self.run['id'], 1)), [run_note['id']])
        self.assertIsNone(self.materials.get_material_by_id(material['id'], 1))
        self.assertIsNotNone(self.materials.get_material_by_id(survivor['id'], 1))
        self.assertEqual(len(self.storage.objects), 1)

    def test_launch_delete_keeps_file_shared_with_other_launch(self):
        section = self.section()
        material = self.material(section['id'])
        copied = self.material_service.copy_material(material['id'], 1, CopyMaterialRequest(launch_id=self.target['id']))
        self.note_service.create_note(self.run['id'], 1, CreateNoteRequest(title='Note', content='Text', section_id=section['id'], material_id=material['id']))
        self.assertTrue(self.launch_service.delete_launch(self.run['id'], 1)['success'])
        self.assertEqual(self.sections.get_all_sections(self.run['id'], 1), {})
        self.assertEqual(self.notes.get_all_notes(self.run['id'], 1), {})
        self.assertTrue(self.file_service.get_material_download_url(copied['id'], 1)['success'])
        self.assertFalse(self.files.get_file_by_id(material['stored_file_id'], 1)['deletion_pending'])
        self.assertTrue(self.launch_service.delete_launch(self.target['id'], 1)['success'])
        self.assertFalse(self.storage.objects)

    def test_module_delete_cleans_all_children_but_not_another_user(self):
        section = self.section()
        material = self.material(section['id'])
        self.material_service.copy_material(material['id'], 1, CopyMaterialRequest(launch_id=self.target['id']))
        self.note_service.create_note(self.run['id'], 1, CreateNoteRequest(title='Note', content='Text', section_id=section['id']))
        self.assertTrue(self.module_service.delete_module(self.module['id'], 1)['success'])
        self.assertEqual(self.launches.get_all_launches(self.module['id'], 1), {})
        self.assertIsNotNone(self.modules.get_module_by_id(self.other_module['id'], 2))
        self.assertIsNotNone(self.launches.get_launch_by_id(self.other_run['id'], 2))
        self.assertEqual(self.db.scalar(select(func.count()).select_from(Note)), 0)
        self.assertFalse(self.storage.objects)

    def test_parent_delete_failure_rolls_back_before_s3(self):
        material = self.material()
        with patch.object(self.db, 'commit', side_effect=SQLAlchemyError('fake parent commit failure')):
            with patch.object(self.storage, 'delete_file', wraps=self.storage.delete_file) as deletion:
                result = self.launch_service.delete_launch(self.run['id'], 1)
                self.assertEqual(result['status_code'], 503)
                deletion.assert_not_called()
        self.assertIsNotNone(self.launches.get_launch_by_id(self.run['id'], 1))
        self.assertIsNotNone(self.materials.get_material_by_id(material['id'], 1))
        self.assertFalse(self.files.get_file_by_id(material['stored_file_id'], 1)['deletion_pending'])

    def test_parent_cleanup_failure_is_retryable_and_other_files_are_cleaned(self):
        first = self.material()
        second = self.material()
        first_file = self.files.get_file_by_id(first['stored_file_id'], 1)
        original_delete = self.storage.delete_file
        def fail_first(key):
            if key == first_file['storage_key']:
                raise FileStorageError('fake first object failure')
            return original_delete(key)
        with patch.object(self.storage, 'delete_file', side_effect=fail_first):
            result = self.launch_service.delete_launch(self.run['id'], 1)
        self.assertEqual(result['status_code'], 503)
        self.assertIn(str(first['stored_file_id']), result['message'])
        self.assertIsNone(self.launches.get_launch_by_id(self.run['id'], 1))
        self.assertTrue(self.files.get_file_by_id(first['stored_file_id'], 1)['deletion_pending'])
        self.assertIsNone(self.files.get_file_by_id(second['stored_file_id'], 1))
        self.assertTrue(self.file_service.delete_file(first['stored_file_id'], 1)['success'])
        self.assertFalse(self.storage.objects)

    def test_http_executable_as_pdf_returns_400_without_storage_upload(self):
        boundary = 'invalid-pdf-test'
        prefix = (f'--{boundary}\r\nContent-Disposition: form-data; name="title"\r\n\r\nDisguised PDF\r\n--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="lecture.pdf"\r\nContent-Type: application/pdf\r\n\r\n').encode()
        body = prefix + b'MZ\x90\x00' + f'\r\n--{boundary}--\r\n'.encode()
        with patch.object(self.storage, 'upload_file', wraps=self.storage.upload_file) as uploading:
            status, response = self.request('POST', f"/launches/{self.run['id']}/materials", raw=body, headers={'content-type': f'multipart/form-data; boundary={boundary}'})
            self.assertEqual(status, 400)
            uploading.assert_not_called()
        self.assertEqual(self.db.scalar(select(func.count()).select_from(StoredFile)), 0)

    def test_executable_disguised_as_pdf_rejected_before_s3(self):
        executable = b'MZ\x90\x00' + b'\x00' * 128
        with patch.object(self.storage, 'upload_file', wraps=self.storage.upload_file) as uploading:
            result = self.material_service.create_material(self.run['id'], 1, 'Disguised', None, upload('lecture.pdf', 'application/pdf', executable))
            self.assertEqual(result['status_code'], 400)
            uploading.assert_not_called()
        self.assertEqual(self.db.scalar(select(func.count()).select_from(StoredFile)), 0)

    def test_invalid_replacement_keeps_original_file_and_material(self):
        material = self.material()
        before = dict(self.storage.objects)
        result = self.material_service.replace_file(material['id'], 1, upload('lecture.pdf', 'application/pdf', b'MZ\x00fake'))
        self.assertEqual(result['status_code'], 400)
        self.assertEqual(self.storage.objects, before)
        self.assertEqual(self.materials.get_material_by_id(material['id'], 1)['stored_file_id'], material['stored_file_id'])

    def test_mime_extension_mismatch_and_uppercase_extension(self):
        with patch.object(self.storage, 'upload_file', wraps=self.storage.upload_file) as uploading:
            result = self.material_service.create_material(self.run['id'], 1, 'Mismatch', None, upload('test.exe', 'text/plain', b'a'))
            self.assertEqual(result['status_code'], 400)
            uploading.assert_not_called()
        self.assertTrue(self.material_service.create_material(self.run['id'], 1, 'Uppercase', None, upload('test.TXT'))['success'])
        filename, data = SAMPLES['image/jpeg']
        self.assertTrue(self.material_service.create_material(self.run['id'], 1, 'JPEG alias', None, upload('test.JPEG', 'image/jpeg', data))['success'])

    def test_pending_download_never_calls_storage(self):
        material = self.material()
        stored = self.db.get(StoredFile, material['stored_file_id'])
        stored.deletion_pending = True
        self.db.commit()
        with patch.object(self.storage, 'get_download_url', wraps=self.storage.get_download_url) as download:
            status, response = self.request('GET', f"/stored-files/{stored.id}/download")
            self.assertEqual(status, 409)
            download.assert_not_called()
        status, metadata = self.request('GET', f"/stored-files/{stored.id}")
        self.assertEqual(status, 200)
        self.assertTrue(metadata['deletion_pending'])

    def test_delete_db_failure_leaves_durable_pending_state_and_can_retry(self):
        material = self.material()
        file_id = material['stored_file_id']
        with patch.object(self.files, 'delete_file', side_effect=SQLAlchemyError('fake final commit failure')):
            result = self.material_service.delete_material(material['id'], 1)
        self.assertEqual(result['status_code'], 503)
        stored = self.files.get_file_by_id(file_id, 1)
        self.assertTrue(stored['deletion_pending'])
        self.assertFalse(self.storage.objects)
        self.assertEqual(self.file_service.get_download_url(file_id, 1)['status_code'], 409)
        self.db.close()
        with Session(engine) as retry_db:
            service = StoredFileService(StoredFileRepository(retry_db), MaterialRepository(retry_db), self.storage)
            self.assertTrue(service.delete_file(file_id, 1)['success'])
            self.assertIsNone(retry_db.get(StoredFile, file_id))

    def test_delete_marker_failure_never_calls_s3(self):
        stored = StoredFile(bucket='fake-test-bucket', storage_key='unused-key', original_filename='test.txt', mime_type='text/plain', size_bytes=1, uploaded_by_id=1)
        self.db.add(stored)
        self.db.commit()
        self.storage.objects[stored.storage_key] = (b'a', 'text/plain')
        with patch.object(self.db, 'commit', side_effect=SQLAlchemyError('fake marker commit failure')):
            with patch.object(self.storage, 'delete_file', wraps=self.storage.delete_file) as deletion:
                self.assertEqual(self.file_service.delete_file(stored.id, 1)['status_code'], 503)
                deletion.assert_not_called()
        self.assertFalse(self.files.get_file_by_id(stored.id, 1)['deletion_pending'])
        self.assertEqual(len(self.storage.objects), 1)

    def test_s3_failure_keeps_pending_file_retryable(self):
        material = self.material()
        self.storage.delete_error = True
        self.assertEqual(self.material_service.delete_material(material['id'], 1)['status_code'], 503)
        self.assertTrue(self.files.get_file_by_id(material['stored_file_id'], 1)['deletion_pending'])
        self.assertEqual(self.file_service.get_download_url(material['stored_file_id'], 1)['status_code'], 409)
        self.assertEqual(len(self.storage.objects), 1)
        self.storage.delete_error = False
        self.assertTrue(self.file_service.delete_file(material['stored_file_id'], 1)['success'])
        self.assertFalse(self.storage.objects)

    def test_copy_cannot_reuse_file_pending_deletion(self):
        material = self.material()
        stored = self.db.get(StoredFile, material['stored_file_id'])
        stored.deletion_pending = True
        self.db.commit()
        result = self.material_service.copy_material(material['id'], 1, CopyMaterialRequest(launch_id=self.target['id']))
        self.assertEqual(result['status_code'], 409)
        result = self.launch_service.copy_launch(self.run['id'], 1, CreateLaunchRequest(**self.run_data('Unavailable copy')))
        self.assertEqual(result['status_code'], 409)
        self.assertEqual(self.materials.get_all_materials(self.target['id'], 1), {})
        self.assertEqual(self.db.scalar(select(func.count()).select_from(Launch)), 3)

    def test_signed_download_adapter_uses_expiry_and_private_object(self):
        from urllib.parse import parse_qs, urlparse
        from botocore.stub import Stubber
        from adapters.file_storage.s3 import S3FileStorageAdapter
        storage = S3FileStorageAdapter('fake-test-bucket', 'fake-access-key', 'fake-secret-key')
        try:
            with Stubber(storage.client) as stub:
                stub.add_response('head_object', {'ContentLength': 1}, {'Bucket': 'fake-test-bucket', 'Key': 'materials/test.txt'})
                url = storage.get_download_url('materials/test.txt', 3600)
                params = parse_qs(urlparse(url).query)
                self.assertEqual(params['X-Amz-Expires'], ['3600'])
                self.assertIn('X-Amz-Signature', params)
                stub.assert_no_pending_responses()
        finally:
            storage.client.close()

    def test_shared_file_does_not_trigger_s3_deletion(self):
        original = self.material()
        copied = self.material_service.copy_material(original['id'], 1, CopyMaterialRequest(launch_id=self.target['id']))
        with patch.object(self.storage, 'delete_file', wraps=self.storage.delete_file) as deletion:
            self.assertTrue(self.material_service.delete_material(copied['id'], 1)['success'])
            deletion.assert_not_called()
        self.assertTrue(self.file_service.get_material_download_url(original['id'], 1)['success'])

    def test_repeated_cleanup_of_missing_file_is_safe(self):
        self.assertTrue(self.file_service.delete_file_if_unused(99999, 1)['success'])
        self.assertFalse(self.storage.objects)

    def test_auto_cleanup_db_failure_preserves_record_for_retry(self):
        material = self.material()
        with patch.object(self.files, 'delete_file', side_effect=SQLAlchemyError('fake cleanup failure')):
            result = self.material_service.delete_material(material['id'], 1)
        self.assertEqual(result['status_code'], 503)
        self.assertIn('Материал удалён', result['message'])
        self.assertIsNone(self.materials.get_material_by_id(material['id'], 1))
        self.assertIsNotNone(self.files.get_file_by_id(material['stored_file_id'], 1))
        self.assertTrue(self.file_service.delete_file(material['stored_file_id'], 1)['success'])

    def test_last_material_deletion_removes_file_automatically(self):
        material = self.material()
        result = self.material_service.delete_material(material['id'], 1)
        self.assertTrue(result['success'])
        self.assertFalse(self.storage.objects)
        self.assertIsNone(self.files.get_file_by_id(material['stored_file_id'], 1))
        self.assertIsNone(self.materials.get_material_by_id(material['id'], 1))

    def test_replacement_removes_unshared_old_file_automatically(self):
        material = self.material()
        old_file = self.files.get_file_by_id(material['stored_file_id'], 1)
        result = self.material_service.replace_file(material['id'], 1, upload('new.txt', data=b'new'))
        self.assertTrue(result['success'])
        self.assertNotIn(old_file['storage_key'], self.storage.objects)
        self.assertIsNone(self.files.get_file_by_id(old_file['id'], 1))
        self.assertEqual(len(self.storage.objects), 1)
        self.assertTrue(self.file_service.get_material_download_url(material['id'], 1)['success'])

    def test_replacement_cleanup_failure_keeps_new_material_and_all_files(self):
        material = self.material()
        self.storage.delete_error = True
        result = self.material_service.replace_file(material['id'], 1, upload('new.txt', data=b'new'))
        self.assertEqual(result['status_code'], 503)
        self.assertIn('Файл материала заменён', result['message'])
        current = self.materials.get_material_by_id(material['id'], 1)
        self.assertNotEqual(current['stored_file_id'], material['stored_file_id'])
        self.assertEqual(len(self.storage.objects), 2)
        self.assertIsNotNone(self.files.get_file_by_id(material['stored_file_id'], 1))
        self.storage.delete_error = False
        self.assertTrue(self.file_service.delete_file(material['stored_file_id'], 1)['success'])
        self.assertEqual(len(self.storage.objects), 1)

    def test_failed_material_deletion_does_not_delete_file(self):
        material = self.material()
        with patch.object(self.materials, 'delete_material', side_effect=SQLAlchemyError('fake DB failure')):
            with patch.object(self.storage, 'delete_file', wraps=self.storage.delete_file) as deletion:
                self.assertEqual(self.material_service.delete_material(material['id'], 1)['status_code'], 503)
                deletion.assert_not_called()
        self.assertIsNotNone(self.files.get_file_by_id(material['stored_file_id'], 1))

    def test_copying_never_uploads_to_storage(self):
        material = self.material()
        with patch.object(self.storage, 'upload_file', wraps=self.storage.upload_file) as uploading:
            self.assertTrue(self.material_service.copy_material(material['id'], 1, CopyMaterialRequest(launch_id=self.target['id']))['success'])
            self.assertTrue(self.launch_service.copy_launch(self.run['id'], 1, CreateLaunchRequest(**self.run_data('Copy')))['success'])
            uploading.assert_not_called()
        self.assertEqual(len(self.storage.objects), 1)
        self.assertEqual(self.db.scalar(select(func.count()).select_from(StoredFile)), 1)

    def test_metadata_edit_never_deletes_or_uploads_file(self):
        material = self.material()
        with patch.object(self.storage, 'delete_file') as deletion, patch.object(self.storage, 'upload_file') as uploading:
            self.assertTrue(self.material_service.edit_material(material['id'], 1, UpdateMaterialRequest(title='Edited'))['success'])
            deletion.assert_not_called()
            uploading.assert_not_called()

    def test_http_sections_notes_copy_and_replacement(self):
        status, section = self.request('POST', f"/launches/{self.run['id']}/sections", {'title': 'HTTP section'})
        self.assertEqual(status, 201)
        material = self.material(section['id'])
        status, note = self.request('POST', f"/launches/{self.run['id']}/notes", {'title': 'HTTP note', 'content': 'Content', 'material_id': material['id']})
        self.assertEqual(status, 201)
        self.assertEqual(note['author_id'], 1)
        status, copied = self.request('POST', f"/launches/{self.run['id']}/copy", self.run_data('HTTP copy'))
        self.assertEqual(status, 201)
        self.assertEqual(self.request('GET', f"/launches/{copied['id']}/notes"), (200, {}))
        status, listing = self.request('GET', f"/launches/{copied['id']}/materials")
        self.assertEqual(status, 200)
        self.assertEqual(next(iter(listing.values()))['stored_file_id'], material['stored_file_id'])

    def test_http_user_delete_respects_restrict(self):
        self.assertEqual(self.request('DELETE', '/users/1')[0], 409)
        self.assertEqual(self.request('DELETE', '/users/2')[0], 403)

    def test_erd_tables_and_postgres_ddl(self):
        self.assertEqual(set(database.Base.metadata.tables), {'users', 'modules', 'launches', 'run_sections', 'materials', 'stored_files', 'notes', 'launch_designs'})
        for table in database.Base.metadata.sorted_tables:
            self.assertTrue(str(CreateTable(table).compile(dialect=postgresql.dialect())))
        self.assertEqual(len(database.Base.metadata.tables['materials'].foreign_key_constraints), 4)

    def test_module_and_launch_crud(self):
        created = self.module_service.create_module(1, CreateModuleRequest(title='New', description='Description'))
        self.assertTrue(created['success'])
        self.assertEqual(created['owner_id'], 1)
        self.assertTrue(self.module_service.edit_module(created['id'], 1, UpdateModuleRequest(title='Edited'))['success'])
        self.assertTrue(self.module_service.delete_module(created['id'], 1)['success'])
        run = self.launch_service.create_launch(self.module['id'], 1, CreateLaunchRequest(**self.run_data('New run')))
        self.assertEqual(run['status'], 'draft')
        self.assertEqual(self.launch_service.edit_launch(run['id'], 1, UpdateLaunchRequest(status='active'))['status'], 'active')
        self.assertTrue(self.launch_service.delete_launch(run['id'], 1)['success'])

    def test_sections_crud_and_order(self):
        first = self.section_service.create_section(self.run['id'], 1, CreateSectionRequest(title='First', position=8))
        second = self.section_service.create_section(self.run['id'], 1, CreateSectionRequest(title='Second', position=2))
        self.assertEqual(list(self.section_service.get_all_sections(self.run['id'], 1)['data']), [second['id'], first['id']])
        self.assertEqual(self.section_service.edit_section(first['id'], 1, UpdateSectionRequest(position=1))['position'], 1)
        self.assertTrue(self.section_service.delete_section(first['id'], 1)['success'])

    def test_upload_metadata_and_mime(self):
        material = self.material()
        stored = self.files.get_file_by_id(material['stored_file_id'], 1)
        self.assertEqual(stored['size_bytes'], 1)
        self.assertEqual(stored['mime_type'], 'text/plain')
        self.assertEqual(stored['indexing_status'], 'pending')
        self.assertEqual(stored['uploaded_by_id'], 1)
        self.assertEqual(self.storage.objects[stored['storage_key']], (b'a', 'text/plain'))

    def test_upload_validation(self):
        for file, status in [(upload('test.sql', 'application/sql'), 400), (upload(mime=None), 400), (upload(data=b''), 400), (upload(declared_size=5*1024*1024+1), 413), (upload(name='../..'), 400)]:
            with self.subTest(file=file.filename, mime=file.content_type):
                result = self.material_service.create_material(self.run['id'], 1, 'T', None, file)
                self.assertEqual(result['status_code'], status)
                self.assertFalse(self.storage.objects)
        self.assertEqual(self.material_service.create_material(self.run['id'], 1, 'SQL as plain text', None, upload('test.sql'))['status_code'], 400)

    def test_all_allowed_mime_types(self):
        from services.materials import ALLOWED_MATERIAL_TYPES
        for mime in ALLOWED_MATERIAL_TYPES:
            filename, data = SAMPLES[mime]
            self.assertTrue(self.material_service.create_material(self.run['id'], 1, 'Allowed', None, upload(filename, mime, data))['success'])

    def test_real_read_size_limit(self):
        file = upload(data=b'a'*(5*1024*1024+1))
        file.size = None
        self.assertEqual(self.material_service.create_material(self.run['id'], 1, 'T', None, file)['status_code'], 413)
        self.assertFalse(self.storage.objects)

    def test_cross_run_section_rejected(self):
        other_section = self.section(self.target['id'])
        result = self.material_service.create_material(self.run['id'], 1, 'T', None, upload(), other_section['id'])
        self.assertFalse(result['success'])
        self.assertFalse(self.storage.objects)
        material = self.material()
        self.assertFalse(self.material_service.edit_material(material['id'], 1, UpdateMaterialRequest(section_id=other_section['id']))['success'])

    def test_material_edit_and_detach_section(self):
        section = self.section()
        material = self.material(section['id'])
        edited = self.material_service.edit_material(material['id'], 1, UpdateMaterialRequest(title='Edited', section_id=None, kind=MaterialKind.reading, position=3))
        self.assertEqual(edited['title'], 'Edited')
        self.assertIsNone(edited['section_id'])
        self.assertEqual(edited['kind'], 'reading')
        self.assertEqual(edited['position'], 3)

    def test_notes_material_link_and_author(self):
        material = self.material()
        note = self.note_service.create_note(self.run['id'], 1, CreateNoteRequest(title='Note', content='Content', material_id=material['id']))
        self.assertEqual(note['author_id'], 1)
        self.assertEqual(note['material_id'], material['id'])
        self.assertFalse(self.note_service.create_note(self.target['id'], 1, CreateNoteRequest(title='Bad', content='Content', material_id=material['id']))['success'])
        self.assertTrue(self.note_service.edit_note(note['id'], 1, UpdateNoteRequest(material_id=None))['success'])
        self.assertTrue(self.material_service.delete_material(material['id'], 1)['success'])

    def test_note_edit_cannot_link_other_run(self):
        material = self.material()
        note = self.note_service.create_note(self.target['id'], 1, CreateNoteRequest(title='Note', content='Content'))
        self.assertFalse(self.note_service.edit_note(note['id'], 1, UpdateNoteRequest(material_id=material['id']))['success'])

    def test_database_section_cascade_deletes_material_and_notes(self):
        section = self.section()
        material = self.material(section['id'])
        note = self.note_service.create_note(self.run['id'], 1, CreateNoteRequest(title='Note', content='Content', material_id=material['id'], section_id=section['id']))
        self.db.delete(self.db.get(RunSection, section['id']))
        self.db.commit()
        self.assertIsNone(self.notes.get_note_by_id(note['id'], 1))
        self.assertIsNone(self.materials.get_material_by_id(material['id'], 1))
        self.assertIsNotNone(self.files.get_file_by_id(material['stored_file_id'], 1))

    def test_copy_run_remaps_sections_and_keeps_shared_files(self):
        section = self.section(position=5)
        material = self.material(section['id'])
        self.note_service.create_note(self.run['id'], 1, CreateNoteRequest(title='Note', content='Content'))
        result = self.launch_service.copy_launch(self.run['id'], 1, CreateLaunchRequest(**self.run_data('Copy')))
        self.assertTrue(result['success'])
        self.assertEqual(result['copied_from_launch_id'], self.run['id'])
        copied_sections = self.sections.get_all_sections(result['id'], 1)
        copied_materials = self.materials.get_all_materials(result['id'], 1)
        self.assertEqual(len(copied_sections), 1)
        copied_section = next(iter(copied_sections.values()))
        copied = next(iter(copied_materials.values()))
        self.assertNotEqual(copied_section['id'], section['id'])
        self.assertEqual(copied['section_id'], copied_section['id'])
        self.assertEqual(copied['stored_file_id'], material['stored_file_id'])
        self.assertEqual(copied['copied_from_material_id'], material['id'])
        self.assertEqual(self.notes.get_all_notes(result['id'], 1), {})
        self.assertEqual(len(self.storage.objects), 1)

    def test_copy_material_delete_does_not_touch_source(self):
        original = self.material()
        copied = self.material_service.copy_material(original['id'], 1, CopyMaterialRequest(launch_id=self.target['id']))
        self.assertTrue(copied['success'])
        self.assertEqual(copied['stored_file_id'], original['stored_file_id'])
        self.assertTrue(self.material_service.delete_material(copied['id'], 1)['success'])
        self.assertIsNotNone(self.materials.get_material_by_id(original['id'], 1))
        self.assertEqual(len(self.storage.objects), 1)
        self.assertEqual(self.file_service.delete_file(original['stored_file_id'], 1)['status_code'], 409)

    def test_copy_material_rejects_other_module(self):
        material = self.material()
        another = self.modules.create_module(1, {'title': 'Another', 'description': ''})
        run = self.launches.create_launch(another['id'], self.run_data('Another'))
        self.assertEqual(self.material_service.copy_material(material['id'], 1, CopyMaterialRequest(launch_id=run['id']))['status_code'], 400)
        self.assertFalse(self.material_service.copy_material(material['id'], 1, CopyMaterialRequest(launch_id=self.other_run['id']))['success'])
        self.assertEqual(self.material_service.copy_material(material['id'], 1, CopyMaterialRequest(launch_id=self.run['id']))['status_code'], 400)

    def test_replace_file_only_changes_selected_copy(self):
        original = self.material()
        copied = self.material_service.copy_material(original['id'], 1, CopyMaterialRequest(launch_id=self.target['id']))
        replaced = self.material_service.replace_file(copied['id'], 1, upload('new.txt', data=b'new'))
        self.assertTrue(replaced['success'])
        self.assertNotEqual(replaced['stored_file_id'], original['stored_file_id'])
        self.assertEqual(self.materials.get_material_by_id(original['id'], 1)['stored_file_id'], original['stored_file_id'])
        self.assertEqual(len(self.storage.objects), 2)

    def test_file_deletion_only_when_no_materials_use_it(self):
        original = self.material()
        copied = self.material_service.copy_material(original['id'], 1, CopyMaterialRequest(launch_id=self.target['id']))
        file_id = original['stored_file_id']
        self.material_service.delete_material(original['id'], 1)
        self.assertEqual(self.file_service.delete_file(file_id, 1)['status_code'], 409)
        self.material_service.delete_material(copied['id'], 1)
        self.assertFalse(self.file_service.delete_file(file_id, 1)['success'])
        self.assertEqual(self.storage.objects, {})
        self.assertIsNone(self.files.get_file_by_id(file_id, 1))

    def test_deleting_source_nulls_copy_provenance(self):
        original = self.material()
        copied = self.material_service.copy_material(original['id'], 1, CopyMaterialRequest(launch_id=self.target['id']))
        self.material_service.delete_material(original['id'], 1)
        self.db.expire_all()
        self.assertIsNone(self.materials.get_material_by_id(copied['id'], 1)['copied_from_material_id'])

    def test_ownership_on_all_services(self):
        section = self.section()
        material = self.material()
        note = self.note_service.create_note(self.run['id'], 1, CreateNoteRequest(title='Note', content='Content'))
        for service, identifier, methods in [
            (self.module_service, self.module['id'], ['get_module_by_id', 'delete_module']),
            (self.launch_service, self.run['id'], ['get_launch_by_id', 'delete_launch']),
            (self.section_service, section['id'], ['get_section_by_id', 'delete_section']),
            (self.material_service, material['id'], ['get_material_by_id', 'delete_material']),
            (self.note_service, note['id'], ['get_note_by_id', 'delete_note']),
            (self.file_service, material['stored_file_id'], ['get_file_by_id', 'delete_file', 'get_download_url']),
        ]:
            for method in methods:
                self.assertFalse(getattr(service, method)(identifier, 2)['success'], method)
        self.assertEqual(len(self.storage.objects), 1)

    def test_unauthorized_upload_does_not_touch_storage(self):
        self.assertFalse(self.material_service.create_material(self.run['id'], 2, 'T', None, upload())['success'])
        self.assertFalse(self.storage.objects)

    def test_upload_storage_failure(self):
        self.storage.upload_error = True
        self.assertEqual(self.material_service.create_material(self.run['id'], 1, 'T', None, upload())['status_code'], 503)
        self.assertEqual(self.db.scalar(select(func.count()).select_from(StoredFile)), 0)

    def test_database_failure_removes_just_uploaded_file(self):
        with patch.object(self.materials, 'create_material', side_effect=SQLAlchemyError('fake')):
            self.assertEqual(self.material_service.create_material(self.run['id'], 1, 'T', None, upload())['status_code'], 503)
        self.assertFalse(self.storage.objects)

    def test_replace_database_failure_keeps_original(self):
        material = self.material()
        before = dict(self.storage.objects)
        with patch.object(self.materials, 'replace_file', side_effect=SQLAlchemyError('fake')):
            self.assertEqual(self.material_service.replace_file(material['id'], 1, upload())['status_code'], 503)
        self.assertEqual(self.storage.objects, before)

    def test_delete_storage_failure_keeps_database_record(self):
        material = self.material()
        self.storage.delete_error = True
        result = self.material_service.delete_material(material['id'], 1)
        self.assertEqual(result['status_code'], 503)
        self.assertIn('Материал удалён', result['message'])
        self.assertEqual(self.file_service.delete_file(material['stored_file_id'], 1)['status_code'], 503)
        self.assertIsNotNone(self.files.get_file_by_id(material['stored_file_id'], 1))

    def test_download_and_error_handling(self):
        material = self.material()
        result = self.file_service.get_material_download_url(material['id'], 1)
        self.assertTrue(result['success'])
        self.assertEqual(result['expires_in'], 3600)
        self.storage.download_error = True
        self.assertEqual(self.file_service.get_material_download_url(material['id'], 1)['status_code'], 503)
        self.storage.download_error = False
        self.storage.objects.clear()
        self.assertFalse(self.file_service.get_material_download_url(material['id'], 1)['success'])

    def test_cross_run_links_enforced_in_database(self):
        section = self.section(self.target['id'])
        stored = StoredFile(bucket='fake', storage_key='key', original_filename='f', mime_type='text/plain', size_bytes=1, uploaded_by_id=1)
        self.db.add(stored)
        self.db.commit()
        self.db.add(Material(launch_id=self.run['id'], section_id=section['id'], stored_file_id=stored.id, title='Bad'))
        with self.assertRaises(IntegrityError):
            self.db.commit()
        self.db.rollback()
        material = self.material()
        self.db.add(Note(launch_id=self.target['id'], material_id=material['id'], author_id=1, title='Bad', content='Bad'))
        with self.assertRaises(IntegrityError):
            self.db.commit()
        self.db.rollback()

    def test_invalid_patch_and_enum_fields(self):
        for model, values in [(UpdateModuleRequest, {'description': None}), (UpdateLaunchRequest, {'status': None}), (CreateLaunchRequest, {**self.run_data('T'), 'status': 'invalid'}), (UpdateSectionRequest, {'position': -1}), (UpdateMaterialRequest, {'kind': 'bad'}), (UpdateNoteRequest, {'content': None}), (CopyMaterialRequest, {'launch_id': 0})]:
            with self.assertRaises(ValidationError):
                model(**values)

    def test_openapi_endpoints_and_private_storage_fields(self):
        schema = app.openapi()
        for path in ['/launches/{launch_id}/copy', '/launches/{launch_id}/sections', '/launches/{launch_id}/notes', '/sections/{section_id}', '/materials/{material_id}/file', '/materials/{material_id}/download', '/materials/{material_id}/copy', '/stored-files/{file_id}/download']:
            self.assertIn(path, schema['paths'])
        self.assertNotIn('storage_key', schema['components']['schemas']['StoredFileResponse']['properties'])
        self.assertNotIn('bucket', schema['components']['schemas']['StoredFileResponse']['properties'])

    def test_http_crud_and_validation(self):
        status, response = self.request('POST', '/modules', {'title': 'HTTP', 'description': 'test'})
        self.assertEqual(status, 201)
        self.assertEqual(response['owner_id'], 1)
        status, listing = self.request('GET', '/modules')
        self.assertEqual(status, 200)
        self.assertIn(str(response['id']), listing)
        status, _ = self.request('POST', f"/modules/{self.module['id']}/launches", {**self.run_data('HTTP'), 'year': 0})
        self.assertEqual(status, 422)
        self.assertEqual(self.request('GET', f"/launches/{self.other_run['id']}")[0], 404)
        self.assertEqual(self.request('DELETE', f"/modules/{self.module['id']}")[0], 200)

    def test_http_multipart_upload_download_and_delete(self):
        boundary = 'kms-test-boundary'
        body = (f'--{boundary}\r\nContent-Disposition: form-data; name="title"\r\n\r\nHTTP file\r\n--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="test.txt"\r\nContent-Type: text/plain\r\n\r\na\r\n--{boundary}--\r\n').encode()
        status, material = self.request('POST', f"/launches/{self.run['id']}/materials", raw=body, headers={'content-type': f'multipart/form-data; boundary={boundary}'})
        self.assertEqual(status, 201, material)
        self.assertEqual(self.request('GET', f"/materials/{material['id']}/download")[0], 200)
        status, metadata = self.request('GET', f"/stored-files/{material['stored_file_id']}")
        self.assertEqual(status, 200)
        self.assertEqual(metadata['original_filename'], 'test.txt')
        self.assertNotIn('storage_key', metadata)
        self.assertEqual(self.request('DELETE', f"/stored-files/{material['stored_file_id']}")[0], 409)
        self.assertEqual(self.request('DELETE', f"/materials/{material['id']}")[0], 200)
        self.assertEqual(self.request('DELETE', f"/stored-files/{material['stored_file_id']}")[0], 404)
        self.assertFalse(self.storage.objects)

    def test_http_unauthenticated_is_401(self):
        del app.dependency_overrides[get_current_user]
        self.assertEqual(self.request('GET', '/modules')[0], 401)

    def test_note_create_commit_failure_rolls_back(self):
        before = self.db.scalar(select(func.count()).select_from(Note))
        with patch.object(self.db, 'commit', side_effect=SQLAlchemyError('fake commit failure')):
            with self.assertRaises(SQLAlchemyError):
                self.note_service.create_note(self.run['id'], 1, CreateNoteRequest(title='Note', content='Content'))
        self.assertEqual(self.db.scalar(select(func.count()).select_from(Note)), before)
        self.assertTrue(self.note_service.create_note(self.run['id'], 1, CreateNoteRequest(title='Retry', content='Content'))['success'])

    def test_note_edit_commit_failure_restores_links_and_content(self):
        material = self.material()
        note = self.note_service.create_note(self.run['id'], 1, CreateNoteRequest(title='Note', content='Original', material_id=material['id']))
        with patch.object(self.db, 'commit', side_effect=SQLAlchemyError('fake commit failure')):
            with self.assertRaises(SQLAlchemyError):
                self.note_service.edit_note(note['id'], 1, UpdateNoteRequest(content='Changed', material_id=None))
        saved = self.notes.get_note_by_id(note['id'], 1)
        self.assertEqual(saved['content'], 'Original')
        self.assertEqual(saved['material_id'], material['id'])

    def test_material_edit_commit_failure_restores_section(self):
        first, second = self.section(), self.section()
        material = self.material(first['id'])
        with patch.object(self.db, 'commit', side_effect=SQLAlchemyError('fake commit failure')):
            with self.assertRaises(SQLAlchemyError):
                self.material_service.edit_material(material['id'], 1, UpdateMaterialRequest(section_id=second['id']))
        self.assertEqual(self.materials.get_material_by_id(material['id'], 1)['section_id'], first['id'])
        self.assertEqual(len(self.storage.objects), 1)

    def test_copy_launch_transaction_rolls_back_on_error(self):
        section = self.section()
        self.material(section['id'])
        before_runs = self.db.scalar(select(func.count()).select_from(Launch))
        before_sections = self.db.scalar(select(func.count()).select_from(RunSection))
        original_flush = self.db.flush
        calls = 0
        def failing_flush(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 3:
                raise SQLAlchemyError('fake copy failure')
            return original_flush(*args, **kwargs)
        with patch.object(self.db, 'flush', side_effect=failing_flush):
            with self.assertRaises(SQLAlchemyError):
                self.launch_service.copy_launch(self.run['id'], 1, CreateLaunchRequest(**self.run_data('Failed copy')))
        self.assertEqual(self.db.scalar(select(func.count()).select_from(Launch)), before_runs)
        self.assertEqual(self.db.scalar(select(func.count()).select_from(RunSection)), before_sections)


if __name__ == '__main__':
    unittest.main()
