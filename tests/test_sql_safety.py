# -*- coding: utf-8 -*-
"""SQL 安全性与 # 注释兼容性单元测试。"""
import os
import sys
import unittest

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from core.sql_safety import (
    normalize_sql_for_safety,
    sql_tokens_for_safety,
    convert_hash_comments_to_sql,
    contains_sql_keyword,
)
from form_parser import FormParser


class SqlSafetyHashCommentTest(unittest.TestCase):

    def test_hash_comment_at_start_allows_select(self):
        sql = "# 这是表单首行注释\nSELECT ID, Name FROM Users"
        self.assertEqual(FormParser.is_safe_sql(sql, 'select'), (True, 'OK'))

    def test_hash_comment_without_space_chinese(self):
        sql = "#首行无空格中文注释\nSELECT ID, Name FROM Users"
        self.assertEqual(FormParser.is_safe_sql(sql, 'select'), (True, 'OK'))

    def test_hash_comment_inline_and_multiline(self):
        sql = """
        # 查询说明
        SELECT ID, Name # 字段注释
        FROM Users
        # AND Status = 1
        WHERE 1=1
        #WHERE col = 2
        """
        self.assertEqual(FormParser.is_safe_sql(sql, 'select'), (True, 'OK'))

    def test_hash_comment_with_single_quotes_and_brackets(self):
        sql = "# don't fail this (special bracket) and 'quotes'\nSELECT * FROM Orders"
        clean = normalize_sql_for_safety(sql).strip()
        self.assertTrue(clean.startswith("SELECT * FROM Orders"))
        self.assertNotIn("don't", clean)
        self.assertEqual(FormParser.is_safe_sql(sql, 'select'), (True, 'OK'))

    def test_temp_table_after_into_is_preserved_and_blocked(self):
        # INTO #TempTable 必须被识别为写入临时表并被拒绝
        blocked = [
            "SELECT 1 INTO/**/#Temp",
            "SELECT 1 INTO #Temp",
            "SELECT 1 INTO ##GlobalTemp",
            "SELECT 1 INTO /**/ ##GlobalTemp",
        ]
        for sql in blocked:
            with self.subTest(sql=sql):
                ok, reason = FormParser.is_safe_sql(sql, 'select')
                self.assertFalse(ok)
                self.assertIn("INTO", reason)

    def test_temp_table_in_from_and_join_is_preserved(self):
        sql = "SELECT a.ID FROM #Temp a INNER JOIN #AnotherTemp b ON a.ID = b.ID"
        converted = convert_hash_comments_to_sql(sql)
        self.assertIn("FROM #Temp", converted)
        self.assertIn("JOIN #AnotherTemp", converted)
        self.assertEqual(FormParser.is_safe_sql(sql, 'select'), (True, 'OK'))

    def test_convert_hash_comments_to_sql(self):
        sql = (
            "# 统计信息\n"
            "SELECT ID, '#not_comment' AS Tag\n"
            "# 过滤\n"
            "FROM Users\n"
            "WHERE 1=1\n"
            "#AND Status = 1"
        )
        converted = convert_hash_comments_to_sql(sql)
        self.assertTrue(converted.startswith("-- 统计信息"))
        self.assertIn("'#not_comment'", converted)
        self.assertIn("-- 过滤", converted)
        self.assertIn("--AND Status = 1", converted)
        # 确保不出现未转换的独立 # 行注释
        for line in converted.splitlines():
            line_s = line.strip()
            if line_s:
                self.assertFalse(line_s.startswith('#'), msg=f"未转换的行: {line_s}")

    def test_form_editor_validation_with_hash_comments(self):
        os.environ['QT_QPA_PLATFORM'] = 'offscreen'
        from PyQt5.QtWidgets import QApplication
        from widgets.form_editor import FormEditorDialog
        from form_parser import QueryForm

        _app = QApplication.instance() or QApplication([])
        dialog = FormEditorDialog(None, 'forms')
        content = (
            "[meta]\n"
            "title = 测试查询\n"
            "group = 默认\n\n"
            "[params]\n"
            "dept = 科室 | text | 内科\n\n"
            "[sql]\n"
            "# 这是一个注释带括号 (测试) 和单引号 '测试'\n"
            "SELECT * FROM Doctor WHERE Department = '{dept}'\n"
            "# AND 1=1\n"
        )
        is_valid, errors, warnings = dialog.validate_form(content)
        self.assertTrue(is_valid, msg=f"校验应通过但失败：errors={errors}")
        self.assertEqual(errors, [])
        self.assertEqual(warnings, [])


if __name__ == '__main__':
    unittest.main()
