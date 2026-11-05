from unittest.mock import patch

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

import test_erd as runtime
import test_http_errors_cors as http_runtime
from models.launch_reflections import LaunchReflection
from repositories.launch_reflections import LaunchReflectionRepository


class NotesReflectionTests(http_runtime.HTTPTestCase):
    text_fields = ('problem_or_practice', 'cause', 'proposed_solution')
    reflection_fields = ('what_went_well', 'recurring_problems', 'materials_to_update', 'decisions_to_keep')

    def note(self, **fields):
        status, _, result = self.request('POST', f"/launches/{self.fixture.run['id']}/notes", body={
            'title': 'Note', 'content': 'What happened', **fields,
        })
        self.assertEqual(status, 201, result)
        return result

    def reflection_path(self, launch_id=None):
        return f"/launches/{launch_id or self.fixture.run['id']}/reflection"

    def test_old_note_requests_keep_title_content_and_get_defaults(self):
        note = self.note()
        self.assertEqual(note['title'], 'Note')
        self.assertEqual(note['content'], 'What happened')
        self.assertEqual(note['priority'], 'medium')
        self.assertEqual(note['status'], 'open')
        for name in self.text_fields:
            self.assertIsNone(note[name])
        self.assertEqual(self.request('GET', f"/notes/{note['id']}")[2], note)
        self.assertEqual(self.request('GET', f"/launches/{self.fixture.run['id']}/notes")[2], {str(note['id']): note})
        status, _, saved = self.request('PATCH', f"/notes/{note['id']}", body={'content': 'Updated old request'})
        self.assertEqual(status, 200)
        self.assertEqual(saved['content'], 'Updated old request')
        self.assertEqual(saved['priority'], 'medium')
        self.assertEqual(saved['status'], 'open')

    def test_new_note_fields_roundtrip_patch_omission_and_null_clearing(self):
        fields = {'problem_or_practice': 'Useful practice', 'cause': 'Cause', 'proposed_solution': 'Solution',
                  'priority': 'high', 'status': 'in_progress'}
        note = self.note(**fields)
        for name, value in fields.items():
            self.assertEqual(note[name], value)
        path = f"/notes/{note['id']}"
        status, _, changed = self.request('PATCH', path, body={'cause': 'New cause'})
        self.assertEqual(status, 200)
        for name, value in {**fields, 'cause': 'New cause'}.items():
            self.assertEqual(changed[name], value)
        for name in self.text_fields:
            status, _, changed = self.request('PATCH', path, body={name: None})
            self.assertEqual(status, 200)
            self.assertIsNone(changed[name])
            self.assertEqual(changed['priority'], 'high')
            self.assertEqual(changed['status'], 'in_progress')
        self.assertEqual(self.request('PATCH', path, body={})[2], changed)
        self.assertEqual(self.request('GET', path)[2], changed)

    def test_all_priority_and_status_values_work_for_create_and_patch(self):
        for priority in ('low', 'medium', 'high'):
            for status in ('open', 'in_progress', 'done'):
                with self.subTest(priority=priority, status=status):
                    note = self.note(priority=priority, status=status)
                    self.assertEqual((note['priority'], note['status']), (priority, status))
                    response = self.request('PATCH', f"/notes/{note['id']}", body={'priority': 'low', 'status': 'done'})
                    self.assertEqual(response[0], 200)
                    self.assertEqual((response[2]['priority'], response[2]['status']), ('low', 'done'))

    def test_invalid_note_fields_and_null_required_values_are_rejected(self):
        note = self.note(cause='Keep')
        bad_fields = [{'priority': 'urgent'}, {'status': 'closed'}, {'priority': None}, {'status': None},
                      {'title': None}, {'content': None}, {'cause': 1}, {'proposed_solution': []},
                      {'problem_or_practice': True}, {'unknown': 'x'}]
        for fields in bad_fields:
            with self.subTest(fields=fields):
                self.assertEqual(self.request('POST', f"/launches/{self.fixture.run['id']}/notes", body={
                    'title': 'Bad', 'content': 'Bad', **fields,
                })[0], 422)
                self.assertEqual(self.request('PATCH', f"/notes/{note['id']}", body=fields)[0], 422)
        self.assertEqual(self.request('GET', f"/notes/{note['id']}")[2], note)

    def test_note_new_fields_preserve_link_validation_and_atomicity(self):
        first, second = self.fixture.section(), self.fixture.section()
        material = self.fixture.material(first['id'])
        other_section = self.fixture.section(self.fixture.target['id'])
        other_material = self.fixture.material_service.create_material(
            self.fixture.target['id'], 1, 'Other material', None, runtime.upload(),
        )
        invalid = [
            ({'section_id': other_section['id']}, 404, 'SECTION_NOT_FOUND_IN_LAUNCH'),
            ({'material_id': other_material['id']}, 404, 'MATERIAL_NOT_FOUND_IN_LAUNCH'),
            ({'section_id': second['id'], 'material_id': material['id']}, 400, 'MATERIAL_SECTION_MISMATCH'),
        ]
        note = self.note(section_id=first['id'], material_id=material['id'], cause='Keep cause')
        for links, status, code in invalid:
            with self.subTest(links=links):
                response = self.request('POST', f"/launches/{self.fixture.run['id']}/notes", body={
                    'title': 'Bad', 'content': 'Bad', 'proposed_solution': 'Bad', **links,
                })
                self.assertEqual(response[0], status)
                self.assertEqual(response[2]['error']['ErrorCode'], code)
                response = self.request('PATCH', f"/notes/{note['id']}", body={**links, 'cause': 'Do not save'})
                self.assertEqual(response[0], status)
                self.assertEqual(response[2]['error']['ErrorCode'], code)
        self.assertEqual(self.request('GET', f"/notes/{note['id']}")[2], note)
        status, _, changed = self.request('PATCH', f"/notes/{note['id']}", body={'cause': 'Changed'})
        self.assertEqual(status, 200)
        self.assertEqual(changed['material_id'], material['id'])
        self.assertEqual(changed['section_id'], first['id'])

    def test_notes_of_other_owner_remain_private(self):
        from schemas.notes import CreateNoteRequest
        foreign = self.fixture.note_service.create_note(self.fixture.other_run['id'], 2,
                                                       CreateNoteRequest(title='Private', content='Private', cause='Private cause'))
        for method in ('GET', 'PATCH', 'DELETE'):
            response = self.request(method, f"/notes/{foreign['id']}", body={'cause': 'Changed'} if method == 'PATCH' else None)
            self.assert_error(response, 404, 'NOTE_NOT_FOUND', 'Заметка не найдена')
        self.assertEqual(self.fixture.notes.get_note_by_id(foreign['id'], 2)['cause'], 'Private cause')
        self.assertEqual(self.request('GET', f"/launches/{self.fixture.other_run['id']}/notes")[0], 404)
        self.assertEqual(self.request('POST', f"/launches/{self.fixture.other_run['id']}/notes", body={
            'title': 'Forbidden', 'content': 'Forbidden', 'priority': 'high',
        })[0], 404)

    def test_reflection_get_is_read_only_and_returns_explicit_empty_response(self):
        with patch.object(self.fixture.db, 'add', side_effect=AssertionError('GET writes')), \
             patch.object(self.fixture.db, 'commit', side_effect=AssertionError('GET commits')):
            status, _, reflection = self.request('GET', self.reflection_path())
        self.assertEqual(status, 200)
        self.assertEqual(reflection, {'launch_id': self.fixture.run['id'], 'created_at': None, 'updated_at': None,
                                      **{name: None for name in self.reflection_fields}})
        self.assertIsNone(self.fixture.db.get(LaunchReflection, self.fixture.run['id']))

    def test_reflection_partial_create_and_full_replace_keep_single_record(self):
        fields = {name: f'Text for {name}' for name in self.reflection_fields}
        status, _, saved = self.request('PUT', self.reflection_path(), body=fields)
        self.assertEqual(status, 200)
        for name, value in fields.items():
            self.assertEqual(saved[name], value)
        self.assertIsNotNone(saved['created_at'])
        self.assertIsNotNone(saved['updated_at'])
        self.assertEqual(self.request('GET', self.reflection_path())[2], saved)
        status, _, changed = self.request('PUT', self.reflection_path(), body={'what_went_well': 'New'})
        self.assertEqual(status, 200)
        self.assertEqual(changed['what_went_well'], 'New')
        self.assertEqual(changed['created_at'], saved['created_at'])
        for name in self.reflection_fields[1:]:
            self.assertIsNone(changed[name])
        self.assertEqual(self.fixture.db.scalar(select(func.count()).select_from(LaunchReflection)), 1)
        for body in ({'what_went_well': None}, {}):
            status, _, cleared = self.request('PUT', self.reflection_path(), body=body)
            self.assertEqual(status, 200)
            for name in self.reflection_fields:
                self.assertIsNone(cleared[name])
            self.assertEqual(self.fixture.db.scalar(select(func.count()).select_from(LaunchReflection)), 1)

    def test_reflection_rejects_unknown_fields_and_non_text_values(self):
        for body in ({'unknown': 'x'}, {'what_went_well': 1}, {'decisions_to_keep': []},
                     {'recurring_problems': True}, {'materials_to_update': {}}):
            with self.subTest(body=body):
                self.assertEqual(self.request('PUT', self.reflection_path(), body=body)[0], 422)
        self.assertIsNone(self.fixture.db.get(LaunchReflection, self.fixture.run['id']))

    def test_reflection_ownership_missing_launch_and_authentication(self):
        repository = LaunchReflectionRepository(self.fixture.db)
        repository.replace_reflection(self.fixture.other_run['id'], 2, {
            name: 'Private' for name in self.reflection_fields
        })
        for launch_id in (999999, self.fixture.other_run['id']):
            for method in ('GET', 'PUT'):
                with self.subTest(launch_id=launch_id, method=method):
                    self.assert_error(self.request(method, self.reflection_path(launch_id), body={} if method == 'PUT' else None),
                                      404, 'LAUNCH_NOT_FOUND', 'Запуск не найден')
        self.assertEqual(repository.get_reflection(self.fixture.other_run['id'], 2)['what_went_well'], 'Private')
        del self.app.dependency_overrides[runtime.get_current_user]
        for method in ('GET', 'PUT'):
            self.assertEqual(self.request(method, self.reflection_path(), body={} if method == 'PUT' else None)[0], 401)

    def test_completed_launch_still_allows_notes_and_reflection_edits(self):
        self.assertEqual(self.request('PATCH', f"/launches/{self.fixture.run['id']}", body={'status': 'completed'})[0], 200)
        note = self.note(priority='high', status='done')
        self.assertEqual(self.request('PATCH', f"/notes/{note['id']}", body={'cause': 'New'})[0], 200)
        self.assertEqual(self.request('PUT', self.reflection_path(), body={'what_went_well': 'Good'})[0], 200)
        self.assertEqual(self.request('PUT', self.reflection_path(), body={'what_went_well': 'Better'})[0], 200)

    def test_copy_excludes_notes_and_reflection_and_preserves_source(self):
        note = self.note(problem_or_practice='Practice', cause='Cause', proposed_solution='Solution', priority='high', status='done')
        source = self.request('PUT', self.reflection_path(), body={'what_went_well': 'Good', 'decisions_to_keep': 'Keep'})[2]
        status, _, copied = self.request('POST', f"/launches/{self.fixture.run['id']}/copy", body={
            'title': 'Copy', 'year': 2028, 'semester': 'Spring',
        })
        self.assertEqual(status, 201)
        self.assertEqual(self.request('GET', f"/launches/{copied['id']}/notes")[2], {})
        reflection = self.request('GET', self.reflection_path(copied['id']))[2]
        for name in self.reflection_fields:
            self.assertIsNone(reflection[name])
        self.assertIsNone(self.fixture.db.get(LaunchReflection, copied['id']))
        self.assertEqual(self.request('GET', self.reflection_path())[2], source)
        self.assertEqual(self.request('GET', f"/notes/{note['id']}")[2], note)

    def test_deleting_launch_cascades_notes_and_reflection(self):
        note = self.note(cause='Cause')
        self.request('PUT', self.reflection_path(), body={'what_went_well': 'Good'})
        self.assertEqual(self.request('DELETE', f"/launches/{self.fixture.run['id']}")[0], 200)
        self.fixture.db.expire_all()
        self.assertIsNone(self.fixture.db.get(LaunchReflection, self.fixture.run['id']))
        self.assertIsNone(self.fixture.db.get(runtime.Note, note['id']))

    def test_reflection_failed_commit_rolls_back_create_and_replace(self):
        with patch.object(self.fixture.db, 'commit', side_effect=SQLAlchemyError('fake commit failure')):
            with self.assertRaises(SQLAlchemyError):
                self.request('PUT', self.reflection_path(), body={'what_went_well': 'Failed'})
        self.assertIsNone(self.fixture.db.get(LaunchReflection, self.fixture.run['id']))
        original = self.request('PUT', self.reflection_path(), body={'what_went_well': 'Keep'})[2]
        with patch.object(self.fixture.db, 'commit', side_effect=IntegrityError('fake', {}, Exception('internal'))):
            response = self.request('PUT', self.reflection_path(), body={'what_went_well': 'Failed'})
        self.assert_error(response, 409, 'RELATED_DATA_CHANGED', 'Связанные данные изменились, повторите запрос')
        self.assertEqual(self.request('GET', self.reflection_path())[2], original)
