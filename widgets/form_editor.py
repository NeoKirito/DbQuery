# -*- coding: utf-8 -*-
"""
表单编辑器对话框
支持新建和编辑 .qry 文件，带语法高亮
"""
import os
import re
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QPlainTextEdit, QGroupBox, QFormLayout,
    QMessageBox, QFileDialog, QSizePolicy
)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import (
    QFont, QTextCharFormat, QColor, QSyntaxHighlighter, QFontMetrics
)
from form_parser import TEMPLATE, FormParser


# ──────────────────────────────────────────────
#  语法高亮器
# ──────────────────────────────────────────────
class QryHighlighter(QSyntaxHighlighter):
    """为 .qry 文件提供基础语法高亮"""

    def __init__(self, document):
        super(QryHighlighter, self).__init__(document)
        self.rules = []

        def fmt(color, bold=False, italic=False):
            f = QTextCharFormat()
            f.setForeground(QColor(color))
            if bold:
                f.setFontWeight(700)
            if italic:
                f.setFontItalic(True)
            return f

        # Section 标题 [meta] [params] [sql]
        self.rules.append(
            (re.compile(r'^\[[\w\s]+\]', re.MULTILINE),
             fmt('#8B4513', bold=True))
        )
        # key = value 行的 key 部分
        self.rules.append(
            (re.compile(r'^[a-zA-Z_]\w*\s*(?==)', re.MULTILINE),
             fmt('#006080'))
        )
        # SQL 关键字
        kw = (r'\b(SELECT|FROM|WHERE|AND|OR|NOT|IN|LIKE|JOIN|LEFT|RIGHT|INNER|'
              r'OUTER|CROSS|ON|GROUP\s+BY|ORDER\s+BY|HAVING|TOP|DISTINCT|AS|'
              r'BETWEEN|IS|NULL|COUNT|SUM|AVG|MIN|MAX|CASE|WHEN|THEN|ELSE|END|'
              r'UNION|ALL|WITH|EXISTS|INTO|SET|INSERT|UPDATE|DELETE|EXEC|'
              r'CAST|CONVERT|ISNULL|COALESCE|LEN|TRIM|GETDATE|DATEADD|DATEDIFF)\b')
        self.rules.append(
            (re.compile(kw, re.IGNORECASE), fmt('#0000CC', bold=True))
        )
        # 字符串 '...'
        self.rules.append(
            (re.compile(r"'[^'\\]*(?:\\.[^'\\]*)*'"), fmt('#007700'))
        )
        # 参数占位符 {param_name}
        self.rules.append(
            (re.compile(r'\{[^}\s]+\}'), fmt('#CC0099', bold=True))
        )
        # 注释 -- 和 #
        self.rules.append(
            (re.compile(r'(--[^\n]*)|(#[^\n]*)'), fmt('#888888', italic=True))
        )
        # 数字
        self.rules.append(
            (re.compile(r'\b\d+(\.\d+)?\b'), fmt('#AA4400'))
        )

    def highlightBlock(self, text):
        for pattern, fmt in self.rules:
            for m in pattern.finditer(text):
                self.setFormat(m.start(), m.end() - m.start(), fmt)


# ──────────────────────────────────────────────
#  对话框主体
# ──────────────────────────────────────────────
class FormEditorDialog(QDialog):

    def __init__(self, form, forms_dir, parent=None):
        """
        form      : QueryForm（编辑已有表单）或 None（新建）
        forms_dir : forms 根目录路径
        """
        super(FormEditorDialog, self).__init__(parent)
        self.form      = form
        self.forms_dir = forms_dir
        self.setWindowTitle("编辑表单" if form else "新建表单")
        self.setMinimumSize(720, 600)
        self.resize(840, 680)
        self._setup_ui()
        if form:
            self._load_form_file()
        else:
            self.editor.setPlainText(TEMPLATE)

    # ── UI 初始化 ──────────────────────────────
    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        # 顶部：路径提示 + 帮助按钮
        top_row = QHBoxLayout()
        self.path_label = QLabel(
            "文件: " + (self.form.file_path if self.form else "（尚未保存）")
        )
        self.path_label.setStyleSheet("color: #555; font-size: 11px;")
        help_btn = QPushButton("格式说明")
        help_btn.setFixedWidth(80)
        help_btn.clicked.connect(self._show_help)
        top_row.addWidget(self.path_label)
        top_row.addStretch()
        top_row.addWidget(help_btn)
        layout.addLayout(top_row)

        # 新建表单时显示"保存位置"区域
        if not self.form:
            loc_grp = QGroupBox("保存位置")
            loc_form = QFormLayout(loc_grp)
            loc_form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)

            self.group_edit = QLineEdit()
            self.group_edit.setPlaceholderText("分组名称（同时作为子目录），如：销售管理")

            self.filename_edit = QLineEdit()
            self.filename_edit.setPlaceholderText("文件名（不含 .qry 扩展名）")

            loc_form.addRow("分组目录:", self.group_edit)
            loc_form.addRow("文件名:", self.filename_edit)
            layout.addWidget(loc_grp)

        # 编辑器
        self.editor = QPlainTextEdit()
        mono_font = QFont("Courier New", 10)
        mono_font.setStyleHint(QFont.TypeWriter)
        self.editor.setFont(mono_font)
        # Tab = 4 spaces 宽
        metrics = QFontMetrics(mono_font)
        self.editor.setTabStopDistance(metrics.width(' ') * 4)
        self.editor.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.highlighter = QryHighlighter(self.editor.document())
        layout.addWidget(self.editor, stretch=1)

        # 行号 / 状态
        self.cursor_lbl = QLabel("行 1，列 1")
        self.cursor_lbl.setStyleSheet("color: #666; font-size: 11px;")
        self.editor.cursorPositionChanged.connect(self._update_cursor_pos)

        # 底部按钮
        btn_row = QHBoxLayout()
        btn_row.addWidget(self.cursor_lbl)
        btn_row.addStretch()

        if self.form:
            save_as_btn = QPushButton("另存为...")
            save_as_btn.clicked.connect(self._save_as)
            btn_row.addWidget(save_as_btn)

        save_btn = QPushButton("保存")
        save_btn.setDefault(True)
        save_btn.setMinimumWidth(80)
        save_btn.clicked.connect(self._save)

        cancel_btn = QPushButton("取消")
        cancel_btn.clicked.connect(self.reject)

        btn_row.addWidget(save_btn)
        btn_row.addWidget(cancel_btn)
        layout.addLayout(btn_row)

    # ── 辅助方法 ──────────────────────────────
    def _update_cursor_pos(self):
        cursor = self.editor.textCursor()
        self.cursor_lbl.setText(
            "行 {}，列 {}".format(
                cursor.blockNumber() + 1,
                cursor.columnNumber() + 1
            )
        )

    def _load_form_file(self):
        try:
            with open(self.form.file_path, 'r', encoding='utf-8-sig') as f:
                self.editor.setPlainText(f.read())
        except Exception as e:
            QMessageBox.warning(self, "读取失败", "无法读取文件：\n{}".format(e))

    def _get_save_path(self):
        """获取保存路径；返回 None 表示用户取消或输入无效"""
        if self.form:
            return self.form.file_path

        group = self.group_edit.text().strip() or '默认'
        name  = self.filename_edit.text().strip()

        if not name:
            QMessageBox.warning(self, "提示", "请输入文件名")
            return None

        # 清理非法字符
        name  = re.sub(r'[\\/:*?"<>|]', '_', name)
        group = re.sub(r'[\\/:*?"<>|]', '_', group)

        group_dir = os.path.join(self.forms_dir, group)
        os.makedirs(group_dir, exist_ok=True)

        path = os.path.join(group_dir, name + '.qry')

        if os.path.exists(path):
            reply = QMessageBox.question(
                self, "确认覆盖",
                "文件已存在，是否覆盖？\n\n{}".format(path),
                QMessageBox.Yes | QMessageBox.No
            )
            if reply != QMessageBox.Yes:
                return None

        return path

    def _do_save(self, path):
        """执行实际写入"""
        content = self.editor.toPlainText()

        # 提取 query_type（从 [meta] 段的 type 字段）
        query_type = 'select'
        meta_m = re.search(r'\[meta\](.*?)(?=\n\s*\[|\Z)', content,
                           re.DOTALL | re.IGNORECASE)
        if meta_m:
            for line in meta_m.group(1).splitlines():
                line = line.strip()
                if line.startswith('#') or line.startswith(';'):
                    continue
                if '=' in line:
                    k, v = line.split('=', 1)
                    if k.strip().lower() == 'type':
                        query_type = v.strip().lower()
                        break

        # SQL 安全检查（警告，不强制阻止保存）
        m = re.search(r'\[sql\](.*?)(?=\n\s*\[|\Z)', content,
                      re.DOTALL | re.IGNORECASE)
        if m:
            sql = m.group(1).strip()
            if sql:
                ok, reason = FormParser.is_safe_sql(sql, query_type)
                if not ok:
                    reply = QMessageBox.warning(
                        self, "SQL 安全警告",
                        "SQL 安全检查未通过：{}\n\n仍要保存吗？".format(reason),
                        QMessageBox.Yes | QMessageBox.No
                    )
                    if reply != QMessageBox.Yes:
                        return False

        try:
            with open(path, 'w', encoding='utf-8') as f:
                f.write(content)
            return True
        except Exception as e:
            QMessageBox.critical(self, "保存失败", str(e))
            return False

    def _save(self):
        path = self._get_save_path()
        if path is None:
            return
        if self._do_save(path):
            QMessageBox.information(self, "保存成功",
                                    "表单已保存：\n{}".format(path))
            self.accept()

    def _save_as(self):
        default = os.path.join(
            self.forms_dir,
            os.path.basename(self.form.file_path)
        )
        path, _ = QFileDialog.getSaveFileName(
            self, "另存为", default,
            "查询表单 (*.qry);;所有文件 (*)"
        )
        if not path:
            return
        if not path.endswith('.qry'):
            path += '.qry'
        if self._do_save(path):
            QMessageBox.information(self, "另存为成功",
                                    "已另存为：\n{}".format(path))
            self.accept()

    def _show_help(self):
        text = u"""\
表单文件 (.qry) 格式说明
═══════════════════════════════════════════

[meta]  基本信息
  title       = 表单在标签页上显示的名称
  group       = 分组（同时是子目录名称）
  description = 描述信息（可选）
  type        = select（默认，SELECT 查询）
                exec  （存储过程，SQL 以 EXEC 开头）

[params]  查询条件（可选）
  格式：参数名 = 显示标签 | 类型 | 默认值

  类型：
    text           文本输入框
    date           日期选择（YYYY-MM-DD）
    datetime       日期时间选择
    number         数字输入框
    select:A,B,C   下拉选择框（逗号分隔选项）

  特殊默认值：
    {today}  在 date/datetime 中代表今日

  示例：
    start_date = 开始日期 | date
    end_date   = 结束日期 | date | {today}
    status     = 状态     | select:全部,启用,禁用 | 全部
    keyword    = 关键字   | text

[sql]  SQL 查询语句
  • SELECT 模式：只能使用 SELECT，不允许 INSERT/UPDATE/DELETE 等
  • 存储过程模式：以 EXEC 或 EXECUTE 开头，调用存储过程
  • 用 {参数名} 引用 [params] 中定义的参数
  • 支持 SQL 注释（-- 或 /* */ 格式）

SELECT 模式示例：
  SELECT TOP 1000 *
  FROM Orders
  WHERE OrderDate BETWEEN '{start_date}' AND '{end_date}'
    AND Status = '{status}'
    AND CustomerName LIKE '%{keyword}%'

存储过程模式示例（需在 [meta] 中设置 type = exec）：
  EXEC dbo.usp_QueryOrders
      @StartDate = '{start_date}',
      @EndDate   = '{end_date}',
      @Status    = '{status}'
═══════════════════════════════════════════"""
        QMessageBox.information(self, "格式说明", text)
