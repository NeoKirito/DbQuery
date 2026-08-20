# -*- coding: utf-8 -*-
import os
import tempfile
import unittest

from core.query_service import load_all_forms
from db_manager import DBManager
from form_parser import FormParser


class FakeCursor:
    def __init__(self, found=True):
        self.found = found
        self.calls = []
        self.closed = False

    def execute(self, sql, *params):
        self.calls.append((sql, params))

    def fetchone(self):
        return (1,) if self.found else None

    def close(self):
        self.closed = True


class FakeConnection:
    def __init__(self, cursor):
        self.cursor_instance = cursor
        self.timeout = None
        self.closed = False

    def cursor(self):
        return self.cursor_instance

    def close(self):
        self.closed = True


class AuthenticationTests(unittest.TestCase):
    def make_manager(self, found=True):
        cursor = FakeCursor(found=found)
        connection = FakeConnection(cursor)
        manager = DBManager.__new__(DBManager)
        manager._open_connection = lambda connect_timeout=10: connection
        return manager, connection, cursor

    def test_authenticate_user_uses_bound_values_and_enabled_not_deleted_filter(self):
        manager, connection, cursor = self.make_manager(found=True)
        self.assertTrue(manager.authenticate_user('operator01', 'secret-value'))
        self.assertEqual(connection.timeout, 10)
        self.assertTrue(connection.closed)
        self.assertTrue(cursor.closed)
        sql, params = cursor.calls[0]
        self.assertIn('czybm = ?', sql)
        self.assertIn('[pass] = ?', sql)
        self.assertIn('czyzt = ?', sql)
        self.assertIn('deleted = ?', sql)
        self.assertNotIn('operator01', sql)
        self.assertNotIn('secret-value', sql)
        self.assertEqual(params, ('operator01', 'secret-value', '启用', '0'))

    def test_authenticate_user_rejects_empty_or_not_found_credentials(self):
        manager, connection, cursor = self.make_manager(found=False)
        self.assertFalse(manager.authenticate_user('operator01', 'bad-password'))
        self.assertTrue(connection.closed)
        self.assertTrue(cursor.closed)

        manager, connection, cursor = self.make_manager(found=True)
        self.assertFalse(manager.authenticate_user('', 'secret'))
        self.assertFalse(manager.authenticate_user('operator01', ''))
        self.assertFalse(cursor.calls)


class DesktopLoginDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PyQt5.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def test_login_dialog_accepts_only_authenticated_user(self):
        from unittest.mock import patch
        from widgets.login_dialog import LoginDialog

        manager = type('M', (), {
            'authenticate_user': lambda self, username, password: username == 'tester' and password == 'secret',
            'load_config': lambda self: None,
        })()
        with patch('widgets.login_dialog.DBManager', return_value=manager):
            dialog = LoginDialog()
            dialog.username_edit.setText('tester')
            dialog.password_edit.setText('secret')
            dialog._attempt_login()
            self.assertEqual(dialog.username, 'tester')
            self.assertEqual(dialog.result(), dialog.Accepted)
            dialog.close()


class FormEditorWebPermissionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PyQt5.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def test_editor_writes_explicit_web_enabled_value(self):
        from widgets.form_editor import FormEditorDialog
        with tempfile.TemporaryDirectory() as forms_dir:
            dialog = FormEditorDialog(None, forms_dir)
            content = '[meta]\ntitle = 测试\n[params]\n[sql]\nSELECT 1\n'
            dialog.web_enabled_check.setChecked(True)
            self.assertIn('web_enabled = true', dialog._apply_web_enabled(content))
            dialog.web_enabled_check.setChecked(False)
            self.assertIn('web_enabled = false', dialog._apply_web_enabled(content))
            dialog.close()


class WebVisibilityTests(unittest.TestCase):
    def test_default_denies_web_and_true_explicitly_allows(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            forms_dir = os.path.join(temp_dir, 'forms')
            os.makedirs(forms_dir)
            with open(os.path.join(forms_dir, 'hidden.qry'), 'w', encoding='utf-8') as form_file:
                form_file.write('[meta]\ntitle = 内部表单\n[params]\n[sql]\nSELECT 1\n')
            with open(os.path.join(forms_dir, 'public.qry'), 'w', encoding='utf-8') as form_file:
                form_file.write('[meta]\ntitle = Web 表单\nweb_enabled = true\n[params]\n[sql]\nSELECT 1\n')

            hidden = FormParser.parse_file(os.path.join(forms_dir, 'hidden.qry'))
            public = FormParser.parse_file(os.path.join(forms_dir, 'public.qry'))
            self.assertFalse(hidden.web_enabled)
            self.assertTrue(public.web_enabled)
            web_forms = load_all_forms(forms_dir, web_only=True)
            titles = [item['title'] for items in web_forms.values() for item in items]
            self.assertEqual(titles, ['Web 表单'])


if __name__ == '__main__':
    unittest.main()
