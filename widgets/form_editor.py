# -*- coding: utf-8 -*-
"""
表单编辑器对话框
支持新建和编辑 .qry 文件，带语法高亮
"""
import os
import re
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QPlainTextEdit, QGroupBox, QFormLayout, QCheckBox,
    QMessageBox, QFileDialog, QSizePolicy, QComboBox
)
from PyQt5.QtCore import Qt, QObject, QEvent, QTimer
from PyQt5.QtGui import (
    QFont, QTextCharFormat, QColor, QSyntaxHighlighter, QFontMetrics
)
from form_parser import TEMPLATE, FormParser
from core.param_service import validate_options_sql, sql_placeholders


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


class ComboLineEditClickFilter(QObject):
    """确保点击可编辑 QComboBox 的输入框区域时，也能直接触发弹出下拉菜单"""

    def __init__(self, combo):
        super(ComboLineEditClickFilter, self).__init__(combo)
        self.combo = combo

    def eventFilter(self, obj, event):
        if event.type() == QEvent.MouseButtonPress:
            if not self.combo.view().isVisible():
                QTimer.singleShot(10, self.combo.showPopup)
        return False


# ──────────────────────────────────────────────
#  对话框主体
# ──────────────────────────────────────────────
class FormEditorDialog(QDialog):

    def __init__(self, form, forms_dir, parent=None, default_group=None, db_manager=None):
        """
        form          : QueryForm（编辑已有表单）或 None（新建）
        forms_dir     : forms 根目录路径
        default_group : 预选分组名称（新建表单时）
        db_manager    : 可选的数据库管理器实例
        """
        super(FormEditorDialog, self).__init__(parent)
        self.form          = form
        self.forms_dir     = forms_dir
        self.parent_window = parent
        self.db_manager    = db_manager or getattr(parent, 'db_manager', None)
        self.default_group = default_group or (form.group if form else '默认')
        self.setWindowTitle("编辑表单" if form else "新建表单")
        self.setMinimumSize(720, 600)
        self.resize(840, 680)
        self._setup_ui()
        if form:
            self._load_form_file()
        else:
            init_text = TEMPLATE.replace('group = 默认', 'group = {}'.format(self.default_group))
            self.editor.setPlainText(init_text)

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

        # 表单属性与所属分组设置（新建和编辑模式均支持下拉选择或输入分组）
        info_grp = QGroupBox("表单信息与所属分组")
        info_form = QFormLayout(info_grp)
        info_form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        info_form.setContentsMargins(10, 8, 10, 8)
        info_form.setVerticalSpacing(6)

        # 所属分组下拉框（可编辑下拉框）
        self.group_combo = QComboBox()
        self.group_combo.setEditable(True)
        self.group_combo.setInsertPolicy(QComboBox.NoInsert)
        self.group_combo.setMinimumHeight(26)
        self.group_combo.setMaxVisibleItems(15)
        self.group_combo.setToolTip("可直接下拉选择已有分组，或直接输入新分组名称（保存时将自动归入对应文件夹）")
        if self.group_combo.lineEdit():
            self._combo_click_filter = ComboLineEditClickFilter(self.group_combo)
            self.group_combo.lineEdit().installEventFilter(self._combo_click_filter)

        existing_groups = []
        if os.path.isdir(self.forms_dir):
            for name in sorted(os.listdir(self.forms_dir)):
                full = os.path.join(self.forms_dir, name)
                if os.path.isdir(full) and not name.startswith(('.', '_')):
                    existing_groups.append(name)
        if '默认' not in existing_groups:
            existing_groups.insert(0, '默认')
        if self.form and self.form.group and self.form.group not in existing_groups:
            existing_groups.append(self.form.group)
        self.group_combo.addItems(existing_groups)

        initial_group = (self.form.group if self.form and self.form.group else self.default_group) or '默认'
        idx = self.group_combo.findText(initial_group)
        if idx >= 0:
            self.group_combo.setCurrentIndex(idx)
        else:
            self.group_combo.setEditText(initial_group)

        self.group_combo.currentTextChanged.connect(self._on_group_combo_changed)

        group_row = QHBoxLayout()
        group_row.addWidget(self.group_combo, stretch=1)
        group_hint = QLabel("（可下拉选择已有分组，或直接输入新分组名称）")
        group_hint.setStyleSheet("color: #7A869A; font-size: 11px;")
        group_row.addWidget(group_hint)
        info_form.addRow("所属分组:", group_row)

        if not self.form:
            self.filename_edit = QLineEdit()
            self.filename_edit.setPlaceholderText("文件名（不含 .qry 扩展名）")
            info_form.addRow("文件名称:", self.filename_edit)
        else:
            self.filename_label = QLabel(os.path.basename(self.form.file_path))
            self.filename_label.setStyleSheet("color: #333; font-weight: bold;")
            info_form.addRow("当前文件:", self.filename_label)

        access_row = QHBoxLayout()
        self.web_enabled_check = QCheckBox(u"允许已登录 Web 用户查看此表单")
        self.web_enabled_check.setChecked(False)
        self.web_enabled_check.setToolTip(
            u"默认不允许。勾选后，已登录的 Web/嵌入页用户才能看到和执行该表单。"
        )
        access_hint = QLabel(u"默认关闭，桌面端不受影响")
        access_hint.setStyleSheet("color: #667085; font-size: 11px;")
        access_row.addWidget(self.web_enabled_check)
        access_row.addWidget(access_hint)
        access_row.addStretch()
        info_form.addRow("Web 权限:", access_row)

        layout.addWidget(info_grp)

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

        # 底部按钮栏
        btn_row = QHBoxLayout()
        btn_row.addWidget(self.cursor_lbl)
        btn_row.addStretch()

        # 保存退出时校验复选框（默认勾选）
        self.validate_on_save_check = QCheckBox("保存退出时校验")
        self.validate_on_save_check.setChecked(True)
        self.validate_on_save_check.setToolTip("勾选后，点击保存时将先自动执行完整校验；若存在错误将阻止保存")
        btn_row.addWidget(self.validate_on_save_check)

        # 独立校验按钮
        self.validate_btn = QPushButton("校验")
        self.validate_btn.setToolTip("单独校验当前表单配置与 SQL 脚本，不保存退出")
        self.validate_btn.clicked.connect(self._on_validate_clicked)
        btn_row.addWidget(self.validate_btn)

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
                raw_text = f.read()
            self.editor.setPlainText(raw_text)
            self.web_enabled_check.setChecked(bool(getattr(self.form, 'web_enabled', False)))

            # 从文件 [meta] 或 self.form 中回填分组到下拉框
            grp = getattr(self.form, 'group', None) or '默认'
            meta_m = re.search(r'\[meta\](.*?)(?=\n\s*\[|\Z)', raw_text, re.DOTALL | re.IGNORECASE)
            if meta_m:
                for line in meta_m.group(1).splitlines():
                    line = line.strip()
                    if line.startswith(('#', ';')):
                        continue
                    if '=' in line:
                        k, v = line.split('=', 1)
                        if k.strip().lower() == 'group' and v.strip():
                            grp = v.strip()
                            break

            self.group_combo.blockSignals(True)
            idx = self.group_combo.findText(grp)
            if idx >= 0:
                self.group_combo.setCurrentIndex(idx)
            else:
                self.group_combo.setEditText(grp)
            self.group_combo.blockSignals(False)
        except Exception as e:
            QMessageBox.warning(self, "读取失败", "无法读取文件：\n{}".format(e))

    def _on_group_combo_changed(self, new_group):
        """当用户切换或修改所属分组时，同步更新编辑器 [meta] 中的 group 属性"""
        new_group = new_group.strip() or '默认'
        content = self.editor.toPlainText()
        updated = self._apply_group(content, new_group)
        if updated != content:
            cursor = self.editor.textCursor()
            pos = cursor.position()
            self.editor.setPlainText(updated)
            cursor.setPosition(min(pos, len(updated)))
            self.editor.setTextCursor(cursor)

    def _apply_group(self, content, group_name):
        """确保将 group 安全写入 [meta]，保持其他元数据和旧格式。"""
        meta_m = re.search(r'\[meta\](.*?)(?=\n\s*\[|\Z)', content,
                           re.DOTALL | re.IGNORECASE)
        if not meta_m:
            return content

        meta_body = meta_m.group(1)
        grp_line = re.compile(r'^\s*group\s*=.*$', re.MULTILINE | re.IGNORECASE)
        if grp_line.search(meta_body):
            meta_body = grp_line.sub('group = ' + group_name, meta_body)
        else:
            meta_body = meta_body.rstrip() + '\ngroup = ' + group_name + '\n'
        start, end = meta_m.span(1)
        return content[:start] + meta_body + content[end:]

    def _apply_web_enabled(self, content):
        """将可视开关安全写入 [meta]，保留其他元数据和旧格式。"""
        meta_m = re.search(r'\[meta\](.*?)(?=\n\s*\[|\Z)', content,
                           re.DOTALL | re.IGNORECASE)
        if not meta_m:
            return content

        value = 'true' if self.web_enabled_check.isChecked() else 'false'
        meta_body = meta_m.group(1)
        web_line = re.compile(r'^\s*web_enabled\s*=.*$', re.MULTILINE | re.IGNORECASE)
        if web_line.search(meta_body):
            meta_body = web_line.sub('web_enabled = ' + value, meta_body)
        else:
            meta_body = meta_body.rstrip() + '\nweb_enabled = ' + value + '\n'
        start, end = meta_m.span(1)
        return content[:start] + meta_body + content[end:]

    def validate_form(self, content=None):
        """
        校验表单元信息、参数定义与 SQL 脚本。
        返回 (is_valid: bool, errors: list[str], warnings: list[str])
        """
        if content is None:
            content = self.editor.toPlainText()

        errors = []
        warnings = []

        if not content or not content.strip():
            errors.append("表单内容为空")
            return False, errors, warnings

        # 1. 提取各配置段
        meta_section = FormParser._get_section(content, 'meta')
        params_section = FormParser._get_section(content, 'params')
        sql_section = FormParser._get_section(content, 'sql')

        if not meta_section:
            warnings.append("未找到 [meta] 配置段，建议补充表单元数据（title、group 等）")

        if not sql_section:
            errors.append("未找到 [sql] 配置段，表单必须包含 SQL 执行脚本")

        # 2. 校验 [meta]
        query_type = 'select'
        meta_title = ''
        if meta_section:
            for line in meta_section.splitlines():
                line = line.strip()
                if not line or line.startswith(('#', ';')):
                    continue
                if '=' in line:
                    k, v = line.split('=', 1)
                    k = k.strip().lower()
                    v = v.strip()
                    if k == 'type':
                        query_type = v.lower()
                        if query_type not in ('select', 'exec'):
                            errors.append("元数据 [meta] 中的 type='{}' 无效，仅支持 select 或 exec".format(v))
                    elif k == 'title':
                        meta_title = v
                    elif k == 'web_enabled':
                        if v.lower() not in ('true', 'false', '1', '0', 'yes', 'no', '是', '否'):
                            warnings.append("元数据 web_enabled='{}' 不是标准布尔值（建议使用 true 或 false）".format(v))

            if not meta_title:
                warnings.append("元数据 [meta] 未配置 title，系统将默认使用文件名作为表单标题")

        # 3. 校验 [params]
        defined_params = set()
        if params_section:
            for line_no, line in enumerate(params_section.splitlines(), 1):
                token = line.strip()
                if not token or token.startswith(('#', ';')):
                    continue
                if '=' not in token:
                    errors.append("[params] 第 {} 行格式错误：缺少等号 '='（标准格式：参数名 = 显示标签 | 类型 | 默认值 | 属性...）".format(line_no))
                    continue
                raw_name, rest = token.split('=', 1)
                p_name = raw_name.strip()
                if not p_name:
                    errors.append("[params] 第 {} 行参数名为空".format(line_no))
                    continue
                if not re.match(r'^[a-zA-Z_]\w*$', p_name):
                    errors.append("[params] 第 {} 行参数名「{}」不合法，必须以字母或下划线开头，仅包含字母、数字和下划线".format(line_no, p_name))
                    continue
                if p_name in defined_params:
                    errors.append("[params] 第 {} 行参数名「{}」重复定义".format(line_no, p_name))
                defined_params.add(p_name)

                parts = [p.strip() for p in rest.split('|')]
                raw_type = parts[1] if len(parts) >= 2 else 'text'
                ptype, static_opts = FormParser._parse_type(raw_type)

                valid_base_types = ('text', 'date', 'datetime', 'number', 'textarea', 'checkbox', 'hidden', 'select', 'radio')
                clean_type = raw_type.split(':', 1)[0].strip().lower()
                if clean_type not in valid_base_types:
                    warnings.append("[params] 参数「{}」的类型「{}」非系统内置控件类型，将默认按单行文本框显示".format(p_name, raw_type))

                attrs = parts[2:] if len(parts) > 2 else []
                (default_val, placeholder, required, width, options_sql,
                 searchable, allow_custom) = FormParser._parse_param_attributes(attrs)

                if options_sql:
                    ok, reason = validate_options_sql(options_sql)
                    if not ok:
                        errors.append("[params] 参数「{}」的 options_sql 检查失败：{}".format(p_name, reason))

                if clean_type in ('select', 'radio') and not static_opts and not options_sql:
                    warnings.append("[params] 参数「{}」为 {} 类型，但既未配置静态候选项，也未配置 options_sql 动态候选项".format(p_name, clean_type))

        # 4. 校验 [sql]
        sql = sql_section.strip()
        if sql:
            ok, reason = FormParser.is_safe_sql(sql, query_type)
            if not ok:
                errors.append("SQL 安全检查未通过：{}".format(reason))

            # 占位符匹配检查
            placeholders = sql_placeholders(sql)
            for p in placeholders:
                if p.lower() in ('today', 'now'):
                    continue
                if p not in defined_params:
                    errors.append("SQL 中引用了未在 [params] 中定义的参数：{{{}}}".format(p))

            for p in defined_params:
                if p not in placeholders:
                    warnings.append("参数「{}」已在 [params] 中定义，但未在 SQL 脚本中被引用".format(p))

            # 单引号匹配启发式检查（过滤注释）
            no_comment_sql = re.sub(r'--[^\n]*', '', sql)
            no_comment_sql = re.sub(r'/\*.*?\*/', '', no_comment_sql, flags=re.DOTALL)
            clean_quotes = no_comment_sql.replace("''", "")
            if clean_quotes.count("'") % 2 != 0:
                warnings.append("SQL 脚本中的单引号数量不成对，可能存在未闭合的字符串常量")

            # 圆括号匹配启发式检查
            left_p = no_comment_sql.count('(')
            right_p = no_comment_sql.count(')')
            if left_p != right_p:
                warnings.append("SQL 脚本中的圆括号数量不匹配（左括号 {} 个，右括号 {} 个）".format(left_p, right_p))

        is_valid = (len(errors) == 0)
        return is_valid, errors, warnings

    def _on_validate_clicked(self):
        """单独执行表单校验并弹窗展示结果"""
        is_valid, errors, warnings = self.validate_form()
        if errors:
            msg = "表单校验未通过，发现以下错误：\n\n"
            msg += "\n".join("❌ " + e for e in errors)
            if warnings:
                msg += "\n\n另外发现以下建议项：\n\n"
                msg += "\n".join("⚠️ " + w for w in warnings)
            QMessageBox.critical(self, "表单校验未通过", msg)
        elif warnings:
            msg = "表单基本校验通过，但发现以下建议项：\n\n"
            msg += "\n".join("⚠️ " + w for w in warnings)
            QMessageBox.warning(self, "表单校验提醒", msg)
        else:
            QMessageBox.information(
                self, "表单校验通过",
                "✅ 校验通过！\n\n表单元数据配置、参数定义与 SQL 脚本结构完整无误。"
            )

    def _get_save_path(self):
        """获取保存路径；返回 None 表示用户取消或输入无效"""
        # 目标分组优先取下拉框输入值，同时兼顾用户直接在编辑器中手动修改的 group
        target_group = self.group_combo.currentText().strip() or '默认'
        content = self.editor.toPlainText()
        meta_m = re.search(r'\[meta\](.*?)(?=\n\s*\[|\Z)', content, re.DOTALL | re.IGNORECASE)
        if meta_m:
            for line in meta_m.group(1).splitlines():
                line = line.strip()
                if line.startswith(('#', ';')):
                    continue
                if '=' in line:
                    k, v = line.split('=', 1)
                    if k.strip().lower() == 'group' and v.strip():
                        target_group = v.strip()
                        break

        target_group = re.sub(r'[\\/:*?"<>|]', '_', target_group)

        if self.form:
            current_dir = os.path.dirname(os.path.abspath(self.form.file_path))
            target_dir = os.path.abspath(os.path.join(self.forms_dir, target_group))
            if current_dir != target_dir:
                # 分组发生变更，移动到新分组目录
                os.makedirs(target_dir, exist_ok=True)
                new_path = os.path.join(target_dir, os.path.basename(self.form.file_path))
                if os.path.exists(new_path) and os.path.abspath(new_path) != os.path.abspath(self.form.file_path):
                    reply = QMessageBox.question(
                        self, "确认覆盖",
                        "目标分组下已存在同名表单文件，是否覆盖？\n\n{}".format(new_path),
                        QMessageBox.Yes | QMessageBox.No
                    )
                    if reply != QMessageBox.Yes:
                        return None
                return new_path
            return self.form.file_path

        name = self.filename_edit.text().strip()
        if not name:
            QMessageBox.warning(self, "提示", "请输入文件名")
            return None

        # 清理非法字符
        name = re.sub(r'[\\/:*?"<>|]', '_', name)
        group_dir = os.path.join(self.forms_dir, target_group)
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
        # 根据实际保存路径的目录推断并规范化 group
        folder_group = os.path.basename(os.path.dirname(path))
        if folder_group.lower() == 'forms':
            folder_group = self.group_combo.currentText().strip() or '默认'

        raw_content = self.editor.toPlainText()
        content = self._apply_group(raw_content, folder_group)
        content = self._apply_web_enabled(content)

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
            self.editor.setPlainText(content)
            self.saved_group = folder_group
            self.saved_path = path

            # 如果已有表单保存到了新路径（如修改了分组），移除旧位置文件
            if self.form and self.form.file_path and os.path.abspath(path) != os.path.abspath(self.form.file_path):
                old_path = self.form.file_path
                try:
                    if os.path.exists(old_path):
                        os.remove(old_path)
                except Exception:
                    pass
                self.form.file_path = path
                self.form.group = folder_group

            return True
        except Exception as e:
            QMessageBox.critical(self, "保存失败", str(e))
            return False

    def _save(self):
        if self.validate_on_save_check.isChecked():
            is_valid, errors, warnings = self.validate_form()
            if errors:
                msg = "表单存在以下错误，无法保存：\n\n"
                msg += "\n".join("❌ " + e for e in errors)
                msg += "\n\n请修正错误后再保存，或取消勾选「保存退出时校验」。"
                QMessageBox.critical(self, "保存受阻 - 表单校验未通过", msg)
                return
            if warnings:
                msg = "表单发现以下建议项：\n\n"
                msg += "\n".join("⚠️ " + w for w in warnings)
                msg += "\n\n是否仍然确认保存？"
                reply = QMessageBox.warning(
                    self, "保存确认 - 存在校验警告", msg,
                    QMessageBox.Yes | QMessageBox.No
                )
                if reply != QMessageBox.Yes:
                    return

        path = self._get_save_path()
        if path is None:
            return
        if self._do_save(path):
            QMessageBox.information(self, "保存成功",
                                    "表单已保存：\n{}".format(path))
            self.accept()

    def _save_as(self):
        if self.validate_on_save_check.isChecked():
            is_valid, errors, warnings = self.validate_form()
            if errors:
                msg = "表单存在以下错误，无法另存为：\n\n"
                msg += "\n".join("❌ " + e for e in errors)
                msg += "\n\n请修正错误后再另存为，或取消勾选「保存退出时校验」。"
                QMessageBox.critical(self, "另存为受阻 - 表单校验未通过", msg)
                return
            if warnings:
                msg = "表单发现以下建议项：\n\n"
                msg += "\n".join("⚠️ " + w for w in warnings)
                msg += "\n\n是否仍然确认另存为？"
                reply = QMessageBox.warning(
                    self, "另存为确认 - 存在校验警告", msg,
                    QMessageBox.Yes | QMessageBox.No
                )
                if reply != QMessageBox.Yes:
                    return

        default_dir = os.path.join(self.forms_dir, self.form.group or '默认') if self.form else self.forms_dir
        default = os.path.join(
            default_dir,
            os.path.basename(self.form.file_path if self.form else 'new_form.qry')
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
  默认值是类型后的第一个普通字段；没有默认值时保留空位，例如：keyword = 关键词 | text | | placeholder=请输入关键词
  以 # 或 ; 开头的整行是注释，不会作为查询条件。

【查询条件类型】
  text                 单行文字输入。
  textarea             多行文字输入。
  date                 日期，格式 yyyy-MM-dd。
  datetime             日期时间，格式 yyyy-MM-dd HH:mm:ss。
  number               仅允许有效数字。
  checkbox             选中提交 1，未选中提交 0。
  radio:A,B            单选项，提交选中项的值。
  hidden               不显示，始终提交配置的默认值。
  select:A,B,C         下拉框；可写静态候选，也可加 options_sql 从数据库加载候选项。

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
  allow_custom 是可搜索 Select 的自定义输入开关。
  allow_custom=false：默认值，必须选择候选项，临时搜索文字不能作为 SQL 参数。
  allow_custom=true：允许直接输入候选列表中没有的内容。

  例如：
    keyword_type = 关键词类型 | select:姓名,体检号 | 姓名 | allow_custom=true

【主查询类型】
  type = select：默认值；[sql] 必须以 SELECT 开头。
  type = exec：仅在调用受控存储过程时使用；[sql] 必须以 EXEC 或 EXECUTE 开头。
  type 写在 [meta] 段，例如：type = exec。

【Web 访问权限】
  web_enabled = false：默认值；该表单仅可在 EXE 中查看和使用，Web/嵌入页不显示也不能直接访问。
  web_enabled = true：已登录的 Web 用户可以查看、加载候选项、执行查询和导出。
  在本窗口直接勾选“允许已登录 Web 用户查看此表单”即可自动写入该配置。
  Web 用户未登录时，不能查看任何表单或调用查询接口。

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
  web_enabled = true

  [params]
  start_date = 开始日期 | date | {today} | required
  end_date = 结束日期 | date | {today} | required
  department = 科室 | select:全部 | 全部 | searchable | options_sql=SELECT DISTINCT Department FROM Employee WHERE Department IS NOT NULL ORDER BY Department
  doctor = 医生 | select | | searchable | options_sql=SELECT DoctorID, DoctorName FROM Doctor WHERE Enabled=1 ORDER BY DoctorName
  keyword = 姓名/体检号 | text | | placeholder=请输入姓名或体检号

  [sql]
  SELECT ...
  FROM ...
  WHERE CheckDate BETWEEN '{start_date}' AND '{end_date}'
    AND Department = '{department}'
    AND DoctorID = '{doctor}'

【其他说明】
  [meta] 可填写 title、group、description、web_enabled；type 默认 select。
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
