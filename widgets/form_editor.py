# -*- coding: utf-8 -*-
"""
表单设计器对话框
支持可视化设计（基本信息、查询参数、多区块与排版）与源码模式实时双向同步，带语法高亮与多维安全校验。
"""
import os
import re
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QPlainTextEdit, QGroupBox, QFormLayout, QCheckBox,
    QMessageBox, QFileDialog, QSizePolicy, QComboBox, QTabWidget,
    QWidget, QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
    QSplitter, QScrollArea, QFrame, QToolButton
)
from PyQt5.QtCore import Qt, QObject, QEvent, QTimer
from PyQt5.QtGui import (
    QFont, QTextCharFormat, QColor, QSyntaxHighlighter, QFontMetrics
)
from form_parser import TEMPLATE, FormParser, QueryForm, QueryParam, QueryBlock
from core.param_service import validate_options_sql, sql_placeholders
from core.sql_safety import normalize_sql_for_safety


# ──────────────────────────────────────────────
#  语法高亮器
# ──────────────────────────────────────────────
class QryHighlighter(QSyntaxHighlighter):
    """为 .qry 文件及 SQL 编辑器提供语法高亮"""

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

        # Section 标题 [meta] [params] [sql] [block.xxx]
        self.rules.append(
            (re.compile(r'^\s*\[[\w\s\.\-]+\]', re.MULTILINE),
             fmt('#8B4513', bold=True))
        )
        # key = value 行的 key 部分
        self.rules.append(
            (re.compile(r'^\s*[a-zA-Z_]\w*\s*(?==)', re.MULTILINE),
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
        # 参数扩展属性与控件类型
        self.rules.append(
            (re.compile(r'\b(options_sql|searchable|allow_custom|required|placeholder|width|datasource|summary_footer|layout)\b', re.IGNORECASE),
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
#  对话框主体：双模式可视化表单设计器
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

        # 内部状态控制
        self._syncing = False
        self._loading_param = False
        self._loading_block = False
        self._selected_param_index = -1
        self._selected_block_index = -1
        self._params_data = []
        self._blocks_data = []
        self._prev_tab_index = 0

        self.setWindowTitle("表单设计器 - 编辑表单" if form else "表单设计器 - 新建表单")
        self.setMinimumSize(880, 640)
        self.resize(1000, 720)

        self._setup_ui()

        if form:
            self._load_form_file()
        else:
            init_text = TEMPLATE.replace('group = 默认', 'group = {}'.format(self.default_group))
            self.editor.setPlainText(init_text)
            self._sync_raw_to_visual()

    # ── UI 布局搭建 ────────────────────────────
    def _setup_ui(self):
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(12, 12, 12, 10)
        root_layout.setSpacing(8)

        # 顶部：路径提示 + 帮助按钮
        top_row = QHBoxLayout()
        self.path_label = QLabel(
            "文件: " + (self.form.file_path if self.form else "（尚未保存）")
        )
        self.path_label.setStyleSheet("color: #555; font-size: 11px;")
        help_btn = QPushButton("格式说明")
        help_btn.setFixedWidth(85)
        help_btn.clicked.connect(self._show_help)
        top_row.addWidget(self.path_label)
        top_row.addStretch()
        top_row.addWidget(help_btn)
        root_layout.addLayout(top_row)

        # 核心 Tab 容器（4个标签页：基本信息、查询参数、区块与排版、源码模式）
        self.tab_widget = QTabWidget()
        self.tab_widget.setStyleSheet("""
            QTabBar::tab {
                padding: 6px 16px;
                font-size: 12px;
                min-width: 90px;
            }
            QTabBar::tab:selected {
                font-weight: bold;
            }
        """)

        self.tab_widget.addTab(self._create_meta_tab(), "📋 基本信息")
        self.tab_widget.addTab(self._create_params_tab(), "⚙️ 查询条件")
        self.tab_widget.addTab(self._create_blocks_tab(), "📊 报表区块与排版")
        self.tab_widget.addTab(self._create_raw_tab(), "📝 源码模式 (.qry)")
        self.tab_widget.currentChanged.connect(self._on_tab_changed)
        root_layout.addWidget(self.tab_widget, stretch=1)

        # 底部操作栏
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)

        # 行号 / 状态指示
        self.cursor_lbl = QLabel("行 1，列 1")
        self.cursor_lbl.setStyleSheet("color: #666; font-size: 11px;")
        self.editor.cursorPositionChanged.connect(self._update_cursor_pos)
        btn_row.addWidget(self.cursor_lbl)
        btn_row.addStretch()

        self.validate_on_save_check = QCheckBox("保存退出时校验")
        self.validate_on_save_check.setChecked(True)
        self.validate_on_save_check.setToolTip("勾选后，点击保存时将先自动执行完整校验；若存在错误将阻止保存")
        btn_row.addWidget(self.validate_on_save_check)

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
        root_layout.addLayout(btn_row)

    # ── Tab 0: 基本信息 (Meta) ─────────────────
    def _create_meta_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)

        # 分组一：表单基本属性
        info_grp = QGroupBox("表单信息与分类")
        info_form = QFormLayout(info_grp)
        info_form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        info_form.setContentsMargins(12, 10, 12, 10)
        info_form.setVerticalSpacing(8)

        self.title_edit = QLineEdit()
        self.title_edit.setPlaceholderText("请输入表单标题（如：体检人员统计）")
        self.title_edit.textChanged.connect(self._on_meta_field_changed)
        info_form.addRow("表单标题:", self.title_edit)

        # 所属分组（保持兼容属性 self.group_combo）
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

        # 显示排序（保持兼容属性 self.order_edit）
        order_row = QHBoxLayout()
        self.order_edit = QLineEdit()
        self.order_edit.setPlaceholderText("排序序号（数字，越小越靠前，留空默认按名称自然排序）")
        self.order_edit.setToolTip("设置表单在分组内的排序顺序，数值越小越靠前（例如 1, 2, 10 等）")
        order_row.addWidget(self.order_edit, stretch=1)
        order_hint = QLabel("（数值越小越靠前，留空默认按名称自然排序）")
        order_hint.setStyleSheet("color: #7A869A; font-size: 11px;")
        order_row.addWidget(order_hint)
        info_form.addRow("显示排序:", order_row)
        self.order_edit.textChanged.connect(self._on_order_edit_changed)

        self.desc_edit = QLineEdit()
        self.desc_edit.setPlaceholderText("表单的简要说明或用途（可选）")
        self.desc_edit.textChanged.connect(self._on_meta_field_changed)
        info_form.addRow("表单描述:", self.desc_edit)

        layout.addWidget(info_grp)

        # 分组二：执行属性与高级配置
        adv_grp = QGroupBox("执行特性与多数据源设置")
        adv_form = QFormLayout(adv_grp)
        adv_form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        adv_form.setContentsMargins(12, 10, 12, 10)
        adv_form.setVerticalSpacing(8)

        # 默认数据源下拉选择
        self.datasource_combo = QComboBox()
        self.datasource_combo.setEditable(True)
        self._populate_datasources(self.datasource_combo)
        self.datasource_combo.currentTextChanged.connect(self._on_meta_field_changed)
        ds_row = QHBoxLayout()
        ds_row.addWidget(self.datasource_combo, stretch=1)
        ds_hint = QLabel("（缺省为主库 default，支持跨库配置命名数据源）")
        ds_hint.setStyleSheet("color: #7A869A; font-size: 11px;")
        ds_row.addWidget(ds_hint)
        adv_form.addRow("默认数据源:", ds_row)

        # 查询类型 (select / exec)
        self.query_type_combo = QComboBox()
        self.query_type_combo.addItem("select - 标准数据查询 (SELECT)", "select")
        self.query_type_combo.addItem("exec - 受控存储过程调用 (EXEC)", "exec")
        self.query_type_combo.currentIndexChanged.connect(self._on_meta_field_changed)
        adv_form.addRow("查询类型:", self.query_type_combo)

        # Web 权限
        access_row = QHBoxLayout()
        self.web_enabled_check = QCheckBox("允许已登录 Web 用户查看此表单")
        self.web_enabled_check.setChecked(False)
        self.web_enabled_check.setToolTip("默认不允许。勾选后，已登录的 Web/嵌入页用户才能看到和执行该表单。")
        self.web_enabled_check.toggled.connect(self._on_web_enabled_toggled)
        access_hint = QLabel("默认关闭，桌面端不受影响")
        access_hint.setStyleSheet("color: #667085; font-size: 11px;")
        access_row.addWidget(self.web_enabled_check)
        access_row.addWidget(access_hint)
        access_row.addStretch()
        adv_form.addRow("Web 权限:", access_row)

        # 默认合计规则
        self.meta_summary_edit = QLineEdit()
        self.meta_summary_edit.setPlaceholderText("留空按常规，或填写 auto（自动对数值列求和），或指定 sum:实收金额; count:体检号")
        self.meta_summary_edit.textChanged.connect(self._on_meta_field_changed)
        adv_form.addRow("默认合计规则:", self.meta_summary_edit)

        # 区块排版自定义
        self.layout_edit = QLineEdit()
        self.layout_edit.setPlaceholderText("多区块排版顺序（逗号分隔区块ID，留空默认按下方区块列表顺序）")
        self.layout_edit.textChanged.connect(self._on_meta_field_changed)
        adv_form.addRow("排版顺序(layout):", self.layout_edit)

        layout.addWidget(adv_grp)
        layout.addStretch()
        return tab

    # ── Tab 1: 查询条件 (Params) ───────────────
    def _create_params_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        # 上半部分：参数列表表格 + 操作按钮
        table_grp = QGroupBox("参数列表清单")
        t_layout = QVBoxLayout(table_grp)
        t_layout.setContentsMargins(8, 8, 8, 8)

        btn_bar = QHBoxLayout()
        self.param_add_btn = QPushButton("➕ 添加参数")
        self.param_add_btn.setStyleSheet("background-color: #0052CC; color: white; font-weight: bold; padding: 4px 10px;")
        self.param_add_btn.clicked.connect(self._on_param_add)
        self.param_del_btn = QPushButton("➖ 删除参数")
        self.param_del_btn.clicked.connect(self._on_param_delete)
        self.param_up_btn = QPushButton("⬆️ 上移")
        self.param_up_btn.clicked.connect(self._on_param_move_up)
        self.param_down_btn = QPushButton("⬇️ 下移")
        self.param_down_btn.clicked.connect(self._on_param_move_down)

        btn_bar.addWidget(self.param_add_btn)
        btn_bar.addWidget(self.param_del_btn)
        btn_bar.addWidget(self.param_up_btn)
        btn_bar.addWidget(self.param_down_btn)
        btn_bar.addStretch()
        t_layout.addLayout(btn_bar)

        self.param_table = QTableWidget()
        self.param_table.setColumnCount(5)
        self.param_table.setHorizontalHeaderLabels(["参数名 (ID)", "显示标签", "控件类型", "默认值", "必填"])
        self.param_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Interactive)
        self.param_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Interactive)
        self.param_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Interactive)
        self.param_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.param_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.Interactive)
        self.param_table.setColumnWidth(0, 130)
        self.param_table.setColumnWidth(1, 140)
        self.param_table.setColumnWidth(2, 110)
        self.param_table.setColumnWidth(4, 60)
        self.param_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.param_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.param_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.param_table.itemSelectionChanged.connect(self._on_param_table_selection_changed)
        t_layout.addWidget(self.param_table)

        layout.addWidget(table_grp, stretch=1)

        # 下半部分：当前选中参数属性编辑面板
        self.param_detail_group = QGroupBox("参数详细属性设置")
        p_form = QFormLayout(self.param_detail_group)
        p_form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        p_form.setContentsMargins(10, 8, 10, 8)
        p_form.setVerticalSpacing(6)

        # 参数标识与标签
        id_lbl_row = QHBoxLayout()
        self.p_name_edit = QLineEdit()
        self.p_name_edit.setPlaceholderText("英文标识，如 start_date")
        self.p_name_edit.textChanged.connect(self._save_current_param_details)
        id_lbl_row.addWidget(self.p_name_edit, stretch=1)
        id_lbl_row.addWidget(QLabel("标签:"))
        self.p_label_edit = QLineEdit()
        self.p_label_edit.setPlaceholderText("界面显示，如 开始日期")
        self.p_label_edit.textChanged.connect(self._save_current_param_details)
        id_lbl_row.addWidget(self.p_label_edit, stretch=1)
        p_form.addRow("参数标识/标签:", id_lbl_row)

        # 控件类型与必填
        type_row = QHBoxLayout()
        self.p_type_combo = QComboBox()
        types = [
            ('text', '单行文本 (text)'),
            ('date', '日期选择 (date, yyyy-MM-dd)'),
            ('datetime', '日期时间 (datetime, yyyy-MM-dd HH:mm:ss)'),
            ('number', '数值输入 (number)'),
            ('select', '下拉选择框 (select)'),
            ('radio', '单选项 (radio)'),
            ('textarea', '多行长文本 (textarea)'),
            ('checkbox', '复选框 (checkbox, 1/0)'),
            ('hidden', '隐藏参数 (hidden)')
        ]
        for val, desc in types:
            self.p_type_combo.addItem(desc, val)
        self.p_type_combo.currentIndexChanged.connect(self._on_param_type_changed)
        type_row.addWidget(self.p_type_combo, stretch=2)

        self.p_required_check = QCheckBox("必填项 (required)")
        self.p_required_check.toggled.connect(self._save_current_param_details)
        type_row.addWidget(self.p_required_check)

        self.p_width_edit = QLineEdit()
        self.p_width_edit.setPlaceholderText("宽度 (如 220px, 30%)")
        self.p_width_edit.textChanged.connect(self._save_current_param_details)
        type_row.addWidget(self.p_width_edit, stretch=1)
        p_form.addRow("控件类型/特性:", type_row)

        # 默认值（带快捷填入按键）
        def_row = QHBoxLayout()
        self.p_default_edit = QLineEdit()
        self.p_default_edit.setPlaceholderText("默认填充值，日期可使用 {today}")
        self.p_default_edit.textChanged.connect(self._save_current_param_details)
        def_row.addWidget(self.p_default_edit, stretch=1)

        btn_today = QPushButton("+ {today}")
        btn_today.setToolTip("快捷填入 {today} 动态当天宏")
        btn_today.clicked.connect(lambda: self.p_default_edit.setText("{today}"))
        def_row.addWidget(btn_today)

        self.p_placeholder_edit = QLineEdit()
        self.p_placeholder_edit.setPlaceholderText("输入提示 (placeholder)")
        self.p_placeholder_edit.textChanged.connect(self._save_current_param_details)
        def_row.addWidget(self.p_placeholder_edit, stretch=1)
        p_form.addRow("默认值/提示:", def_row)

        # 候选项设置（针对 select / radio）
        opt_row = QHBoxLayout()
        self.p_options_edit = QLineEdit()
        self.p_options_edit.setPlaceholderText("静态候选项（逗号分隔，如：全部,启用,禁用）")
        self.p_options_edit.textChanged.connect(self._save_current_param_details)
        opt_row.addWidget(self.p_options_edit, stretch=2)

        self.p_searchable_check = QCheckBox("可输入搜索")
        self.p_searchable_check.setChecked(True)
        self.p_searchable_check.toggled.connect(self._save_current_param_details)
        opt_row.addWidget(self.p_searchable_check)

        self.p_allow_custom_check = QCheckBox("允许自定义输入")
        self.p_allow_custom_check.toggled.connect(self._save_current_param_details)
        opt_row.addWidget(self.p_allow_custom_check)
        p_form.addRow("候选项配置:", opt_row)

        # 动态 SQL 候选项
        self.p_options_sql_edit = QLineEdit()
        self.p_options_sql_edit.setPlaceholderText("动态只读 SELECT 语句，返回一列为值，两列为 值,显示标签 (options_sql)")
        self.p_options_sql_edit.textChanged.connect(self._save_current_param_details)
        p_form.addRow("动态候选 SQL:", self.p_options_sql_edit)

        layout.addWidget(self.param_detail_group)
        return tab

    # ── Tab 2: 报表区块与排版 (Blocks & Layout) ─
    def _create_blocks_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        splitter = QSplitter(Qt.Vertical)

        # 上半部分：区块清单表格 + 新建按钮
        block_list_grp = QGroupBox("报表区块清单（支持多数据源与指标卡）")
        b_layout = QVBoxLayout(block_list_grp)
        b_layout.setContentsMargins(8, 8, 8, 8)

        btn_bar = QHBoxLayout()
        self.block_add_table_btn = QPushButton("➕ 新增表格区块 (table)")
        self.block_add_table_btn.setStyleSheet("background-color: #0052CC; color: white; font-weight: bold; padding: 4px 10px;")
        self.block_add_table_btn.clicked.connect(self._on_block_add_table)
        self.block_add_cards_btn = QPushButton("➕ 新增指标卡 (cards)")
        self.block_add_cards_btn.setStyleSheet("background-color: #00875A; color: white; font-weight: bold; padding: 4px 10px;")
        self.block_add_cards_btn.clicked.connect(self._on_block_add_cards)
        self.block_del_btn = QPushButton("➖ 删除区块")
        self.block_del_btn.clicked.connect(self._on_block_delete)
        self.block_up_btn = QPushButton("⬆️ 上移")
        self.block_up_btn.clicked.connect(self._on_block_move_up)
        self.block_down_btn = QPushButton("⬇️ 下移")
        self.block_down_btn.clicked.connect(self._on_block_move_down)

        btn_bar.addWidget(self.block_add_table_btn)
        btn_bar.addWidget(self.block_add_cards_btn)
        btn_bar.addWidget(self.block_del_btn)
        btn_bar.addWidget(self.block_up_btn)
        btn_bar.addWidget(self.block_down_btn)
        btn_bar.addStretch()
        b_layout.addLayout(btn_bar)

        self.block_table = QTableWidget()
        self.block_table.setColumnCount(5)
        self.block_table.setHorizontalHeaderLabels(["区块标识 (ID)", "区块标题", "类型", "独立数据源", "合计规则"])
        self.block_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Interactive)
        self.block_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Interactive)
        self.block_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Interactive)
        self.block_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Interactive)
        self.block_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.Stretch)
        self.block_table.setColumnWidth(0, 110)
        self.block_table.setColumnWidth(1, 140)
        self.block_table.setColumnWidth(2, 90)
        self.block_table.setColumnWidth(3, 110)
        self.block_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.block_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.block_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.block_table.itemSelectionChanged.connect(self._on_block_table_selection_changed)
        b_layout.addWidget(self.block_table)

        splitter.addWidget(block_list_grp)

        # 下半部分：区块配置与 SQL 编辑
        self.block_detail_group = QGroupBox("当前区块配置与 SQL 脚本")
        bd_layout = QVBoxLayout(self.block_detail_group)
        bd_layout.setContentsMargins(10, 8, 10, 8)
        bd_layout.setSpacing(6)

        b_meta_row = QHBoxLayout()
        b_meta_row.addWidget(QLabel("区块标识:"))
        self.b_id_edit = QLineEdit()
        self.b_id_edit.setPlaceholderText("区块ID，如 main, summary, detail")
        self.b_id_edit.textChanged.connect(self._save_current_block_details)
        b_meta_row.addWidget(self.b_id_edit, stretch=1)

        b_meta_row.addWidget(QLabel("标题:"))
        self.b_title_edit = QLineEdit()
        self.b_title_edit.setPlaceholderText("展示标题")
        self.b_title_edit.textChanged.connect(self._save_current_block_details)
        b_meta_row.addWidget(self.b_title_edit, stretch=2)

        b_meta_row.addWidget(QLabel("类型:"))
        self.b_type_combo = QComboBox()
        self.b_type_combo.addItem("table - 明细表格", "table")
        self.b_type_combo.addItem("cards - 指标汇总卡", "cards")
        self.b_type_combo.currentIndexChanged.connect(self._save_current_block_details)
        b_meta_row.addWidget(self.b_type_combo, stretch=1)

        b_meta_row.addWidget(QLabel("数据源:"))
        self.b_ds_combo = QComboBox()
        self.b_ds_combo.setEditable(True)
        self._populate_datasources(self.b_ds_combo)
        self.b_ds_combo.currentTextChanged.connect(self._save_current_block_details)
        b_meta_row.addWidget(self.b_ds_combo, stretch=1)

        bd_layout.addLayout(b_meta_row)

        b_meta_row2 = QHBoxLayout()
        b_meta_row2.addWidget(QLabel("合计规则:"))
        self.b_summary_edit = QLineEdit()
        self.b_summary_edit.setPlaceholderText("auto 或 sum:实收金额; count:体检号")
        self.b_summary_edit.textChanged.connect(self._save_current_block_details)
        b_meta_row2.addWidget(self.b_summary_edit, stretch=2)

        b_meta_row2.addWidget(QLabel("显示宽度:"))
        self.b_width_edit = QLineEdit()
        self.b_width_edit.setPlaceholderText("100% 或 50%")
        self.b_width_edit.textChanged.connect(self._save_current_block_details)
        b_meta_row2.addWidget(self.b_width_edit, stretch=1)
        bd_layout.addLayout(b_meta_row2)

        # ★ 参数快捷插入工具条
        self.quick_param_frame = QFrame()
        self.quick_param_frame.setStyleSheet("background-color: #F4F5F7; border-radius: 4px; padding: 3px;")
        self.quick_param_layout = QHBoxLayout(self.quick_param_frame)
        self.quick_param_layout.setContentsMargins(6, 2, 6, 2)
        self.quick_param_layout.setSpacing(6)
        bd_layout.addWidget(self.quick_param_frame)

        # SQL 编辑框
        self.b_sql_edit = QPlainTextEdit()
        mono_font = QFont("Courier New", 10)
        mono_font.setStyleHint(QFont.TypeWriter)
        self.b_sql_edit.setFont(mono_font)
        metrics = QFontMetrics(mono_font)
        self.b_sql_edit.setTabStopDistance(metrics.width(' ') * 4)
        self.b_sql_edit.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.b_highlighter = QryHighlighter(self.b_sql_edit.document())
        self.b_sql_edit.textChanged.connect(self._on_b_sql_changed)
        bd_layout.addWidget(self.b_sql_edit, stretch=1)

        b_sql_status = QHBoxLayout()
        self.b_cursor_lbl = QLabel("行 1，列 1")
        self.b_cursor_lbl.setStyleSheet("color: #666; font-size: 11px;")
        self.b_sql_edit.cursorPositionChanged.connect(self._update_block_cursor_pos)
        b_sql_status.addWidget(self.b_cursor_lbl)
        b_sql_status.addStretch()
        sql_tip = QLabel("提示：在 SQL 中使用 {参数名} 引用参数，例如：WHERE RegDate >= '{start_date}'")
        sql_tip.setStyleSheet("color: #0052CC; font-size: 11px;")
        b_sql_status.addWidget(sql_tip)
        bd_layout.addLayout(b_sql_status)

        splitter.addWidget(self.block_detail_group)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 5)

        layout.addWidget(splitter)
        return tab

    # ── Tab 3: 源码模式 (Raw .qry) ─────────────
    def _create_raw_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(6)

        info_bar = QHBoxLayout()
        info_lbl = QLabel("💡 提示：在此处可直接查看与编辑完整的 .qry 纯文本代码。切换到其他标签页时会自动双向同步。")
        info_lbl.setStyleSheet("color: #0747A6; font-size: 11px;")
        info_bar.addWidget(info_lbl)
        info_bar.addStretch()

        self.btn_sync_to_visual = QPushButton("🔄 立即同步到可视化设计器")
        self.btn_sync_to_visual.setToolTip("手动解析当前纯文本内容并更新至可视化标签页")
        self.btn_sync_to_visual.clicked.connect(self._sync_raw_to_visual)
        info_bar.addWidget(self.btn_sync_to_visual)
        layout.addLayout(info_bar)

        self.editor = QPlainTextEdit()
        mono_font = QFont("Courier New", 10)
        mono_font.setStyleHint(QFont.TypeWriter)
        self.editor.setFont(mono_font)
        metrics = QFontMetrics(mono_font)
        self.editor.setTabStopDistance(metrics.width(' ') * 4)
        self.editor.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.highlighter = QryHighlighter(self.editor.document())
        layout.addWidget(self.editor, stretch=1)

        return tab

    # ── 数据源辅助填充 ─────────────────────────
    def _populate_datasources(self, combo):
        combo.clear()
        combo.addItem("default (默认主库)", "default")
        datasources = {}
        if self.db_manager and hasattr(self.db_manager, 'get_datasources'):
            try:
                datasources = self.db_manager.get_datasources()
            except Exception:
                pass
        else:
            try:
                from db_manager import DBManager
                mgr = DBManager()
                datasources = mgr.get_datasources()
            except Exception:
                pass

        for ds_id, info in datasources.items():
            if ds_id.lower() != 'default':
                name = info.get('name', ds_id)
                combo.addItem(f"{ds_id} - {name}", ds_id)

    # ── 参数管理逻辑 ───────────────────────────
    def _reload_param_table(self, select_row=0):
        self.param_table.blockSignals(True)
        self.param_table.setRowCount(len(self._params_data))
        for r, p in enumerate(self._params_data):
            self.param_table.setItem(r, 0, QTableWidgetItem(p.name or ''))
            self.param_table.setItem(r, 1, QTableWidgetItem(p.label or ''))
            self.param_table.setItem(r, 2, QTableWidgetItem(p.ptype or 'text'))
            self.param_table.setItem(r, 3, QTableWidgetItem(str(p.default or '')))
            self.param_table.setItem(r, 4, QTableWidgetItem("是" if p.required else "否"))
        self.param_table.blockSignals(False)

        if self._params_data:
            r = max(0, min(select_row, len(self._params_data) - 1))
            self.param_table.selectRow(r)
            self._selected_param_index = r
            self._load_param_to_details(self._params_data[r])
        else:
            self._selected_param_index = -1
            self.param_detail_group.setEnabled(False)

    def _on_param_table_selection_changed(self):
        row = self.param_table.currentRow()
        if 0 <= row < len(self._params_data):
            self._selected_param_index = row
            self.param_detail_group.setEnabled(True)
            self._load_param_to_details(self._params_data[row])
        else:
            self._selected_param_index = -1
            self.param_detail_group.setEnabled(False)

    def _load_param_to_details(self, param):
        self._loading_param = True
        try:
            self.p_name_edit.setText(param.name or '')
            self.p_label_edit.setText(param.label or '')

            # 控件类型匹配
            idx = self.p_type_combo.findData(param.ptype)
            if idx >= 0:
                self.p_type_combo.setCurrentIndex(idx)
            else:
                self.p_type_combo.setCurrentIndex(0)

            self.p_default_edit.setText(str(param.default or ''))
            self.p_required_check.setChecked(bool(param.required))
            self.p_width_edit.setText(param.width or '')
            self.p_placeholder_edit.setText(param.placeholder or '')

            opts = ','.join(param.options) if getattr(param, 'options', None) else ''
            self.p_options_edit.setText(opts)
            self.p_options_sql_edit.setText(getattr(param, 'options_sql', '') or '')
            self.p_searchable_check.setChecked(bool(getattr(param, 'searchable', False)))
            self.p_allow_custom_check.setChecked(bool(getattr(param, 'allow_custom', False)))

            is_opt = param.ptype in ('select', 'radio')
            self.p_options_edit.setEnabled(is_opt)
            self.p_options_sql_edit.setEnabled(is_opt)
            self.p_searchable_check.setEnabled(param.ptype == 'select')
            self.p_allow_custom_check.setEnabled(is_opt)
        finally:
            self._loading_param = False

    def _on_param_type_changed(self, idx):
        ptype = self.p_type_combo.currentData() or 'text'
        is_opt = ptype in ('select', 'radio')
        self.p_options_edit.setEnabled(is_opt)
        self.p_options_sql_edit.setEnabled(is_opt)
        self.p_searchable_check.setEnabled(ptype == 'select')
        self.p_allow_custom_check.setEnabled(is_opt)
        self._save_current_param_details()

    def _save_current_param_details(self):
        if self._loading_param:
            return
        row = self._selected_param_index
        if 0 <= row < len(self._params_data):
            p = self._params_data[row]
            p.name = self.p_name_edit.text().strip()
            p.label = self.p_label_edit.text().strip()
            p.ptype = self.p_type_combo.currentData() or 'text'
            p.default = self.p_default_edit.text().strip()
            p.required = self.p_required_check.isChecked()
            p.width = self.p_width_edit.text().strip()
            p.placeholder = self.p_placeholder_edit.text().strip()

            raw_opts = self.p_options_edit.text().strip()
            p.options = [x.strip() for x in raw_opts.split(',') if x.strip()] if raw_opts else []
            p.options_sql = self.p_options_sql_edit.text().strip()
            p.searchable = self.p_searchable_check.isChecked()
            p.allow_custom = self.p_allow_custom_check.isChecked()

            self.param_table.blockSignals(True)
            self.param_table.item(row, 0).setText(p.name)
            self.param_table.item(row, 1).setText(p.label)
            self.param_table.item(row, 2).setText(p.ptype)
            self.param_table.item(row, 3).setText(p.default)
            self.param_table.item(row, 4).setText("是" if p.required else "否")
            self.param_table.blockSignals(False)

    def _on_param_add(self):
        cnt = len(self._params_data) + 1
        new_p = QueryParam(
            name=f"param_{cnt}",
            label=f"参数_{cnt}",
            ptype="text"
        )
        self._params_data.append(new_p)
        self._reload_param_table(select_row=len(self._params_data) - 1)

    def _on_param_delete(self):
        row = self.param_table.currentRow()
        if 0 <= row < len(self._params_data):
            del self._params_data[row]
            self._reload_param_table(select_row=max(0, row - 1))

    def _on_param_move_up(self):
        row = self.param_table.currentRow()
        if row > 0:
            self._params_data[row - 1], self._params_data[row] = self._params_data[row], self._params_data[row - 1]
            self._reload_param_table(select_row=row - 1)

    def _on_param_move_down(self):
        row = self.param_table.currentRow()
        if 0 <= row < len(self._params_data) - 1:
            self._params_data[row], self._params_data[row + 1] = self._params_data[row + 1], self._params_data[row]
            self._reload_param_table(select_row=row + 1)

    # ── 区块管理逻辑 ───────────────────────────
    def _reload_block_table(self, select_row=0):
        self.block_table.blockSignals(True)
        self.block_table.setRowCount(len(self._blocks_data))
        for r, b in enumerate(self._blocks_data):
            self.block_table.setItem(r, 0, QTableWidgetItem(b.id or ''))
            self.block_table.setItem(r, 1, QTableWidgetItem(b.title or ''))
            self.block_table.setItem(r, 2, QTableWidgetItem(b.btype or 'table'))
            self.block_table.setItem(r, 3, QTableWidgetItem(b.datasource or 'default'))
            self.block_table.setItem(r, 4, QTableWidgetItem(b.summary_footer or ''))
        self.block_table.blockSignals(False)

        if self._blocks_data:
            r = max(0, min(select_row, len(self._blocks_data) - 1))
            self.block_table.selectRow(r)
            self._selected_block_index = r
            self._load_block_to_details(self._blocks_data[r])
        else:
            self._selected_block_index = -1
            self.block_detail_group.setEnabled(False)

    def _on_block_table_selection_changed(self):
        # 切换前先保存当前区块 SQL
        if 0 <= self._selected_block_index < len(self._blocks_data):
            self._blocks_data[self._selected_block_index].sql = self.b_sql_edit.toPlainText().strip()

        row = self.block_table.currentRow()
        if 0 <= row < len(self._blocks_data):
            self._selected_block_index = row
            self.block_detail_group.setEnabled(True)
            self._load_block_to_details(self._blocks_data[row])
        else:
            self._selected_block_index = -1
            self.block_detail_group.setEnabled(False)

    def _load_block_to_details(self, block):
        self._loading_block = True
        try:
            self.b_id_edit.setText(block.id or '')
            self.b_title_edit.setText(block.title or '')

            idx = self.b_type_combo.findData(block.btype)
            if idx >= 0:
                self.b_type_combo.setCurrentIndex(idx)
            else:
                self.b_type_combo.setCurrentIndex(0)

            ds_idx = self.b_ds_combo.findData(block.datasource)
            if ds_idx < 0:
                ds_idx = self.b_ds_combo.findText(block.datasource)
            if ds_idx >= 0:
                self.b_ds_combo.setCurrentIndex(ds_idx)
            else:
                self.b_ds_combo.setEditText(block.datasource or 'default')

            self.b_width_edit.setText(block.width or '100%')
            self.b_summary_edit.setText(block.summary_footer or '')
            self.b_sql_edit.setPlainText(block.sql or '')
        finally:
            self._loading_block = False

    def _save_current_block_details(self):
        if self._loading_block:
            return
        row = self._selected_block_index
        if 0 <= row < len(self._blocks_data):
            b = self._blocks_data[row]
            b.id = self.b_id_edit.text().strip() or 'main'
            b.title = self.b_title_edit.text().strip() or b.id
            b.btype = self.b_type_combo.currentData() or 'table'
            ds = self.b_ds_combo.currentData() or self.b_ds_combo.currentText().strip() or 'default'
            b.datasource = ds
            b.width = self.b_width_edit.text().strip() or '100%'
            b.summary_footer = self.b_summary_edit.text().strip()
            b.sql = self.b_sql_edit.toPlainText().strip()

            self.block_table.blockSignals(True)
            self.block_table.item(row, 0).setText(b.id)
            self.block_table.item(row, 1).setText(b.title)
            self.block_table.item(row, 2).setText(b.btype)
            self.block_table.item(row, 3).setText(b.datasource)
            self.block_table.item(row, 4).setText(b.summary_footer)
            self.block_table.blockSignals(False)

    def _on_b_sql_changed(self):
        if not self._loading_block and 0 <= self._selected_block_index < len(self._blocks_data):
            self._blocks_data[self._selected_block_index].sql = self.b_sql_edit.toPlainText().strip()

    def _on_block_add_table(self):
        cnt = len(self._blocks_data) + 1
        new_b = QueryBlock(
            block_id=f"detail_{cnt}",
            title=f"明细报表_{cnt}",
            btype="table",
            datasource="default",
            sql="SELECT TOP 100 * FROM YourTable WHERE 1=1"
        )
        self._blocks_data.append(new_b)
        self._reload_block_table(select_row=len(self._blocks_data) - 1)

    def _on_block_add_cards(self):
        cnt = len(self._blocks_data) + 1
        new_b = QueryBlock(
            block_id=f"kpi_{cnt}",
            title=f"关键指标_{cnt}",
            btype="cards",
            datasource="default",
            sql="SELECT COUNT(*) AS [总记录数], SUM(Amount) AS [总金额] FROM YourTable WHERE 1=1"
        )
        self._blocks_data.append(new_b)
        self._reload_block_table(select_row=len(self._blocks_data) - 1)

    def _on_block_delete(self):
        if len(self._blocks_data) <= 1:
            QMessageBox.information(self, "提示", "表单必须至少保留一个查询区块。")
            return
        row = self.block_table.currentRow()
        if 0 <= row < len(self._blocks_data):
            del self._blocks_data[row]
            self._reload_block_table(select_row=max(0, row - 1))

    def _on_block_move_up(self):
        row = self.block_table.currentRow()
        if row > 0:
            self._blocks_data[row - 1], self._blocks_data[row] = self._blocks_data[row], self._blocks_data[row - 1]
            self._reload_block_table(select_row=row - 1)

    def _on_block_move_down(self):
        row = self.block_table.currentRow()
        if 0 <= row < len(self._blocks_data) - 1:
            self._blocks_data[row], self._blocks_data[row + 1] = self._blocks_data[row + 1], self._blocks_data[row]
            self._reload_block_table(select_row=row + 1)

    def _refresh_quick_param_buttons(self):
        """刷新区块 SQL 框上方的快捷插入参数按钮"""
        while self.quick_param_layout.count():
            item = self.quick_param_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

        lbl = QLabel("点击插入参数占位符:")
        lbl.setStyleSheet("font-weight: bold; color: #172B4D; font-size: 11px;")
        self.quick_param_layout.addWidget(lbl)

        btn_today = QPushButton("+ {today}")
        btn_today.setStyleSheet("padding: 2px 6px; font-size: 11px; background-color: #EAE6FF; color: #403294; border: 1px solid #C0B6F2; border-radius: 3px;")
        btn_today.setToolTip("插入当天日期宏 {today}")
        btn_today.clicked.connect(lambda: self._insert_param_into_sql("today"))
        self.quick_param_layout.addWidget(btn_today)

        if not self._params_data:
            empty_hint = QLabel("（可在「查询条件」Tab 先行添加参数，然后在此一键插入）")
            empty_hint.setStyleSheet("color: #6B778C; font-size: 11px;")
            self.quick_param_layout.addWidget(empty_hint)
        else:
            for p in self._params_data:
                p_btn = QPushButton(f"+ {{{p.name}}}")
                p_btn.setStyleSheet("padding: 2px 7px; font-size: 11px; background-color: #DEEBFF; color: #0747A6; border: 1px solid #B3D4FF; border-radius: 3px;")
                p_btn.setToolTip(f"在光标处插入占位符 {{{p.name}}}\n显示标签: {p.label or p.name}")
                p_btn.clicked.connect(lambda _, n=p.name: self._insert_param_into_sql(n))
                self.quick_param_layout.addWidget(p_btn)

        self.quick_param_layout.addStretch()

    def _insert_param_into_sql(self, param_name):
        cursor = self.b_sql_edit.textCursor()
        cursor.insertText(f"{{{param_name}}}")
        self.b_sql_edit.setFocus()

    # ── 双向无缝同步机制 ───────────────────────
    def _on_tab_changed(self, new_index):
        if self._syncing:
            return

        # 从源码模式切出到可视化模式
        if self._prev_tab_index == 3 and new_index != 3:
            self._sync_raw_to_visual()
        # 从可视化模式切入源码模式
        elif self._prev_tab_index in (0, 1, 2) and new_index == 3:
            self._sync_visual_to_raw()

        if new_index == 2:
            self._refresh_quick_param_buttons()

        self._prev_tab_index = new_index

    def _on_meta_field_changed(self):
        """基本信息改变时的非阻塞反馈"""
        pass

    def _sync_visual_to_raw(self):
        """将 Tab 0, 1, 2 中的可视化控件内容序列化并无损同步到 self.editor"""
        if self._syncing:
            return
        self._syncing = True
        try:
            self._save_current_param_details()
            self._save_current_block_details()

            form = QueryForm()
            form.title = self.title_edit.text().strip() or (self.form.title if self.form else '新建查询')
            form.description = self.desc_edit.text().strip()
            form.group = self.group_combo.currentText().strip() or '默认'

            order_str = self.order_edit.text().strip()
            if order_str:
                try:
                    form.order = float(order_str)
                except ValueError:
                    form.order = None
            else:
                form.order = None

            ds = self.datasource_combo.currentData() or self.datasource_combo.currentText().strip()
            form.datasource = ds or 'default'

            q_type = self.query_type_combo.currentData() or self.query_type_combo.currentText().strip()
            form.query_type = q_type.split()[0].lower() if q_type else 'select'

            form.web_enabled = self.web_enabled_check.isChecked()
            form.summary_footer = self.meta_summary_edit.text().strip()

            layout_str = self.layout_edit.text().strip()
            if layout_str:
                form.layout = [s.strip() for s in layout_str.split(',') if s.strip()]
            else:
                form.layout = [b.id for b in self._blocks_data] if len(self._blocks_data) > 1 else []

            form.params = list(self._params_data)
            form.blocks = list(self._blocks_data)
            if form.blocks:
                form.sql = form.blocks[0].sql

            dumped = FormParser.dump_content(form)
            self.editor.setPlainText(dumped)
        finally:
            self._syncing = False

    def _sync_raw_to_visual(self):
        """从 self.editor 的文本重新反向解析填充 Tab 0, 1, 2 的可视化控件"""
        if self._syncing:
            return
        self._syncing = True
        try:
            raw_text = self.editor.toPlainText()
            if not raw_text.strip():
                return
            parsed = FormParser.parse_content(raw_text, forms_root=self.forms_dir)

            # Tab 0: Meta
            self.title_edit.setText(parsed.title or '')
            self.desc_edit.setText(parsed.description or '')

            self.group_combo.blockSignals(True)
            grp = parsed.group or '默认'
            idx = self.group_combo.findText(grp)
            if idx >= 0:
                self.group_combo.setCurrentIndex(idx)
            else:
                self.group_combo.setEditText(grp)
            self.group_combo.blockSignals(False)

            self.order_edit.blockSignals(True)
            if parsed.order is not None:
                val = int(parsed.order) if parsed.order == int(parsed.order) else parsed.order
                self.order_edit.setText(str(val))
            else:
                self.order_edit.setText('')
            self.order_edit.blockSignals(False)

            ds_idx = self.datasource_combo.findData(parsed.datasource)
            if ds_idx < 0:
                ds_idx = self.datasource_combo.findText(parsed.datasource)
            if ds_idx >= 0:
                self.datasource_combo.setCurrentIndex(ds_idx)
            else:
                self.datasource_combo.setEditText(parsed.datasource or 'default')

            qt_idx = self.query_type_combo.findData(parsed.query_type)
            if qt_idx >= 0:
                self.query_type_combo.setCurrentIndex(qt_idx)
            else:
                self.query_type_combo.setCurrentIndex(0)

            self.web_enabled_check.blockSignals(True)
            self.web_enabled_check.setChecked(bool(parsed.web_enabled))
            self.web_enabled_check.blockSignals(False)

            self.meta_summary_edit.setText(parsed.summary_footer or '')
            self.layout_edit.setText(', '.join(parsed.layout) if parsed.layout else '')

            # Tab 1: Params
            self._params_data = list(parsed.params)
            self._reload_param_table()

            # Tab 2: Blocks
            self._blocks_data = list(parsed.blocks)
            if not self._blocks_data and parsed.sql:
                self._blocks_data = [QueryBlock(
                    block_id='main',
                    title=parsed.title or '主查询',
                    btype='table',
                    datasource=parsed.datasource,
                    summary_footer=parsed.summary_footer,
                    sql=parsed.sql
                )]
            self._reload_block_table()
            self._refresh_quick_param_buttons()
        except Exception:
            pass
        finally:
            self._syncing = False

    # ── 光标指示与向后兼容方法 ─────────────────
    def _update_cursor_pos(self):
        cursor = self.editor.textCursor()
        self.cursor_lbl.setText(
            f"行 {cursor.blockNumber() + 1}，列 {cursor.columnNumber() + 1}"
        )

    def _update_block_cursor_pos(self):
        cursor = self.b_sql_edit.textCursor()
        self.b_cursor_lbl.setText(
            f"行 {cursor.blockNumber() + 1}，列 {cursor.columnNumber() + 1}"
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

            # 回填排序序号
            order_text = ''
            if hasattr(self.form, 'order') and self.form.order is not None:
                val = self.form.order
                order_text = str(int(val)) if int(val) == val else str(val)
            elif meta_m:
                for line in meta_m.group(1).splitlines():
                    line = line.strip()
                    if line.startswith(('#', ';')):
                        continue
                    if '=' in line:
                        k, v = line.split('=', 1)
                        if k.strip().lower() in ('order', 'sort', 'sort_order', 'seq') and v.strip():
                            order_text = v.strip()
                            break
            self.order_edit.blockSignals(True)
            self.order_edit.setText(order_text)
            self.order_edit.blockSignals(False)

            # 反向初始化可视化面板
            self._sync_raw_to_visual()
        except Exception as e:
            QMessageBox.warning(self, "读取失败", f"无法读取文件：\n{e}")

    def _on_group_combo_changed(self, new_group):
        """当用户切换或修改所属分组时，同步更新编辑器 [meta] 中的 group 属性"""
        if self._syncing:
            return
        new_group = new_group.strip() or '默认'
        content = self.editor.toPlainText()
        updated = self._apply_group(content, new_group)
        if updated != content:
            cursor = self.editor.textCursor()
            pos = cursor.position()
            self.editor.setPlainText(updated)
            cursor.setPosition(min(pos, len(updated)))
            self.editor.setTextCursor(cursor)

    def _on_order_edit_changed(self, new_val):
        """当用户修改排序序号时，同步更新编辑器 [meta] 中的 order 属性"""
        if self._syncing:
            return
        content = self.editor.toPlainText()
        updated = self._apply_order(content)
        if updated != content:
            cursor = self.editor.textCursor()
            pos = cursor.position()
            self.editor.setPlainText(updated)
            cursor.setPosition(min(pos, len(updated)))
            self.editor.setTextCursor(cursor)

    def _on_web_enabled_toggled(self, checked):
        if self._syncing:
            return
        content = self.editor.toPlainText()
        updated = self._apply_web_enabled(content)
        if updated != content:
            self.editor.setPlainText(updated)

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

    def _apply_order(self, content):
        """将排序序号安全写入 [meta]，保留其他元数据。若清空则移除 order 属性。"""
        meta_m = re.search(r'\[meta\](.*?)(?=\n\s*\[|\Z)', content,
                           re.DOTALL | re.IGNORECASE)
        if not meta_m:
            return content

        order_val = self.order_edit.text().strip() if hasattr(self, 'order_edit') else ''
        meta_body = meta_m.group(1)
        order_line = re.compile(r'^\s*(?:order|sort|sort_order|seq)\s*=.*$', re.MULTILINE | re.IGNORECASE)
        if order_val:
            if order_line.search(meta_body):
                meta_body = order_line.sub('order = ' + order_val, meta_body)
            else:
                meta_body = meta_body.rstrip() + '\norder = ' + order_val + '\n'
        else:
            if order_line.search(meta_body):
                meta_body = order_line.sub('', meta_body)
                meta_body = re.sub(r'\n{3,}', '\n\n', meta_body)

        start, end = meta_m.span(1)
        return content[:start] + meta_body + content[end:]

    # ── 表单全面安全校验引擎 ───────────────────
    def validate_form(self, content=None):
        """
        校验表单元信息、参数定义与 SQL 脚本（支持传统 [sql] 以及多区块 [block.<id>]）。
        返回 (is_valid: bool, errors: list[str], warnings: list[str])
        """
        if content is None:
            if hasattr(self, 'tab_widget') and self.tab_widget.currentIndex() != 3:
                self._sync_visual_to_raw()
            content = self.editor.toPlainText()

        errors = []
        warnings = []

        if not content or not content.strip():
            errors.append("表单内容为空")
            return False, errors, warnings

        # 1. 提取各配置段与多区块 SQL
        meta_section = FormParser._get_section(content, 'meta')
        params_section = FormParser._get_section(content, 'params')
        sql_section = FormParser._get_section(content, 'sql')

        all_sections = FormParser._get_all_sections(content)
        block_sqls = []
        for sec_name, sec_body in all_sections:
            sec_lower = sec_name.lower()
            if sec_lower.startswith('block.') or (sec_lower.startswith('sql.') and sec_lower != 'sql'):
                b_sql_lines = []
                in_sql = False
                for line in sec_body.splitlines():
                    trimmed = line.strip()
                    if not in_sql:
                        if not trimmed or trimmed.startswith('#') or trimmed.startswith(';'):
                            continue
                        if trimmed.lower().startswith('sql =') or trimmed.lower().startswith('sql='):
                            in_sql = True
                            b_sql_lines.append(trimmed.split('=', 1)[1].strip())
                            continue
                        first_word = trimmed.split()[0].upper() if trimmed else ''
                        if first_word in ('SELECT', 'EXEC', 'EXECUTE', 'WITH', '--'):
                            in_sql = True
                            b_sql_lines.append(line)
                            continue
                    else:
                        b_sql_lines.append(line)
                b_sql = '\n'.join(b_sql_lines).strip()
                if b_sql:
                    block_sqls.append((sec_name, b_sql))

        if not meta_section:
            warnings.append("未找到 [meta] 配置段，建议补充表单元数据（title、group 等）")

        if not sql_section and not block_sqls:
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
                            errors.append(f"元数据 [meta] 中的 type='{v}' 无效，仅支持 select 或 exec")
                    elif k == 'title':
                        meta_title = v
                    elif k == 'web_enabled':
                        if v.lower() not in ('true', 'false', '1', '0', 'yes', 'no', '是', '否'):
                            warnings.append(f"元数据 web_enabled='{v}' 不是标准布尔值（建议使用 true 或 false）")
                    elif k in ('order', 'sort', 'sort_order', 'seq'):
                        try:
                            float(v)
                        except ValueError:
                            errors.append(f"元数据 [meta] 中的 {k}='{v}' 无效，必须为数字（如 1, 2, 10 等）")

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
                    errors.append(f"[params] 第 {line_no} 行格式错误：缺少等号 '='（标准格式：参数名 = 显示标签 | 类型 | 默认值 | 属性...）")
                    continue
                raw_name, rest = token.split('=', 1)
                p_name = raw_name.strip()
                if not p_name:
                    errors.append(f"[params] 第 {line_no} 行参数名为空")
                    continue
                if not re.match(r'^[a-zA-Z_]\w*$', p_name):
                    errors.append(f"[params] 第 {line_no} 行参数名「{p_name}」不合法，必须以字母或下划线开头，仅包含字母、数字和下划线")
                    continue
                if p_name in defined_params:
                    errors.append(f"[params] 第 {line_no} 行参数名「{p_name}」重复定义")
                defined_params.add(p_name)

                parts = [p.strip() for p in rest.split('|')]
                raw_type = parts[1] if len(parts) >= 2 else 'text'
                ptype, static_opts = FormParser._parse_type(raw_type)

                valid_base_types = ('text', 'date', 'datetime', 'number', 'textarea', 'checkbox', 'hidden', 'select', 'radio')
                clean_type = raw_type.split(':', 1)[0].strip().lower()
                if clean_type not in valid_base_types:
                    warnings.append(f"[params] 参数「{p_name}」的类型「{raw_type}」非系统内置控件类型，将默认按单行文本框显示")

                attrs = parts[2:] if len(parts) > 2 else []
                (default_val, placeholder, required, width, options_sql,
                 searchable, allow_custom) = FormParser._parse_param_attributes(attrs)

                if options_sql:
                    ok, reason = validate_options_sql(options_sql)
                    if not ok:
                        errors.append(f"[params] 参数「{p_name}」的 options_sql 检查失败：{reason}")

                if clean_type in ('select', 'radio') and not static_opts and not options_sql:
                    warnings.append(f"[params] 参数「{p_name}」为 {clean_type} 类型，但既未配置静态候选项，也未配置 options_sql 动态候选项")

        # 4. 校验 SQL 脚本（包括 [sql] 及各 [block.<id>]）
        sqls_to_validate = []
        if sql_section.strip():
            sqls_to_validate.append(('[sql]', sql_section.strip()))
        for b_name, b_sql in block_sqls:
            sqls_to_validate.append((b_name, b_sql))

        all_sql_placeholders = set()
        for label, sql in sqls_to_validate:
            ok, reason = FormParser.is_safe_sql(sql, query_type)
            if not ok:
                if label == '[sql]':
                    errors.append(f"SQL 安全检查未通过：{reason}")
                else:
                    errors.append(f"区块 [{label}] SQL 安全检查未通过：{reason}")

            # 占位符匹配检查
            placeholders = sql_placeholders(sql)
            for p in placeholders:
                all_sql_placeholders.add(p)
                if p.lower() in ('today', 'now'):
                    continue
                if p not in defined_params:
                    errors.append(f"SQL 中引用了未在 [params] 中定义的参数：{{{p}}}")

            # 单引号与圆括号匹配启发式检查（过滤注释）
            no_comment_sql = normalize_sql_for_safety(sql)
            clean_quotes = no_comment_sql.replace("''", "")
            if clean_quotes.count("'") % 2 != 0:
                warnings.append(f"SQL 脚本{(' (' + label + ')') if label != '[sql]' else ''}中的单引号数量不成对，可能存在未闭合的字符串常量")

            left_p = no_comment_sql.count('(')
            right_p = no_comment_sql.count(')')
            if left_p != right_p:
                warnings.append(f"SQL 脚本{(' (' + label + ')') if label != '[sql]' else ''}中的圆括号数量不匹配（左括号 {left_p} 个，右括号 {right_p} 个）")

        for p in defined_params:
            if p not in all_sql_placeholders:
                warnings.append(f"参数「{p}」已在 [params] 中定义，但未在 SQL 脚本中被引用")

        is_valid = (len(errors) == 0)
        return is_valid, errors, warnings

    def _on_validate_clicked(self):
        """单独执行表单校验并弹窗展示结果"""
        if hasattr(self, 'tab_widget') and self.tab_widget.currentIndex() != 3:
            self._sync_visual_to_raw()

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

    # ── 保存与另存为流程 ───────────────────────
    def _get_save_path(self):
        """获取保存路径；返回 None 表示用户取消或输入无效"""
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
                os.makedirs(target_dir, exist_ok=True)
                new_path = os.path.join(target_dir, os.path.basename(self.form.file_path))
                if os.path.exists(new_path) and os.path.abspath(new_path) != os.path.abspath(self.form.file_path):
                    reply = QMessageBox.question(
                        self, "确认覆盖",
                        f"目标分组下已存在同名表单文件，是否覆盖？\n\n{new_path}",
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

        name = re.sub(r'[\\/:*?"<>|]', '_', name)
        group_dir = os.path.join(self.forms_dir, target_group)
        os.makedirs(group_dir, exist_ok=True)

        path = os.path.join(group_dir, name + '.qry')

        if os.path.exists(path):
            reply = QMessageBox.question(
                self, "确认覆盖",
                f"文件已存在，是否覆盖？\n\n{path}",
                QMessageBox.Yes | QMessageBox.No
            )
            if reply != QMessageBox.Yes:
                return None

        return path

    def _do_save(self, path):
        """执行实际写入"""
        folder_group = os.path.basename(os.path.dirname(path))
        if folder_group.lower() == 'forms':
            folder_group = self.group_combo.currentText().strip() or '默认'

        raw_content = self.editor.toPlainText()
        content = self._apply_group(raw_content, folder_group)
        content = self._apply_web_enabled(content)
        content = self._apply_order(content)

        query_type = 'select'
        meta_m = re.search(r'\[meta\](.*?)(?=\n\s*\[|\Z)', content,
                           re.DOTALL | re.IGNORECASE)
        if meta_m:
            for line in meta_m.group(1).splitlines():
                line = line.strip()
                if line.startswith(('#', ';')):
                    continue
                if '=' in line:
                    k, v = line.split('=', 1)
                    if k.strip().lower() == 'type':
                        query_type = v.strip().lower()
                        break

        # 动态候选 SQL 安全检查
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
                        f"第 {line_number} 行的 options_sql 未通过安全检查：{reason}\n\n仅允许一条只读 SELECT 语句。"
                    )
                    return False

        # 主查询及区块 SQL 安全检查
        parsed_form = FormParser.parse_content(content, forms_root=self.forms_dir)
        sqls_to_check = []
        if parsed_form.sql:
            sqls_to_check.append(parsed_form.sql)
        for b in parsed_form.blocks:
            if b.sql and b.sql not in sqls_to_check:
                sqls_to_check.append(b.sql)

        for sql in sqls_to_check:
            ok, reason = FormParser.is_safe_sql(sql, query_type)
            if not ok:
                reply = QMessageBox.warning(
                    self, "SQL 安全警告",
                    f"SQL 安全检查未通过：{reason}\n\n仍要保存吗？",
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

            # 如果已有表单保存到了新路径，移除旧文件
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
        if hasattr(self, 'tab_widget') and self.tab_widget.currentIndex() != 3:
            self._sync_visual_to_raw()

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
            QMessageBox.information(self, "保存成功", f"表单已保存：\n{path}")
            self.accept()

    def _save_as(self):
        if hasattr(self, 'tab_widget') and self.tab_widget.currentIndex() != 3:
            self._sync_visual_to_raw()

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
            QMessageBox.information(self, "另存为成功", f"已另存为：\n{path}")
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

【多数据源与跨库支持】
  在 [meta] 中配置 datasource = xxx 可指定默认数据源；
  在 [block.xxx] 中配置 datasource = xxx 可指定该区块的独立数据源。
  默认主库为 default。

【顶部指标卡 (cards)】
  在区块中配置 type = cards，第一行返回的字段将自动渲染为顶部大字 KPI 指标汇总卡。

【表格底部合计行 (summary_footer)】
  - summary_footer = auto：自动识别数值列并累加求和，首列显示“合计 (N条)”；
  - summary_footer = sum:金额,人次; count:体检号; avg:均价：按列名指定聚合函数。

【自由排版 (layout)】
  在 [meta] 中设置 layout = summary, dept_stat, detail，
  系统将严格按照 layout 指定的顺序渲染区块。
"""
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
