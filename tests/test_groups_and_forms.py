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

    def test_directly_copied_directory_and_gbk_encoded_files(self):
        """测试直接复制进 forms 的分组目录与包含 GB18030/GBK 编码的文件能被及时正确识别"""
        copied_group_dir = os.path.join(self.forms_dir, '体检中心')
        os.makedirs(copied_group_dir, exist_ok=True)

        gbk_file = os.path.join(copied_group_dir, '体检汇总表.qry')
        gbk_content = (
            "[meta]\n"
            "title = 体检汇总表（GBK测试）\n"
            "group = 随意默认\n"
            "description = 这是一个GBK编码的表单\n"
            "[params]\n"
            "[sql]\n"
            "SELECT 1\n"
        ).encode('gb18030')

        with open(gbk_file, 'wb') as f:
            f.write(gbk_content)

        data = FormParser.load_forms_from_dir(self.forms_dir)
        self.assertIn('体检中心', data)
        self.assertEqual(len(data['体检中心']), 1)
        self.assertEqual(data['体检中心'][0].title, '体检汇总表（GBK测试）')
        self.assertEqual(data['体检中心'][0].group, '体检中心')

    def test_form_editor_creates_new_group_folder_by_typing(self):
        """测试在新建表单时，直接在下拉框输入全新分组名称，保存时自动创建文件夹并正确归组"""
        dlg = FormEditorDialog(None, self.forms_dir)
        dlg.group_combo.setEditText('全新业务组')
        dlg.filename_edit.setText('体检流水账')

        save_path = dlg._get_save_path()
        self.assertIsNotNone(save_path)
        expected_dir = os.path.join(self.forms_dir, '全新业务组')
        self.assertTrue(os.path.isdir(expected_dir))
        self.assertEqual(save_path, os.path.join(expected_dir, '体检流水账.qry'))

        ok = dlg._do_save(save_path)
        self.assertTrue(ok)
        self.assertEqual(dlg.saved_group, '全新业务组')
        self.assertTrue(os.path.exists(save_path))

        parsed = FormParser.parse_file(save_path, forms_root=self.forms_dir)
        self.assertEqual(parsed.group, '全新业务组')

    def test_no_standalone_new_group_button_in_toolbar(self):
        """测试工具栏中已彻底移除独立的‘新建分组’按钮"""
        from PyQt5.QtWidgets import QPushButton
        win = MainWindow()
        buttons = win.findChildren(QPushButton)
        button_texts = [b.text() for b in buttons]
        self.assertNotIn('新建分组', button_texts)
        self.assertIn('新建表单', button_texts)
        self.assertIn('刷新表单', button_texts)


    def test_form_editor_group_dropdown_in_edit_mode(self):
        """测试在编辑已有表单时，所属分组下拉框正常显示并支持下拉选择与同步"""
        os.makedirs(os.path.join(self.forms_dir, '科室A'), exist_ok=True)
        os.makedirs(os.path.join(self.forms_dir, '科室B'), exist_ok=True)
        form_path = os.path.join(self.forms_dir, '科室A', '检查单.qry')
        with open(form_path, 'w', encoding='utf-8') as f:
            f.write("[meta]\ntitle = 检查单\ngroup = 科室A\n[params]\n[sql]\nSELECT 1\n")

        form = FormParser.parse_file(form_path, forms_root=self.forms_dir)
        dlg = FormEditorDialog(form, self.forms_dir)

        # 检查 group_combo 存在且当前值为 科室A
        self.assertIsNotNone(getattr(dlg, 'group_combo', None))
        self.assertEqual(dlg.group_combo.currentText(), '科室A')

        # 下拉框中包含了所有已有分组
        items = [dlg.group_combo.itemText(i) for i in range(dlg.group_combo.count())]
        self.assertIn('科室A', items)
        self.assertIn('科室B', items)

        # 在下拉框切换到 科室B，验证代码自动同步
        idx = dlg.group_combo.findText('科室B')
        self.assertGreaterEqual(idx, 0)
        dlg.group_combo.setCurrentIndex(idx)
        self.assertIn('group = 科室B', dlg.editor.toPlainText())

        # 保存并验证移动
        save_path = dlg._get_save_path()
        self.assertTrue(save_path.endswith(os.path.join('科室B', '检查单.qry')))
        ok = dlg._do_save(save_path)
        self.assertTrue(ok)
        self.assertTrue(os.path.exists(save_path))
        self.assertFalse(os.path.exists(form_path))

    def test_form_editor_validation_engine(self):
        """测试 FormEditorDialog 的多维度校验引擎"""
        dlg = FormEditorDialog(None, self.forms_dir)

        # 1. 合法表单校验
        valid_content = (
            "[meta]\n"
            "title = 体检查询\n"
            "group = 默认\n"
            "type = select\n\n"
            "[params]\n"
            "start_date = 开始日期 | date | {today} | required\n"
            "status = 状态 | select:全部,启用,禁用 | 全部 | searchable\n\n"
            "[sql]\n"
            "SELECT * FROM Users WHERE RegDate >= '{start_date}' AND Status = '{status}'\n"
        )
        is_valid, errors, warnings = dlg.validate_form(valid_content)
        self.assertTrue(is_valid)
        self.assertEqual(errors, [])

        # 2. 空内容校验
        is_valid, errors, warnings = dlg.validate_form("")
        self.assertFalse(is_valid)
        self.assertTrue(any('为空' in e for e in errors))

        # 3. 未知查询类型
        bad_type_content = valid_content.replace('type = select', 'type = insert_mode')
        is_valid, errors, warnings = dlg.validate_form(bad_type_content)
        self.assertFalse(is_valid)
        self.assertTrue(any('无效' in e or '仅支持' in e for e in errors))

        # 4. 参数格式错误（缺少等号）
        bad_param_content = valid_content.replace(
            "start_date = 开始日期 | date | {today} | required",
            "start_date 开始日期 | date"
        )
        is_valid, errors, warnings = dlg.validate_form(bad_param_content)
        self.assertFalse(is_valid)
        self.assertTrue(any('等号' in e for e in errors))

        # 5. 参数名重复
        dup_param_content = valid_content.replace(
            "status = 状态",
            "start_date = 状态"
        )
        is_valid, errors, warnings = dlg.validate_form(dup_param_content)
        self.assertFalse(is_valid)
        self.assertTrue(any('重复定义' in e for e in errors))

        # 6. options_sql 不安全检测
        unsafe_opt_content = (
            "[meta]\ntitle = 测试\n[params]\n"
            "dept = 科室 | select | | options_sql=DELETE FROM Dept\n"
            "[sql]\nSELECT * FROM Users\n"
        )
        is_valid, errors, warnings = dlg.validate_form(unsafe_opt_content)
        self.assertFalse(is_valid)
        self.assertTrue(any('options_sql' in e for e in errors))

        # 7. SQL 包含危险关键字
        danger_sql_content = (
            "[meta]\ntitle = 测试\n[params]\n"
            "[sql]\nDROP TABLE ImportantData\n"
        )
        is_valid, errors, warnings = dlg.validate_form(danger_sql_content)
        self.assertFalse(is_valid)
        self.assertTrue(any('安全检查未通过' in e for e in errors))

        # 8. SQL 引用了未定义的参数占位符
        missing_placeholder_content = (
            "[meta]\ntitle = 测试\n[params]\n"
            "start_date = 开始日期 | date\n"
            "[sql]\nSELECT * FROM Users WHERE Age = {user_age}\n"
        )
        is_valid, errors, warnings = dlg.validate_form(missing_placeholder_content)
        self.assertFalse(is_valid)
        self.assertTrue(any('user_age' in e for e in errors))

        # 9. 括号不匹配产生警告
        unbalanced_paren_content = (
            "[meta]\ntitle = 测试\n[params]\n"
            "start_date = 开始日期 | date\n"
            "[sql]\nSELECT * FROM Users WHERE (CreateDate >= '{start_date}'\n"
        )
        is_valid, errors, warnings = dlg.validate_form(unbalanced_paren_content)
        self.assertTrue(is_valid)  # 警告不阻断有效性
        self.assertTrue(any('括号' in w for w in warnings))

    def test_form_editor_validation_ui_components(self):
        """测试 FormEditorDialog 校验 UI 控件状态与保存退出勾选交互"""
        from unittest.mock import patch
        dlg = FormEditorDialog(None, self.forms_dir)

        # 校验控件存在性与默认状态
        self.assertIsNotNone(getattr(dlg, 'validate_btn', None))
        self.assertIsNotNone(getattr(dlg, 'validate_on_save_check', None))
        self.assertTrue(dlg.validate_on_save_check.isChecked())

        # 当勾选保存退出校验且表单有错误时，保存被拦截
        dlg.editor.setPlainText("[meta]\ntitle = 错误表单\n[sql]\nDROP TABLE Test\n")
        with patch('PyQt5.QtWidgets.QMessageBox.critical') as mock_critical:
            dlg._save()
            self.assertTrue(mock_critical.called)


if __name__ == '__main__':
    unittest.main()

