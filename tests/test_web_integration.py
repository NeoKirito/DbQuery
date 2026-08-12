# -*- coding: utf-8 -*-
import os
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

# 测试环境可能没有 Windows ODBC 驱动或与项目 Python 版本匹配的 pyodbc。
# 仅在缺失时注入最小桩，使路由/业务测试与实际数据库驱动隔离。
try:
    import pyodbc  # noqa: F401
except ImportError:
    class _PyodbcError(Exception):
        pass

    sys.modules['pyodbc'] = types.SimpleNamespace(
        Error=_PyodbcError,
        connect=lambda *args, **kwargs: None,
        drivers=lambda: []
    )

from form_parser import FormParser
from core.query_service import build_final_sql, serialize_form
import web_server
from db_manager import DBManager, QueryTimeoutError


class LimitedQueryExecutionTests(unittest.TestCase):
    def test_limited_query_reads_one_extra_record_and_closes_cursor(self):
        class FakeCursor:
            def __init__(self):
                self.description = [('编号',), ('姓名',)]
                self.fetch_size = None
                self.timeout = None
                self.closed = False

            def execute(self, sql):
                self.sql = sql

            def fetchmany(self, size):
                self.fetch_size = size
                return [(1, '甲'), (2, '乙'), (3, '丙')]

            def close(self):
                self.closed = True

        class FakeConnection:
            def __init__(self):
                self.cursor_instance = FakeCursor()

            def cursor(self):
                return self.cursor_instance

        manager = DBManager.__new__(DBManager)
        connection = FakeConnection()
        columns, rows, truncated = manager._run_limited_query(
            connection, 'SELECT 1', query_timeout=60, max_rows=2
        )

        self.assertEqual(columns, ['编号', '姓名'])
        self.assertEqual(rows, [[1, '甲'], [2, '乙']])
        self.assertTrue(truncated)
        self.assertEqual(connection.cursor_instance.fetch_size, 3)
        self.assertEqual(connection.cursor_instance.timeout, 60)
        self.assertTrue(connection.cursor_instance.closed)

    def test_desktop_interface_keeps_unlimited_path_separate_from_web_limits(self):
        class FakeConnection:
            def __init__(self):
                self.closed = False

            def close(self):
                self.closed = True

        manager = DBManager.__new__(DBManager)
        connection = FakeConnection()
        manager._open_connection = lambda: connection
        manager._run_unlimited_query = lambda conn, sql: (['编号'], [[1], [2], [3]])
        manager.execute_query_limited = lambda *args, **kwargs: self.fail('桌面端不应调用 Web 限制路径')

        columns, rows = manager.execute_query('SELECT 1')
        self.assertEqual(columns, ['编号'])
        self.assertEqual(rows, [[1], [2], [3]])
        self.assertTrue(connection.closed)


class FormParserCompatibilityTests(unittest.TestCase):
    def parse_content(self, content):
        handle, path = tempfile.mkstemp(suffix='.qry')
        try:
            with os.fdopen(handle, 'w', encoding='utf-8') as form_file:
                form_file.write(content)
            return FormParser.parse_file(path)
        finally:
            if os.path.exists(path):
                os.remove(path)

    def test_old_and_extended_parameter_types_are_parsed(self):
        form = self.parse_content('''
[meta]
title = 综合测试
group = 测试

[params]
keyword = 关键词 | text
start_date = 开始日期 | date | {today}
visit_time = 就诊时间 | datetime
count = 数量 | number | 10
status = 状态 | select:全部,有效 | 全部
notes = 备注 | textarea | 默认备注 | placeholder=请输入备注 | required | width=320
active = 仅有效 | checkbox | 1
sex = 性别 | radio:全部,男,女 | 全部
source = 来源 | hidden | PEIS
other = 其他 | unsupported | 默认值 | ignored=value

[sql]
SELECT '{keyword}' AS Keyword
''')
        parameters = {param.name: param for param in form.params}

        self.assertEqual(parameters['keyword'].ptype, 'text')
        self.assertEqual(parameters['start_date'].ptype, 'date')
        self.assertEqual(parameters['visit_time'].ptype, 'datetime')
        self.assertEqual(parameters['count'].ptype, 'number')
        self.assertEqual(parameters['status'].ptype, 'select')
        self.assertEqual(parameters['status'].options, ['全部', '有效'])
        self.assertEqual(parameters['notes'].ptype, 'textarea')
        self.assertEqual(parameters['notes'].placeholder, '请输入备注')
        self.assertTrue(parameters['notes'].required)
        self.assertEqual(parameters['notes'].width, '320px')
        self.assertEqual(parameters['active'].ptype, 'checkbox')
        self.assertEqual(parameters['sex'].ptype, 'radio')
        self.assertEqual(parameters['sex'].options, ['全部', '男', '女'])
        self.assertEqual(parameters['source'].ptype, 'hidden')
        self.assertEqual(parameters['source'].default, 'PEIS')
        self.assertEqual(parameters['other'].ptype, 'text')
        self.assertEqual(parameters['other'].default, '默认值')

        payload = serialize_form(form)
        self.assertEqual(payload['params'][5]['placeholder'], '请输入备注')
        self.assertTrue(payload['params'][5]['required'])
        self.assertEqual(payload['params'][5]['width'], '320px')

    def test_invalid_width_and_unknown_attributes_are_safe(self):
        form = self.parse_content('''
[params]
keyword = 关键词 | text | | width=bad;value | unknown=anything
[sql]
SELECT 1
''')
        parameter = form.params[0]
        self.assertEqual(parameter.ptype, 'text')
        self.assertEqual(parameter.width, '')
        self.assertEqual(parameter.default, '')

    def test_sql_building_and_safety_regression(self):
        form = self.parse_content('''
[meta]
type = select
[params]
keyword = 关键词 | text
[sql]
SELECT '{keyword}' AS Keyword
''')
        sql = build_final_sql(form, {'keyword': "O'Brien"})
        self.assertIn("O''Brien", sql)
        self.assertEqual(FormParser.is_safe_sql(sql, 'select'), (True, 'OK'))
        self.assertFalse(FormParser.is_safe_sql('INSERT INTO T VALUES (1)', 'select')[0])
        self.assertTrue(FormParser.is_safe_sql('EXEC dbo.usp_Test @P=1', 'exec')[0])
        self.assertFalse(FormParser.is_safe_sql('EXEC dbo.usp_Test; DELETE FROM T', 'exec')[0])


class SuccessfulManager:
    def get_web_config(self):
        return {'query_timeout': 60, 'max_rows': 2}

    def execute_query_limited(self, sql, query_timeout, max_rows):
        return ['编号', '姓名'], [[1, '张三'], [2, '李四']], True


class TimeoutManager:
    def get_web_config(self):
        return {'query_timeout': 60, 'max_rows': 5000}

    def execute_query_limited(self, sql, query_timeout, max_rows):
        raise QueryTimeoutError('driver timeout')


class FailingManager:
    def get_web_config(self):
        return {'query_timeout': 60, 'max_rows': 5000}

    def execute_query_limited(self, sql, query_timeout, max_rows):
        raise RuntimeError('internal driver details')


class WebRouteTests(unittest.TestCase):
    def setUp(self):
        web_server.app.config.update(TESTING=True)
        self.client = web_server.app.test_client()
        self.file_path = 'forms/系统/数据库表结构.qry'

    def query(self):
        return self.client.post('/api/query', json={'file_path': self.file_path, 'params': {}})

    def test_index_and_embed_routes_render_business_ui(self):
        response = self.client.get('/')
        self.assertEqual(response.status_code, 200)
        self.assertIn('综合查询'.encode('utf-8'), response.data)

        response = self.client.get('/?hide_header=1')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'data-embed-mode="1"', response.data)
        self.assertNotIn('数据库查询工具'.encode('utf-8'), response.data)

        response = self.client.get('/?embed=1')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'data-embed-mode="1"', response.data)

    def test_query_page_hides_technical_badge_and_sidebar_when_embedded(self):
        response = self.client.get('/query/{}?embed=1&sidebar=0'.format(self.file_path))
        self.assertEqual(response.status_code, 200)
        self.assertIn('查询条件'.encode('utf-8'), response.data)
        self.assertIn('查询结果'.encode('utf-8'), response.data)
        self.assertNotIn(b'class="app-sidebar"', response.data)
        self.assertNotIn(b'type-badge', response.data)

    def test_forms_api_and_limited_query_response(self):
        response = self.client.get('/api/forms')
        self.assertEqual(response.status_code, 200)
        self.assertIsInstance(response.get_json(), dict)

        with patch('web_server.DBManager', SuccessfulManager):
            response = self.query()
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload['row_count'], 2)
        self.assertTrue(payload['truncated'])
        self.assertEqual(payload['max_rows'], 2)

    def test_timeout_and_generic_error_do_not_expose_driver_details(self):
        with patch('web_server.DBManager', TimeoutManager):
            response = self.query()
        self.assertEqual(response.status_code, 408)
        self.assertEqual(response.get_json()['error'], '查询超时，请缩小查询范围或增加查询条件。')

        with patch('web_server.DBManager', FailingManager):
            response = self.query()
        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.get_json()['error'], '数据服务暂时不可用，请稍后重试。')
        self.assertNotIn('internal driver details', response.get_json()['error'])

    def test_export_returns_title_based_filename(self):
        def fake_export(path, columns, rows, *args):
            with open(path, 'wb') as export_file:
                export_file.write(b'xlsx')

        with patch('web_server.export_to_excel', fake_export):
            response = self.client.post('/api/export', json={
                'file_path': self.file_path,
                'params': {},
                'columns': ['编号'],
                'rows': [[1]],
                'elapsed': 0.2,
            })
        self.assertEqual(response.status_code, 200)
        disposition = response.headers.get('Content-Disposition', '')
        self.assertIn('.xlsx', disposition)
        self.assertNotIn('export.xlsx', disposition)
        response.close()


if __name__ == '__main__':
    unittest.main()
