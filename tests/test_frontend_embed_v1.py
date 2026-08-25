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
        web_server.app.config.update(
            TESTING=True,
            SECRET_KEY='frontend-embed-v1-test-secret',
            SESSION_COOKIE_NAME='dbquery_session',
            SESSION_COOKIE_PATH='/',
            SESSION_COOKIE_HTTPONLY=True,
            SESSION_COOKIE_SAMESITE='Lax',
            SESSION_COOKIE_SECURE=False,
        )
        self.client = web_server.app.test_client()
        with web_server._LOGIN_LOCK:
            web_server._LOGIN_FAILURES.clear()
        with web_server._INTEGRATION_LOCK:
            web_server._EMBED_CONTEXTS.clear()
        self.form = self.make_form()

    def tearDown(self):
        with web_server._LOGIN_LOCK:
            web_server._LOGIN_FAILURES.clear()
        with web_server._INTEGRATION_LOCK:
            web_server._EMBED_CONTEXTS.clear()

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

    def request_login(self, manager, username='tester', password='correct', origin=None, extra_headers=None):
        headers = dict(extra_headers or {})
        if origin is not None:
            headers['Origin'] = origin
        elif 'Origin' not in headers:
            headers['Origin'] = self.origin
        with self.manager_patch(manager):
            return self.client.post('/api/integration/frontend-login', headers=headers,
                                    json={'username': username, 'password': password})

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

    def test_dbquery_cookie_name_isolated_from_host_session_and_http_only(self):
        manager = EmbedManager()
        self.client.set_cookie('session', 'PEIS_SESSION_VALUE', domain='localhost')
        response = self.request_login(manager)

        set_cookie = response.headers.get('Set-Cookie', '')
        self.assertIn('dbquery_session=', set_cookie)
        self.assertIn('HttpOnly', set_cookie)
        self.assertNotIn('session=PEIS_SESSION_VALUE', set_cookie)
        self.assertEqual(self.client.get_cookie('session', domain='localhost').value, 'PEIS_SESSION_VALUE')
        self.assertIsNotNone(self.client.get_cookie('dbquery_session', domain='localhost'))

    def test_embed_logout_clears_only_dbquery_cookie(self):
        manager = EmbedManager()
        self.client.set_cookie('session', 'PEIS_SESSION_VALUE', domain='localhost')
        self.request_login(manager)
        with self.manager_patch(manager):
            logout = self.client.post('/api/integration/logout', headers={'Origin': self.origin})

        self.assertEqual(logout.status_code, 200)
        self.assertIn('dbquery_session=', logout.headers.get('Set-Cookie', ''))
        self.assertEqual(self.client.get_cookie('session', domain='localhost').value, 'PEIS_SESSION_VALUE')

    def test_cookie_secure_and_samesite_configuration_are_emitted(self):
        web_server.app.config.update(SESSION_COOKIE_SECURE=True, SESSION_COOKIE_SAMESITE='None')
        response = self.request_login(EmbedManager())
        set_cookie = response.headers.get('Set-Cookie', '')
        self.assertIn('Secure', set_cookie)
        self.assertIn('SameSite=None', set_cookie)

    def test_cookie_environment_configuration_supports_subpath_scope(self):
        with patch.dict(os.environ, {
            'DBQUERY_SESSION_COOKIE_NAME': 'dbquery_session_custom',
            'DBQUERY_SESSION_COOKIE_PATH': '/dbquery',
            'DBQUERY_SESSION_COOKIE_SECURE': 'true',
            'DBQUERY_SESSION_COOKIE_SAMESITE': 'Lax',
        }, clear=False):
            web_server._configure_session_cookie(web_server.app)
        self.assertEqual(web_server.app.config['SESSION_COOKIE_NAME'], 'dbquery_session_custom')
        self.assertEqual(web_server.app.config['SESSION_COOKIE_PATH'], '/dbquery')
        self.assertTrue(web_server.app.config['SESSION_COOKIE_SECURE'])
        self.assertEqual(web_server.app.config['SESSION_COOKIE_SAMESITE'], 'Lax')

    def test_same_origin_session_probe_without_origin_is_allowed(self):
        manager = EmbedManager(origins=['https://peis.example.com'])
        with self.manager_patch(manager):
            response = self.client.get('/api/integration/session', base_url='https://peis.example.com',
                                       headers={'Sec-Fetch-Site': 'same-origin'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {'authenticated': False})
        self.assertIsNone(response.headers.get('Access-Control-Allow-Origin'))

    def test_legacy_browser_same_origin_probe_without_fetch_metadata_is_allowed_only_for_allowed_host(self):
        manager = EmbedManager(origins=['https://peis.example.com'])
        with self.manager_patch(manager):
            allowed = self.client.get('/api/integration/session', base_url='https://peis.example.com')
            denied = self.client.get('/api/integration/session', base_url='https://dbquery.example.com')
        self.assertEqual(allowed.status_code, 200)
        self.assertEqual(denied.status_code, 403)

    def test_cross_site_session_probe_without_origin_is_rejected(self):
        manager = EmbedManager(origins=['https://peis.example.com'])
        with self.manager_patch(manager):
            response = self.client.get('/api/integration/session', base_url='https://peis.example.com',
                                       headers={'Sec-Fetch-Site': 'cross-site'})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.get_json()['error_type'], 'ORIGIN_DENIED')

    def test_evil_origin_session_probe_is_rejected(self):
        manager = EmbedManager()
        with self.manager_patch(manager):
            response = self.client.get('/api/integration/session', headers={'Origin': 'https://evil.example.com'})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.get_json()['error_type'], 'ORIGIN_DENIED')

    def test_missing_or_evil_origin_post_is_rejected_before_authentication(self):
        manager = EmbedManager()
        missing = self.request_login(manager, origin='')
        evil = self.request_login(manager, origin='https://evil.example.com')
        self.assertEqual(missing.status_code, 403)
        self.assertEqual(evil.status_code, 403)
        self.assertEqual(missing.get_json()['error_type'], 'ORIGIN_DENIED')
        self.assertEqual(evil.get_json()['error_type'], 'ORIGIN_DENIED')
        self.assertFalse(manager.authenticate_calls)

    def test_rate_limit_isolated_by_username_and_ignores_untrusted_forwarded_for(self):
        manager = EmbedManager(authenticated=False)
        spoof_headers = {'X-Forwarded-For': '198.51.100.77'}
        for _ in range(web_server._LOGIN_LIMIT):
            self.assertEqual(self.request_login(manager, username='userA', password='bad',
                                                extra_headers=spoof_headers).status_code, 401)
        blocked = self.request_login(manager, username='userA', password='bad', extra_headers=spoof_headers)
        other_user = self.request_login(manager, username='userB', password='bad', extra_headers=spoof_headers)

        self.assertEqual(blocked.status_code, 429)
        self.assertEqual(other_user.status_code, 401)
        self.assertTrue(any(key.endswith('|usera') for key in web_server._LOGIN_FAILURES))
        self.assertFalse(any(key.startswith('198.51.100.77|') for key in web_server._LOGIN_FAILURES))

    def test_proxy_forwarded_for_is_only_enabled_by_dedicated_opt_in(self):
        with patch.dict(os.environ, {'DBQUERY_TRUST_PROXY_FOR': 'false',
                                     'DBQUERY_TRUST_PROXY_PREFIX': 'true'}, clear=False):
            self.assertEqual(web_server._proxy_fix_options(), {'x_prefix': 1})
        with patch.dict(os.environ, {'DBQUERY_TRUST_PROXY_FOR': 'true',
                                     'DBQUERY_TRUST_PROXY_PREFIX': 'false'}, clear=False):
            self.assertEqual(web_server._proxy_fix_options(), {'x_for': 1})

    def test_embed_url_uses_session_bound_context_without_business_value_in_url(self):
        manager = EmbedManager()
        self.establish_session()
        with self.manager_patch(manager), self.forms_patch():
            create = self.client.post('/api/integration/embed-url', headers={'Origin': self.origin}, json={
                'form': 'person-detail',
                'params': {'tjh': '202608250001', 'internal': 'override', 'source': 'override'},
            })
            embed_url = create.get_json()['embed_url']
            rendered = self.client.get(embed_url)

        self.assertEqual(create.status_code, 200)
        self.assertIn('ctx=', embed_url)
        self.assertNotIn('tjh=', embed_url)
        self.assertNotIn('202608250001', embed_url)
        self.assertEqual(rendered.status_code, 200)
        html = rendered.get_data(as_text=True)
        self.assertIn('value="202608250001"', html)
        self.assertIn('server-only', html)
        self.assertNotIn('override', html)

    def test_ctx_url_rejects_appended_business_and_hidden_values(self):
        manager = EmbedManager()
        self.establish_session('tester')
        with self.manager_patch(manager), self.forms_patch():
            create = self.client.post('/api/integration/embed-url', headers={'Origin': self.origin}, json={
                'form': 'person-detail', 'params': {'tjh': 'original'}
            })
            response = self.client.get(create.get_json()['embed_url'] + '&tjh=override&source=override')
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()['error_type'], 'EMBED_CONTEXT_REQUIRED')

    def test_expired_embed_context_is_rejected(self):
        manager = EmbedManager()
        self.establish_session('tester')
        with self.manager_patch(manager), self.forms_patch():
            create = self.client.post('/api/integration/embed-url', headers={'Origin': self.origin}, json={
                'form': 'person-detail', 'params': {'tjh': 'original'}
            })
            context_token = create.get_json()['embed_url'].split('ctx=', 1)[1]
            with web_server._INTEGRATION_LOCK:
                web_server._EMBED_CONTEXTS[context_token]['expires_at'] = 0
            response = self.client.get(create.get_json()['embed_url'])
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.get_json()['error_type'], 'INVALID_EMBED_CONTEXT')

    def test_embed_context_cannot_be_reused_by_another_session(self):
        manager = EmbedManager()
        self.establish_session('tester')
        with self.manager_patch(manager), self.forms_patch():
            create = self.client.post('/api/integration/embed-url', headers={'Origin': self.origin}, json={
                'form': 'person-detail', 'params': {'tjh': '202608250001'}
            })
            other_client = web_server.app.test_client()
            with other_client.session_transaction() as state:
                state['auth_user'] = 'tester'
                state['auth_source'] = 'frontend_embed_v1'
            response = other_client.get(create.get_json()['embed_url'])

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.get_json()['error_type'], 'INVALID_EMBED_CONTEXT')

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
        self.assertIn('ctx=', embed_url)
        self.assertNotIn('tjh=', embed_url)
        self.assertNotIn('202608250001', embed_url)
        self.assertNotIn('internal=', embed_url)
        self.assertNotIn('source=', embed_url)
        self.assertNotIn('password', embed_url.lower())

    def test_embed_route_rejects_bare_url_parameters_without_context(self):
        manager = EmbedManager()
        self.establish_session()
        with self.manager_patch(manager), self.forms_patch():
            response = self.client.get('/embed/person-detail?embed=1&sidebar=0&tjh=ABC&internal=evil&source=evil')
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()['error_type'], 'EMBED_CONTEXT_REQUIRED')

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
