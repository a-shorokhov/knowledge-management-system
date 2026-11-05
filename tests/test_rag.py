import io
import unittest
from unittest.mock import Mock

import test_erd
from openpyxl import Workbook


class ExtractionTests(unittest.TestCase):
    def test_long_text_chunks_overlap_and_are_bounded(self):
        from services.document_extraction import extract_chunks
        text = ''.join(str(n % 10) for n in range(2500))
        chunks = extract_chunks(text.encode(), 'lecture.txt')
        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(len(c['content']) <= 1000 for c in chunks))
        self.assertEqual(chunks[0]['content'][-120:], chunks[1]['content'][:120])

    def test_xlsx_preserves_sheets_and_cells(self):
        from services.document_extraction import extract_chunks
        book = Workbook()
        book.active.title = 'Отзывы'
        book.active.append(['Тема', 'Оценка'])
        book.active.append(['Git', 4])
        book.create_sheet('Итоги').append(['Среднее', 4])
        stream = io.BytesIO()
        book.save(stream)
        chunks = extract_chunks(stream.getvalue(), 'feedback.xlsx')
        self.assertEqual({c['sheet_name'] for c in chunks}, {'Отзывы', 'Итоги'})
        self.assertTrue(any(c['cell_range'] == 'A2:B2' and 'Git' in c['content'] for c in chunks))

    def test_empty_corrupt_and_image_fail_explicitly(self):
        from adapters.ai.yandex import AIError
        from services.document_extraction import extract_chunks
        for name, data in [('empty.txt', b'  '), ('bad.pdf', b'%PDF-1.4\nno'), ('photo.png', b'png')]:
            with self.subTest(name=name), self.assertRaises(AIError):
                extract_chunks(data, name)


class RagServiceTests(unittest.TestCase):
    def service(self, rows):
        from services.rag import RagService
        repo = Mock()
        repo.has_scope.return_value = True
        repo.search.return_value = rows
        ai = Mock()
        ai.embed.return_value = [1.0] * 256
        ai.generate.return_value = {'answer': 'Подтверждено [S1]', 'usage': {}, 'finish_reason': 'stop'}
        return RagService(repo, ai), repo, ai

    def test_no_sources_does_not_call_generation(self):
        service, repo, ai = self.service([])
        result = service.ask(1, 2, None, 'Что известно?')
        self.assertEqual(result['status'], 'no_sources')
        ai.generate.assert_not_called()

    def test_foreign_scope_is_rejected_before_embedding(self):
        from core.exceptions import ModuleNotFoundException
        service, repo, ai = self.service([])
        repo.has_scope.return_value = False
        with self.assertRaises(ModuleNotFoundException):
            service.ask(1, 2, None, 'Вопрос')
        ai.embed.assert_not_called()

    def test_insufficient_data_without_citations_is_a_normal_response(self):
        row = dict(chunk_id=8, material_id=9, launch_id=10, title='Лекция', year=2026,
                   content='Git', page_number=2, slide_number=None, sheet_name=None, cell_range=None, chunk_index=0)
        for answer in ('В найденных материалах недостаточно данных для ответа.', 'Источники не содержат сведений по этому вопросу.'):
            with self.subTest(answer=answer):
                service, repo, ai = self.service([row])
                ai.generate.return_value['answer'] = answer
                result = service.ask(1, 2, None, 'Какой средний балл?')
                self.assertEqual(result, {'status': 'ok', 'answer': answer, 'sources': []})

    def test_insufficient_data_with_fabricated_citation_is_still_rejected(self):
        from adapters.ai.yandex import AIError
        row = dict(chunk_id=8, material_id=9, launch_id=10, title='Лекция', year=2026,
                   content='Git', page_number=2, slide_number=None, sheet_name=None, cell_range=None, chunk_index=0)
        service, repo, ai = self.service([row])
        ai.generate.return_value['answer'] = 'Недостаточно данных [S999]'
        with self.assertRaises(AIError) as error:
            service.ask(1, 2, None, 'Какой средний балл?')
        self.assertEqual(error.exception.code, 'AI_INVALID_CITATIONS')

    def test_only_retrieved_citations_can_reach_response(self):
        from adapters.ai.yandex import AIError
        row = dict(chunk_id=8, material_id=9, launch_id=10, title='Лекция', year=2026,
                   content='Git', page_number=2, slide_number=None, sheet_name=None, cell_range=None, chunk_index=0)
        service, repo, ai = self.service([row])
        result = service.ask(1, 2, None, 'Git?')
        self.assertEqual(result['sources'][0]['material_id'], 9)
        ai.generate.return_value['answer'] = 'Чужое [S999]'
        with self.assertRaises(AIError):
            service.ask(1, 2, None, 'Git?')


class YandexAdapterTests(unittest.TestCase):
    def adapter(self, handler):
        import httpx
        from types import SimpleNamespace
        from pydantic import SecretStr
        from adapters.ai.yandex import YandexAIAdapter
        settings = SimpleNamespace(AI_ENABLED=True, YANDEX_AI_FOLDER_ID='test-folder',
            YANDEX_AI_API_KEY=SecretStr('test-only-key'), AI_EMBED_DOC_MODEL='text-embeddings-v2-doc/latest',
            AI_EMBED_QUERY_MODEL='text-embeddings-v2-query/latest', AI_LLM_MODEL='deepseek-v4.1-flash',
            AI_REQUEST_TIMEOUT_SECONDS=1)
        return YandexAIAdapter(settings, httpx.Client(transport=httpx.MockTransport(handler)))

    def test_embedding_uses_distinct_models_and_dimension(self):
        import httpx, json
        payloads = []
        def handle(request):
            payloads.append(json.loads(request.content))
            return httpx.Response(200, json={'embedding': ['0.1'] * 256, 'numTokens': '3'})
        adapter = self.adapter(handle)
        try:
            self.assertEqual(len(adapter.embed('Document')), 256)
            adapter.embed('Question', query=True)
        finally:
            adapter.close()
        self.assertIn('/text-embeddings-v2-doc/latest', payloads[0]['modelUri'])
        self.assertIn('/text-embeddings-v2-query/latest', payloads[1]['modelUri'])
        self.assertTrue(all(item['dim'] == '256' for item in payloads))

    def test_invalid_vectors_are_rejected(self):
        from adapters.ai.yandex import AIError, validate_embedding
        for value in ([1] * 255, [1] * 257, [float('nan')] * 256, [0] * 256, [True] * 256):
            with self.subTest(value=str(value)[:20]), self.assertRaises(AIError):
                validate_embedding(value)

    def test_errors_do_not_expose_upstream_body_or_secret(self):
        import httpx
        from adapters.ai.yandex import AIError
        from unittest.mock import patch
        for status in (401, 403, 429, 500):
            with self.subTest(status=status), patch('adapters.ai.yandex.time.sleep'):
                adapter = self.adapter(lambda req: httpx.Response(status, text='upstream private data test-only-key'))
                try:
                    with self.assertRaises(AIError) as error:
                        adapter.embed('Test')
                    self.assertNotIn('private', str(error.exception))
                    self.assertNotIn('test-only-key', str(error.exception))
                finally:
                    adapter.close()

    def test_generation_supports_separate_token_budget_for_retrospectives(self):
        import httpx, json
        payloads = []
        def handle(request):
            payloads.append(json.loads(request.content))
            return httpx.Response(200, json={'choices': [{'finish_reason': 'stop', 'message': {'content': 'Done'}}]})
        adapter = self.adapter(handle)
        try:
            adapter.generate([{'role': 'user', 'content': 'Test'}])
            adapter.generate([{'role': 'user', 'content': 'Test'}], max_completion_tokens=8192)
        finally:
            adapter.close()
        self.assertEqual(payloads[0]['max_completion_tokens'], 32768)
        self.assertEqual(payloads[1]['max_completion_tokens'], 8192)

    def test_generation_classifies_unfinished_filtered_empty_and_malformed_responses(self):
        import httpx
        from adapters.ai.yandex import AIError
        cases = [
            ({'choices': [{'finish_reason': 'length', 'message': {'content': 'Partial private text'}}]}, 'AI_OUTPUT_LIMIT'),
            ({'choices': [{'finish_reason': 'content_filter', 'message': {'content': None}}]}, 'AI_CONTENT_FILTER'),
            ({'choices': [{'finish_reason': 'stop', 'message': {'content': ''}}]}, 'AI_EMPTY_RESPONSE'),
            ({'choices': []}, 'AI_INVALID_RESPONSE'),
        ]
        for payload, code in cases:
            with self.subTest(code=code):
                adapter = self.adapter(lambda req: httpx.Response(200, json=payload))
                try:
                    with self.assertRaises(AIError) as error:
                        adapter.generate([{'role': 'user', 'content': 'Test'}])
                    self.assertEqual(error.exception.code, code)
                    self.assertNotIn('private', str(error.exception))
                finally:
                    adapter.close()

    def test_finished_generation_keeps_answer_and_logs_only_safe_metadata(self):
        import httpx
        payload = {'choices': [{'finish_reason': 'stop', 'message': {'content': 'Private answer [S1]'}}],
                   'usage': {'prompt_tokens': 10, 'completion_tokens': 20, 'unexpected': 'private metadata'}}
        adapter = self.adapter(lambda req: httpx.Response(200, json=payload))
        try:
            import logging
            logging.disable(logging.NOTSET)
            with self.assertLogs('adapters.ai.yandex', level='INFO') as logs:
                result = adapter.generate([{'role': 'user', 'content': 'Test'}])
            self.assertEqual(result['answer'], 'Private answer [S1]')
            self.assertNotIn('private', ' '.join(logs.output).lower())
        finally:
            logging.disable(logging.CRITICAL)
            adapter.close()

    def test_timeout_is_controlled(self):
        import httpx
        from adapters.ai.yandex import AIError
        def handle(req):
            raise httpx.ReadTimeout('secret', request=req)
        adapter = self.adapter(handle)
        try:
            with self.assertRaises(AIError) as error:
                adapter.embed('Test')
            self.assertEqual(error.exception.status_code, 504)
        finally:
            adapter.close()


import os
import sqlalchemy as sa
from sqlalchemy.orm import Session
import test_schema_upgrade as migrations


@unittest.skipUnless(os.environ.get('KMS_TEST_DATABASE_URL'), 'Нужен отдельный PostgreSQL с pgvector')
class RagPostgreSQLTests(unittest.TestCase):
    setUp = migrations.PostgreSQLMigrationTests.setUp
    connect = migrations.PostgreSQLMigrationTests.connect
    tearDown = migrations.PostgreSQLMigrationTests.tearDown
    upgrade = migrations.PostgreSQLMigrationTests.upgrade
    legacy_data = migrations.PostgreSQLMigrationTests.legacy_data

    def prepare(self):
        self.legacy_data()
        self.upgrade()

    def test_owner_filter_precedes_top_five_and_shared_file_is_not_duplicated(self):
        from repositories.rag import RagRepository
        self.prepare()
        self.connection.execute(sa.text("INSERT INTO users (id,username,email,hashed_password) VALUES (2,'other','other@example.com','hash')"))
        self.connection.execute(sa.text("INSERT INTO modules (id,owner_id,title,description) VALUES (2,2,'Private','Private')"))
        self.connection.execute(sa.text("INSERT INTO launches (id,module_id,title,year,semester) VALUES (2,2,'Private',2026,'Fall'),(3,1,'Copy',2027,'Fall')"))
        self.connection.execute(sa.text("INSERT INTO stored_files (id,bucket,storage_key,original_filename,mime_type,size_bytes,uploaded_by_id,indexing_status) VALUES (2,'test','private','private.txt','text/plain',10,2,'ready')"))
        self.connection.execute(sa.text("INSERT INTO materials (launch_id,stored_file_id,title) VALUES (2,2,'Private'),(3,1,'Copy')"))
        self.connection.execute(sa.text("UPDATE stored_files SET indexing_status='ready' WHERE id=1"))
        for index in range(8):
            for file_id, vector in [(1, [0, 1] + [0] * 254), (2, [1] + [0] * 255)]:
                self.connection.execute(sa.text("INSERT INTO document_chunks (stored_file_id,chunk_index,content,embedding) VALUES (:file,:index,:content,CAST(:embedding AS vector))"),
                    {'file': file_id, 'index': index, 'content': 'Public' if file_id == 1 else 'Private secret', 'embedding': str(vector)})
        self.connection.commit()
        with Session(bind=self.connection) as db:
            repo = RagRepository(db)
            self.assertFalse(repo.has_scope(1, 2, None))
            self.assertFalse(repo.has_scope(1, 1, 2))
            self.assertEqual(repo.search(1, 2, None, [1] + [0] * 255), [])
            rows = repo.search(1, 1, None, [1] + [0] * 255)
            self.assertEqual(len(rows), 5)
            self.assertEqual(len({r['chunk_id'] for r in rows}), 5)
            self.assertTrue(all(r['content'] == 'Public' for r in rows))
            scoped = repo.search(1, 1, 3, [1] + [0] * 255)
            self.assertTrue(all(r['launch_id'] == 3 for r in scoped))
            db.execute(sa.text("UPDATE stored_files SET indexing_status='processing' WHERE id=1"))
            self.assertEqual(repo.search(1, 1, None, [1] + [0] * 255), [])
            db.execute(sa.text("UPDATE stored_files SET indexing_status='ready' WHERE id=1"))
            db.execute(sa.text("UPDATE stored_files SET deletion_pending=true WHERE id=1"))
            self.assertEqual(repo.search(1, 1, None, [1] + [0] * 255), [])

    def test_worker_recovery_exclusion_and_idempotent_reindex(self):
        from repositories.indexing import IndexingRepository
        from services.indexing import IndexingService
        self.prepare()
        data = b'Git keeps project history.'
        self.connection.execute(sa.text('UPDATE stored_files SET size_bytes=:size'), {'size': len(data)})
        bucket = self.connection.scalar(sa.text('SELECT bucket FROM stored_files WHERE id=1'))
        self.connection.commit()
        with self.connect() as second_connection, Session(bind=self.connection) as first_db, Session(bind=second_connection) as second_db:
            first, second = IndexingRepository(first_db), IndexingRepository(second_db)
            try:
                self.assertEqual(first.claim()['id'], 1)
                self.assertIsNone(second.claim())
                first.release()
                self.assertEqual(second.claim()['id'], 1)
                second.release()
                storage = Mock()
                storage.read_file.return_value = data
                ai = Mock()
                ai.embed.return_value = [0.1] * 256
                service = IndexingService(first, storage, ai, bucket)
                self.assertTrue(service.process_next())
                self.assertEqual(first_db.scalar(sa.text('SELECT count(*) FROM document_chunks')), 1)
                self.assertEqual(first_db.scalar(sa.text('SELECT indexing_status::text FROM stored_files')), 'ready')
                first.reindex(1, 1)
                self.assertTrue(service.process_next())
                self.assertEqual(first_db.scalar(sa.text('SELECT count(*) FROM document_chunks')), 1)
                first.reindex(1, 1)
                ai.embed.side_effect = RuntimeError('private diagnostic')
                service.process_next()
                self.assertEqual(first_db.scalar(sa.text('SELECT indexing_error_code FROM stored_files')), 'INDEX_INTERNAL_ERROR')
                self.assertEqual(first_db.scalar(sa.text('SELECT count(*) FROM document_chunks')), 1)
            finally:
                first.release()
                second.release()


class AIConfigurationTests(unittest.TestCase):
    def test_compose_string_environment_accepts_fixed_dimension_and_top_k(self):
        import importlib.util
        from pathlib import Path
        spec = importlib.util.spec_from_file_location('rag_config_test', Path(__file__).resolve().parents[1] / 'app/core/config.py')
        config = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(config)
        settings = config.Settings(AI_EMBED_DIM='256', AI_TOP_K='5')
        self.assertEqual(settings.AI_EMBED_DIM, 256)
        self.assertEqual(settings.AI_TOP_K, 5)


class AdditionalFormatsTests(unittest.TestCase):
    def test_docx_pptx_csv_extract_text_with_real_coordinates(self):
        from docx import Document
        from pptx import Presentation
        from services.document_extraction import extract_chunks
        document = Document()
        document.add_paragraph('DOCX lesson')
        stream = io.BytesIO()
        document.save(stream)
        chunks = extract_chunks(stream.getvalue(), 'lesson.docx')
        self.assertIn('DOCX lesson', chunks[0]['content'])
        self.assertNotIn('page_number', chunks[0])
        slides = Presentation()
        slide = slides.slides.add_slide(slides.slide_layouts[1])
        slide.shapes.title.text = 'PPTX lesson'
        stream = io.BytesIO()
        slides.save(stream)
        self.assertEqual(extract_chunks(stream.getvalue(), 'lesson.pptx')[0]['slide_number'], 1)
        self.assertIn('Git', extract_chunks(b'Topic,Score\nGit,4\n', 'scores.csv')[1]['content'])

    def test_pdf_extracts_text_and_page_number_and_rejects_scans(self):
        from pypdf import PdfWriter
        from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject
        from services.document_extraction import extract_chunks
        from adapters.ai.yandex import AIError
        writer = PdfWriter()
        page = writer.add_blank_page(width=300, height=300)
        stream = io.BytesIO()
        writer.write(stream)
        with self.assertRaises(AIError):
            extract_chunks(stream.getvalue(), 'scan.pdf')
        font = DictionaryObject({NameObject('/Type'): NameObject('/Font'),
            NameObject('/Subtype'): NameObject('/Type1'), NameObject('/BaseFont'): NameObject('/Helvetica')})
        page[NameObject('/Resources')] = DictionaryObject({NameObject('/Font'): DictionaryObject({NameObject('/F1'): font})})
        content = DecodedStreamObject()
        content.set_data(b'BT /F1 12 Tf 10 250 Td (Git history) Tj ET')
        page[NameObject('/Contents')] = writer._add_object(content)
        stream = io.BytesIO()
        writer.write(stream)
        chunks = extract_chunks(stream.getvalue(), 'lesson.pdf')
        self.assertEqual(chunks[0]['page_number'], 1)
        self.assertIn('Git history', chunks[0]['content'])


import test_http_errors_cors as http_runtime


class RagHTTPTests(http_runtime.HTTPTestCase):
    def test_insufficient_data_without_citations_returns_http_200(self):
        from core.depends import get_rag_service
        from services.rag import RagService
        repository, ai = Mock(), Mock()
        repository.has_scope.return_value = True
        repository.search.return_value = [dict(chunk_id=8, material_id=9, launch_id=10,
            title='Лекция', year=2026, content='Git', chunk_index=0)]
        ai.embed.return_value = [1.0] * 256
        ai.generate.return_value = {'answer': 'Недостаточно данных для ответа.'}
        self.app.dependency_overrides[get_rag_service] = lambda: RagService(repository, ai)
        status, _, response = self.request('POST', '/ai/ask', body={'module_id': 1, 'question': 'Какой средний балл?'})
        self.assertEqual(status, 200)
        self.assertEqual(response, {'status': 'ok', 'answer': 'Недостаточно данных для ответа.', 'sources': []})
