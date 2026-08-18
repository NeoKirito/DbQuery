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
from core.param_service import validate_options_sql


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
        # 参数扩展属性与控件类型。
        self.rules.append(
            (re.compile(r'\b(options_sql|searchable|allow_custom|required|placeholder|width)\b', re.IGNORECASE),
             fmt('#7A3E9D', bold=True))
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

        # 动态候选 SQL 必须在保存时即通过只读 SELECT 校验，不能延迟到现场使用。
        for line_number, line in enumerate(content.splitlines(), 1):
            token = line.strip()
            if not token or token.startswith(('#', ';')):
                continue
            match = re.search(r'\boptions_sql\s*=\s*(.+)$', token, re.IGNORECASE)
            if match:
                ok, reason = validate_options_sql(match.group(1).strip())
                if not ok:
                    QMessageBox.warning(
                        self, "候选项 SQL 无效",
                        "第 {} 行的 options_sql 未通过安全检查：{}\n\n仅允许一条只读 SELECT 语句。".format(
                            line_number, reason
                        )
                    )
                    return False

        # 主查询 SQL 安全检查（保留既有保存确认行为）
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
        """显示可滚动帮助，内容与 TEMPLATE/README 的 .qry 语法保持一致。"""
        text = u""".qry 表单格式说明

【基本结构】
  参数名 = 显示标签 | 类型 | 默认值 | 可选属性...
  [params] 中每行配置一个查询条件；[sql] 中用 {参数名} 引用它。

【查询条件类型】
  text                 单行文字输入。
  textarea             多行文字输入。
  date                 日期，格式 yyyy-MM-dd。
  datetime             日期时间，格式 yyyy-MM-dd HH:mm:ss。
  number               仅允许有效数字。
  checkbox             选中提交 1，未选中提交 0。
  radio:A,B            单选项，提交选中项的值。
  hidden               不显示，始终提交配置的默认值。
  select:A,B,C         普通下拉框；也可加 options_sql 从数据库加载候选项。

【静态可搜索 Select】
  示例（可直接粘贴到 [params]）：
    status = 状态 | select:全部,启用,禁用 | 全部 | searchable

  下拉候选直接写在 .qry 中；可以输入关键字搜索；查询提交选中的 value。
  本例的默认值是“全部”。

【动态单列 Select】
  数据库候选项使用 options_sql=；整条配置必须写在同一行。

  示例（可直接粘贴到 [params]）：
    department = 科室 | select:全部 | 全部 | searchable | options_sql=SELECT DISTINCT Department FROM Employee WHERE Department IS NOT NULL ORDER BY Department

  上例中数据库返回的 Department 同时是 value 和 label；“全部”保持在第一项。
  也就是说，界面显示“内科”时，最终 SQL 参数也是“内科”。

【动态 value/label 双列 Select】
  示例（可直接粘贴到 [params]）：
    doctor = 医生 | select | | searchable | options_sql=SELECT DoctorID, DoctorName FROM Doctor WHERE Enabled=1 ORDER BY DoctorName

  上例界面显示 DoctorName，最终 SQL 参数使用 DoctorID。
  例如界面显示“张医生”时可提交 1032：第一列 DoctorID 是 value，第二列 DoctorName 是 label。

【静态 + 数据库动态混合】
  上面的“动态单列 Select”就是静态 + 动态混合：`select:全部` 的“全部”来自静态配置，
  Department 由数据库加载。两者按 value 合并并去重；数据库候选加载失败时，静态“全部”仍可使用并可刷新重试。

【是否允许自定义输入】
  allow_custom=false：默认值，必须选择候选项。
  allow_custom=true：允许直接输入候选列表中没有的内容。

  例如：
    keyword_type = 关键词类型 | select:姓名,体检号 | 姓名 | allow_custom=true

【常用属性】
  required 或 required=true      必填；checkbox 必须为 1。
  placeholder=提示文字           输入框提示。
  searchable                     select 可输入关键字搜索（select 默认可搜索）。
  width=220                      控件宽度；也支持 px、%、rem、em、vw。
  {today}                        date/text 为当天 yyyy-MM-dd；datetime 为当前日期时间。

【数据库候选 SQL 限制】
  options_sql 只能写一条只读 SELECT 查询。
  不能使用 INSERT、UPDATE、DELETE、EXEC、SELECT INTO 或多条 SQL。

【常用完整示例】
  [meta]
  title = 体检人员查询
  group = 综合查询
  description = 按日期、科室和人员信息查询

  [params]
  start_date = 开始日期 | date | {today} | required
  end_date = 结束日期 | date | {today} | required
  department = 科室 | select:全部 | 全部 | searchable | options_sql=SELECT DISTINCT DepartmentName FROM Department WHERE Enabled=1 ORDER BY DepartmentName
  doctor = 医生 | select | | searchable | options_sql=SELECT DoctorID, DoctorName FROM Doctor WHERE Enabled=1 ORDER BY DoctorName
  keyword = 姓名/体检号 | text | | placeholder=请输入姓名或体检号

  [sql]
  SELECT ...
  FROM ...
  WHERE CheckDate BETWEEN '{start_date}' AND '{end_date}'
    AND DepartmentName = '{department}'
    AND DoctorID = '{doctor}'

【其他说明】
  [meta] 可填写 title、group、description；type 默认 select。
  SELECT 模式仅允许查询；exec 模式仅允许受控存储过程调用。参数中的单引号会自动转义。"""
        dialog = QDialog(self)
        dialog.setWindowTitle("表单格式说明")
        dialog.setMinimumSize(760, 560)
        dialog.resize(850, 680)
        layout = QVBoxLayout(dialog)
        title = QLabel(".qry 表单格式说明")
        title.setStyleSheet("font-size: 16px; font-weight: bold;")
        viewer = QPlainTextEdit()
        viewer.setReadOnly(True)
        viewer.setPlainText(text)
        mono_font = QFont("Courier New", 10)
        mono_font.setStyleHint(QFont.TypeWriter)
        viewer.setFont(mono_font)
        close_btn = QPushButton("关闭")
        close_btn.clicked.connect(dialog.accept)
        button_row = QHBoxLayout()
        button_row.addStretch()
        button_row.addWidget(close_btn)
        layout.addWidget(title)
        layout.addWidget(viewer, stretch=1)
        layout.addLayout(button_row)
        dialog.exec_()
