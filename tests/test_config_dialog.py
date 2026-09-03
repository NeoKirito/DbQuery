# -*- coding: utf-8 -*-
import os
import sys
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from PyQt5.QtWidgets import QApplication, QGroupBox, QLabel

from widgets.config_dialog import ConfigDialog


class DialogManager:
    def __init__(self):
        self.saved_db_config = None
        self.saved_integration_config = None
        self.integration_config = {
            'enabled': True,
            'shared_key': 'x' * 48,
            'ticket_ttl_seconds': 45,
            'max_clock_skew_seconds': 50,
            'frontend_enabled': True,
            'frontend_allowed_origins': ['https://legacy.example.com'],
            'frontend_embed_enabled': True,
            'frontend_embed_allowed_origins': ['http://192.168.0.51:8080'],
            'frontend_embed_session_minutes': 120,
            'frame_ancestors': ['http://192.168.0.51:8080'],
        }

    def get_db_config(self):
        return {
            'server': 'localhost',
            'port': '1433',
            'database': 'master',
            'driver': 'ODBC Driver 17 for SQL Server',
            'trusted_connection': 'no',
            'username': 'sa',
            'password': '',
        }

    def get_integration_config(self):
        return dict(self.integration_config)

    def set_db_config(self, config):
        self.saved_db_config = config

    def set_integration_config(self, config):
        self.saved_integration_config = config


class ConfigDialogTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def create_dialog(self):
        manager = DialogManager()
        with patch('db_manager.DBManager.list_drivers', return_value=[]):
            dialog = ConfigDialog(manager)
        return manager, dialog

    def test_embed_section_only_shows_required_controls_and_clear_help(self):
        _, dialog = self.create_dialog()
        group_titles = [group.title() for group in dialog.findChildren(QGroupBox)]
        help_text = ' '.join(label.text() for label in dialog.findChildren(QLabel))

        self.assertIn('前端无感登录', group_titles)
        self.assertTrue(dialog.frontend_embed_enabled_check.isChecked())
        self.assertEqual(
            dialog.frontend_address_edit.text(), '192.168.0.51:8080'
        )
        self.assertIn('自动补全 HTTP 协议', help_text)
        self.assertIn('同步所有前端授权配置', help_text)
        self.assertFalse(hasattr(dialog, 'integration_key_edit'))
        self.assertFalse(hasattr(dialog, 'frontend_integration_enabled_check'))
        dialog.close()

    def test_build_config_normalizes_one_address_and_syncs_all_origin_fields(self):
        _, dialog = self.create_dialog()
        dialog.frontend_address_edit.setText('192.168.0.39:8080')
        config = dialog._build_integration_config()

        self.assertTrue(config['enabled'])
        self.assertEqual(config['shared_key'], 'x' * 48)
        self.assertTrue(config['frontend_enabled'])
        self.assertEqual(config['frontend_embed_session_minutes'], 120)
        self.assertEqual(config['frontend_allowed_origins'], 'http://192.168.0.39:8080')
        self.assertEqual(config['frontend_embed_allowed_origins'], 'http://192.168.0.39:8080')
        self.assertEqual(config['frame_ancestors'], config['frontend_embed_allowed_origins'])
        dialog.close()

    def test_https_address_keeps_its_protocol(self):
        _, dialog = self.create_dialog()
        dialog.frontend_address_edit.setText('https://192.168.0.39:8443')

        config = dialog._build_integration_config()

        self.assertEqual(config['frontend_allowed_origins'], 'https://192.168.0.39:8443')
        self.assertEqual(config['frontend_embed_allowed_origins'], 'https://192.168.0.39:8443')
        self.assertEqual(config['frame_ancestors'], 'https://192.168.0.39:8443')
        dialog.close()

    def test_save_rejects_enabled_embed_without_a_valid_frontend_origin(self):
        manager, dialog = self.create_dialog()
        dialog.frontend_address_edit.setText(
            'http://192.168.0.51:8080/#/director/reportStatistics'
        )
        with patch('widgets.config_dialog.QMessageBox.warning') as warning:
            dialog._save()

        warning.assert_called_once()
        self.assertIsNone(manager.saved_integration_config)
        dialog.close()


if __name__ == '__main__':
    unittest.main()
