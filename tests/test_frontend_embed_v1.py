# -*- coding: utf-8 -*-
import logging
import os
import tempfile
import unittest
from unittest.mock import patch

import web_server
from db_manager import DBManager
from core.query_service import serialize_form
from form_parser import QueryForm, QueryParam


class EmbedManager:
    """避免测试访问真实配置或数据库，并记录认证调用。"""

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
        self.form = self.make_form()

    @staticmethod
    def make_form(public_id='person-detail', web_enabled=True):
        form = QueryForm()
        form.file_path = os.path.join(web_server.FORMS_DIR, 'test.qry')
        form.title = '人员明细'
        form.description = 'Embed test form'
        form.public_id = public_id
        form.web_enabled = web_enabled
        form.query_type = 'select'
        form.sql = "SELECT '{tjh}' AS TJH, '{internal}' AS Internal, '{source}' AS Source"
        form.params = [
            QueryParam('tjh', '体检号', 'text', default='', required=True, external_allowed=True),
            QueryParam('internal', '内部条件', 'text', default='server-only'),
            QueryParam('source', '来源', 'hidden', default='DBQuery', external_allowed=True),
            QueryParam('visit_date', '日期', 'date', default='', external_allowed=True),
        ]
        return form

    def manager_patch(self, manager):
        return patch('web_server.DBManager', return_value=manager)

    def forms_patch(self, forms=None):
        return patch('web_server.FormParser.load_forms_from_dir', return_value={
            '测试': list(forms or [self.form])
        })

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

    def test_login_from_allowed_origin_creates_session_without_returning_password(self):
        manager = EmbedManager()
        response = self.request_login(manager)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers.get('Access-Control-Allow-Origin'), self.origin)
        self.assertEqual(response.headers.get('Access-Control-Allow-Credentials'), 'true')
        payload = response.get_json()
        self.assertTrue(payload['authenticated'])
        self.assertNotIn('password', response.get_data(as_text=True).lower())
        self.assertEqual(manager.authenticate_calls, [('tester', 'correct')])
        self.assertIn('HttpOnly', response.headers.get('Set-Cookie', ''))
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

    def test_login_password_is_not_written_to_application_logs(self):
        manager = EmbedManager(authenticated=False)
        handler = CapturingHandler()
        loggers = [logging.getLogger('DBQuery.web'), logging.getLogger('DBQuery.db_manager')]
        for logger in loggers:
            logger.addHandler(handler)
        try:
            response = self.request_login(manager, username='tester', password='log-secret-should-not-appear')
        finally:
            for logger in loggers:
                logger.removeHandler(handler)
        self.assertEqual(response.status_code, 401)
        self.assertNotIn('log-secret-should-not-appear', '\n'.join(handler.messages))

    def test_authentication_failures_have_the_same_client_response(self):
        unknown_user = EmbedManager(authenticated=False)
        unknown_response = self.request_login(unknown_user, username='missing', password='bad')
        with web_server._LOGIN_LOCK:
            web_server._LOGIN_FAILURES.clear()
        disabled_user = EmbedManager(authenticated=False)
        disabled_response = self.request_login(disabled_user, username='disabled', password='bad')
        self.assertEqual(unknown_response.status_code, disabled_response.status_code)
        self.assertEqual(unknown_response.get_json(), disabled_response.get_json())
        self.assertEqual(unknown_response.get_json()['error'], '账号或密码错误。')

    def test_session_endpoint_reuses_existing_session_without_reauthenticating(self):
        manager = EmbedManager()
        self.establish_session()
        with self.manager_patch(manager):
            response = self.client.get('/api/integration/session', headers={'Origin': self.origin})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {'authenticated': True})
        self.assertFalse(manager.authenticate_calls)

    def test_login_rate_limit_applies_to_embed_endpoint(self):
        manager = EmbedManager(authenticated=False)
        for _ in range(web_server._LOGIN_LIMIT):
            self.assertEqual(self.request_login(manager).status_code, 401)
        response = self.request_login(manager)
        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.get_json()['error_type'], 'AUTH_FAILED')

    def test_embed_url_only_includes_external_allowed_business_parameter(self):
        manager = EmbedManager()
        self.establish_session()
        with self.manager_patch(manager), self.forms_patch():
            response = self.client.post('/api/integration/embed-url', headers={'Origin': self.origin}, json={
                'form': 'person-detail',
                'params': {'tjh': '202608250001', 'internal': 'override', 'source': 'override'},
            })
        self.assertEqual(response.status_code, 200)
        embed_url = response.get_json()['embed_url']
        self.assertIn('embed=1', embed_url)
        self.assertIn('tjh=202608250001', embed_url)
        self.assertNotIn('internal=', embed_url)
        self.assertNotIn('source=', embed_url)
        self.assertNotIn('password', embed_url.lower())

    def test_embed_route_revalidates_params_and_never_allows_hidden_or_internal_override(self):
        manager = EmbedManager()
        self.establish_session()
        with self.manager_patch(manager), self.forms_patch():
            response = self.client.get('/embed/person-detail?embed=1&sidebar=0&tjh=ABC&internal=evil&source=evil')
        html = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn('value="ABC"', html)
        self.assertIn('server-only', html)
        self.assertNotIn('evil', html)

    def test_invalid_type_and_path_like_form_id_are_rejected(self):
        manager = EmbedManager()
        self.establish_session()
        with self.manager_patch(manager), self.forms_patch():
            invalid_param = self.client.post('/api/integration/embed-url', headers={'Origin': self.origin}, json={
                'form': 'person-detail', 'params': {'visit_date': 'not-a-date'}
            })
            traversal = self.client.post('/api/integration/embed-url', headers={'Origin': self.origin}, json={
                'form': '../forms/test.qry', 'params': {}
            })
        self.assertEqual(invalid_param.status_code, 400)
        self.assertEqual(invalid_param.get_json()['error_type'], 'INVALID_PARAM')
        self.assertEqual(traversal.status_code, 404)
        self.assertEqual(traversal.get_json()['error_type'], 'FORM_NOT_FOUND')

    def test_non_web_enabled_form_cannot_be_embedded(self):
        manager = EmbedManager()
        self.establish_session()
        blocked = self.make_form(web_enabled=False)
        with self.manager_patch(manager), self.forms_patch([blocked]):
            response = self.client.post('/api/integration/embed-url', headers={'Origin': self.origin}, json={
                'form': 'person-detail', 'params': {}
            })
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.get_json()['error_type'], 'FORM_NOT_WEB_ENABLED')

    def test_logout_invalidates_embed_session(self):
        manager = EmbedManager()
        self.establish_session()
        with self.manager_patch(manager):
            logout = self.client.post('/api/integration/logout', headers={'Origin': self.origin})
            session_state = self.client.get('/api/integration/session', headers={'Origin': self.origin})
        self.assertEqual(logout.status_code, 200)
        self.assertEqual(session_state.get_json(), {'authenticated': False})

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

    def test_csp_uses_configured_frame_ancestors_without_x_frame_options(self):
        manager = EmbedManager(frame_ancestors=['https://peis.example.com'])
        with self.manager_patch(manager):
            response = self.client.get('/login')
        self.assertEqual(response.headers.get('Content-Security-Policy'),
                         "frame-ancestors 'self' https://peis.example.com")
        self.assertIsNone(response.headers.get('X-Frame-Options'))

    def test_serialized_form_and_rendered_query_never_expose_options_sql(self):
        dynamic_form = self.make_form()
        dynamic_form.params = [QueryParam(
            'doctor', '医生', 'select', options_sql='SELECT DoctorID FROM Doctor WHERE Secret = 1'
        )]
        serialized = serialize_form(dynamic_form, web_server.BASE_DIR)
        self.assertTrue(serialized['params'][0]['dynamic_options'])
        self.assertNotIn('options_sql', serialized['params'][0])
        self.establish_session()
        form_tuple = (dynamic_form, 'forms/test.qry', dynamic_form.file_path)
        manager = EmbedManager()
        with patch('web_server.get_form_from_path', return_value=form_tuple), self.manager_patch(manager):
            response = self.client.get('/query/forms/test.qry')
        self.assertNotIn('SELECT DoctorID FROM Doctor WHERE Secret = 1', response.get_data(as_text=True))

    def test_sdk_static_contract_keeps_password_out_of_url_and_storage(self):
        sdk_path = os.path.join(web_server.BASE_DIR, 'static', 'js', 'dbquery-embed.js')
        with open(sdk_path, 'r', encoding='utf-8') as source:
            sdk = source.read()
        self.assertIn('global.DBQueryEmbed', sdk)
        self.assertIn('}(window));', sdk)
        self.assertIn('/api/integration/frontend-login', sdk)
        self.assertIn('/api/integration/embed-url', sdk)
        self.assertIn('/api/integration/logout', sdk)
        self.assertIn('AUTH_FAILED', sdk)
        self.assertNotIn('localStorage', sdk)
        self.assertNotIn('sessionStorage', sdk)
        self.assertNotIn('username: username, password: password, form', sdk)


if __name__ == '__main__':
    unittest.main()
