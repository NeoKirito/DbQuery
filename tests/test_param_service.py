# -*- coding: utf-8 -*-
import datetime
import os
import tempfile
import unittest

from core.sql_safety import contains_sql_keyword, normalize_sql_for_safety, sql_tokens_for_safety
from core.param_service import (
    OptionsLoadError, ParameterError, QueryConfigurationError, RequiredParameterError,
    dynamic_options, load_options, merge_options, normalize_params, resolve_default,
    validate_options_sql
)
from core.query_service import build_final_sql
from form_parser import FormParser, QueryForm, QueryParam


class FakeOptionsManager:
    def __init__(self, rows=None, error=None):
        self.rows = rows or []
        self.error = error
        self.calls = []

    def execute_query_limited(self, sql, query_timeout, max_rows, query_type):
        self.calls.append((sql, query_timeout, max_rows, query_type))
        if self.error:
            raise self.error
        return ['ID', 'Name'], self.rows, False


class ParamServiceTests(unittest.TestCase):
    def parse_form(self, content):
        handle, path = tempfile.mkstemp(suffix='.qry')
        try:
            with os.fdopen(handle, 'w', encoding='utf-8') as form_file:
                form_file.write(content)
            return FormParser.parse_file(path)
        finally:
            if os.path.exists(path):
                os.remove(path)

    def unified_form(self):
        form = QueryForm()
        form.sql = (
            "SELECT '{text}' AS T, '{date}' AS D, '{datetime}' AS DT, "
            "'{number}' AS N, '{checkbox}' AS C, '{radio}' AS R, "
            "'{hidden}' AS H, '{select}' AS S, '{textarea}' AS TA"
        )
        form.params = [
            QueryParam('text', '文本'),
            QueryParam('date', '日期', 'date'),
            QueryParam('datetime', '日期时间', 'datetime'),
            QueryParam('number', '数量', 'number'),
            QueryParam('checkbox', '启用', 'checkbox'),
            QueryParam('radio', '性别', 'radio', ['M', 'F']),
            QueryParam('hidden', '来源', 'hidden', default='PEIS'),
            QueryParam('select', '医生', 'select', ['全部'], default='全部'),
            QueryParam('textarea', '备注', 'textarea'),
        ]
        return form

    def test_existing_static_select_and_new_dynamic_attributes_parse(self):
        form = self.parse_form('''
[params]
status = 状态 | select:全部,启用,禁用 | 全部
doctor = 医生 | select | | searchable | allow_custom=true | options_sql=SELECT DoctorID, DoctorName FROM Doctor WHERE Enabled=1
[sql]
SELECT 1
''')
        status, doctor = form.params
        self.assertEqual(status.options, ['全部', '启用', '禁用'])
        self.assertEqual(status.options_sql, '')
        self.assertEqual(doctor.ptype, 'select')
        self.assertEqual(doctor.options, [])
        self.assertTrue(doctor.searchable)
        self.assertTrue(doctor.allow_custom)
        self.assertEqual(doctor.options_sql, 'SELECT DoctorID, DoctorName FROM Doctor WHERE Enabled=1')

    def test_defaults_are_deterministic_for_today(self):
        now = datetime.datetime(2026, 8, 17, 9, 8, 7)
        self.assertEqual(resolve_default(QueryParam('d', '日期', 'date', default='{today}'), now), '2026-08-17')
        self.assertEqual(resolve_default(QueryParam('dt', '时间', 'datetime', default='{today}'), now), '2026-08-17 09:08:07')
        self.assertEqual(resolve_default(QueryParam('t', '文本', 'text', default='{today}'), now), '2026-08-17')

    def test_desktop_and_web_raw_values_normalize_to_identical_params_and_sql(self):
        form = self.unified_form()
        options = {'select': [
            {'value': '全部', 'label': '全部'},
            {'value': '1032', 'label': '张医生'},
        ]}
        desktop_values = {
            'text': "O'Brien 中文", 'date': '2026-08-17',
            'datetime': '2026-08-17 09:08:07', 'number': '-10.50',
            'checkbox': '1', 'radio': 'F', 'hidden': 'tampered',
            'select': '1032', 'textarea': '第一行\n第二行', 'ignored': 'not-used'
        }
        web_values = dict(desktop_values)
        web_values['datetime'] = '2026-08-17T09:08:07'
        web_values['checkbox'] = True
        web_params = normalize_params(form, web_values, options_by_name=options)
        desktop_params = normalize_params(form, desktop_values, options_by_name=options)
        self.assertEqual(desktop_params, web_params)
        self.assertEqual(desktop_params['hidden'], 'PEIS')
        self.assertNotIn('ignored', desktop_params)
        self.assertEqual(
            build_final_sql(form, desktop_params, already_normalized=True),
            build_final_sql(form, web_params, already_normalized=True)
        )
        self.assertIn("O''Brien 中文", build_final_sql(form, web_params, already_normalized=True))

    def test_required_and_number_validation_are_consistent(self):
        form = QueryForm()
        form.params = [
            QueryParam('keyword', '关键词', required=True),
            QueryParam('active', '启用', 'checkbox', required=True),
            QueryParam('count', '数量', 'number'),
        ]
        with self.assertRaises(RequiredParameterError):
            normalize_params(form, {'keyword': '', 'active': '0', 'count': '2'})
        with self.assertRaises(ParameterError):
            normalize_params(form, {'keyword': 'ok', 'active': '1', 'count': '1e3'})
        self.assertEqual(
            normalize_params(form, {'keyword': 'ok', 'active': '1', 'count': '12.30'}),
            {'keyword': 'ok', 'active': '1', 'count': '12.30'}
        )

    def test_select_rejects_unconfirmed_search_text_without_allow_custom(self):
        form = QueryForm()
        form.params = [QueryParam('department', '科室', 'select', ['内科', '外科'])]
        with self.assertRaises(ParameterError):
            normalize_params(form, {'department': '内'})
        form.params[0].allow_custom = True
        self.assertEqual(normalize_params(form, {'department': '内'}), {'department': '内'})

    def test_dynamic_options_normalize_single_and_double_columns_and_merge_in_order(self):
        param = QueryParam('doctor', '医生', 'select', ['全部'], options_sql='SELECT ID, Name FROM Doctor')
        manager = FakeOptionsManager(rows=[
            [None, '忽略'], ['1001', '张医生'], ['1001', '重复医生'], ['1002', None]
        ])
        self.assertEqual(dynamic_options(param, manager), [
            {'value': '1001', 'label': '张医生'},
            {'value': '1002', 'label': '1002'},
        ])
        self.assertEqual(load_options(param, manager), [
            {'value': '全部', 'label': '全部'},
            {'value': '1001', 'label': '张医生'},
            {'value': '1002', 'label': '1002'},
        ])
        self.assertEqual(manager.calls[0][1:], (10, 1000, 'select'))
        single = QueryParam('department', '科室', 'select', options_sql='SELECT Department FROM Employee')
        single_manager = FakeOptionsManager(rows=[['内科'], ['内科'], ['外科']])
        self.assertEqual(dynamic_options(single, single_manager), [
            {'value': '内科', 'label': '内科'}, {'value': '外科', 'label': '外科'}
        ])

    def test_dynamic_options_failure_does_not_change_static_fallback_contract(self):
        param = QueryParam('department', '科室', 'select', ['全部'], options_sql='SELECT Department FROM Employee')
        with self.assertRaises(OptionsLoadError):
            load_options(param, FakeOptionsManager(error=RuntimeError('database unavailable')))
        self.assertEqual(merge_options(['全部']), [{'value': '全部', 'label': '全部'}])

    def test_options_sql_rejects_write_operations_and_multiple_statements(self):
        self.assertEqual(validate_options_sql('SELECT Department FROM Employee'), (True, 'OK'))
        self.assertFalse(validate_options_sql('UPDATE Employee SET Department = 1')[0])
        self.assertFalse(validate_options_sql('SELECT 1; DELETE FROM Employee')[0])
        self.assertFalse(validate_options_sql('EXEC dbo.usp_ListDoctors')[0])

    def test_options_sql_rejects_select_into_all_identifier_forms(self):
        """P0-1 验收：INTO 各种 SQL Server 标识符形式应全部被拒绝。"""
        bad_sqls = [
            # 普通、schema-qualified、方括号、双引号、临时表等所有标识符形式。
            'SELECT 1 INTO TableName',
            'SELECT 1 INTO dbo.TableName',
            'SELECT 1 INTO [TableName]',
            'SELECT 1 INTO [dbo].[TableName]',
            'SELECT 1 INTO "TableName"',
            'SELECT 1 INTO "dbo"."TableName"',
            'SELECT 1 INTO #TempTable',
            'SELECT 1 INTO ##GlobalTempTable',
            # 注释分隔和跨行形式。
            'SELECT 1 INTO/**/"TableName"',
            'SELECT 1 INTO/**/[TableName]',
            'SELECT 1 INTO/**/#TempTable',
            'SELECT 1\nINTO/**/\n"TableName"',
            # 大小写变化与多余空白。
            'select 1 into #tmp',
            'SELECT 1 INTO [Schema].[Table]',
            'SELECT 1\nINTO  [AnotherTable]',
            'SELECT  1  INTO  ##GlobalTemp',
        ]
        for sql in bad_sqls:
            ok, reason = validate_options_sql(sql)
            self.assertFalse(ok, msg='\u5e94拒绝但通过： ' + repr(sql))

    def test_options_sql_normal_select_still_passes_after_into_fix(self):
        """P0-1 回归：合法 SELECT 不应受影响。"""
        good_sqls = [
            'SELECT ID, Name FROM Doctor',
            'SELECT ID, Name FROM Doctor WHERE Enabled=1 ORDER BY Name',
            'SELECT DISTINCT Department FROM Employee WHERE Department IS NOT NULL',
            'SELECT CASE WHEN 1=1 THEN 1 ELSE 0 END AS Flag FROM T',
            # INTO 出现在字符串、quoted identifier、方括号或注释中均不是 SQL keyword。
            "SELECT 'INTO #Temp' AS Example",
            "SELECT 'text INTO Table' AS Example",
            'SELECT [INTO] FROM SomeTable',
            'SELECT "INTO" FROM SomeTable',
            'SELECT INTOCount FROM SomeTable',
            'SELECT SomeINTOValue FROM SomeTable',
            'SELECT ID /* INTO #Temp */ FROM Doctor',
        ]
        for sql in good_sqls:
            ok, reason = validate_options_sql(sql)
            self.assertTrue(ok, msg='\u5e94通过但被拒绝（' + reason + '\uff09： ' + repr(sql))

    def test_sql_safety_normalization_preserves_comment_token_separation(self):
        self.assertEqual(
            normalize_sql_for_safety('SELECT 1 INTO/**/#DBQuery_Options_Test'),
            'SELECT 1 INTO #DBQuery_Options_Test'
        )
        self.assertEqual(
            normalize_sql_for_safety('SELECT 1 INTO /* comment */ #DBQuery_Options_Test'),
            'SELECT 1 INTO   #DBQuery_Options_Test'
        )
        self.assertEqual(
            normalize_sql_for_safety('SELECT 1\nINTO/**/\n#DBQuery_Options_Test'),
            'SELECT 1\nINTO \n#DBQuery_Options_Test'
        )

    def test_form_and_options_sql_reject_comment_separated_select_into_variants(self):
        blocked = [
            'SELECT 1 INTO/**/#DBQuery_Options_Test',
            'SELECT 1 INTO/**/##DBQuery_Options_Test',
            'SELECT 1 INTO/**/[DBQuery_Options_Test]',
            'SELECT 1 INTO/**/[dbo].[DBQuery_Options_Test]',
            'SELECT 1 INTO /* comment */ #DBQuery_Options_Test',
            'SELECT 1\nINTO/**/\n#DBQuery_Options_Test',
            'select 1 into/**/[dbo].[DBQuery_Options_Test]',
            'SELECT 1 INTO/**/"DBQuery_Options_Test"',
        ]
        for sql in blocked:
            with self.subTest(sql=sql):
                self.assertFalse(FormParser.is_safe_sql(sql, 'select')[0])
                self.assertFalse(validate_options_sql(sql)[0])

    def test_token_scanner_detects_only_executable_into_keyword(self):
        self.assertTrue(contains_sql_keyword('SELECT 1 INTO "TableName"', 'INTO'))
        self.assertTrue(contains_sql_keyword('SELECT 1 INTO/**/#TempTable', 'into'))
        self.assertFalse(contains_sql_keyword("SELECT 'INTO #Temp' AS Example", 'INTO'))
        self.assertFalse(contains_sql_keyword('SELECT [INTO] FROM SomeTable', 'INTO'))
        self.assertFalse(contains_sql_keyword('SELECT "INTO" FROM SomeTable', 'INTO'))
        self.assertFalse(contains_sql_keyword('SELECT ID /* INTO #Temp */ FROM Doctor', 'INTO'))
        self.assertNotIn('INTO', sql_tokens_for_safety('SELECT INTOCount, SomeINTOValue FROM T'))

    def test_safe_selects_with_comments_remain_allowed(self):
        allowed = [
            'SELECT ID, Name FROM Doctor',
            'SELECT DISTINCT Department FROM Employee',
            'SELECT ID /* harmless comment */, Name FROM Doctor',
            'SELECT ID FROM Doctor /* trailing comment */',
        ]
        for sql in allowed:
            with self.subTest(sql=sql):
                self.assertEqual(FormParser.is_safe_sql(sql, 'select'), (True, 'OK'))
                self.assertEqual(validate_options_sql(sql), (True, 'OK'))

    def test_unknown_or_unresolved_sql_placeholders_raise_configuration_error(self):
        form = QueryForm()
        form.params = [QueryParam('known', '已知参数')]
        form.sql = "SELECT '{known}', '{missing}'"
        with self.assertRaises(QueryConfigurationError):
            build_final_sql(form, {'known': 'ok'})


if __name__ == '__main__':
    unittest.main()
