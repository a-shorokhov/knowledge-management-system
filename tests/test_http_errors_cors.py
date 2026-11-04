import asyncio
import importlib.util
import json
import unittest
from unittest.mock import patch

import test_erd as runtime
from core.security import hash_password


class HTTPTestCase(unittest.TestCase):
    def setUp(self):
        self.fixture = runtime.ERDTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        self.app = runtime.app

    def request(self, method, path, body=None, headers=None, raw=None):
        # Call the real ASGI app, without ServiceErrorAdapter or service overrides.
        async def invoke():
            data = raw if raw is not None else json.dumps(body).encode() if body is not None else b''
            request_headers = [(b'content-type', b'application/json')] if raw is None else []
            request_headers += [(key.lower().encode(), value.encode()) for key, value in (headers or {}).items()]
            messages = []
            sent = False

            async def receive():
                nonlocal sent
                if sent:
                    return {'type': 'http.disconnect'}
                sent = True
                return {'type': 'http.request', 'body': data, 'more_body': False}

            async def send(message):
                messages.append(message)

            await self.app({
                'type': 'http', 'asgi': {'version': '3.0'}, 'http_version': '1.1',
                'method': method, 'scheme': 'http', 'path': path, 'raw_path': path.encode(),
                'query_string': b'', 'root_path': '', 'headers': request_headers,
                'server': ('test', 80), 'client': ('test', 1),
            }, receive, send)
            start = next(message for message in messages if message['type'] == 'http.response.start')
            response_headers = {key.decode(): value.decode() for key, value in start['headers']}
            data = b''.join(message.get('body', b'') for message in messages if message['type'] == 'http.response.body')
            try:
                response = json.loads(data) if data else None
            except ValueError:
                response = data.decode()
            return start['status'], response_headers, response

        return asyncio.run(invoke())

    def assert_error(self, response, status, code, message):
        actual_status, headers, body = response
        self.assertEqual(actual_status, status)
        self.assertEqual(headers['content-type'], 'application/json')
        self.assertEqual(body, {'error': {
            'ErrorCode': code,
            'ErrorMessage': message,
            'ErrorField': None,
            'ErrorContext': None,
        }})


class APIErrorTests(HTTPTestCase):
    def test_missing_objects_return_typed_http_errors(self):
        cases = [
            ('/users/999999', 'USER_NOT_FOUND', 'Пользователь не найден'),
            ('/modules/999999', 'MODULE_NOT_FOUND', 'Модуль не найден'),
            ('/launches/999999', 'LAUNCH_NOT_FOUND', 'Запуск не найден'),
            ('/sections/999999', 'SECTION_NOT_FOUND', 'Раздел не найден'),
            ('/materials/999999', 'MATERIAL_NOT_FOUND', 'Материал не найден'),
            ('/notes/999999', 'NOTE_NOT_FOUND', 'Заметка не найдена'),
            ('/stored-files/999999', 'FILE_NOT_FOUND', 'Файл не найден'),
        ]
        for path, code, message in cases:
            with self.subTest(path=path):
                self.assert_error(self.request('GET', path), 404, code, message)

    def test_other_users_objects_are_hidden_as_not_found(self):
        cases = [
            (f"/modules/{self.fixture.other_module['id']}", 'MODULE_NOT_FOUND', 'Модуль не найден'),
            (f"/launches/{self.fixture.other_run['id']}", 'LAUNCH_NOT_FOUND', 'Запуск не найден'),
        ]
        for path, code, message in cases:
            with self.subTest(path=path):
                self.assert_error(self.request('GET', path), 404, code, message)

    def test_other_account_update_is_forbidden(self):
        self.assert_error(
            self.request('PATCH', '/users/2', body={'email': 'new@example.com'}),
            403, 'ACCOUNT_ACCESS_DENIED', 'Нет доступа к чужому аккаунту',
        )

    def test_missing_token_keeps_standard_401_and_bearer_header(self):
        del self.app.dependency_overrides[runtime.get_current_user]
        status, headers, body = self.request('GET', '/auth/me')
        self.assertEqual(status, 401)
        self.assertEqual(headers['www-authenticate'], 'Bearer')
        self.assertEqual(body, {'detail': 'Not authenticated'})

    def test_invalid_token_returns_typed_401_and_bearer_header(self):
        del self.app.dependency_overrides[runtime.get_current_user]
        response = self.request('GET', '/auth/me', headers={'Authorization': 'Bearer invalid-token'})
        self.assert_error(response, 401, 'INVALID_TOKEN', 'Недействительный токен')
        self.assertEqual(response[1]['www-authenticate'], 'Bearer')

    def test_incorrect_login_returns_typed_401_and_bearer_header(self):
        user = self.fixture.db.get(runtime.User, 1)
        user.hashed_password = hash_password('Correct-password-123')
        self.fixture.db.commit()
        for username in ('missing-user', 'user1'):
            with self.subTest(username=username):
                response = self.request(
                    'POST', '/auth/login',
                    raw=f'username={username}&password=Wrong-password-123'.encode(),
                    headers={'Content-Type': 'application/x-www-form-urlencoded'},
                )
                self.assert_error(response, 401, 'INCORRECT_CREDENTIALS', 'Неверный логин или пароль')
                self.assertEqual(response[1]['www-authenticate'], 'Bearer')

    def test_validation_still_returns_standard_422(self):
        status, _, body = self.request('POST', '/modules', body={})
        self.assertEqual(status, 422)
        self.assertIn('detail', body)
        self.assertIsInstance(body['detail'], list)
        self.assertNotIn('error', body)

    def test_unknown_route_and_method_keep_standard_errors(self):
        self.assertEqual(self.request('GET', '/no-such-route')[::2], (404, {'detail': 'Not Found'}))
        status, headers, body = self.request('PUT', '/auth/login')
        self.assertEqual(status, 405)
        self.assertEqual(body, {'detail': 'Method Not Allowed'})
        self.assertIn('POST', headers['allow'])


class CORSTests(HTTPTestCase):
    origin = 'http://localhost:3000'
    foreign_origin = 'http://untrusted.invalid'

    def configure_origins(self, origins):
        # Execute the real application construction with test settings; do not
        # mutate the shared app's middleware or add CORS only inside the test.
        spec = importlib.util.spec_from_file_location('kms_cors_test_app', runtime.APP / 'main.py')
        module = importlib.util.module_from_spec(spec)
        with patch.object(runtime.config.settings, 'CORS_ORIGINS', origins):
            spec.loader.exec_module(module)
        self.app = module.app
        self.app.dependency_overrides.update(runtime.app.dependency_overrides)
        self.addCleanup(self.app.dependency_overrides.clear)

    def setUp(self):
        super().setUp()
        self.configure_origins([self.origin])

    def test_allowed_origin_gets_permission_on_success(self):
        status, headers, _ = self.request('GET', '/modules', headers={'Origin': self.origin})
        self.assertEqual(status, 200)
        self.assertEqual(headers['access-control-allow-origin'], self.origin)
        self.assertIn('origin', headers['vary'].lower())
        self.assertNotIn('access-control-allow-credentials', headers)

    def test_foreign_origin_gets_no_permission_on_success(self):
        status, headers, _ = self.request('GET', '/modules', headers={'Origin': self.foreign_origin})
        self.assertEqual(status, 200)
        self.assertNotIn('access-control-allow-origin', headers)

    def test_empty_origins_gets_no_permission(self):
        self.configure_origins([])
        status, headers, _ = self.request('GET', '/modules', headers={'Origin': self.origin})
        self.assertEqual(status, 200)
        self.assertNotIn('access-control-allow-origin', headers)

    def preflight(self, origin):
        return self.request('OPTIONS', '/modules', headers={
            'Origin': origin,
            'Access-Control-Request-Method': 'POST',
            'Access-Control-Request-Headers': 'Authorization, Content-Type',
        })

    def test_allowed_preflight_accepts_method_and_auth_headers(self):
        status, headers, _ = self.preflight(self.origin)
        self.assertEqual(status, 200)
        self.assertEqual(headers['access-control-allow-origin'], self.origin)
        self.assertIn('POST', headers['access-control-allow-methods'].split(', '))
        allowed_headers = {value.strip().lower() for value in headers['access-control-allow-headers'].split(',')}
        self.assertTrue({'authorization', 'content-type'}.issubset(allowed_headers))
        self.assertNotIn('access-control-allow-credentials', headers)

    def test_foreign_preflight_is_rejected(self):
        status, headers, _ = self.preflight(self.foreign_origin)
        self.assertEqual(status, 400)
        self.assertNotIn('access-control-allow-origin', headers)

    def test_empty_origins_rejects_preflight(self):
        self.configure_origins([])
        status, headers, _ = self.preflight(self.origin)
        self.assertEqual(status, 400)
        self.assertNotIn('access-control-allow-origin', headers)

    def test_expected_http_error_has_cors_permission(self):
        response = self.request('GET', '/modules/999999', headers={'Origin': self.origin})
        self.assert_error(response, 404, 'MODULE_NOT_FOUND', 'Модуль не найден')
        self.assertEqual(response[1]['access-control-allow-origin'], self.origin)

    def test_authentication_error_has_cors_and_bearer_headers(self):
        del self.app.dependency_overrides[runtime.get_current_user]
        response = self.request('GET', '/auth/me', headers={
            'Origin': self.origin, 'Authorization': 'Bearer invalid-token',
        })
        self.assert_error(response, 401, 'INVALID_TOKEN', 'Недействительный токен')
        self.assertEqual(response[1]['access-control-allow-origin'], self.origin)
        self.assertEqual(response[1]['www-authenticate'], 'Bearer')


if __name__ == '__main__':
    unittest.main()
