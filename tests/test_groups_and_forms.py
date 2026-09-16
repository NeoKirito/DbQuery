# -*- coding: utf-8 -*-
"""
分组管理与 forms 物理目录加载单元测试
"""
import os
import shutil
import tempfile
import unittest

from PyQt5.QtWidgets import QApplication
from PyQt5.QtCore import Qt

from form_parser import FormParser, QueryForm
from core.query_service import load_all_forms
from widgets.form_editor import FormEditorDialog
from main import MainWindow

app = QApplication.instance() or QApplication([])


class GroupAndFormLoadingTests(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.forms_dir = os.path.join(self.temp_dir, 'forms')
        os.makedirs(self.forms_dir, exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_load_forms_includes_empty_groups(self):
        """测试 load_forms_from_dir 能正确发现并包含新建的空分组目录"""
        empty_grp1 = os.path.join(self.forms_dir, '新分组A')
        empty_grp2 = os.path.join(self.forms_dir, '财务报表')
        os.makedirs(empty_grp1, exist_ok=True)
        os.makedirs(empty_grp2, exist_ok=True)

        res = FormParser.load_forms_from_dir(self.forms_dir)
        self.assertIn('新分组A', res)
        self.assertIn('财务报表', res)
        self.assertEqual(res['新分组A'], [])
        self.assertEqual(res['财务报表'], [])

    def test_forms_grouped_by_subdirectory_overrides_stale_meta(self):
        """测试放置在子目录中的表单，即使内部 [meta] 写着 group = 默认，也能严格归入物理子目录分组"""
        grp_dir = os.path.join(self.forms_dir, '体检业务')
        os.makedirs(grp_dir, exist_ok=True)
        qry_file = os.path.join(grp_dir, '体检登记查询.qry')

        content = (
            "[meta]\n"
            "title = 体检登记查询\n"
            "group = 默认\n"
            "description = 测试查询\n"
            "[params]\n"
            "[sql]\n"
            "SELECT 1\n"
        )
        with open(qry_file, 'w', encoding='utf-8') as f:
            f.write(content)

        form = FormParser.parse_file(qry_file, forms_root=self.forms_dir)
        self.assertEqual(form.group, '体检业务')

        res = FormParser.load_forms_from_dir(self.forms_dir)
        self.assertIn('体检业务', res)
        self.assertEqual(len(res['体检业务']), 1)
        self.assertEqual(res['体检业务'][0].title, '体检登记查询')
        self.assertEqual(res['体检业务'][0].group, '体检业务')
        self.assertNotIn('默认', res)

    def test_forms_root_fallback(self):
        """测试直接放在 forms 根目录下的文件按 [meta] 或默认归组"""
        root_file1 = os.path.join(self.forms_dir, 'direct1.qry')
        with open(root_file1, 'w', encoding='utf-8') as f:
            f.write("[meta]\ntitle = 显式分组\ngroup = 自定义组\n[params]\n[sql]\nSELECT 1\n")

        root_file2 = os.path.join(self.forms_dir, 'direct2.qry')
        with open(root_file2, 'w', encoding='utf-8') as f:
            f.write("[meta]\ntitle = 无分组\n[params]\n[sql]\nSELECT 1\n")

        f1 = FormParser.parse_file(root_file1, forms_root=self.forms_dir)
        f2 = FormParser.parse_file(root_file2, forms_root=self.forms_dir)
        self.assertEqual(f1.group, '自定义组')
        self.assertEqual(f2.group, '默认')

    def test_form_editor_group_sync(self):
        """测试 FormEditorDialog 预选分组并在保存时自动同步 [meta] group"""
        os.makedirs(os.path.join(self.forms_dir, '财务部'), exist_ok=True)
        dlg = FormEditorDialog(None, self.forms_dir, default_group='财务部')

        self.assertEqual(dlg.group_combo.currentText(), '财务部')
        self.assertIn('group = 财务部', dlg.editor.toPlainText())

        dlg.filename_edit.setText('月度营收')
        save_path = dlg._get_save_path()
        self.assertTrue(save_path.endswith(os.path.join('财务部', '月度营收.qry')))

        ok = dlg._do_save(save_path)
        self.assertTrue(ok)
        self.assertTrue(os.path.exists(save_path))

        saved_form = FormParser.parse_file(save_path, forms_root=self.forms_dir)
        self.assertEqual(saved_form.group, '财务部')

    def test_form_editor_move_group_on_edit(self):
        """测试编辑已有表单并修改 [meta] group 时自动移动文件至新分组目录"""
        old_dir = os.path.join(self.forms_dir, '旧分组')
        os.makedirs(old_dir, exist_ok=True)
        old_path = os.path.join(old_dir, '报表.qry')
        with open(old_path, 'w', encoding='utf-8') as f:
            f.write("[meta]\ntitle = 报表\ngroup = 旧分组\n[params]\n[sql]\nSELECT 1\n")

        form = FormParser.parse_file(old_path, forms_root=self.forms_dir)
        dlg = FormEditorDialog(form, self.forms_dir)

        content = dlg.editor.toPlainText().replace('group = 旧分组', 'group = 新分组B')
        dlg.editor.setPlainText(content)

        new_save_path = dlg._get_save_path()
        self.assertTrue(new_save_path.endswith(os.path.join('新分组B', '报表.qry')))

        ok = dlg._do_save(new_save_path)
        self.assertTrue(ok)
        self.assertTrue(os.path.exists(new_save_path))
        self.assertFalse(os.path.exists(old_path))

    def test_tree_rebuild_with_empty_and_filled_groups(self):
        """测试主窗口树结构在包含空分组和非空分组时正确展示占位符与节点"""
        os.makedirs(os.path.join(self.forms_dir, '空分组'), exist_ok=True)
        filled = os.path.join(self.forms_dir, '日常查询')
        os.makedirs(filled, exist_ok=True)
        with open(os.path.join(filled, '日结.qry'), 'w', encoding='utf-8') as f:
            f.write("[meta]\ntitle = 日结表单\ngroup = 日常查询\n[params]\n[sql]\nSELECT 1\n")

        data = FormParser.load_forms_from_dir(self.forms_dir)
        self.assertIn('空分组', data)
        self.assertIn('日常查询', data)

        win = MainWindow()
        win.form_tree.clear()
        win._rebuild_tree(data)

        top_count = win.form_tree.topLevelItemCount()
        self.assertGreaterEqual(top_count, 2)

        top_names = [win.form_tree.topLevelItem(i).data(0, Qt.UserRole + 1) for i in range(top_count)]
        self.assertIn('空分组', top_names)
        self.assertIn('日常查询', top_names)

        for i in range(top_count):
            item = win.form_tree.topLevelItem(i)
            if item.data(0, Qt.UserRole + 1) == '空分组':
                self.assertEqual(item.childCount(), 1)
                child = item.child(0)
                self.assertEqual(child.data(0, Qt.UserRole), '__placeholder__')
            elif item.data(0, Qt.UserRole + 1) == '日常查询':
                self.assertEqual(item.childCount(), 1)
                child = item.child(0)
                self.assertIsInstance(child.data(0, Qt.UserRole), QueryForm)


if __name__ == '__main__':
    unittest.main()
