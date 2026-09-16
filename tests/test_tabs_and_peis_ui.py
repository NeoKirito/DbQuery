# -*- coding: utf-8 -*-
import os
import tempfile
import unittest
from unittest.mock import patch

import web_server


class TabsAndPeisUiTests(unittest.TestCase):
    def setUp(self):
        web_server.app.config['TESTING'] = True
        self.client = web_server.app.test_client()
        self.old_base_dir = web_server.BASE_DIR
        self.old_forms_dir = web_server.FORMS_DIR
        self.temp_dir = tempfile.TemporaryDirectory()
        self.forms_dir = os.path.join(self.temp_dir.name, 'forms')
        os.makedirs(self.forms_dir, exist_ok=True)

        self.form_path = os.path.join(self.forms_dir, 'daily_stat.qry')
        with open(self.form_path, 'w', encoding='utf-8') as f:
            f.write("""[meta]
title = 每日加项统计
group = 体检报表
type = select
web_enabled = true

[params]
start_date = 开始日期 | date | {today} | required
dept = 科室 | select:全部,内科,外科 | 全部

[sql]
SELECT 1 AS Result
""")

        web_server.BASE_DIR = self.temp_dir.name
        web_server.FORMS_DIR = self.forms_dir
        self.file_path = 'forms/daily_stat.qry'
        self._authenticate()

    def tearDown(self):
        web_server.BASE_DIR = self.old_base_dir
        web_server.FORMS_DIR = self.old_forms_dir
        self.temp_dir.cleanup()

    def _authenticate(self):
        with self.client.session_transaction() as session_state:
            session_state['auth_user'] = 'tester'
            session_state['csrf_token'] = 'test-csrf-token'

    def test_index_page_renders_tabbar_with_welcome_tab(self):
        response = self.client.get('/')
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn('app-tabbar-container', html)
        self.assertIn('id="app-tabbar"', html)
        self.assertIn('data-tab-id="tab-welcome"', html)
        self.assertIn('tab-panes-container', html)
        self.assertIn('id="pane-tab-welcome"', html)
        self.assertIn('每日加项统计', html)

    def test_query_page_renders_multi_tabbar_and_reset_button(self):
        response = self.client.get('/query/{}'.format(self.file_path))
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        # Tab bar
        self.assertIn('app-tabbar-container', html)
        self.assertIn('id="app-tabbar"', html)
        self.assertIn('data-tab-id="tab-welcome"', html)
        self.assertIn('data-tab-id="tab-init"', html)
        self.assertIn('每日加项统计', html)
        self.assertIn('class="tab-close"', html)
        # Reset button
        self.assertIn('btn-reset-action', html)
        self.assertIn('resetQueryParams()', html)
        self.assertIn('重置', html)

    def test_embed_mode_renders_clean_tabs_and_embed_classes(self):
        response = self.client.get('/query/{}?embed=1'.format(self.file_path))
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn('embed-mode', html)
        self.assertIn('app-tabbar-container', html)
        self.assertIn('class="tab-item active"', html)
        self.assertIn('btn-primary-action', html)
        self.assertIn('btn-reset-action', html)
        self.assertIn('class="report-home-link"', html)

    def test_stylesheet_contains_peis_theme_and_tab_styles(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        css_path = os.path.join(root, 'static', 'css', 'style.css')
        with open(css_path, encoding='utf-8') as f:
            css = f.read()
        self.assertIn('--peis-primary:', css)
        self.assertIn('.app-tabbar-container', css)
        self.assertIn('.app-tabbar', css)
        self.assertIn('.tab-item', css)
        self.assertIn('.tab-close', css)
        self.assertIn('.btn-primary-action', css)
        self.assertIn('.btn-reset-action', css)
        self.assertIn('.conditions-section', css)
        self.assertIn('.result-section', css)

    def test_javascript_contains_tab_manager_and_reset_functions(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        js_path = os.path.join(root, 'static', 'js', 'app.js')
        with open(js_path, encoding='utf-8') as f:
            js = f.read()
        self.assertIn('var TabManager = {', js)
        self.assertIn('TabManager.init()', js)
        self.assertIn('function resetQueryParams(', js)
        self.assertIn('openReport', js)
        self.assertIn('closeTab', js)
        self.assertIn('activateTab', js)


if __name__ == '__main__':
    unittest.main()
