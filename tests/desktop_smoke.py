# -*- coding: utf-8 -*-
"""无显示环境下的桌面控件冒烟检查；不连接数据库。"""
from PyQt5.QtWidgets import QApplication, QCheckBox, QComboBox, QPlainTextEdit, QButtonGroup

from form_parser import QueryForm, QueryParam
from widgets.query_tab import QueryTab


class NoopDBManager:
    def execute_query(self, sql, query_type='select'):
        return [], []


def main():
    app = QApplication.instance() or QApplication([])
    form = QueryForm()
    form.title = '桌面控件冒烟'
    form.sql = "SELECT '{text}', '{date}', '{datetime}', '{number}', '{select}', '{textarea}', '{checkbox}', '{radio}', '{hidden}'"
    form.params = [
        QueryParam('text', '文本', 'text', default='中文'),
        QueryParam('date', '日期', 'date', default='2026-08-17'),
        QueryParam('datetime', '日期时间', 'datetime', default='2026-08-17 09:08:07'),
        QueryParam('number', '数量', 'number', default='1.25'),
        QueryParam('select', '科室', 'select', ['全部', '内科'], default='内科'),
        QueryParam('textarea', '备注', 'textarea', default='多行'),
        QueryParam('checkbox', '启用', 'checkbox', default='1'),
        QueryParam('radio', '性别', 'radio', ['男', '女'], default='女'),
        QueryParam('hidden', '来源', 'hidden', default='PEIS'),
    ]
    tab = QueryTab(form, NoopDBManager(), 'forms')
    assert isinstance(tab._param_widgets['select'], QComboBox)
    assert tab._param_widgets['select'].isEditable()
    assert isinstance(tab._param_widgets['textarea'], QPlainTextEdit)
    assert isinstance(tab._param_widgets['checkbox'], QCheckBox)
    assert isinstance(tab._param_widgets['radio'], QButtonGroup)
    assert tab._param_widgets['hidden'] is None
    params = tab._normalized_param_values()
    assert params['select'] == '内科'
    assert params['checkbox'] == '1'
    assert params['radio'] == '女'
    assert params['hidden'] == 'PEIS'
    assert '2026-08-17 09:08:07' in tab._build_final_sql()
    tab.close()
    app.processEvents()
    print('desktop smoke: OK')


if __name__ == '__main__':
    main()
