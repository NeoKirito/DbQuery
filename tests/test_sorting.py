# -*- coding: utf-8 -*-
"""
表单与分组统一排序测试
验证：
1. natural_sort_key 自然语言数字排序算法
2. [meta] 中的 order / sort / sort_order / seq 属性解析与排序
3. config.ini 中的 [groups] order 配置优先级
4. FormParser 与 query_service (Web端) 的排序结果 100% 一致
5. FormEditorDialog 对 order 属性的加载、修改、校验与持久化
"""
import os
import shutil
import tempfile
import unittest
from collections import OrderedDict

from PyQt5.QtWidgets import QApplication

from form_parser import FormParser, QueryForm
from core.query_service import load_all_forms
from widgets.form_editor import FormEditorDialog

app = QApplication.instance() or QApplication([])


class SortingTests(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.forms_dir = os.path.join(self.temp_dir, 'forms')
        os.makedirs(self.forms_dir, exist_ok=True)
        self.config_path = os.path.join(self.temp_dir, 'config.ini')

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _create_qry(self, subfolder, filename, title, order=None, group_order=None, web_enabled=True):
        grp_dir = os.path.join(self.forms_dir, subfolder) if subfolder else self.forms_dir
        os.makedirs(grp_dir, exist_ok=True)
        qry_path = os.path.join(grp_dir, filename if filename.endswith('.qry') else filename + '.qry')
        lines = ["[meta]", f"title = {title}"]
        if order is not None:
            lines.append(f"order = {order}")
        if group_order is not None:
            lines.append(f"group_order = {group_order}")
        lines.append(f"web_enabled = {'true' if web_enabled else 'false'}")
        lines.extend(["[params]", "[sql]", "SELECT 1"])
        with open(qry_path, 'w', encoding='utf-8') as f:
            f.write('\n'.join(lines) + '\n')
        return qry_path

    def test_natural_sort_key(self):
        """测试自然语言排序：数字片段按数值比较，避免 ASCII 字典序混乱"""
        items = [
            '11 - 副本 (10)',
            '11 - 副本 (2)',
            '11 - 副本 (1)',
            '11 - 副本 (20)',
            '11 - 副本',
        ]
        sorted_items = sorted(items, key=FormParser.natural_sort_key)
        expected = [
            '11 - 副本',
            '11 - 副本 (1)',
            '11 - 副本 (2)',
            '11 - 副本 (10)',
            '11 - 副本 (20)',
        ]
        self.assertEqual(sorted_items, expected)

    def test_form_order_priority_and_fallback(self):
        """测试表单排序：显式 order 权重优先，未指定时按自然语言标题排序"""
        self._create_qry('示例', 'b.qry', '表单B', order=10)
        self._create_qry('示例', 'a.qry', '表单A', order=2)
        self._create_qry('示例', 'c.qry', '表单C', order=1)
        self._create_qry('示例', 'd2.qry', '表单D (2)')  # 无 order，按自然标题
        self._create_qry('示例', 'd10.qry', '表单D (10)') # 无 order，按自然标题

        forms = FormParser.load_forms_from_dir(self.forms_dir)['示例']
        titles = [f.title for f in forms]

        # 预期：order=1(C), order=2(A), order=10(B), 随后无order的自然排序 D(2), D(10)
        expected = ['表单C', '表单A', '表单B', '表单D (2)', '表单D (10)']
        self.assertEqual(titles, expected)

    def test_form_order_aliases(self):
        """测试兼容 sort, sort_order, seq 别名"""
        grp_dir = os.path.join(self.forms_dir, '别名测试')
        os.makedirs(grp_dir, exist_ok=True)
        with open(os.path.join(grp_dir, 'f1.qry'), 'w', encoding='utf-8') as f:
            f.write("[meta]\ntitle = F1\nsort = 5\n[params]\n[sql]\nSELECT 1\n")
        with open(os.path.join(grp_dir, 'f2.qry'), 'w', encoding='utf-8') as f:
            f.write("[meta]\ntitle = F2\nsort_order = 2\n[params]\n[sql]\nSELECT 1\n")
        with open(os.path.join(grp_dir, 'f3.qry'), 'w', encoding='utf-8') as f:
            f.write("[meta]\ntitle = F3\nseq = 8\n[params]\n[sql]\nSELECT 1\n")

        forms = FormParser.load_forms_from_dir(self.forms_dir)['别名测试']
        titles = [f.title for f in forms]
        self.assertEqual(titles, ['F2', 'F1', 'F3'])

    def test_group_order_from_config(self):
        """测试 config.ini 中 [groups] order 配置置顶"""
        self._create_qry('系统', 'sys.qry', '系统表单')
        self._create_qry('报表', 'rep.qry', '报表表单')
        self._create_qry('11 - 副本 (2)', 'f2.qry', '表单2')
        self._create_qry('11 - 副本 (10)', 'f10.qry', '表单10')
        self._create_qry('11', 'f11.qry', '表单11')

        # 写入 config.ini 指定: 报表, 11 优先
        with open(self.config_path, 'w', encoding='utf-8') as f:
            f.write("[groups]\norder = 报表, 11\n")

        parsed = FormParser.load_forms_from_dir(self.forms_dir, config_path=self.config_path)
        group_keys = list(parsed.keys())

        # 报表, 11 置顶；剩下的按自然排序：11 - 副本 (2), 11 - 副本 (10), 系统
        expected = ['报表', '11', '11 - 副本 (2)', '11 - 副本 (10)', '系统']
        self.assertEqual(group_keys, expected)

    def test_desktop_and_web_parity(self):
        """测试桌面端 FormParser 与 Web 端 query_service.load_all_forms 排序完全一致"""
        self._create_qry('Z组', 'z2.qry', 'Z2', order=2)
        self._create_qry('Z组', 'z1.qry', 'Z1', order=1)
        self._create_qry('A组', 'a.qry', 'A', order=100)
        self._create_qry('10_数字组', 'num10.qry', 'Num10')
        self._create_qry('2_数字组', 'num2.qry', 'Num2')

        desktop_data = FormParser.load_forms_from_dir(self.forms_dir)
        web_data = load_all_forms(self.forms_dir)

        # 1. 分组顺序完全一致
        desktop_groups = list(desktop_data.keys())
        web_groups = list(web_data.keys())
        self.assertEqual(desktop_groups, web_groups)

        # 2. 每个分组内的表单顺序完全一致
        for grp in desktop_groups:
            desktop_titles = [f.title for f in desktop_data[grp]]
            web_titles = [f['title'] for f in web_data[grp]]
            self.assertEqual(desktop_titles, web_titles)

    def test_form_editor_order_support(self):
        """测试表单编辑器对 order 属性的加载、编辑、持久化与校验"""
        qry_path = self._create_qry('示例', 'test_order.qry', '测试排序', order=5)
        form = FormParser.parse_file(qry_path, forms_root=self.forms_dir)

        dlg = FormEditorDialog(form, self.forms_dir)
        self.assertEqual(dlg.order_edit.text(), '5')

        # 修改 order 为 1
        dlg.order_edit.setText('1')
        self.assertIn('order = 1', dlg.editor.toPlainText())

        # 保存
        ok = dlg._do_save(qry_path)
        self.assertTrue(ok)

        # 重新读取验证
        form = FormParser.parse_file(qry_path, forms_root=self.forms_dir)
        self.assertEqual(form.order, 1.0)

        # 测试校验：输入非法字符串
        dlg.order_edit.setText('abc')
        is_valid, errors, _ = dlg.validate_form(dlg.editor.toPlainText())
        self.assertFalse(is_valid)
        self.assertTrue(any('order' in err.lower() or '无效' in err for err in errors))

        # 测试清空 order
        dlg.order_edit.setText('')
        self.assertNotIn('order =', dlg.editor.toPlainText())
        ok = dlg._do_save(qry_path)
        self.assertTrue(ok)
        form2 = FormParser.parse_file(qry_path, forms_root=self.forms_dir)
        self.assertIsNone(form2.order)


if __name__ == '__main__':
    unittest.main()
