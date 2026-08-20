# -*- coding: utf-8 -*-
import hashlib
import hmac
import os
import tempfile
import time
import unittest
from unittest.mock import patch

import web_server
from db_manager import DBManager


class IntegrationManager:
    def __init__(self, enabled=True, key='integration-test-key-with-sufficient-length-2026',
                 authenticated=True, frontend_enabled=False, frontend_allowed_origins=None):
        self.enabled = enabled
        self.key = key
        self.authenticated = authenticated
        self.frontend_enabled = frontend_enabled
        self.frontend_allowed_origins = frontend_allowed_origins or []
        self.authenticate_calls = []

    def get_integration_config(self):
        return {
            'enabled': self.enabled,
            'shared_key': self.key,
            'ticket_ttl_seconds': 60,
            'max_clock_skew_seconds': 60,
            'frontend_enabled': self.frontend_enabled,
            'frontend_allowed_origins': self.frontend_allowed_origins,
        }

    def authenticate_user(self, username, password):
        self.authenticate_calls.append((username, password))
        return self.authenticated


class HostIntegrationTests(unittest.TestCase):
    def setUp(self):
        web_server.app.config.update(TESTING=True, SECRET_KEY='host-integration-test-secret')
        self.client = web_server.app.test_client()
        with web_server._INTEGRATION_LOCK:
            web_server._INTEGRATION_NONCES.clear()
            web_server._INTEGRATION_TICKETS.clear()
        with web_server._LOGIN_LOCK:
            web_server._LOGIN_FAILURES.clear()

    @staticmethod
    def signed_headers(key, username, password, nonce='nonce-001', timestamp=None):
        timestamp = str(int(time.time()) if timestamp is None else timestamp)
        canonical = 'POST\n/api/integration/sso-ticket\n{}\n{}\n{}\n{}'.format(
            timestamp, nonce, username, password
        )
        signature = hmac.new(
            key.encode('utf-8'), canonical.encode('utf-8'), hashlib.sha256
        ).hexdigest()
        return {
            'X-DBQuery-Integration-Timestamp': timestamp,
            'X-DBQuery-Integration-Nonce': nonce,
            'X-DBQuery-Integration-Signature': signature,
        }

    def request_ticket(self, manager, username='tester', password='secret',
                       nonce='nonce-001', next_url='/query/forms/示例/Web快速上手.qry?embed=1'):
        headers = self.signed_headers(manager.key, username, password, nonce=nonce)
        with patch('web_server.DBManager', return_value=manager):
            return self.client.post('/api/integration/sso-ticket', headers=headers, json={
                'username': username,
                'password': password,
                'next': next_url,
            })

    def request_frontend_ticket(self, manager, username='tester', password='secret',
                                origin='https://portal.example.com',
                                next_url='/query/forms/示例/Web快速上手.qry?embed=1'):
        with patch('web_server.DBManager', return_value=manager):
            return self.client.post('/api/integration/frontend-ticket',
                                    headers={'Origin': origin}, json={
                                        'username': username,
                                        'password': password,
                                        'next': next_url,
                                    })

    def test_valid_signed_request_issues_ticket_without_returning_credentials(self):

        manager = IntegrationManager()
        response = self.request_ticket(manager)
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertIn('ticket', payload)
        self.assertEqual(payload['consume_path'], '/sso/consume')
        self.assertNotIn('password', payload)
        self.assertNotIn('secret', response.get_data(as_text=True))
        self.assertEqual(manager.authenticate_calls, [('tester', 'secret')])
        with web_server._INTEGRATION_LOCK:
            state = web_server._INTEGRATION_TICKETS[payload['ticket']]
        self.assertEqual(state['username'], 'tester')
        self.assertNotIn('password', state)

    def test_ticket_can_only_be_consumed_once_and_creates_web_session(self):
        manager = IntegrationManager()
        ticket = self.request_ticket(manager).get_json()['ticket']
        response = self.client.post('/sso/consume', data={'ticket': ticket})
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.headers.get('Location', '').startswith('/query/forms/'))
        with self.client.session_transaction() as session_state:
            self.assertEqual(session_state.get('auth_user'), 'tester')
            self.assertEqual(session_state.get('auth_source'), 'host_integration')
            self.assertNotIn('password', session_state)
        self.assertEqual(self.client.post('/sso/consume', data={'ticket': ticket}).status_code, 401)

    def test_replayed_nonce_is_rejected_before_second_database_check(self):
        manager = IntegrationManager()
        self.assertEqual(self.request_ticket(manager, nonce='replay-nonce').status_code, 200)
        response = self.request_ticket(manager, nonce='replay-nonce')
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.get_json()['error_type'], 'replayed_integration_request')
        self.assertEqual(len(manager.authenticate_calls), 1)

    def test_invalid_signature_and_expired_timestamp_do_not_authenticate(self):
        manager = IntegrationManager()
        headers = self.signed_headers('wrong-key', 'tester', 'secret', nonce='bad-signature')
        with patch('web_server.DBManager', return_value=manager):
            response = self.client.post('/api/integration/sso-ticket', headers=headers, json={
                'username': 'tester', 'password': 'secret'
            })
        self.assertEqual(response.status_code, 403)
        self.assertFalse(manager.authenticate_calls)

        headers = self.signed_headers(manager.key, 'tester', 'secret', nonce='expired',
                                      timestamp=int(time.time()) - 61)
        with patch('web_server.DBManager', return_value=manager):
            response = self.client.post('/api/integration/sso-ticket', headers=headers, json={
                'username': 'tester', 'password': 'secret'
            })
        self.assertEqual(response.status_code, 401)
        self.assertFalse(manager.authenticate_calls)

    def test_disabled_integration_rejects_request(self):
        manager = IntegrationManager(enabled=False)
        response = self.request_ticket(manager)
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.get_json()['error_type'], 'integration_not_enabled')
        self.assertFalse(manager.authenticate_calls)

    def test_frontend_password_exchange_requires_exact_origin_and_creates_session(self):
        manager = IntegrationManager(
            frontend_enabled=True,
            frontend_allowed_origins=['https://portal.example.com']
        )
        with patch('web_server.DBManager', return_value=manager):
            preflight = self.client.open('/api/integration/frontend-ticket', method='OPTIONS',
                                         headers={'Origin': 'https://portal.example.com'})
        self.assertEqual(preflight.status_code, 204)
        self.assertEqual(preflight.headers.get('Access-Control-Allow-Origin'),
                         'https://portal.example.com')

        response = self.request_frontend_ticket(manager)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers.get('Access-Control-Allow-Origin'),
                         'https://portal.example.com')
        payload = response.get_json()
        self.assertIn('ticket', payload)
        self.assertNotIn('password', response.get_data(as_text=True))

        consumed = self.client.post('/sso/consume', data={'ticket': payload['ticket']})
        self.assertEqual(consumed.status_code, 302)
        with self.client.session_transaction() as session_state:
            self.assertEqual(session_state.get('auth_user'), 'tester')
            self.assertEqual(session_state.get('auth_source'), 'frontend_password_exchange')

    def test_frontend_password_exchange_rejects_disabled_or_untrusted_origin(self):
        disabled = IntegrationManager(frontend_enabled=False,
                                      frontend_allowed_origins=['https://portal.example.com'])
        response = self.request_frontend_ticket(disabled)
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.get_json()['error_type'], 'frontend_integration_not_enabled')
        self.assertFalse(disabled.authenticate_calls)

        manager = IntegrationManager(frontend_enabled=True,
                                     frontend_allowed_origins=['https://portal.example.com'])
        response = self.request_frontend_ticket(manager, origin='https://untrusted.example.com')
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.get_json()['error_type'], 'frontend_integration_origin_denied')
        self.assertFalse(manager.authenticate_calls)

    def test_frontend_password_exchange_uses_existing_login_rate_limit(self):
        manager = IntegrationManager(
            authenticated=False, frontend_enabled=True,
            frontend_allowed_origins=['https://portal.example.com']
        )
        for _ in range(web_server._LOGIN_LIMIT):
            response = self.request_frontend_ticket(manager)
            self.assertEqual(response.status_code, 401)
        response = self.request_frontend_ticket(manager)
        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.get_json()['error_type'], 'frontend_integration_rate_limited')

    def test_integration_config_persists_generated_key_and_safe_limits(self):

        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = os.path.join(temp_dir, 'config.ini')
            with patch('db_manager.CONFIG_PATH', config_path):
                manager = DBManager()
                shared_key = manager.generate_integration_key()
                self.assertGreaterEqual(len(shared_key), 32)
                manager.set_integration_config({
                    'enabled': True,
                    'shared_key': shared_key,
                                        'ticket_ttl_seconds': 60,
                    'max_clock_skew_seconds': 60,
                    'frontend_enabled': True,
                    'frontend_allowed_origins': 'https://Portal.Example.com/, invalid, https://portal.example.com',
                })

                restored = DBManager().get_integration_config()
            self.assertTrue(restored['enabled'])
            self.assertEqual(restored['shared_key'], shared_key)
            self.assertEqual(restored['ticket_ttl_seconds'], 60)
            self.assertEqual(restored['max_clock_skew_seconds'], 60)
            self.assertTrue(restored['frontend_enabled'])
            self.assertEqual(restored['frontend_allowed_origins'], ['https://portal.example.com'])


if __name__ == '__main__':
    unittest.main()
