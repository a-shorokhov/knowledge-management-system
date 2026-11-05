from datetime import date
from unittest.mock import patch

from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError

import test_http_errors_cors as http_runtime
import test_erd as runtime
from models.launch_designs import LaunchDesign
from models.launches import Launch


class LaunchDesignTests(http_runtime.HTTPTestCase):
    def path(self, launch_id=None):
        return f"/launches/{launch_id or self.fixture.run['id']}/design"

    def put(self, data, **extra):
        return self.request('PUT', self.path(), body={'data': data, **extra})

    def test_minimal_creation_is_empty_and_does_not_copy_previous(self):
        self.put({'passport': {'category': 'Previous'}})
        self.fixture.section()
        self.fixture.material()
        status, _, launch = self.request('POST', f"/modules/{self.fixture.module['id']}/launches", body={
            'title': 'New', 'year': 2027, 'semester': 'Весна',
        })
        self.assertEqual(status, 201)
        self.assertEqual(launch['description'], '')
        self.assertEqual(launch['status'], 'draft')
        self.assertIsNone(launch['copied_from_launch_id'])
        design = self.fixture.db.get(LaunchDesign, launch['id'])
        self.assertIsNotNone(design)
        self.assertEqual(design.data, {})
        self.assertEqual(design.template_version, 1)
        self.assertEqual(self.fixture.sections.get_all_sections(launch['id'], 1), {})
        self.assertEqual(self.fixture.materials.get_all_materials(launch['id'], 1), {})

    def test_creation_rolls_back_launch_when_design_cannot_be_saved(self):
        before = self.fixture.db.scalar(select(func.count()).select_from(Launch))
        original_flush = self.fixture.db.flush

        def fail_design(*args, **kwargs):
            if any(isinstance(obj, LaunchDesign) for obj in self.fixture.db.new):
                raise SQLAlchemyError('fake design insert failure')
            return original_flush(*args, **kwargs)

        with patch.object(self.fixture.db, 'flush', side_effect=fail_design):
            with self.assertRaises(SQLAlchemyError):
                self.fixture.launches.create_launch(self.fixture.module['id'], self.fixture.run_data('Fail'))
        self.assertEqual(self.fixture.db.scalar(select(func.count()).select_from(Launch)), before)
        self.assertEqual(self.fixture.db.scalar(select(func.count()).select_from(LaunchDesign)), before)

    def test_empty_form_created_with_launch(self):
        status, _, design = self.request('GET', self.path())
        self.assertEqual(status, 200)
        self.assertEqual(design['data'], {})
        self.assertEqual(design['template_version'], 1)
        self.assertIsNotNone(design['created_at'])
        self.assertIsNotNone(design['updated_at'])

    def test_full_document_roundtrip_preserves_array_order(self):
        data = {
            'passport': {'category': 'Education', 'module_type': 'mixed', 'annotation': 'Annotation',
                         'target_audience': 'Students', 'duration_weeks': 4, 'duration_academic_hours': 72,
                         'delivery_format': 'online', 'language': 'ru', 'planned_capacity': 30},
            'educational_concept': {'relevance': 'Relevant', 'goal': 'Goal',
                                    'learning_outcomes': [f'Outcome {i}' for i in range(8, -1, -1)],
                                    'prerequisites': 'Basics', 'success_criteria': 'Criteria'},
            'project': {'task': 'Task', 'context': 'Context', 'partner': None, 'expected_output': 'Report',
                        'work_format': 'team', 'stages': [
                            {'position': i, 'student_activity': f'Activity {i}', 'intermediate_result': f'Result {i}'}
                            for i in range(8, -1, -1)]},
        }
        status, _, saved = self.put(data)
        self.assertEqual(status, 200)
        self.assertEqual(saved['data'], data)
        self.fixture.db.expire_all()
        status, _, loaded = self.request('GET', self.path())
        self.assertEqual(status, 200)
        self.assertEqual(loaded['data'], data)
        self.assertEqual(self.fixture.db.get(LaunchDesign, self.fixture.run['id']).data, data)

    def test_partial_draft_and_nullable_partner(self):
        for data in ({'passport': {'duration_weeks': 1, 'planned_capacity': 0}},
                     {'project': {'partner': None, 'stages': [{'student_activity': 'Start'}]}},
                     {'educational_concept': {'learning_outcomes': []}}):
            with self.subTest(data=data):
                status, _, result = self.put(data)
                self.assertEqual(status, 200)
                self.assertEqual(result['data'], data)

    def test_put_replaces_entire_document_including_nested_fields(self):
        self.put({'passport': {'category': 'Old', 'language': 'ru'}, 'project': {'task': 'Old'}})
        status, _, saved = self.put({'passport': {'category': 'New'}})
        self.assertEqual(status, 200)
        self.assertEqual(saved['data'], {'passport': {'category': 'New'}})
        self.assertEqual(self.request('GET', self.path())[2]['data'], saved['data'])
        self.assertEqual(self.put({})[2]['data'], {})
        self.put({'project': {'task': 'Again'}})
        self.assertEqual(self.request('PUT', self.path(), body={})[2]['data'], {})

    def test_invalid_types_enums_bounds_and_unknown_fields_are_rejected(self):
        documents = [
            [], None, {'owner_id': 1}, {'title': 'Duplicate'}, {'passport': {'module_id': 1}},
            {'passport': {'module_type': 'unknown'}}, {'passport': {'delivery_format': 'hybrid'}},
            {'passport': {'duration_weeks': 0}}, {'passport': {'duration_academic_hours': -1}},
            {'passport': {'planned_capacity': -1}}, {'passport': {'planned_capacity': True}},
            {'passport': {'duration_weeks': '4'}}, {'passport': {'category': 123}},
            {'passport': None}, {'passport': {'language': None}},
            {'educational_concept': {'learning_outcomes': [1]}},
            {'educational_concept': {'learning_outcomes': 'text'}},
            {'project': {'work_format': 'pair'}}, {'project': {'stages': [{}], 'unknown': 'x'}},
            {'project': {'stages': [{'position': -1}]}}, {'project': {'stages': [{'unknown': 'x'}]}},
        ]
        for data in documents:
            with self.subTest(data=data):
                self.assertEqual(self.put(data)[0], 422)
        self.assertEqual(self.request('GET', self.path())[2]['data'], {})

    def test_template_version_is_strict_and_supported(self):
        for version in (0, -1, 2, True, '1', None):
            with self.subTest(version=version):
                self.assertEqual(self.put({}, template_version=version)[0], 422)
        self.assertEqual(self.put({}, template_version=1)[0], 200)
        self.assertEqual(self.request('PUT', self.path(), body={'data': {}, 'unknown': 1})[0], 422)

    def test_missing_design_get_is_read_only_and_put_creates_record(self):
        self.fixture.db.delete(self.fixture.db.get(LaunchDesign, self.fixture.run['id']))
        self.fixture.db.commit()
        with patch.object(self.fixture.db, 'add', side_effect=AssertionError('GET writes')), patch.object(self.fixture.db, 'commit', side_effect=AssertionError('GET commits')):
            status, _, result = self.request('GET', self.path())
        self.assertEqual(status, 200)
        self.assertEqual(result, {'launch_id': self.fixture.run['id'], 'template_version': 1, 'data': {}, 'created_at': None, 'updated_at': None})
        self.assertIsNone(self.fixture.db.get(LaunchDesign, self.fixture.run['id']))
        self.assertEqual(self.put({'project': {'task': 'New'}})[0], 200)
        self.assertIsNotNone(self.fixture.db.get(LaunchDesign, self.fixture.run['id']))

    def test_design_is_private_and_missing_launch_returns_404(self):
        for launch_id in (999999, self.fixture.other_run['id']):
            for method in ('GET', 'PUT'):
                with self.subTest(launch_id=launch_id, method=method):
                    self.assert_error(self.request(method, self.path(launch_id), body={} if method == 'PUT' else None),
                                      404, 'LAUNCH_NOT_FOUND', 'Запуск не найден')
        self.assertEqual(self.fixture.db.get(LaunchDesign, self.fixture.other_run['id']).data, {})

    def test_design_requires_authentication(self):
        del self.app.dependency_overrides[runtime.get_current_user]
        for method, path in [('GET', self.path()), ('PUT', self.path()), ('GET', '/launch-design/template')]:
            with self.subTest(method=method, path=path):
                self.assertEqual(self.request(method, path, body={} if method == 'PUT' else None)[0], 401)

    def test_launch_deletion_cascades_design(self):
        self.put({'project': {'task': 'Delete'}})
        self.assertEqual(self.request('DELETE', f"/launches/{self.fixture.run['id']}")[0], 200)
        self.fixture.db.expire_all()
        self.assertIsNone(self.fixture.db.get(LaunchDesign, self.fixture.run['id']))

    def test_copy_keeps_old_behavior_without_copying_design(self):
        self.put({'project': {'task': 'Do not copy yet'}})
        status, _, copied = self.request('POST', f"/launches/{self.fixture.run['id']}/copy", body={
            'title': 'Copy', 'year': 2027, 'semester': 'Весна',
        })
        self.assertEqual(status, 201)
        self.assertEqual(copied['copied_from_launch_id'], self.fixture.run['id'])
        self.assertEqual(self.request('GET', self.path(copied['id']))[2]['data'], {})
        self.assertEqual(self.request('GET', self.path())[2]['data'], {'project': {'task': 'Do not copy yet'}})

    def test_template_describes_fixed_structure_and_put_semantics(self):
        status, _, template = self.request('GET', '/launch-design/template')
        self.assertEqual(status, 200)
        self.assertEqual(template['template_version'], 1)
        schema = template['data_schema']
        self.assertEqual(set(schema['properties']), {'passport', 'educational_concept', 'project'})
        passport = schema['$defs']['DesignPassport']['properties']
        self.assertEqual(passport['module_type']['enum'], ['project', 'non_project', 'mixed'])
        self.assertEqual(passport['duration_weeks']['exclusiveMinimum'], 0)
        self.assertEqual(passport['planned_capacity']['minimum'], 0)
        for definition in [schema, *schema['$defs'].values()]:
            self.assertFalse(definition['additionalProperties'])
            for prop in definition['properties'].values():
                self.assertTrue(prop.get('description'))
        operation = self.app.openapi()['paths']['/launches/{launch_id}/design']['put']
        self.assertIn('полностью заменяет', operation['description'])

    def test_launch_extra_fields_roundtrip_and_clear(self):
        fields = {'starts_on': '2027-02-01', 'ends_on': '2027-05-01', 'participant_count': 0,
                  'changes_summary': 'New plan', 'changes_reason': 'Feedback'}
        path = f"/launches/{self.fixture.run['id']}"
        status, _, saved = self.request('PATCH', path, body=fields)
        self.assertEqual(status, 200)
        for key, value in fields.items():
            self.assertEqual(saved[key], value)
        self.assertEqual(self.request('GET', path)[2], saved)
        self.put({'passport': {'planned_capacity': 30}})
        self.assertEqual(self.request('GET', path)[2]['participant_count'], 0)
        status, _, cleared = self.request('PATCH', path, body={key: None for key in fields})
        self.assertEqual(status, 200)
        for key in fields:
            self.assertIsNone(cleared[key])

    def test_launch_card_validation_and_patch_merged_dates(self):
        path = f"/launches/{self.fixture.run['id']}"
        for fields in ({'participant_count': -1}, {'participant_count': True}, {'starts_on': 'bad'},
                       {'starts_on': '2027-05-01', 'ends_on': '2027-02-01'}):
            with self.subTest(fields=fields):
                self.assertEqual(self.request('PATCH', path, body=fields)[0], 422)
                self.assertEqual(self.request('POST', f"/modules/{self.fixture.module['id']}/launches", body={
                    'title': 'Bad', 'year': 2027, 'semester': 'Весна', **fields})[0], 422)
        self.assertEqual(self.request('PATCH', path, body={'starts_on': '2027-02-01', 'ends_on': '2027-05-01'})[0], 200)
        for fields in ({'starts_on': '2027-06-01'}, {'ends_on': '2027-01-01'}):
            response = self.request('PATCH', path, body=fields)
            self.assertEqual(response[0], 422)
            self.assertEqual(response[2]['error']['ErrorCode'], 'INVALID_LAUNCH_DATES')
        self.assertEqual(self.request('GET', path)[2]['starts_on'], '2027-02-01')
        self.assertEqual(self.request('PATCH', path, body={'ends_on': '2027-02-01'})[0], 200)
