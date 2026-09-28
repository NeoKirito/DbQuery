# -*- coding: utf-8 -*-
"""
双模式可视化表单设计器单元测试
测试基本信息配置、查询参数增删改排版、多区块与指标卡配置、SQL 参数快捷插入、双向同步与保存
"""
import os
import sys
import unittest
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PyQt5.QtWidgets import QApplication
from form_parser import FormParser, QueryForm, QueryParam, QueryBlock
from widgets.form_editor import FormEditorDialog


class TestVisualFormEditor(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        os.environ['QT_QPA_PLATFORM'] = 'offscreen'
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.forms_dir = self.temp_dir.name
        os.makedirs(os.path.join(self.forms_dir, '综合分析'), exist_ok=True)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_new_form_initialization(self):
        """测试新建表单时，可视化设计器默认状态与基础属性"""
        dlg = FormEditorDialog(None, self.forms_dir, default_group='综合分析')
        self.assertEqual(dlg.group_combo.currentText(), '综合分析')
        self.assertEqual(dlg.tab_widget.count(), 6)
        self.assertEqual(dlg.query_type_combo.currentData(), 'select')
        self.assertFalse(dlg.web_enabled_check.isChecked())
        # 默认应有初始 params 和 blocks
        self.assertGreaterEqual(len(dlg._blocks_data), 1)
        self.assertIn('[sql]', dlg.editor.toPlainText())
        dlg.close()

    def test_load_existing_multi_block_form(self):
        """测试加载已有跨库多区块表单并反向初始化至可视化面板"""
        form_content = (
            "[meta]\n"
            "title = 运营看板\n"
            "group = 综合分析\n"
            "description = 经营综合多源分析\n"
            "order = 3\n"
            "datasource = main_db\n"
            "web_enabled = true\n"
            "layout = cards_1, detail_1\n\n"
            "[params]\n"
            "start_date = 开始日期 | date | {today} | required | width=160px\n"
            "dept = 科室 | select:内科,外科 | 内科 | searchable\n\n"
            "[block.cards_1]\n"
            "title = 关键指标\n"
            "type = cards\n"
            "datasource = main_db\n"
            "sql = SELECT COUNT(*) as 总人次 FROM Users WHERE RegDate >= '{start_date}'\n\n"
            "[block.detail_1]\n"
            "title = 人员明细\n"
            "type = table\n"
            "datasource = lis_db\n"
            "summary_footer = auto\n"
            "sql = SELECT * FROM Details WHERE Dept = '{dept}'\n"
        )
        file_path = os.path.join(self.forms_dir, '综合分析', '运营看板.qry')
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(form_content)

        form = FormParser.parse_file(file_path, forms_root=self.forms_dir)
        dlg = FormEditorDialog(form, self.forms_dir)

        # 验证 Tab 0 (基本信息)
        self.assertEqual(dlg.title_edit.text(), '运营看板')
        self.assertEqual(dlg.group_combo.currentText(), '综合分析')
        self.assertEqual(dlg.desc_edit.text(), '经营综合多源分析')
        self.assertEqual(dlg.order_edit.text(), '3')
        self.assertTrue(dlg.web_enabled_check.isChecked())

        # 验证 Tab 1 (参数列表)
        self.assertEqual(len(dlg._params_data), 2)
        self.assertEqual(dlg._params_data[0].name, 'start_date')
        self.assertEqual(dlg._params_data[0].ptype, 'date')
        self.assertTrue(dlg._params_data[0].required)
        self.assertEqual(dlg._params_data[1].name, 'dept')
        self.assertEqual(dlg._params_data[1].ptype, 'select')
        self.assertEqual(dlg._params_data[1].options, ['内科', '外科'])

        # 验证 Tab 2 (区块列表)
        self.assertEqual(len(dlg._blocks_data), 2)
        self.assertEqual(dlg._blocks_data[0].id, 'cards_1')
        self.assertEqual(dlg._blocks_data[0].btype, 'cards')
        self.assertEqual(dlg._blocks_data[1].id, 'detail_1')
        self.assertEqual(dlg._blocks_data[1].btype, 'table')
        self.assertEqual(dlg._blocks_data[1].summary_footer, 'auto')

        dlg.close()

    def test_param_add_modify_move_delete(self):
        """测试在可视化面板中添加、修改、上下移动与删除参数"""
        dlg = FormEditorDialog(None, self.forms_dir)
        initial_count = len(dlg._params_data)

        # 1. 添加参数
        dlg._on_param_add()
        self.assertEqual(len(dlg._params_data), initial_count + 1)
        new_row = len(dlg._params_data) - 1

        # 2. 修改参数属性
        dlg.p_name_edit.setText('user_code')
        dlg.p_label_edit.setText('用户工号')
        idx = dlg.p_type_combo.findData('text')
        dlg.p_type_combo.setCurrentIndex(idx)
        dlg.p_default_edit.setText('U1001')
        dlg.p_required_check.setChecked(True)
        dlg._save_current_param_details()

        p = dlg._params_data[new_row]
        self.assertEqual(p.name, 'user_code')
        self.assertEqual(p.label, '用户工号')
        self.assertEqual(p.default, 'U1001')
        self.assertTrue(p.required)

        # 3. 上移参数
        if new_row > 0:
            dlg.param_table.selectRow(new_row)
            dlg._on_param_move_up()
            self.assertEqual(dlg._params_data[new_row - 1].name, 'user_code')

        # 4. 删除参数
        current_len = len(dlg._params_data)
        dlg.param_table.selectRow(0)
        dlg._on_param_delete()
        self.assertEqual(len(dlg._params_data), current_len - 1)

        dlg.close()

    def test_block_add_and_quick_param_insert(self):
        """测试添加表格与指标卡区块，并使用一键快捷工具插入参数占位符"""
        dlg = FormEditorDialog(None, self.forms_dir)

        # 添加一个指定参数
        dlg._params_data = [
            QueryParam(name='exam_no', label='体检编号', ptype='text'),
            QueryParam(name='start_date', label='起始日期', ptype='date')
        ]
        dlg._reload_param_table()

        # 刷新快捷参数条
        dlg._refresh_quick_param_buttons()
        # 验证快捷工具条中至少包含 2 个参数按钮 + today 按钮
        self.assertGreaterEqual(dlg.quick_param_layout.count(), 3)

        # 添加指标卡区块
        init_blocks = len(dlg._blocks_data)
        dlg._on_block_add_cards()
        self.assertEqual(len(dlg._blocks_data), init_blocks + 1)
        new_block = dlg._blocks_data[-1]
        self.assertEqual(new_block.btype, 'cards')

        # 选中新区块并在 SQL 中插入参数占位符
        dlg.block_table.selectRow(len(dlg._blocks_data) - 1)
        dlg.b_sql_edit.setPlainText("SELECT * FROM Test WHERE No = ")
        # 移动光标到末尾
        cursor = dlg.b_sql_edit.textCursor()
        cursor.movePosition(cursor.End)
        dlg.b_sql_edit.setTextCursor(cursor)

        dlg._insert_param_into_sql("exam_no")
        self.assertIn("No = {exam_no}", dlg.b_sql_edit.toPlainText())

        dlg.close()

    def test_bi_directional_sync_and_save(self):
        """测试可视化 Tab 与源码 Tab 的双向同步以及保存完整流程"""
        dlg = FormEditorDialog(None, self.forms_dir, default_group='综合分析')
        dlg.filename_edit.setText('可视化保存测试')

        # 1. 在可视化 Tab 修改基本信息
        dlg.title_edit.setText('自动化分析看板')
        dlg.desc_edit.setText('测试双向无缝同步')
        dlg.order_edit.setText('10')
        dlg.web_enabled_check.setChecked(True)

        # 2. 设置参数与多区块
        dlg._params_data = [
            QueryParam(name='status', label='状态', ptype='select', options=['有效', '停用'], default='有效', required=True)
        ]
        dlg._blocks_data = [
            QueryBlock(block_id='kpi', title='汇总指标', btype='cards', sql="SELECT 100 AS 总计"),
            QueryBlock(block_id='list', title='清单明细', btype='table', sql="SELECT * FROM List WHERE State = '{status}'")
        ]
        dlg._reload_param_table()
        dlg._reload_block_table()

        # 3. 同步到源码 Tab 3
        dlg._sync_visual_to_raw()
        raw_text = dlg.editor.toPlainText()
        self.assertIn('title = 自动化分析看板', raw_text)
        self.assertIn('web_enabled = true', raw_text)
        self.assertIn('order = 10', raw_text)
        self.assertIn('[block.kpi]', raw_text)
        self.assertIn('[block.list]', raw_text)
        self.assertIn("State = '{status}'", raw_text)

        # 4. 在源码 Tab 修改，反向同步到可视化 Tab
        modified_raw = raw_text.replace('title = 自动化分析看板', 'title = 源码反向同步修改标题')
        dlg.editor.setPlainText(modified_raw)
        dlg._sync_raw_to_visual()
        self.assertEqual(dlg.title_edit.text(), '源码反向同步修改标题')

        # 5. 执行保存
        save_path = dlg._get_save_path()
        self.assertIsNotNone(save_path)
        ok = dlg._do_save(save_path)
        self.assertTrue(ok)
        self.assertTrue(os.path.exists(save_path))

        # 重新读取验证
        saved_form = FormParser.parse_file(save_path, forms_root=self.forms_dir)
        self.assertEqual(saved_form.title, '源码反向同步修改标题')
        self.assertEqual(len(saved_form.params), 1)
        self.assertEqual(saved_form.params[0].name, 'status')
        self.assertEqual(len(saved_form.blocks), 2)
        self.assertEqual(saved_form.blocks[0].id, 'kpi')
        self.assertEqual(saved_form.blocks[1].id, 'list')

        dlg.close()

    def test_live_preview_refresh(self):
        """测试切换至效果预览 Tab 时，自动动态生成模拟控件与表格"""
        dlg = FormEditorDialog(None, self.forms_dir, default_group='综合分析')
        dlg._params_data = [
            QueryParam(name='start_date', label='起始日期', ptype='date', default='{today}', required=True),
            QueryParam(name='dept', label='科室', ptype='select', options=['内科', '外科']),
            QueryParam(name='status', label='状态', ptype='radio', options=['正常', '注销'])
        ]
        dlg._blocks_data = [
            QueryBlock(block_id='kpi', title='总览指标', btype='cards', sql="SELECT 100 AS 人数"),
            QueryBlock(block_id='list', title='明细数据', btype='table', summary_footer='auto', sql="SELECT * FROM Test")
        ]

        # 切换到 Tab 3 效果预览
        dlg.tab_widget.setCurrentWidget(dlg.preview_tab)
        # 触发刷新
        dlg._refresh_live_preview()

        # 检查 preview_layout 中包含的组件
        self.assertGreater(dlg.preview_layout.count(), 0)
        # 验证预览容器中含有模拟参数组、模拟指标卡组、模拟表格组
        group_boxes = dlg.preview_container.findChildren(type(dlg.pv_table_find if hasattr(dlg, 'pv_table_find') else dlg.param_detail_group))
        self.assertGreaterEqual(len(group_boxes), 2)
        dlg.close()

    def test_docs_tab_and_template_loading(self):
        """测试使用说明与示例 Tab 导航、模版列表及一键载入至编辑器"""
        dlg = FormEditorDialog(None, self.forms_dir, default_group='综合分析')
        self.assertIsNotNone(dlg.docs_tab)
        self.assertEqual(dlg.docs_list.count(), 8)
        self.assertEqual(dlg.docs_stack.count(), 8)

        # 切换到模版三页面 (索引 7)
        dlg.docs_list.setCurrentRow(7)
        self.assertEqual(dlg.docs_stack.currentIndex(), 7)

        # 测试直接载入模版一
        tpl_1 = dlg._build_template_page_1()
        self.assertIsNotNone(tpl_1)

        # 直接测试静默载入函数的核心逻辑（不弹出对话框）
        test_qry = (
            "[meta]\n"
            "title = 测试模版载入\n"
            "group = 综合分析\n"
            "[params]\n"
            "k = 键 | text\n"
            "[block.main]\n"
            "title = 明细\n"
            "sql = SELECT 1\n"
        )
        dlg.editor.setPlainText(test_qry)
        dlg._sync_raw_to_visual()
        self.assertEqual(dlg.title_edit.text(), '测试模版载入')
        self.assertEqual(len(dlg._params_data), 1)
        self.assertEqual(dlg._params_data[0].name, 'k')

        dlg.close()


if __name__ == '__main__':
    unittest.main()
