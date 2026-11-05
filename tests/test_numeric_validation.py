from contextlib import ExitStack
from unittest.mock import patch

import test_http_errors_cors as http_runtime
from repositories.launch_designs import LaunchDesignRepository
from repositories.launches import LaunchRepository


class NumericValidationTests(http_runtime.HTTPTestCase):
    maximum = 2147483647

    def launch_body(self, **fields):
        return {'title': 'Boundary test', 'year': 2028, 'semester': 'Spring', **fields}

    def design_path(self):
        return f"/launches/{self.fixture.run['id']}/design"

    def invalid_numbers(self, minimum):
        values = [self.maximum + 1, -1, '1', True, False, 1.5, 1.0, 10 ** 1000]
        if minimum > 0:
            values.append(0)
        return values

    def assert_rejected_before_saving(self, method, path, body, location):
        with ExitStack() as stack:
            saves = [stack.enter_context(patch.object(repository, name)) for repository, name in (
                (LaunchRepository, 'create_launch'),
                (LaunchRepository, 'edit_launch'),
                (LaunchRepository, 'save_launch_copy'),
                (LaunchDesignRepository, 'replace_design'),
            )]
            response = self.request(method, path, body=body)
            for save in saves:
                save.assert_not_called()
        self.assertEqual(response[0], 422, response[2])
        self.assertIsInstance(response[2]['detail'], list)
        self.assertTrue(any(error['loc'] == location for error in response[2]['detail']), response[2])

    def test_participant_count_minimum_and_maximum_on_create_patch_and_copy(self):
        for value in (0, self.maximum):
            with self.subTest(value=value):
                status, _, created = self.request('POST', f"/modules/{self.fixture.module['id']}/launches",
                                                   body=self.launch_body(participant_count=value))
                self.assertEqual(status, 201, created)
                self.assertEqual(created['participant_count'], value)
                self.assertEqual(self.request('GET', f"/launches/{created['id']}")[2]['participant_count'], value)
                status, _, updated = self.request('PATCH', f"/launches/{self.fixture.run['id']}", body={'participant_count': value})
                self.assertEqual(status, 200, updated)
                self.assertEqual(updated['participant_count'], value)
                status, _, copied = self.request('POST', f"/launches/{self.fixture.run['id']}/copy",
                                                 body=self.launch_body(participant_count=value))
                self.assertEqual(status, 201, copied)
                self.assertEqual(copied['participant_count'], value)

    def test_invalid_participant_count_is_422_without_calling_repository_writes(self):
        for value in self.invalid_numbers(0):
            for method, path, body in (
                ('POST', f"/modules/{self.fixture.module['id']}/launches", self.launch_body(participant_count=value)),
                ('POST', f"/launches/{self.fixture.run['id']}/copy", self.launch_body(participant_count=value)),
                ('PATCH', f"/launches/{self.fixture.run['id']}", {'participant_count': value}),
            ):
                with self.subTest(value=value, method=method, path=path):
                    self.assert_rejected_before_saving(method, path, body, ['body', 'participant_count'])

    def test_design_integer_minimums_and_maximums_are_saved_and_read(self):
        for upper_boundary in (False, True):
            data = {'passport': {
                'duration_weeks': self.maximum if upper_boundary else 1,
                'duration_academic_hours': self.maximum if upper_boundary else 1,
                'planned_capacity': self.maximum if upper_boundary else 0,
            }, 'project': {'stages': [{'position': self.maximum if upper_boundary else 0}]}}
            with self.subTest(upper_boundary=upper_boundary):
                status, _, saved = self.request('PUT', self.design_path(), body={'data': data})
                self.assertEqual(status, 200, saved)
                self.assertEqual(saved['data'], data)
                self.assertEqual(self.request('GET', self.design_path())[2]['data'], data)

    def test_invalid_passport_integers_are_422_before_repository_write(self):
        for field, minimum in (('duration_weeks', 1), ('duration_academic_hours', 1), ('planned_capacity', 0)):
            for value in self.invalid_numbers(minimum):
                with self.subTest(field=field, value=value):
                    self.assert_rejected_before_saving('PUT', self.design_path(),
                                                      {'data': {'passport': {field: value}}},
                                                      ['body', 'data', 'passport', field])

    def test_invalid_stage_position_is_422_before_repository_write(self):
        for value in self.invalid_numbers(0):
            with self.subTest(value=value):
                self.assert_rejected_before_saving('PUT', self.design_path(),
                                                  {'data': {'project': {'stages': [{'position': value}]}}},
                                                  ['body', 'data', 'project', 'stages', 0, 'position'])

    def test_omissions_null_and_full_replacement_keep_existing_semantics(self):
        path = f"/launches/{self.fixture.run['id']}"
        self.assertEqual(self.request('PATCH', path, body={'participant_count': self.maximum})[0], 200)
        self.assertEqual(self.request('PATCH', path, body={})[2]['participant_count'], self.maximum)
        self.assertIsNone(self.request('PATCH', path, body={'participant_count': None})[2]['participant_count'])
        self.assertIsNone(self.request('POST', f"/modules/{self.fixture.module['id']}/launches", body=self.launch_body())[2]['participant_count'])
        self.assertEqual(self.request('PUT', self.design_path(), body={'data': {'passport': {'duration_weeks': 1}}})[2]['data'],
                         {'passport': {'duration_weeks': 1}})
        self.assertEqual(self.request('PUT', self.design_path(), body={'data': {'project': {'stages': [{}]}}})[2]['data'],
                         {'project': {'stages': [{}]}})
        self.assertEqual(self.request('PUT', self.design_path(), body={'data': {}})[2]['data'], {})
        for field in ('duration_weeks', 'duration_academic_hours', 'planned_capacity'):
            with self.subTest(field=field):
                self.assert_rejected_before_saving('PUT', self.design_path(),
                                                  {'data': {'passport': {field: None}}},
                                                  ['body', 'data', 'passport', field])
        self.assert_rejected_before_saving('PUT', self.design_path(),
                                          {'data': {'project': {'stages': [{'position': None}]}}},
                                          ['body', 'data', 'project', 'stages', 0, 'position'])

    def test_template_and_openapi_publish_the_technical_maximum(self):
        status, _, template = self.request('GET', '/launch-design/template')
        self.assertEqual(status, 200)
        passport = template['data_schema']['$defs']['DesignPassport']['properties']
        for field in ('duration_weeks', 'duration_academic_hours', 'planned_capacity'):
            self.assertEqual(passport[field]['maximum'], self.maximum)
        self.assertEqual(template['data_schema']['$defs']['ProjectStage']['properties']['position']['maximum'], self.maximum)
        for name in ('CreateLaunchRequest', 'UpdateLaunchRequest'):
            field = self.app.openapi()['components']['schemas'][name]['properties']['participant_count']
            integer = next(option for option in field['anyOf'] if option.get('type') == 'integer')
            self.assertEqual(integer['minimum'], 0)
            self.assertEqual(integer['maximum'], self.maximum)
