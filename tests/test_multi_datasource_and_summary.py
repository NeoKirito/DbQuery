# -*- coding: utf-8 -*-
"""
测试多数据源与汇总统计引擎。
"""
import configparser
import os
import tempfile
import unittest

from core.summary_service import (
    compute_cards, compute_summary, format_metric_value, parse_summary_spec
)
from db_manager import DBManager
from form_parser import FormParser, QueryBlock, QueryForm


class TestSummaryService(unittest.TestCase):
    def test_parse_summary_spec(self):
        spec = "sum:金额, 实收; count:体检号; avg:客单价"
        parsed = parse_summary_spec(spec)
        self.assertFalse(parsed['auto'])
        self.assertEqual(len(parsed['rules']), 3)
        self.assertEqual(parsed['rules'][0]['op'], 'sum')
        self.assertEqual(parsed['rules'][0]['cols'], ['金额', '实收'])
        self.assertEqual(parsed['rules'][1]['op'], 'count')
        self.assertEqual(parsed['rules'][1]['cols'], ['体检号'])
        self.assertEqual(parsed['rules'][2]['op'], 'avg')
        self.assertEqual(parsed['rules'][2]['cols'], ['客单价'])

        auto_parsed = parse_summary_spec("auto")
        self.assertTrue(auto_parsed['auto'])

    def test_compute_summary_explicit(self):
        cols = ['科室', '人次', '金额', '体检号']
        rows = [
            ['内科', 10, 1500.5, '001'],
            ['外科', 20, 3200.0, '002'],
            ['放射科', 5, 800.0, None],
        ]
        spec = "sum:人次,金额; count:体检号; avg:金额"
        # 针对各列聚合
        s_row, s_dict = compute_summary(cols, rows, spec)
        # 第一列默认合计标识
        self.assertIn('合计', s_row[0])
        # 人次 sum = 35 -> '35'
        self.assertEqual(s_row[1], '35')
        # 金额 (avg 覆盖了金额的计算规则)
        self.assertEqual(s_dict['人次']['value'], 35)
        self.assertEqual(s_dict['体检号']['value'], 2)  # non-null count

    def test_compute_summary_auto(self):
        cols = ['科室', '人次', '金额']
        rows = [
            ['内科', 10, 150.0],
            ['外科', 20, 250.0],
        ]
        s_row, s_dict = compute_summary(cols, rows, "auto")
        self.assertIn('合计', s_row[0])
        self.assertEqual(s_row[1], '30')
        self.assertEqual(s_row[2], '400.00')

    def test_compute_cards(self):
        cols = ['登记人次', '实收总额', '客单价']
        rows = [[1248, 386520.0, 309.71]]
        cards = compute_cards(cols, rows)
        self.assertEqual(len(cards), 3)
        self.assertEqual(cards[0]['title'], '登记人次')
        self.assertEqual(cards[0]['formatted'], '1,248')
        self.assertEqual(cards[1]['title'], '实收总额')
        self.assertEqual(cards[1]['formatted'], '386,520.00')


class TestMultiBlockFormParser(unittest.TestCase):
    def test_parse_legacy_single_sql_form(self):
        content = u"""[meta]
title = 老单据查询
group = 默认

[params]
start_date = 开始日期 | date | {today}

[sql]
SELECT * FROM TestTable
"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.qry', encoding='utf-8', delete=False) as tf:
            tf.write(content)
            tf_path = tf.name

        try:
            form = FormParser.parse_file(tf_path)
            self.assertEqual(form.title, u"老单据查询")
            self.assertEqual(form.datasource, "default")
            self.assertEqual(len(form.blocks), 1)
            self.assertEqual(form.blocks[0].id, "main")
            self.assertEqual(form.blocks[0].btype, "table")
            self.assertEqual(form.blocks[0].sql, "SELECT * FROM TestTable")
        finally:
            if os.path.exists(tf_path):
                os.remove(tf_path)

    def test_parse_multi_block_form(self):
        content = u"""[meta]
title = 体检综合看板
group = 综合报表
datasource = tjxt
layout = summary, dept_stat, detail

[params]
start_date = 开始日期 | date | {today}

[block.summary]
title = 核心运营指标
type = cards
datasource = his
sql = SELECT COUNT(1) AS 登记人次, SUM(Fee) AS 实收总额 FROM Orders WHERE Date >= '{start_date}'

[block.detail]
title = 明细流水
type = table
datasource = tjxt
width = 50%
summary_footer = sum:金额; count:体检号
order = 3
sql = SELECT * FROM Detail WHERE Date >= '{start_date}'

[block.dept_stat]
title = 科室统计
type = table
datasource = default
width = 50%
summary_footer = auto
order = 2
sql = SELECT Dept, COUNT(1) AS 人次 FROM Record GROUP BY Dept
"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.qry', encoding='utf-8', delete=False) as tf:
            tf.write(content)
            tf_path = tf.name

        try:
            form = FormParser.parse_file(tf_path)
            self.assertEqual(form.title, u"体检综合看板")
            self.assertEqual(form.datasource, "tjxt")
            self.assertEqual(len(form.blocks), 3)

            # 验证根据 layout 的排序顺序: summary, dept_stat, detail
            self.assertEqual(form.blocks[0].id, "summary")
            self.assertEqual(form.blocks[0].btype, "cards")
            self.assertEqual(form.blocks[0].datasource, "his")

            self.assertEqual(form.blocks[1].id, "dept_stat")
            self.assertEqual(form.blocks[1].btype, "table")
            self.assertEqual(form.blocks[1].width, "50%")
            self.assertEqual(form.blocks[1].summary_footer, "auto")

            self.assertEqual(form.blocks[2].id, "detail")
            self.assertEqual(form.blocks[2].btype, "table")
            self.assertEqual(form.blocks[2].width, "50%")
            self.assertEqual(form.blocks[2].summary_footer, "sum:金额; count:体检号")
        finally:
            if os.path.exists(tf_path):
                os.remove(tf_path)


class TestDBManagerMultiDatasource(unittest.TestCase):
    def test_datasources_read_and_fallback(self):
        mgr = DBManager()
        # 默认数据源
        ds_map = mgr.get_datasources()
        self.assertIn('default', ds_map)
        self.assertTrue(ds_map['default']['is_default'])

        # 未配置的数据源安全回退 default
        cfg_unknown = mgr.get_db_config('non_existent_ds')
        cfg_default = mgr.get_db_config('default')
        self.assertEqual(cfg_unknown['server'], cfg_default['server'])

    def test_set_and_remove_datasource(self):
        mgr = DBManager()
        test_ds_id = 'test_his_db'
        try:
            mgr.set_datasource_config(test_ds_id, {
                'name': 'HIS测试库',
                'server': '192.168.1.99',
                'port': '1433',
                'database': 'HIS_TEST',
                'username': 'sa',
                'password': 'pwd',
                'trusted_connection': 'no'
            })

            ds_map = mgr.get_datasources()
            self.assertIn(test_ds_id, ds_map)
            self.assertEqual(ds_map[test_ds_id]['database'], 'HIS_TEST')

            cfg = mgr.get_db_config(test_ds_id)
            self.assertEqual(cfg['database'], 'HIS_TEST')
            self.assertEqual(cfg['server'], '192.168.1.99')
        finally:
            mgr.remove_datasource(test_ds_id)

        ds_map_after = mgr.get_datasources()
        self.assertNotIn(test_ds_id, ds_map_after)


class TestConfigDialogMultiDatasource(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PyQt5.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def test_dialog_loads_datasources_and_switches(self):
        from widgets.config_dialog import ConfigDialog

        class MockMgr:
            def __init__(self):
                self.saved_db_config = None
                self.saved_datasources = {}

            def get_db_config(self):
                return {'server': 'main_host', 'database': 'MAIN_DB', 'port': '1433'}

            def get_datasources(self):
                return {
                    'default': {'server': 'main_host', 'database': 'MAIN_DB', 'port': '1433'},
                    'lis': {'id': 'lis', 'name': '检验库', 'server': 'lis_host', 'database': 'LIS_DB', 'port': '1433'}
                }

            def set_db_config(self, cfg):
                self.saved_db_config = cfg

            def set_datasource_config(self, ds_id, cfg):
                self.saved_datasources[ds_id] = cfg

            def get_integration_config(self):
                return {'frontend_embed_enabled': False}

            def set_integration_config(self, cfg):
                pass

        mgr = MockMgr()
        dialog = ConfigDialog(mgr)
        self.assertEqual(dialog.ds_combo.count(), 2)
        self.assertEqual(dialog.server_edit.text(), 'main_host')

        # 切换到 lis
        idx = dialog.ds_combo.findData('lis')
        self.assertGreaterEqual(idx, 0)
        dialog.ds_combo.setCurrentIndex(idx)
        self.assertEqual(dialog.server_edit.text(), 'lis_host')
        self.assertEqual(dialog.db_edit.text(), 'LIS_DB')

        # 修改 lis 并切换回 default
        dialog.server_edit.setText('lis_new_host')
        dialog.ds_combo.setCurrentIndex(0)
        self.assertEqual(dialog.server_edit.text(), 'main_host')

        # 保存
        dialog._save()
        self.assertEqual(mgr.saved_db_config['server'], 'main_host')
        self.assertEqual(mgr.saved_datasources['lis']['server'], 'lis_new_host')
        dialog.close()


class TestExportToExcelWithSummaryAndBlocks(unittest.TestCase):
    def test_export_summary_row_and_multi_blocks(self):
        from core.query_service import export_to_excel
        import openpyxl

        tf = tempfile.NamedTemporaryFile(suffix='.xlsx', delete=False)
        tf.close()
        try:
            export_to_excel(
                tf.name,
                columns=['科室', '人次', '金额'],
                rows=[['内科', 10, 1000.0], ['外科', 20, 2000.0]],
                summary_row=['合计 (2条)', 30, 3000.0],
                blocks=[
                    {
                        'title': '科室明细',
                        'type': 'table',
                        'columns': ['编号', '姓名'],
                        'rows': [['001', '张三']],
                        'summary_row': ['合计 (1条)', '']
                    }
                ]
            )
            wb = openpyxl.load_workbook(tf.name)
            self.assertIn('查询结果', wb.sheetnames)
            self.assertIn('科室明细', wb.sheetnames)

            # 验证查询结果 sheet 的合计行
            ws1 = wb['查询结果']
            # 第1行是表头，第2-3行是数据，第4行是合计行
            self.assertEqual(ws1.cell(row=4, column=1).value, '合计 (2条)')
            self.assertEqual(ws1.cell(row=4, column=2).value, 30)

            # 验证科室明细 sheet
            ws2 = wb['科室明细']
            self.assertEqual(ws2.cell(row=1, column=1).value, '编号')
            self.assertEqual(ws2.cell(row=3, column=1).value, '合计 (1条)')
        finally:
            if os.path.exists(tf.name):
                os.remove(tf.name)

    def test_export_no_duplicate_query_result_sheet_when_all_blocks_provided(self):
        from core.query_service import export_to_excel
        import openpyxl

        tf = tempfile.NamedTemporaryFile(suffix='.xlsx', delete=False)
        tf.close()
        try:
            main_cols = ['科室名称', '人次']
            main_rows = [['内科', 10]]
            blocks = [
                {'title': '运营核心指标', 'type': 'cards', 'cards': [{'title': '登记人次', 'formatted': '10', 'raw': 10}]},
                {'title': '各科室汇总', 'type': 'table', 'columns': main_cols, 'rows': main_rows, 'summary_row': ['合计 (1条)', 10]},
                {'title': '人员明细清单', 'type': 'table', 'columns': ['编号', '姓名'], 'rows': [['001', '张三']]}
            ]
            export_to_excel(
                tf.name,
                columns=main_cols,
                rows=main_rows,
                form_title='测试多源表单',
                summary_row=['合计 (1条)', 10],
                blocks=blocks
            )
            wb = openpyxl.load_workbook(tf.name)
            # 应当不包含重复的 '查询结果'，且顺序为：运营核心指标, 各科室汇总, 人员明细清单, 查询信息
            self.assertNotIn('查询结果', wb.sheetnames)
            self.assertEqual(wb.sheetnames, ['运营核心指标', '各科室汇总', '人员明细清单', '查询信息'])
        finally:
            if os.path.exists(tf.name):
                os.remove(tf.name)


class TestSampleFormParsing(unittest.TestCase):
    def test_sample_form_loads(self):
        sample_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'forms', '示例', '多源与合计看板示例.qry'
        )
        self.assertTrue(os.path.isfile(sample_path))
        form = FormParser.parse_file(sample_path)
        self.assertEqual(form.title, u"多数据源与指标合计看板")
        self.assertEqual(len(form.blocks), 3)
        self.assertEqual(form.blocks[0].btype, 'cards')
        self.assertEqual(form.blocks[1].summary_footer, 'auto')
        self.assertEqual(form.blocks[2].summary_footer, 'sum:实收金额; count:体检号')


if __name__ == '__main__':
    unittest.main()
