# -*- coding: utf-8 -*-
import logging
import os
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import web_server
from core.query_service import serialize_form
from db_manager import DBManager
from form_parser import QueryForm, QueryParam


class EmbedManager:
    """隔离真实配置和数据库，并记录 Embed V1 的认证调用。"""

    def __init__(self, authenticated=True, enabled=True, origins=None, frame_ancestors=None):
        self.authenticated = authenticated
        self.enabled = enabled
        self.origins = origins or ['https://peis.example.com']
        self.frame_ancestors = frame_ancestors or ['https://peis.example.com']
        self.authenticate_calls = []

    def get_integration_config(self):
        return {
            'frontend_embed_enabled': self.enabled,
            'frontend_embed_allowed_origins': self.origins,
            'frontend_embed_session_minutes': 60,
            'frame_ancestors': self.frame_ancestors,
        }

    def authenticate_user(self, username, password):
        self.authenticate_calls.append((username, password))
        return self.authenticated


class CapturingHandler(logging.Handler):
    def __init__(self):
        super(CapturingHandler, self).__init__()
        self.messages = []

    def emit(self, record):
        self.messages.append(record.getMessage())


class FrontendEmbedV1Tests(unittest.TestCase):
    origin = 'https://peis.example.com'

    def setUp(self):
        web_server.app.config.update(TESTING=True, SECRET_KEY='frontend-embed-v1-test-secret')
        self.client = web_server.app.test_client()
        with web_server._LOGIN_LOCK:
            web_server._LOGIN_FAILURES.clear()

    def manager_patch(self, manager):
        return patch('web_server.DBManager', return_value=manager)

    def request_login(self, manager, username='tester', password='correct', origin=None):
        with self.manager_patch(manager):
            return self.client.post('/api/integration/frontend-login', headers={
                'Origin': origin or self.origin
            }, json={'username': username, 'password': password})

    def establish_session(self, username='tester'):
        with self.client.session_transaction() as state:
            state['auth_user'] = username
            state['auth_source'] = 'frontend_embed_v1'
            state['csrf_token'] = 'csrf'

    def test_embed_is_disabled_by_default(self):
        manager = EmbedManager(enabled=False)
        response = self.request_login(manager)
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.get_json()['error_type'], 'SESSION_FAILED')
        self.assertFalse(manager.authenticate_calls)

    def test_allowed_origin_login_creates_http_only_dbquery_session(self):
        manager = EmbedManager()
        response = self.request_login(manager)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers.get('Access-Control-Allow-Origin'), self.origin)
        self.assertEqual(response.headers.get('Access-Control-Allow-Credentials'), 'true')
        self.assertIn('HttpOnly', response.headers.get('Set-Cookie', ''))
        payload = response.get_json()
        self.assertTrue(payload['authenticated'])
        self.assertNotIn('password', response.get_data(as_text=True).lower())
        self.assertEqual(manager.authenticate_calls, [('tester', 'correct')])
        with self.client.session_transaction() as state:
            self.assertEqual(state.get('auth_user'), 'tester')
            self.assertEqual(state.get('auth_source'), 'frontend_embed_v1')
            self.assertNotIn('password', state)
            self.assertIn('auth_expires_at', state)

    def test_forbidden_origin_is_rejected_before_database_authentication(self):
        manager = EmbedManager()
        response = self.request_login(manager, origin='https://untrusted.example.com')
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.get_json()['error_type'], 'ORIGIN_DENIED')
        self.assertFalse(manager.authenticate_calls)
        self.assertIsNone(response.headers.get('Access-Control-Allow-Origin'))

    def test_authentication_failures_have_the_same_client_response(self):
        missing_user = EmbedManager(authenticated=False)
        missing_response = self.request_login(missing_user, username='missing', password='bad')
        with web_server._LOGIN_LOCK:
            web_server._LOGIN_FAILURES.clear()
        disabled_user = EmbedManager(authenticated=False)
        disabled_response = self.request_login(disabled_user, username='disabled', password='bad')
        self.assertEqual(missing_response.status_code, disabled_response.status_code)
        self.assertEqual(missing_response.get_json(), disabled_response.get_json())
        self.assertEqual(missing_response.get_json()['error'], '账号或密码错误。')
        self.assertEqual(missing_response.get_json()['error_type'], 'AUTH_FAILED')

    def test_login_password_is_not_written_to_application_logs(self):
        manager = EmbedManager(authenticated=False)
        handler = CapturingHandler()
        loggers = [logging.getLogger('DBQuery.web'), logging.getLogger('DBQuery.db_manager')]
        for logger in loggers:
            logger.addHandler(handler)
        try:
            response = self.request_login(manager, password='log-secret-should-not-appear')
        finally:
            for logger in loggers:
                logger.removeHandler(handler)
        self.assertEqual(response.status_code, 401)
        self.assertNotIn('log-secret-should-not-appear', '\n'.join(handler.messages))

    def test_existing_session_returns_authenticated_without_reauthentication(self):
        manager = EmbedManager()
        self.establish_session()
        with self.manager_patch(manager):
            response = self.client.get('/api/integration/session', headers={'Origin': self.origin})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {'authenticated': True})
        self.assertFalse(manager.authenticate_calls)

    def test_embed_login_rate_limit_applies(self):
        manager = EmbedManager(authenticated=False)
        for _ in range(web_server._LOGIN_LIMIT):
            self.assertEqual(self.request_login(manager).status_code, 401)
        response = self.request_login(manager)
        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.get_json()['error_type'], 'AUTH_FAILED')

    def test_logout_invalidates_only_dbquery_session(self):
        manager = EmbedManager()
        self.establish_session()
        with self.manager_patch(manager):
            logout = self.client.post('/api/integration/logout', headers={'Origin': self.origin})
            session_state = self.client.get('/api/integration/session', headers={'Origin': self.origin})
        self.assertEqual(logout.status_code, 200)
        self.assertEqual(session_state.get_json(), {'authenticated': False})

    def test_csp_uses_configured_frame_ancestors_without_x_frame_options(self):
        manager = EmbedManager(frame_ancestors=['https://peis.example.com'])
        with self.manager_patch(manager):
            response = self.client.get('/login')
        self.assertEqual(response.headers.get('Content-Security-Policy'),
                         "frame-ancestors 'self' https://peis.example.com")
        self.assertIsNone(response.headers.get('X-Frame-Options'))

    def test_embed_config_defaults_to_disabled_and_parses_explicit_boolean_values(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = os.path.join(temp_dir, 'config.ini')
            with patch('db_manager.CONFIG_PATH', config_path):
                manager = DBManager()
                manager.set_integration_config({
                    'enabled': False,
                    'shared_key': '',
                    'ticket_ttl_seconds': 60,
                    'max_clock_skew_seconds': 60,
                    'frontend_enabled': False,
                })
                self.assertFalse(DBManager().get_integration_config()['frontend_embed_enabled'])
                manager.set_integration_config({
                    'enabled': False,
                    'shared_key': '',
                    'ticket_ttl_seconds': 60,
                    'max_clock_skew_seconds': 60,
                    'frontend_enabled': False,
                    'frontend_embed_enabled': 'yes',
                    'frontend_embed_allowed_origins': 'https://PEIS.example.com/, *',
                    'frontend_embed_session_minutes': 9999,
                    'frame_ancestors': 'https://PEIS.example.com/, *',
                })
                restored = DBManager().get_integration_config()
        self.assertTrue(restored['frontend_embed_enabled'])
        self.assertEqual(restored['frontend_embed_allowed_origins'], ['https://peis.example.com'])
        self.assertEqual(restored['frame_ancestors'], ['https://peis.example.com'])
        self.assertEqual(restored['frontend_embed_session_minutes'], 1440)

    def test_options_sql_stays_out_of_browser_serialization(self):
        form = QueryForm()
        form.file_path = os.path.join(web_server.FORMS_DIR, 'test.qry')
        form.params = [QueryParam(
            'doctor', '医生', 'select', options_sql='SELECT DoctorID FROM Doctor WHERE Secret = 1'
        )]
        serialized = serialize_form(form, web_server.BASE_DIR)
        self.assertTrue(serialized['params'][0]['dynamic_options'])
        self.assertNotIn('options_sql', serialized['params'][0])

    def test_removed_form_specific_embed_routes_are_not_exposed(self):
        self.assertEqual(self.client.post('/api/integration/embed-url', json={}).status_code, 404)
        self.assertEqual(self.client.get('/embed/person-detail').status_code, 404)

    def test_sdk_supports_no_form_or_params_and_embeds_home(self):
        completed = subprocess.run(
            ['node', 'tests/test_dbquery_embed_sdk.js'],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn('DBQueryEmbed SDK tests passed', completed.stdout)


if __name__ == '__main__':
    unittest.main()
