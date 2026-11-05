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

    def test_copy_transfers_design(self):
        self.put({'project': {'task': 'Source project'}})
        status, _, copied = self.request('POST', f"/launches/{self.fixture.run['id']}/copy", body={
            'title': 'Copy', 'year': 2027, 'semester': 'Весна',
        })
        self.assertEqual(status, 201)
        self.assertEqual(copied['copied_from_launch_id'], self.fixture.run['id'])
        self.assertEqual(self.request('GET', self.path(copied['id']))[2]['data'], {'project': {'task': 'Source project'}})
        self.assertEqual(self.request('GET', self.path())[2]['data'], {'project': {'task': 'Source project'}})

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

    def copy_launch(self, **fields):
        return self.request('POST', f"/launches/{self.fixture.run['id']}/copy", body={
            'title': 'Copied launch', 'year': 2028, 'semester': 'Весна', **fields,
        })

    def test_copy_transfers_teaching_materials_and_all_sections_without_s3_calls(self):
        from models.enums import MaterialKind
        teaching = self.fixture.section(position=4)
        empty = self.fixture.sections.create_section(self.fixture.run['id'], {'title': 'Empty', 'position': 7})
        feedback_section = self.fixture.sections.create_section(self.fixture.run['id'], {'title': 'Feedback only', 'position': 9})
        originals = {}
        for position, kind in enumerate(MaterialKind):
            section_id = None if kind == MaterialKind.plan else feedback_section['id'] if kind == MaterialKind.feedback else teaching['id']
            material = self.fixture.material_service.create_material(
                self.fixture.run['id'], 1, kind.value, f'Description {kind.value}', runtime.upload(),
                section_id, kind, position,
            )
            self.assertTrue(material['success'], material)
            originals[kind.value] = material
        self.assertEqual(self.request('POST', f"/launches/{self.fixture.run['id']}/notes", body={
            'title': 'Source note', 'content': 'Not for copying',
            'material_id': originals['presentation']['id'], 'section_id': teaching['id'],
        })[0], 201)
        self.put({'educational_concept': {'learning_outcomes': ['Second', 'First']}})
        before_files = self.fixture.db.scalar(select(func.count()).select_from(runtime.StoredFile))
        with patch.object(self.fixture.storage, 'upload_file', side_effect=AssertionError('Copy uploads')) as uploading, \
             patch.object(self.fixture.storage, 'delete_file', side_effect=AssertionError('Copy deletes')):
            status, _, copied = self.copy_launch()
        self.assertEqual(status, 201)
        uploading.assert_not_called()
        self.assertNotEqual(copied['id'], self.fixture.run['id'])
        self.assertEqual(copied['copied_from_launch_id'], self.fixture.run['id'])
        copied_sections = self.request('GET', f"/launches/{copied['id']}/sections")[2]
        section_map = {section['title']: section for section in copied_sections.values()}
        self.assertEqual(len(section_map), 3)
        for original in (teaching, empty, feedback_section):
            section = section_map[original['title']]
            self.assertNotEqual(section['id'], original['id'])
            self.assertEqual(section['launch_id'], copied['id'])
            self.assertEqual(section['position'], original['position'])
            self.assertEqual(section['description'], original['description'])
        copied_materials = self.request('GET', f"/launches/{copied['id']}/materials")[2]
        self.assertEqual({item['kind'] for item in copied_materials.values()}, set(originals) - {'feedback'})
        for item in copied_materials.values():
            original = originals[item['kind']]
            self.assertNotEqual(item['id'], original['id'])
            self.assertEqual(item['copied_from_material_id'], original['id'])
            self.assertEqual(item['stored_file_id'], original['stored_file_id'])
            self.assertEqual(item['launch_id'], copied['id'])
            self.assertEqual(item['title'], original['title'])
            self.assertEqual(item['description'], original['description'])
            self.assertEqual(item['position'], original['position'])
            expected_section = None if item['kind'] == 'plan' else section_map[teaching['title']]['id']
            self.assertEqual(item['section_id'], expected_section)
        self.assertEqual(self.request('GET', f"/launches/{copied['id']}/notes")[2], {})
        self.assertEqual(len(self.request('GET', f"/launches/{self.fixture.run['id']}/notes")[2]), 1)
        self.assertEqual(self.fixture.db.scalar(select(func.count()).select_from(runtime.StoredFile)), before_files)
        self.assertIsNotNone(self.fixture.materials.get_material_by_id(originals['feedback']['id'], 1))

    def test_feedback_pending_deletion_does_not_block_launch_copy(self):
        from models.enums import MaterialKind
        feedback = self.fixture.material_service.create_material(
            self.fixture.run['id'], 1, 'Feedback', None, runtime.upload(), kind=MaterialKind.feedback,
        )
        stored_file = self.fixture.db.get(runtime.StoredFile, feedback['stored_file_id'])
        stored_file.deletion_pending = True
        self.fixture.db.commit()
        status, _, copied = self.copy_launch()
        self.assertEqual(status, 201)
        self.assertEqual(self.request('GET', f"/launches/{copied['id']}/materials")[2], {})

    def test_copy_design_is_independently_editable_in_both_directions(self):
        data = {'passport': {'category': 'Original'},
                'project': {'stages': [{'position': 2, 'student_activity': 'Work'}]}}
        self.put(data)
        status, _, copied = self.copy_launch()
        self.assertEqual(status, 201)
        source_record = self.fixture.db.get(LaunchDesign, self.fixture.run['id'])
        copy_record = self.fixture.db.get(LaunchDesign, copied['id'])
        self.assertIsNot(source_record, copy_record)
        self.assertIsNot(source_record.data, copy_record.data)
        self.assertIsNot(source_record.data['project']['stages'], copy_record.data['project']['stages'])
        self.assertEqual(copy_record.template_version, source_record.template_version)
        self.assertEqual(copy_record.data, data)
        self.assertEqual(self.request('PUT', self.path(copied['id']), body={
            'data': {'project': {'stages': [{'position': 0, 'student_activity': 'Changed'}]}},
        })[0], 200)
        self.assertEqual(self.request('GET', self.path())[2]['data'], data)
        self.put({'passport': {'category': 'Source changed'}})
        self.assertEqual(self.request('GET', self.path(copied['id']))[2]['data'],
                         {'project': {'stages': [{'position': 0, 'student_activity': 'Changed'}]}})

    def test_copy_preserves_stored_template_version(self):
        # The DB can contain a different positive version; copying must not reset it.
        source_record = self.fixture.db.get(LaunchDesign, self.fixture.run['id'])
        source_record.template_version = 3
        self.fixture.db.commit()
        status, _, copied = self.copy_launch()
        self.assertEqual(status, 201)
        self.assertEqual(self.fixture.db.get(LaunchDesign, copied['id']).template_version, 3)

    def test_copy_missing_design_creates_empty_record_without_mutating_source(self):
        self.fixture.db.delete(self.fixture.db.get(LaunchDesign, self.fixture.run['id']))
        self.fixture.db.commit()
        status, _, copied = self.copy_launch()
        self.assertEqual(status, 201)
        record = self.fixture.db.get(LaunchDesign, copied['id'])
        self.assertIsNotNone(record)
        self.assertEqual(record.data, {})
        self.assertEqual(record.template_version, 1)
        self.assertIsNone(self.fixture.db.get(LaunchDesign, self.fixture.run['id']))

    def test_copy_uses_request_parameters_without_inheriting_source_card_fields(self):
        source_fields = {'starts_on': '2027-01-01', 'ends_on': '2027-02-01', 'participant_count': 25,
                         'changes_summary': 'Old summary', 'changes_reason': 'Old reason'}
        self.assertEqual(self.request('PATCH', f"/launches/{self.fixture.run['id']}", body={
            **source_fields, 'status': 'completed', 'description': 'Source description',
        })[0], 200)
        status, _, empty = self.copy_launch()
        self.assertEqual(status, 201)
        self.assertEqual(empty['status'], 'draft')
        self.assertEqual(empty['description'], '')
        for name in source_fields:
            self.assertIsNone(empty[name])
        requested = {'title': 'Requested', 'year': 2029, 'semester': 'Осень', 'description': 'New description',
                     'status': 'active', 'starts_on': '2029-03-01', 'ends_on': '2029-05-01',
                     'participant_count': 0, 'changes_summary': 'New summary', 'changes_reason': 'New reason'}
        status, _, copied = self.copy_launch(**requested)
        self.assertEqual(status, 201)
        for name, value in requested.items():
            self.assertEqual(copied[name], value)
        for name, value in source_fields.items():
            self.assertEqual(self.request('GET', f"/launches/{self.fixture.run['id']}")[2][name], value)

    def test_copy_file_replacement_keeps_source_file_and_material_unchanged(self):
        original = self.fixture.material()
        status, _, copied = self.copy_launch()
        self.assertEqual(status, 201)
        copied_material = next(iter(self.request('GET', f"/launches/{copied['id']}/materials")[2].values()))
        source_file = self.fixture.files.get_file_by_id(original['stored_file_id'], 1)
        source_key = source_file['storage_key']
        original_object = self.fixture.storage.objects[source_key]
        boundary = 'copy-file-test-boundary'
        body = (f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="new.txt"\r\n'
                f'Content-Type: text/plain\r\n\r\nNew copy content\r\n--{boundary}--\r\n').encode()
        status, _, replaced = self.request('PUT', f"/materials/{copied_material['id']}/file", raw=body,
                                           headers={'Content-Type': f'multipart/form-data; boundary={boundary}'})
        self.assertEqual(status, 200)
        self.assertNotEqual(replaced['stored_file_id'], original['stored_file_id'])
        self.assertEqual(self.request('GET', f"/materials/{original['id']}")[2]['stored_file_id'], original['stored_file_id'])
        self.assertEqual(self.fixture.storage.objects[source_key], original_object)
        self.assertEqual(self.request('GET', f"/materials/{original['id']}/download")[0], 200)

    def test_copy_foreign_or_missing_source_creates_nothing(self):
        before = {table: self.fixture.db.scalar(select(func.count()).select_from(table))
                  for table in (Launch, LaunchDesign, runtime.RunSection, runtime.Material)}
        for launch_id in (self.fixture.other_run['id'], 999999):
            with self.subTest(launch_id=launch_id):
                self.assert_error(self.request('POST', f'/launches/{launch_id}/copy', body={
                    'title': 'Forbidden', 'year': 2028, 'semester': 'Spring',
                }), 404, 'LAUNCH_NOT_FOUND', 'Запуск не найден')
        for table, count in before.items():
            self.assertEqual(self.fixture.db.scalar(select(func.count()).select_from(table)), count)

    def test_copy_late_failure_rolls_back_launch_design_sections_and_materials(self):
        self.put({'project': {'task': 'Keep source'}})
        self.fixture.material(self.fixture.section()['id'])
        tables = (Launch, LaunchDesign, runtime.RunSection, runtime.Material, runtime.StoredFile)
        before = {table: self.fixture.db.scalar(select(func.count()).select_from(table)) for table in tables}
        original_flush = self.fixture.db.flush

        def fail_after_material_insert(*args, **kwargs):
            copying_material = any(isinstance(obj, runtime.Material) for obj in self.fixture.db.new)
            result = original_flush(*args, **kwargs)
            if copying_material:
                raise SQLAlchemyError('fake failure after inserting copied material')
            return result

        with patch.object(self.fixture.db, 'flush', side_effect=fail_after_material_insert), \
             patch.object(self.fixture.storage, 'upload_file', side_effect=AssertionError('Copy uploads')):
            with self.assertRaises(SQLAlchemyError):
                self.copy_launch()
        for table, count in before.items():
            self.assertEqual(self.fixture.db.scalar(select(func.count()).select_from(table)), count)
        self.assertEqual(self.request('GET', self.path())[2]['data'], {'project': {'task': 'Keep source'}})
        self.assertEqual(self.copy_launch()[0], 201)

    def test_copy_commit_failure_leaves_no_partial_records(self):
        self.fixture.material(self.fixture.section()['id'])
        tables = (Launch, LaunchDesign, runtime.RunSection, runtime.Material)
        before = {table: self.fixture.db.scalar(select(func.count()).select_from(table)) for table in tables}
        with patch.object(self.fixture.db, 'commit', side_effect=SQLAlchemyError('fake commit failure')):
            with self.assertRaises(SQLAlchemyError):
                self.copy_launch()
        for table, count in before.items():
            self.assertEqual(self.fixture.db.scalar(select(func.count()).select_from(table)), count)
