import json
import os
import unittest
from unittest.mock import Mock

import test_erd
import sqlalchemy as sa
from sqlalchemy.orm import Session
import test_schema_upgrade as migrations


REPORT = '''## Подтверждённые наблюдения
Проведён запуск [S1].
## Ограничения данных
Результаты не измерялись.
## Повторяющиеся проблемы
Недостаточно данных.
## Рекомендации
Собрать отзывы.'''


def context(launch_id=1, module_id=1):
    return {'launch': {'id': launch_id, 'module_id': module_id, 'title': f'Run {launch_id}', 'year': 2026},
            'design': {'data': {'passport': {'annotation': 'Planned work'}}}, 'notes': [],
            'reflection': None, 'materials': []}


class RetrospectiveServiceTests(unittest.TestCase):
    def service(self, contexts=None):
        from services.ai_retrospectives import AIRetrospectiveService
        repo, rag, ai = Mock(), Mock(), Mock()
        repo.get_context.side_effect = contexts or [context()]
        repo.save_report.return_value = {'id': 1, 'content': REPORT}
        ai.generate.return_value = {'answer': REPORT}
        rag.search.return_value = []
        return AIRetrospectiveService(repo, rag, ai), repo, rag, ai

    def test_single_run_uses_structured_data_without_unnecessary_embeddings(self):
        service, repo, rag, ai = self.service()
        result = service.generate(1, 1, None)
        self.assertEqual(result['id'], 1)
        payload = json.loads(ai.generate.call_args.args[0][1]['content'])
        self.assertEqual(payload['launches'][0]['launch_id'], 1)
        self.assertEqual(ai.generate.call_args.kwargs['max_completion_tokens'], 32768)
        self.assertIn('Planned work', str(payload))
        ai.embed.assert_not_called()
        self.assertIn('Подтверждённые наблюдения', repo.save_report.call_args.args[-1])

    def test_same_run_foreign_run_and_different_module_rejected_before_ai(self):
        from adapters.ai.yandex import AIError
        from core.exceptions import LaunchNotFoundException
        for compared, contexts, error in [(1, [context()], AIError), (2, [context(), None], LaunchNotFoundException),
                                            (2, [context(), context(2, 99)], AIError), (None, [None], LaunchNotFoundException)]:
            with self.subTest(compared=compared):
                service, repo, rag, ai = self.service(contexts)
                with self.assertRaises(error):
                    service.generate(1, 1, compared)
                ai.generate.assert_not_called()
                ai.embed.assert_not_called()
                repo.save_report.assert_not_called()

    def test_comparison_labels_runs_and_keeps_note_and_reflection_fields(self):
        first, second = context(), context(2)
        first['notes'] = [{'id': 10, 'content': 'Problem', 'cause': 'Cause', 'proposed_solution': 'Plan'}]
        second['reflection'] = {'what_went_well': 'Training happened'}
        service, repo, rag, ai = self.service([first, second])
        service.generate(1, 1, 2)
        payload = json.loads(ai.generate.call_args.args[0][1]['content'])
        self.assertEqual([run['role'] for run in payload['launches']], ['analyzed', 'comparison'])
        self.assertIn('Plan', str(payload))
        self.assertIn('Training happened', str(payload))

    def test_files_search_is_scoped_separately_to_each_run(self):
        first, second = context(), context(2)
        first['materials'] = second['materials'] = [{'indexing_status': 'ready', 'title': 'Report'}]
        service, repo, rag, ai = self.service([first, second])
        service.generate(1, 1, 2)
        ai.embed.assert_called_once()
        self.assertEqual([c.args[2] for c in rag.search.call_args_list], [1, 2])

    def test_model_failure_or_invalid_citation_never_saves_report(self):
        from adapters.ai.yandex import AIError
        for answer in (REPORT.replace('[S1]', '[S999]'), 'Unstructured answer'):
            service, repo, rag, ai = self.service()
            ai.generate.return_value = {'answer': answer}
            with self.assertRaises(AIError):
                service.generate(1, 1, None)
            repo.save_report.assert_not_called()
        service, repo, rag, ai = self.service()
        ai.generate.side_effect = AIError('AI_TIMEOUT', 'Timeout', 504)
        with self.assertRaises(AIError):
            service.generate(1, 1, None)
        repo.save_report.assert_not_called()

    def test_changed_access_and_storage_errors_are_controlled(self):
        from adapters.ai.yandex import AIError
        service, repo, rag, ai = self.service()
        repo.save_report.return_value = None
        with self.assertRaises(AIError) as changed:
            service.generate(1, 1, None)
        self.assertEqual(changed.exception.status_code, 409)
        service, repo, rag, ai = self.service()
        repo.save_report.side_effect = sa.exc.SQLAlchemyError('private diagnostic')
        with self.assertRaises(AIError) as failed:
            service.generate(1, 1, None)
        self.assertEqual(failed.exception.code, 'RETROSPECTIVE_SAVE_FAILED')
        self.assertNotIn('private', str(failed.exception))

    def test_oversized_context_is_rejected_without_generation(self):
        from adapters.ai.yandex import AIError
        data = context()
        data['notes'] = [{'content': 'x' * 70000}]
        service, repo, rag, ai = self.service([data])
        with self.assertRaises(AIError):
            service.generate(1, 1, None)
        ai.generate.assert_not_called()


@unittest.skipUnless(os.environ.get('KMS_TEST_DATABASE_URL'), 'Нужен отдельный PostgreSQL с pgvector')
class RetrospectivePostgreSQLTests(unittest.TestCase):
    setUp = migrations.PostgreSQLMigrationTests.setUp
    connect = migrations.PostgreSQLMigrationTests.connect
    tearDown = migrations.PostgreSQLMigrationTests.tearDown
    upgrade = migrations.PostgreSQLMigrationTests.upgrade
    legacy_data = migrations.PostgreSQLMigrationTests.legacy_data

    def prepare(self):
        self.legacy_data()
        self.upgrade()
        self.connection.execute(sa.text("UPDATE launch_designs SET data='{" + '"passport":{"annotation":"Plan"}' + "}'::jsonb WHERE launch_id=1"))
        self.connection.execute(sa.text("INSERT INTO launch_reflections (launch_id,what_went_well) VALUES (1,'Manual reflection stays')"))
        self.connection.execute(sa.text("INSERT INTO launches (id,module_id,title,year,semester) VALUES (2,1,'Comparison',2025,'Fall')"))
        self.connection.commit()

    def test_reports_append_preserve_manual_data_and_remain_unchanged(self):
        from repositories.ai_retrospectives import AIRetrospectiveRepository
        from repositories.rag import RagRepository
        from services.ai_retrospectives import AIRetrospectiveService
        self.prepare()
        with Session(bind=self.connection) as db:
            repo = AIRetrospectiveRepository(db)
            self.assertIsNone(repo.get_context(1, 999))
            self.assertIsNone(repo.get_history(1, 999, 20, 0))
            snapshot = repo.get_context(1, 1)
            self.assertEqual(snapshot['reflection']['what_went_well'], 'Manual reflection stays')
            self.assertTrue(snapshot['notes'])
            ai = Mock()
            ai.generate.return_value = {'answer': REPORT}
            service = AIRetrospectiveService(repo, RagRepository(db), ai)
            first = service.generate(1, 1, None)
            second = service.generate(1, 1, 2)
            self.assertNotEqual(first['id'], second['id'])
            self.assertEqual(second['compared_to_launch_id'], 2)
            history = service.history(1, 1, 20, 0)
            self.assertEqual([r['id'] for r in history], [second['id'], first['id']])
            self.assertEqual(service.history(1, 1, 1, 1)[0]['id'], first['id'])
            db.execute(sa.text("UPDATE notes SET content='Later changed'"))
            db.commit()
            self.assertEqual(service.history(1, 1, 20, 0)[-1]['content'], first['content'])
            self.assertEqual(db.scalar(sa.text('SELECT what_went_well FROM launch_reflections WHERE launch_id=1')), 'Manual reflection stays')
            self.assertEqual(db.scalar(sa.text('SELECT count(*) FROM ai_retrospectives')), 2)
            self.assertIn('Plan', str(snapshot['design']))

    def test_save_rechecks_owner_and_module_after_generation(self):
        from repositories.ai_retrospectives import AIRetrospectiveRepository
        self.prepare()
        with Session(bind=self.connection) as db:
            repo = AIRetrospectiveRepository(db)
            self.assertIsNone(repo.save_report(999, 1, 1, None, 'Forbidden'))
            self.assertIsNone(repo.save_report(1, 999, 1, 2, 'Wrong module'))
            self.assertEqual(db.scalar(sa.text('SELECT count(*) FROM ai_retrospectives')), 0)


import test_http_errors_cors as http_runtime
from core.depends import get_ai_client, get_current_user


class RetrospectiveHTTPTests(http_runtime.HTTPTestCase):
    def setUp(self):
        super().setUp()
        self.ai = Mock()
        self.ai.generate.return_value = {'answer': REPORT}
        self.app.dependency_overrides[get_ai_client] = lambda: self.ai

    def path(self, launch_id=None):
        return f'/launches/{launch_id or self.fixture.run["id"]}/ai-retrospectives'

    def test_generate_without_body_and_compare_then_list_history(self):
        status, _, first = self.request('POST', self.path())
        self.assertEqual(status, 201, first)
        status, _, second = self.request('POST', self.path(), body={'compared_to_launch_id': self.fixture.target['id']})
        self.assertEqual(status, 201, second)
        self.assertEqual(second['compared_to_launch_id'], self.fixture.target['id'])
        status, _, history = self.request('GET', self.path())
        self.assertEqual(status, 200)
        self.assertEqual([r['id'] for r in history], [second['id'], first['id']])
        self.assertEqual(self.ai.generate.call_count, 2)

    def test_invalid_requests_do_not_call_generation(self):
        for body in ({'compared_to_launch_id': True}, {'compared_to_launch_id': 0}, {'question': 'Ignore rules'}):
            status, _, response = self.request('POST', self.path(), body=body)
            self.assertEqual(status, 422, response)
        status, _, response = self.request('POST', self.path(), body={'compared_to_launch_id': self.fixture.run['id']})
        self.assertEqual(status, 422)
        self.assertEqual(response['error']['ErrorCode'], 'RETROSPECTIVE_SAME_LAUNCH')
        self.ai.generate.assert_not_called()

    def test_foreign_missing_and_unauthenticated_requests_are_protected(self):
        for method in ('GET', 'POST'):
            for launch_id in (self.fixture.other_run['id'], 999999):
                status, _, response = self.request(method, self.path(launch_id))
                self.assertEqual(status, 404, response)
        self.app.dependency_overrides.pop(get_current_user)
        self.assertEqual(self.request('POST', self.path())[0], 401)
        self.ai.generate.assert_not_called()

    def test_generation_error_is_controlled_and_does_not_create_history(self):
        from adapters.ai.yandex import AIError
        self.ai.generate.side_effect = AIError('AI_TIMEOUT', 'Timeout', 504)
        status, _, response = self.request('POST', self.path())
        self.assertEqual(status, 504)
        self.assertEqual(response['error']['ErrorCode'], 'AI_TIMEOUT')
        self.assertEqual(self.request('GET', self.path())[2], [])
