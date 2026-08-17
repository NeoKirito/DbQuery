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

import db_manager as db_manager_module
import web_server
from core.query_service import build_final_sql, export_to_excel, serialize_form
from db_manager import DBManager, QueryTimeoutError
from form_parser import FormParser, QueryForm, QueryParam


class QueryExecutionBehaviorTests(unittest.TestCase):
    class FakeCursor:
        def __init__(self, rows=None):
            self.description = [('编号',), ('姓名',)]
            self.fetch_size = None
            self.closed = False
            self.rows = rows if rows is not None else [(1, '甲'), (2, '乙'), (3, '丙')]

        def execute(self, sql):
            self.sql = sql

        def fetchmany(self, size):
            self.fetch_size = size
            return self.rows

        def close(self):
            self.closed = True

    class FakeConnection:
        def __init__(self, cursor=None):
            self.cursor_instance = cursor or QueryExecutionBehaviorTests.FakeCursor()
            self.timeout = None
            self.timeout_when_cursor_created = None
            self.closed = False

        def cursor(self):
            self.timeout_when_cursor_created = self.timeout
            return self.cursor_instance

        def close(self):
            self.closed = True

    def make_manager(self):
        manager = DBManager.__new__(DBManager)
        manager.get_web_config = lambda: {'query_timeout': 60, 'max_rows': 5000}
        return manager

    def test_connection_query_timeout_is_set_before_cursor_and_limited_rows_are_read(self):
        manager = self.make_manager()
        connection = self.FakeConnection()
        manager._open_connection = lambda: connection

        columns, rows, truncated = manager.execute_query_limited(
            'SELECT 1', query_timeout=61, max_rows=2, query_type='select'
        )

        self.assertEqual(columns, ['编号', '姓名'])
        self.assertEqual(rows, [[1, '甲'], [2, '乙']])
        self.assertTrue(truncated)
        self.assertEqual(connection.timeout, 61)
        self.assertEqual(connection.timeout_when_cursor_created, 61)
        self.assertEqual(connection.cursor_instance.fetch_size, 3)
        self.assertTrue(connection.cursor_instance.closed)
        self.assertTrue(connection.closed)
        self.assertFalse(hasattr(connection.cursor_instance, 'timeout'))

    def test_limited_query_can_run_with_cursor_that_has_no_timeout_attribute(self):
        manager = self.make_manager()
        connection = self.FakeConnection()
        columns, rows, truncated = manager._run_limited_query(connection, 'SELECT 1', max_rows=2)

        self.assertEqual(columns, ['编号', '姓名'])
        self.assertEqual(rows, [[1, '甲'], [2, '乙']])
        self.assertTrue(truncated)
        self.assertFalse(hasattr(connection.cursor_instance, 'timeout'))

    def test_select_retries_once_only_for_transient_connection_error(self):
        class TestPyodbcError(Exception):
            pass

        manager = self.make_manager()
        connections = [self.FakeConnection(), self.FakeConnection()]
        manager._open_connection = lambda: connections.pop(0)
        calls = []

        def run_query(conn, sql, max_rows):
            calls.append(conn)
            if len(calls) == 1:
                raise TestPyodbcError(('08S01', 'Communication link failure'))
            return ['编号'], [[1]], False

        manager._run_limited_query = run_query
        with patch.object(db_manager_module.pyodbc, 'Error', TestPyodbcError):
            columns, rows, truncated = manager.execute_query_limited(
                'SELECT 1', query_timeout=60, max_rows=10, query_type='select'
            )

        self.assertEqual(columns, ['编号'])
        self.assertEqual(rows, [[1]])
        self.assertFalse(truncated)
        self.assertEqual(len(calls), 2)
        self.assertTrue(all(conn.timeout == 60 for conn in calls))
        self.assertTrue(all(conn.closed for conn in calls))

    def test_exec_does_not_retry_transient_error(self):
        class TestPyodbcError(Exception):
            pass

        manager = self.make_manager()
        connection = self.FakeConnection()
        manager._open_connection = lambda: connection
        calls = []

        def run_query(conn, sql, max_rows):
            calls.append(conn)
            raise TestPyodbcError(('08S01', 'Communication link failure'))

        manager._run_limited_query = run_query
        with patch.object(db_manager_module.pyodbc, 'Error', TestPyodbcError):
            with self.assertRaises(TestPyodbcError):
                manager.execute_query_limited(
                    'EXEC dbo.usp_Report', query_timeout=60, max_rows=10, query_type='exec'
                )

        self.assertEqual(len(calls), 1)
        self.assertTrue(connection.closed)

    def test_timeout_does_not_retry(self):
        class TestPyodbcError(Exception):
            pass

        manager = self.make_manager()
        connection = self.FakeConnection()
        manager._open_connection = lambda: connection
        calls = []

        def run_query(conn, sql, max_rows):
            calls.append(conn)
            raise TestPyodbcError(('HYT00', 'Query timeout expired'))

        manager._run_limited_query = run_query
        with patch.object(db_manager_module.pyodbc, 'Error', TestPyodbcError):
            with self.assertRaises(QueryTimeoutError):
                manager.execute_query_limited(
                    'SELECT 1', query_timeout=60, max_rows=10, query_type='select'
                )

        self.assertEqual(len(calls), 1)
        self.assertTrue(connection.closed)

    def test_desktop_interface_keeps_unlimited_path_separate_from_web_limits(self):
        manager = DBManager.__new__(DBManager)
        connection = self.FakeConnection()
        manager._open_connection = lambda: connection
        manager._run_unlimited_query = lambda conn, sql: (['编号'], [[1], [2], [3]])
        manager.execute_query_limited = lambda *args, **kwargs: self.fail('桌面端不应调用 Web 限制路径')

        columns, rows = manager.execute_query('SELECT 1')
        self.assertEqual(columns, ['编号'])
        self.assertEqual(rows, [[1], [2], [3]])
        self.assertTrue(connection.closed)

    def test_desktop_exec_and_timeout_do_not_retry(self):
        class TestPyodbcError(Exception):
            pass

        for query_type, error in (
            ('exec', TestPyodbcError(('08S01', 'Communication link failure'))),
            ('select', TestPyodbcError(('HYT00', 'Query timeout expired'))),
        ):
            manager = DBManager.__new__(DBManager)
            connection = self.FakeConnection()
            manager._open_connection = lambda: connection
            calls = []

            def run_query(conn, sql):
                calls.append(conn)
                raise error

            manager._run_unlimited_query = run_query
            with patch.object(db_manager_module.pyodbc, 'Error', TestPyodbcError):
                expected = TestPyodbcError if query_type == 'exec' else QueryTimeoutError
                with self.assertRaises(expected):
                    manager.execute_query('EXEC dbo.usp_Report', query_type=query_type)
            self.assertEqual(len(calls), 1)
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
        # P0-1 回归：SELECT INTO 各种标识符形式应全部被拒绝。
        self.assertFalse(FormParser.is_safe_sql('SELECT 1 INTO [DBQuery_Options_Test]', 'select')[0])
        self.assertFalse(FormParser.is_safe_sql('SELECT 1 INTO #DBQuery_Options_Test', 'select')[0])
        self.assertFalse(FormParser.is_safe_sql('SELECT 1 INTO ##DBQuery_Options_Test', 'select')[0])
        self.assertFalse(FormParser.is_safe_sql('SELECT 1 INTO [dbo].[DBQuery_Options_Test]', 'select')[0])
        self.assertFalse(FormParser.is_safe_sql('SELECT 1 INTO dbo.T', 'select')[0])
        # 常规 SELECT 不受影响。
        self.assertEqual(FormParser.is_safe_sql('SELECT ID, Name FROM Doctor', 'select'), (True, 'OK'))

    def test_system_form_casts_extended_property_to_text_for_odbc(self):
        root_dir = os.path.dirname(os.path.dirname(__file__))
        system_form = os.path.join(root_dir, 'forms', '系统', '数据库表结构.qry')
        with open(system_form, 'r', encoding='utf-8') as form_file:
            sql = FormParser.parse_file(system_form).sql
        self.assertIn('CAST(ep.value AS NVARCHAR(4000))', sql)
        self.assertEqual(FormParser.is_safe_sql(sql, 'select'), (True, 'OK'))

    def test_checkbox_web_submit_contract_is_one_or_zero(self):
        js_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'static', 'js', 'app.js')
        with open(js_path, 'r', encoding='utf-8') as js_file:
            source = js_file.read()
        self.assertIn("params[name] = $input.is(':checked') ? '1' : '0';", source)

    def test_app_js_allow_custom_contracts(self):
        """P1-1 验收：断言 app.js 已实现 allow_custom 行为关键合约。"""
        js_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'static', 'js', 'app.js')
        with open(js_path, 'r', encoding='utf-8') as js_file:
            source = js_file.read()
        # 1. 读取 data-allow-custom 标志。
        self.assertIn("data-allow-custom", source,
                      'app.js 应读取 data-allow-custom 属性')
        # 2. allow_custom=true 时，输入文字同步到 value 字段（即自定义值可被提交）。
        self.assertIn("$value.val($input.val())", source,
                      'allow_custom=true 时应将输入文字同步到 value')
        # 3. allow_custom=false 时仍清空 value（严格模式）。
        self.assertIn("$value.val('')", source,
                      'allow_custom=false 时应清空 value')
        # 4. 提供可测试的 resolveSearchableSelectValue 函数。
        self.assertIn("function resolveSearchableSelectValue", source,
                      '应提取 resolveSearchableSelectValue 可测试函数')
        # 5. 点选候选项时提交 data-value（如 DoctorID）而不是显示文字。
        self.assertIn("$value.val($option.data('value'))", source,
                      '点选候选项时应提交 option.data-value')
        # 6. required 校验使用 resolveSearchableSelectValue。
        self.assertIn("resolveSearchableSelectValue($root)", source,
                      'validateRequiredParams 应使用 resolveSearchableSelectValue')


class SuccessfulManager:
    def get_web_config(self):
        return {'query_timeout': 60, 'max_rows': 2}

    def execute_query_limited(self, sql, query_timeout, max_rows, query_type):
        return ['编号', '姓名'], [[1, '张三'], [2, '李四']], True


class TimeoutManager:
    def get_web_config(self):
        return {'query_timeout': 60, 'max_rows': 5000}

    def execute_query_limited(self, sql, query_timeout, max_rows, query_type):
        raise QueryTimeoutError('driver timeout')


class FailingManager:
    def get_web_config(self):
        return {'query_timeout': 60, 'max_rows': 5000}

    def execute_query_limited(self, sql, query_timeout, max_rows, query_type):
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
        self.assertIn(b'class="app-body"', response.data)
        self.assertNotIn(b'app-navbar', response.data)
        self.assertIn(b'class="nav-item-content"', response.data)
        self.assertIn(b'class="nav-item-title"', response.data)

        response = self.client.get('/?hide_header=1')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'data-embed-mode="1"', response.data)
        self.assertNotIn('数据库查询工具'.encode('utf-8'), response.data)

        response = self.client.get('/?embed=1')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'data-embed-mode="1"', response.data)

    def test_query_page_removes_technical_badges_and_uses_embed_project_switcher(self):
        response = self.client.get('/query/{}?embed=1'.format(self.file_path))
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn('查询条件', html)
        self.assertIn('查询结果', html)
        self.assertIn('project-switcher', html)
        self.assertNotIn('class="app-sidebar"', html)
        self.assertNotIn('type-badge', html)
        self.assertNotIn('>SELECT<', html)

    def test_sidebar_parameter_still_supports_explicit_embed_sidebar(self):
        response = self.client.get('/query/{}?embed=1&sidebar=1'.format(self.file_path))
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn('class="app-sidebar"', html)
        self.assertNotIn('project-switcher', html)

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

    def test_required_conditions_are_validated_before_database_query(self):
        form = QueryForm()
        form.query_type = 'select'
        form.sql = "SELECT '{keyword}'"
        form.params = [QueryParam('keyword', '关键词', required=True)]
        with patch('web_server.get_form_from_path', return_value=(form, 'forms/test.qry', '/tmp/test.qry')):
            response = self.client.post('/api/query', json={
                'file_path': 'forms/test.qry',
                'params': {'keyword': ''}
            })
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()['error'], '请填写完整的查询条件。')

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

    def test_allow_custom_false_rejects_unconfirmed_value_via_web_route(self):
        """P1-1 服务端校验：allow_custom=false 时未点选的值应被拒绝。"""
        form = QueryForm()
        form.query_type = 'select'
        form.sql = "SELECT '{doctor}'"
        form.params = [QueryParam('doctor', '医生', 'select', ['全部', '内科'],
                                   allow_custom=False)]
        with patch('web_server.get_form_from_path', return_value=(form, 'forms/test.qry', '/tmp/test.qry')):
            response = self.client.post('/api/query', json={
                'file_path': 'forms/test.qry',
                'params': {'doctor': '未知科室'}
            })
        self.assertEqual(response.status_code, 400,
                         'allow_custom=false + 未知值应返回 400')

    def test_allow_custom_true_accepts_custom_value_via_web_route(self):
        """P1-1 服务端校验：allow_custom=true 时自定义值应被接受并完成查询。"""
        manager = type('M', (), {
            'get_web_config': lambda self: {'query_timeout': 60, 'max_rows': 5000},
            'execute_query_limited': lambda self, sql, **kw: (['r'], [['x']], False),
        })()
        form = QueryForm()
        form.query_type = 'select'
        form.sql = "SELECT '{doctor}'"
        form.params = [QueryParam('doctor', '医生', 'select', ['全部'],
                                   allow_custom=True)]
        with patch('web_server.get_form_from_path', return_value=(form, 'forms/test.qry', '/tmp/test.qry')), \
             patch('web_server.DBManager', return_value=manager):
            response = self.client.post('/api/query', json={
                'file_path': 'forms/test.qry',
                'params': {'doctor': '自定义医生名'}
            })
        self.assertEqual(response.status_code, 200,
                         'allow_custom=true + 自定义值应返回 200')


class ExcelCopyTests(unittest.TestCase):
    def test_query_info_sheet_uses_business_labels(self):
        import openpyxl

        descriptor, path = tempfile.mkstemp(suffix='.xlsx')
        os.close(descriptor)
        try:
            export_to_excel(
                path, ['编号', '姓名'], [[1, '张三']],
                form_title='每日体检人员明细', form_desc='测试说明',
                elapsed=0.3, params_info=[('开始日期', '2026-08-12')]
            )
            # Windows + Python 3.7 的 read_only 工作簿可能延迟释放 ZipFile 句柄，
            # 使临时 xlsx 无法删除；普通读取模式可在 close() 后确定性释放文件。
            workbook = openpyxl.load_workbook(path, read_only=False, data_only=True)
            try:
                sheet = workbook['查询信息']
                labels = [sheet.cell(row=index, column=1).value for index in range(1, 9)]
            finally:
                workbook.close()
                del workbook
        finally:
            if os.path.exists(path):
                os.remove(path)

        self.assertEqual(
            labels,
            ['查询项目', '项目说明', '查询时间', '导出记录数', '字段数', '查询耗时', None, '—— 查询条件 ——']
        )


if __name__ == '__main__':
    unittest.main()
