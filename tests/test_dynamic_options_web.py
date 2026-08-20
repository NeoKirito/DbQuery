# -*- coding: utf-8 -*-
import unittest
from unittest.mock import patch

import web_server
from form_parser import QueryForm, QueryParam


class RecordingManager:
    def __init__(self, fail_options=False):
        self.fail_options = fail_options
        self.option_calls = []
        self.query_sql = ''

    def get_web_config(self):
        return {'query_timeout': 60, 'max_rows': 5000}

    def execute_query_limited(self, sql, query_timeout, max_rows, query_type):
        if 'FROM Doctor' in sql:
            self.option_calls.append((sql, query_timeout, max_rows, query_type))
            if self.fail_options:
                raise RuntimeError('driver detail must stay server-side')
            return ['DoctorID', 'DoctorName'], [[1032, '张医生'], [1033, '李医生']], False
        self.query_sql = sql
        return ['编号'], [[1]], False


class DynamicOptionsWebTests(unittest.TestCase):
    def setUp(self):
        web_server.app.config.update(TESTING=True, SECRET_KEY='dynamic-options-test-secret')
        self.client = web_server.app.test_client()
        with self.client.session_transaction() as session_state:
            session_state['auth_user'] = 'tester'
            session_state['csrf_token'] = 'dynamic-options-csrf'
        self.form = QueryForm()
        self.form.query_type = 'select'
        self.form.sql = "SELECT '{doctor}' AS Doctor, '{hidden}' AS Source"
        self.form.params = [
            QueryParam(
                'doctor', '医生', 'select', ['全部'], default='全部',
                options_sql='SELECT DoctorID, DoctorName FROM Doctor WHERE Enabled=1'
            ),
            QueryParam('hidden', '来源', 'hidden', default='PEIS'),
        ]
        self.form_tuple = (self.form, 'forms/test.qry', '/tmp/test.qry')

    def test_options_api_uses_qry_configuration_not_client_sql(self):
        manager = RecordingManager()
        with patch('web_server.get_form_from_path', return_value=self.form_tuple), \
             patch('web_server.DBManager', return_value=manager):
            response = self.client.post('/api/options', json={
                'file_path': 'forms/test.qry',
                'param_name': 'doctor',
                'options_sql': 'DELETE FROM Doctor',
            })
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload['warning'], '')
        self.assertEqual(payload['options'], [
            {'value': '全部', 'label': '全部'},
            {'value': '1032', 'label': '张医生'},
            {'value': '1033', 'label': '李医生'},
        ])
        self.assertEqual(manager.option_calls, [
            ('SELECT DoctorID, DoctorName FROM Doctor WHERE Enabled=1', 10, 1000, 'select')
        ])

    def test_options_api_keeps_static_options_when_dynamic_load_fails(self):
        manager = RecordingManager(fail_options=True)
        with patch('web_server.get_form_from_path', return_value=self.form_tuple), \
             patch('web_server.DBManager', return_value=manager):
            response = self.client.post('/api/options', json={
                'file_path': 'forms/test.qry', 'param_name': 'doctor'
            })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {
            'options': [{'value': '全部', 'label': '全部'}],
            'warning': '候选数据加载失败，可刷新重试。'
        })

    def test_query_uses_dynamic_value_and_ignores_unknown_client_parameters(self):
        manager = RecordingManager()
        with patch('web_server.get_form_from_path', return_value=self.form_tuple), \
             patch('web_server.DBManager', return_value=manager):
            response = self.client.post('/api/query', json={
                'file_path': 'forms/test.qry',
                'params': {'doctor': '1032', 'hidden': 'tampered', 'unknown': "x' OR 1=1 --"}
            })
        self.assertEqual(response.status_code, 200)
        self.assertIn("'1032'", manager.query_sql)
        self.assertIn("'PEIS'", manager.query_sql)
        self.assertNotIn('unknown', manager.query_sql)
        self.assertNotIn('OR 1=1', manager.query_sql)


if __name__ == '__main__':
    unittest.main()
