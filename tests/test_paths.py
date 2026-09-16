# -*- coding: utf-8 -*-
import os
import sys
import unittest
from unittest.mock import patch


class PathsTests(unittest.TestCase):

    def test_unfrozen_paths(self):
        from core.paths import get_app_dir, get_exe_dir, get_config_path, get_forms_dir
        app_dir = get_app_dir()
        self.assertTrue(os.path.isdir(app_dir))
        self.assertEqual(get_config_path(), os.path.join(app_dir, 'config.ini'))
        self.assertEqual(get_forms_dir(), os.path.join(app_dir, 'forms'))

    def test_frozen_nested_dist(self):
        from core.paths import get_app_dir, get_config_path, get_forms_dir
        with patch('sys.frozen', True, create=True):
            with patch('sys.executable', r'C:\Software\DBQuery\dist\DBQuery.exe'):
                app_dir = get_app_dir()
                self.assertEqual(app_dir, r'C:\Software\DBQuery')
                self.assertEqual(get_config_path(), r'C:\Software\DBQuery\config.ini')
                self.assertEqual(get_forms_dir(), r'C:\Software\DBQuery\forms')

    def test_frozen_flat(self):
        from core.paths import get_app_dir, get_config_path, get_forms_dir
        with patch('sys.frozen', True, create=True):
            with patch('sys.executable', r'C:\Software\DBQuery\DBQuery.exe'):
                app_dir = get_app_dir()
                self.assertEqual(app_dir, r'C:\Software\DBQuery')
                self.assertEqual(get_config_path(), r'C:\Software\DBQuery\config.ini')
                self.assertEqual(get_forms_dir(), r'C:\Software\DBQuery\forms')


if __name__ == '__main__':
    unittest.main()
