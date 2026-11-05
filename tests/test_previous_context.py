from unittest.mock import patch

from sqlalchemy import event, select

import test_erd as runtime
import test_http_errors_cors as http_runtime
from models.launch_designs import LaunchDesign
from models.launch_reflections import LaunchReflection
from repositories.launch_designs import LaunchDesignRepository


class PreviousContextTests(http_runtime.HTTPTestCase):
    empty = {'source_launch': None, 'design': None, 'notes': {}, 'reflection': None}

    def context_path(self, launch_id):
        return f'/launches/{launch_id}/previous-context'

    def create_launch(self, title='New'):
        status, _, launch = self.request('POST', f"/modules/{self.fixture.module['id']}/launches", body={
            'title': title, 'year': 2028, 'semester': 'Spring',
        })
        self.assertEqual(status, 201, launch)
        return launch

    def copy_launch(self, source_id):
        status, _, copied = self.request('POST', f'/launches/{source_id}/copy', body={
            'title': 'Copy', 'year': 2029, 'semester': 'Spring',
        })
        self.assertEqual(status, 201, copied)
        return copied

    def upload_material(self, launch_id, kind, section_id=None):
        boundary = 'mvp-workflow-boundary'
        fields = {'title': f'Material {kind}', 'kind': kind}
        if section_id is not None:
            fields['section_id'] = str(section_id)
        parts = [f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"\r\n\r\n{value}\r\n'
                 for key, value in fields.items()]
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{kind}.txt"\r\nContent-Type: text/plain\r\n\r\nMaterial content\r\n--{boundary}--\r\n')
        status, _, material = self.request('POST', f'/launches/{launch_id}/materials', raw=''.join(parts).encode(),
                                           headers={'Content-Type': f'multipart/form-data; boundary={boundary}'})
        self.assertEqual(status, 201, material)
        return material

    def test_no_source_returns_empty_context_without_choosing_latest(self):
        self.create_launch('Latest')
        status, _, context = self.request('GET', self.context_path(self.fixture.run['id']))
        self.assertEqual(status, 200)
        self.assertEqual(context, self.empty)

    def test_context_uses_explicit_source_and_get_is_read_only(self):
        source_id = self.fixture.run['id']
        self.request('PUT', f'/launches/{source_id}/design', body={'data': {'passport': {'category': 'Original'}}})
        self.request('POST', f'/launches/{source_id}/notes', body={'title': 'Note', 'content': 'Source text', 'priority': 'high'})
        self.request('PUT', f'/launches/{source_id}/reflection', body={'what_went_well': 'Good'})
        copied = self.copy_launch(source_id)
        self.create_launch('Latest, not source')
        expected = {'source_launch': self.request('GET', f'/launches/{source_id}')[2],
                    'design': self.request('GET', f'/launches/{source_id}/design')[2],
                    'notes': self.request('GET', f'/launches/{source_id}/notes')[2],
                    'reflection': self.request('GET', f'/launches/{source_id}/reflection')[2]}
        statements = []

        def capture(connection, cursor, statement, parameters, context, executemany):
            statements.append(statement.lstrip().upper())

        event.listen(runtime.engine, 'before_cursor_execute', capture)
        self.addCleanup(event.remove, runtime.engine, 'before_cursor_execute', capture)
        with patch.object(self.fixture.db, 'commit', side_effect=AssertionError('GET commits')):
            status, _, context = self.request('GET', self.context_path(copied['id']))
        self.assertEqual(status, 200)
        self.assertEqual(context, expected)
        self.assertTrue(statements)
        self.assertTrue(all(statement.startswith('SELECT') for statement in statements), statements)
        # Context is the current source state, not the copied snapshot or latest launch.
        self.request('PUT', f'/launches/{source_id}/reflection', body={'what_went_well': 'Updated'})
        self.assertEqual(self.request('GET', self.context_path(copied['id']))[2]['reflection']['what_went_well'], 'Updated')

    def test_unfilled_source_context_does_not_create_design_or_reflection(self):
        copied = self.copy_launch(self.fixture.run['id'])
        self.fixture.db.delete(self.fixture.db.get(LaunchDesign, self.fixture.run['id']))
        self.fixture.db.commit()
        with patch.object(self.fixture.db, 'add', side_effect=AssertionError('GET creates record')):
            status, _, context = self.request('GET', self.context_path(copied['id']))
        self.assertEqual(status, 200)
        self.assertEqual(context['design']['data'], {})
        self.assertIsNone(context['design']['created_at'])
        self.assertEqual(context['notes'], {})
        self.assertIsNone(context['reflection']['what_went_well'])
        self.assertIsNone(context['reflection']['created_at'])
        self.assertIsNone(self.fixture.db.get(LaunchDesign, self.fixture.run['id']))
        self.assertIsNone(self.fixture.db.get(LaunchReflection, self.fixture.run['id']))

    def test_source_deletion_clears_context_and_preserves_shared_file(self):
        material = self.upload_material(self.fixture.run['id'], 'plan')
        copied = self.copy_launch(self.fixture.run['id'])
        file_key = self.fixture.files.get_file_by_id(material['stored_file_id'], 1)['storage_key']
        self.assertEqual(self.request('DELETE', f"/launches/{self.fixture.run['id']}")[0], 200)
        status, _, context = self.request('GET', self.context_path(copied['id']))
        self.assertEqual(status, 200)
        self.assertEqual(context, self.empty)
        self.assertIsNone(self.request('GET', f"/launches/{copied['id']}")[2]['copied_from_launch_id'])
        self.assertIn(file_key, self.fixture.storage.objects)
        copied_material = next(iter(self.request('GET', f"/launches/{copied['id']}/materials")[2].values()))
        self.assertEqual(self.request('GET', f"/materials/{copied_material['id']}/download")[0], 200)

    def test_missing_or_foreign_requested_launch_returns_existing_404(self):
        for launch_id in (999999, self.fixture.other_run['id']):
            with self.subTest(launch_id=launch_id):
                self.assert_error(self.request('GET', self.context_path(launch_id)), 404,
                                  'LAUNCH_NOT_FOUND', 'Запуск не найден')

    def test_inconsistent_source_module_or_owner_never_discloses_contents(self):
        another_module = self.fixture.modules.create_module(1, {'title': 'Another module', 'description': ''})
        another_run = self.fixture.launches.create_launch(another_module['id'], self.fixture.run_data('Other module source'))
        for source_id in (self.fixture.other_run['id'], another_run['id']):
            with self.subTest(source_id=source_id):
                launch = self.fixture.db.get(runtime.Launch, self.fixture.run['id'])
                launch.copied_from_launch_id = source_id
                self.fixture.db.commit()
                with patch.object(LaunchDesignRepository, 'get_design', side_effect=AssertionError('Reads forbidden source')):
                    status, _, context = self.request('GET', self.context_path(launch.id))
                self.assertEqual(status, 200)
                self.assertEqual(context, self.empty)

    def test_context_requires_authentication(self):
        del self.app.dependency_overrides[runtime.get_current_user]
        response = self.request('GET', self.context_path(self.fixture.run['id']))
        self.assert_error(response, 401, 'AUTHENTICATION_REQUIRED', 'Требуется авторизация')
        self.assertEqual(response[1]['www-authenticate'], 'Bearer')

    def test_context_cors_on_success_and_http_error(self):
        origin = 'http://localhost:3000'
        http_runtime.CORSTests.configure_origins(self, [origin])
        response = self.request('GET', self.context_path(self.fixture.run['id']), headers={'Origin': origin})
        self.assertEqual(response[0], 200)
        self.assertEqual(response[1]['access-control-allow-origin'], origin)
        response = self.request('GET', self.context_path(999999), headers={'Origin': origin})
        self.assert_error(response, 404, 'LAUNCH_NOT_FOUND', 'Запуск не найден')
        self.assertEqual(response[1]['access-control-allow-origin'], origin)
        response = self.request('GET', self.context_path(self.fixture.run['id']), headers={'Origin': 'http://foreign.invalid'})
        self.assertEqual(response[0], 200)
        self.assertNotIn('access-control-allow-origin', response[1])

    def test_full_mvp_workflow_through_real_http_responses(self):
        source = self.create_launch('Source')
        source_id = source['id']
        self.assertIsNone(source['copied_from_launch_id'])
        self.assertEqual(self.request('GET', f'/launches/{source_id}/design')[2]['data'], {})
        self.assertEqual(self.request('GET', f'/launches/{source_id}/sections')[2], {})
        self.assertEqual(self.request('GET', f'/launches/{source_id}/materials')[2], {})
        form = {'passport': {'planned_capacity': 30}, 'educational_concept': {'learning_outcomes': ['Second', 'First']}}
        self.assertEqual(self.request('PUT', f'/launches/{source_id}/design', body={'data': form})[0], 200)
        sections = []
        for title in ('Teaching', 'Empty'):
            status, _, section = self.request('POST', f'/launches/{source_id}/sections', body={'title': title})
            self.assertEqual(status, 201)
            sections.append(section)
        plan = self.upload_material(source_id, 'plan', sections[0]['id'])
        self.upload_material(source_id, 'feedback')
        note = self.request('POST', f'/launches/{source_id}/notes', body={
            'title': 'Issue', 'content': 'What happened', 'material_id': plan['id'], 'section_id': sections[0]['id'],
            'cause': 'Cause', 'priority': 'high', 'status': 'in_progress',
        })
        self.assertEqual(note[0], 201)
        reflection = self.request('PUT', f'/launches/{source_id}/reflection', body={'decisions_to_keep': 'Keep'})
        self.assertEqual(reflection[0], 200)
        with patch.object(self.fixture.storage, 'upload_file', side_effect=AssertionError('Copy uploads')):
            copied = self.copy_launch(source_id)
        copy_id = copied['id']
        self.assertEqual(self.request('GET', f'/launches/{copy_id}/design')[2]['data'], form)
        copied_sections = self.request('GET', f'/launches/{copy_id}/sections')[2]
        self.assertEqual({item['title'] for item in copied_sections.values()}, {'Teaching', 'Empty'})
        self.assertTrue({item['id'] for item in copied_sections.values()}.isdisjoint({item['id'] for item in sections}))
        materials = self.request('GET', f'/launches/{copy_id}/materials')[2]
        self.assertEqual(len(materials), 1)
        copied_plan = next(iter(materials.values()))
        self.assertEqual(copied_plan['kind'], 'plan')
        self.assertEqual(copied_plan['stored_file_id'], plan['stored_file_id'])
        self.assertEqual(copied_plan['copied_from_material_id'], plan['id'])
        self.assertIn(str(copied_plan['section_id']), copied_sections)
        self.assertEqual(copied_sections[str(copied_plan['section_id'])]['title'], 'Teaching')
        self.assertEqual(self.request('GET', f'/launches/{copy_id}/notes')[2], {})
        self.assertIsNone(self.request('GET', f'/launches/{copy_id}/reflection')[2]['decisions_to_keep'])
        status, _, context = self.request('GET', self.context_path(copy_id))
        self.assertEqual(status, 200)
        self.assertEqual(context['source_launch'], source)
        self.assertEqual(context['design']['data'], form)
        self.assertEqual(context['notes'], {str(note[2]['id']): note[2]})
        self.assertEqual(context['reflection'], reflection[2])
        self.assertEqual(self.request('PUT', f'/launches/{copy_id}/design', body={'data': {'passport': {'planned_capacity': 15}}})[0], 200)
        self.assertEqual(self.request('PATCH', f"/materials/{copied_plan['id']}", body={'title': 'Copy plan'})[0], 200)
        self.assertEqual(self.request('GET', f'/launches/{source_id}/design')[2]['data'], form)
        self.assertEqual(self.request('GET', f"/materials/{plan['id']}")[2]['title'], plan['title'])
        self.assertEqual(self.request('GET', self.context_path(copy_id))[2], context)
        file_key = self.fixture.files.get_file_by_id(plan['stored_file_id'], 1)['storage_key']
        self.assertEqual(self.request('DELETE', f'/launches/{copy_id}')[0], 200)
        self.assertIn(file_key, self.fixture.storage.objects)
        self.assertEqual(self.request('GET', f"/materials/{plan['id']}/download")[0], 200)
        self.assertEqual(self.request('GET', f'/launches/{source_id}/reflection')[2], reflection[2])
