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
    QSplitter, QScrollArea, QFrame, QToolButton, QRadioButton, QButtonGroup,
    QDateEdit, QDateTimeEdit, QTabBar, QListWidget, QListWidgetItem, QStackedWidget,
    QTextBrowser
)
from PyQt5.QtCore import Qt, QObject, QEvent, QTimer, QDate, QDateTime
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
        help_btn = QPushButton("📖 查看说明与示例")
        help_btn.setToolTip("查看表单配置语法说明、参数速查表与 3 套完整范例")
        help_btn.setStyleSheet("background-color: #EBF3FF; color: #0052CC; font-weight: bold; border: 1px solid #B3D4FF; border-radius: 4px; padding: 4px 10px;")
        help_btn.clicked.connect(self._goto_docs_tab)
        top_row.addWidget(self.path_label)
        top_row.addStretch()
        top_row.addWidget(help_btn)
        root_layout.addLayout(top_row)

        # 核心 Tab 容器（6个标签页：基本信息、查询参数、区块与排版、效果预览、源码模式、说明与示例）
        self.tab_widget = QTabWidget()
        self.tab_widget.setStyleSheet("""
            QTabBar::tab {
                padding: 6px 14px;
                font-size: 12px;
                min-width: 85px;
            }
            QTabBar::tab:selected {
                font-weight: bold;
            }
        """)

        # 先创建 raw_tab，确保 self.editor 存在
        self.raw_tab = self._create_raw_tab()
        self.meta_tab = self._create_meta_tab()
        self.params_tab = self._create_params_tab()
        self.blocks_tab = self._create_blocks_tab()
        self.preview_tab = self._create_preview_tab()
        self.docs_tab = self._create_docs_tab()

        self.tab_widget.addTab(self.meta_tab, "📋 基本信息")
        self.tab_widget.addTab(self.params_tab, "⚙️ 查询条件")
        self.tab_widget.addTab(self.blocks_tab, "📊 报表区块与排版")
        self.tab_widget.addTab(self.preview_tab, "👀 效果预览")
        self.tab_widget.addTab(self.raw_tab, "📝 源码模式 (.qry)")
        self.tab_widget.addTab(self.docs_tab, "📖 使用说明与示例")
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

    def _goto_docs_tab(self):
        """跳转至说明与示例标签页"""
        if hasattr(self, 'docs_tab'):
            self.tab_widget.setCurrentWidget(self.docs_tab)

    # ── Tab 0: 基本信息 (Meta) ─────────────────
    def _create_meta_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)

        # 顶部操作指引横幅
        meta_banner = QFrame()
        meta_banner.setStyleSheet("QFrame { background-color: #F0F7FF; border: 1px solid #BAE0FF; border-radius: 6px; padding: 4px; }")
        mb_layout = QHBoxLayout(meta_banner)
        mb_layout.setContentsMargins(10, 6, 10, 6)
        mb_lbl = QLabel("💡 <b>基本信息指南</b>：设定表单标题、目录分类及默认数据源。保存后将自动归入对应分类目录；支持指定全表默认合计规则与多区块排版。")
        mb_lbl.setStyleSheet("color: #0050B3; font-size: 11px;")
        mb_layout.addWidget(mb_lbl)
        layout.addWidget(meta_banner)

        # 分组一：表单基本属性
        info_grp = QGroupBox("表单信息与分类")
        info_form = QFormLayout(info_grp)
        info_form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        info_form.setContentsMargins(12, 10, 12, 10)
        info_form.setVerticalSpacing(8)

        self.title_edit = QLineEdit()
        self.title_edit.setPlaceholderText("请输入表单标题（如：体检人员综合统计分析）")
        self.title_edit.setToolTip("【表单标题】显示在左侧导航树和顶部查询标签页中的中文名称")
        self.title_edit.textChanged.connect(self._on_meta_field_changed)
        info_form.addRow("表单标题:", self.title_edit)

        # 所属分组（保持兼容属性 self.group_combo）
        self.group_combo = QComboBox()
        self.group_combo.setEditable(True)
        self.group_combo.setInsertPolicy(QComboBox.NoInsert)
        self.group_combo.setMinimumHeight(26)
        self.group_combo.setMaxVisibleItems(15)
        self.group_combo.setToolTip("【所属分组】可直接下拉选择已有分组，或直接输入新分组名称（保存时系统将自动创建对应文件夹归类）")
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
            self.filename_edit.setToolTip("【文件名称】保存到磁盘时的文件名（无需手动输入 .qry 后缀）")
            info_form.addRow("文件名称:", self.filename_edit)
        else:
            self.filename_label = QLabel(os.path.basename(self.form.file_path))
            self.filename_label.setStyleSheet("color: #333; font-weight: bold;")
            info_form.addRow("当前文件:", self.filename_label)

        # 显示排序（保持兼容属性 self.order_edit）
        order_row = QHBoxLayout()
        self.order_edit = QLineEdit()
        self.order_edit.setPlaceholderText("排序序号（数字，越小越靠前，留空默认按名称自然排序）")
        self.order_edit.setToolTip("【显示排序】设置表单在分组内的排列顺序，数值越小越靠前（例如 1, 2, 10 等；留空按字母自然排序）")
        order_row.addWidget(self.order_edit, stretch=1)
        order_hint = QLabel("（数值越小越靠前，留空默认按名称自然排序）")
        order_hint.setStyleSheet("color: #7A869A; font-size: 11px;")
        order_row.addWidget(order_hint)
        info_form.addRow("显示排序:", order_row)
        self.order_edit.textChanged.connect(self._on_order_edit_changed)

        self.desc_edit = QLineEdit()
        self.desc_edit.setPlaceholderText("表单的简要说明或用途（可选）")
        self.desc_edit.setToolTip("【表单描述】鼠标悬停在左侧导航树或上方标签页时弹出的功能提示")
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
        self.datasource_combo.setToolTip("【默认数据源】表单的主数据库连接。支持跨库多源；跨库数据源可在 config.ini 中进行配置")
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
        self.query_type_combo.setToolTip("【查询类型】select 为常规只读 SQL 查询；exec 为调用存储过程")
        self.query_type_combo.currentIndexChanged.connect(self._on_meta_field_changed)
        adv_form.addRow("查询类型:", self.query_type_combo)

        # Web 权限
        access_row = QHBoxLayout()
        self.web_enabled_check = QCheckBox("允许已登录 Web 用户查看此表单")
        self.web_enabled_check.setChecked(False)
        self.web_enabled_check.setToolTip("【Web权限】勾选后，登录 Web 网页版的用户才能看到并执行该表单。桌面端不受此开关限制。")
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
        self.meta_summary_edit.setToolTip("【合计规则】\n• 留空：不显示合计行；\n• auto：自动识别数值列并累加求和，首列显示「合计 (N条)」；\n• 指定聚合：如 sum:金额,实收; count:单号; avg:单价。")
        self.meta_summary_edit.textChanged.connect(self._on_meta_field_changed)
        adv_form.addRow("默认合计规则:", self.meta_summary_edit)

        # 区块排版自定义
        self.layout_edit = QLineEdit()
        self.layout_edit.setPlaceholderText("多区块排版顺序（逗号分隔区块ID，留空默认按区块列表顺序）")
        self.layout_edit.setToolTip("【排版顺序】当配置了多个表格或指标卡区块时，可在此以逗号指定显示先后顺序（如：kpi, main, sub）")
        self.layout_edit.textChanged.connect(self._on_meta_field_changed)
        adv_form.addRow("排版顺序(layout):", self.layout_edit)

        layout.addWidget(adv_grp)

        # 底部操作提示
        bottom_tip = QLabel("📌 小贴士：配置完成后，可随时点击上方「👀 效果预览」查看真实渲染，或点击右上角「📖 查看说明与示例」获取模版。")
        bottom_tip.setStyleSheet("color: #6B778C; font-size: 11px; padding: 4px;")
        layout.addWidget(bottom_tip)

        layout.addStretch()
        return tab

    # ── Tab 1: 查询条件 (Params) ───────────────
    def _create_params_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        # 顶部操作指引横幅
        params_banner = QFrame()
        params_banner.setStyleSheet("QFrame { background-color: #F0F7FF; border: 1px solid #BAE0FF; border-radius: 6px; padding: 4px; }")
        pb_layout = QHBoxLayout(params_banner)
        pb_layout.setContentsMargins(10, 6, 10, 6)
        pb_lbl = QLabel("💡 <b>查询条件配置指南</b>：定义用户查询界面的输入项。配置后可在报表 SQL 中使用 <b>{参数名}</b> 动态绑定；支持下拉框、日期宏 {today} 及动态 options_sql。")
        pb_lbl.setStyleSheet("color: #0050B3; font-size: 11px;")
        pb_layout.addWidget(pb_lbl)
        layout.addWidget(params_banner)

        # 上半部分：参数列表表格 + 操作按钮
        table_grp = QGroupBox("参数列表清单")
        t_layout = QVBoxLayout(table_grp)
        t_layout.setContentsMargins(8, 8, 8, 8)

        btn_bar = QHBoxLayout()
        self.param_add_btn = QPushButton("➕ 添加参数")
        self.param_add_btn.setStyleSheet("background-color: #0052CC; color: white; font-weight: bold; padding: 4px 10px;")
        self.param_add_btn.setToolTip("向表单追加一个新的查询条件参数")
        self.param_add_btn.clicked.connect(self._on_param_add)
        self.param_del_btn = QPushButton("➖ 删除参数")
        self.param_del_btn.setToolTip("删除当前选中的参数")
        self.param_del_btn.clicked.connect(self._on_param_delete)
        self.param_up_btn = QPushButton("⬆️ 上移")
        self.param_up_btn.setToolTip("将选中参数在查询面板中向前移动一位")
        self.param_up_btn.clicked.connect(self._on_param_move_up)
        self.param_down_btn = QPushButton("⬇️ 下移")
        self.param_down_btn.setToolTip("将选中参数在查询面板中向后移动一位")
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
        self.p_name_edit.setToolTip("【参数名】在 SQL 中用 {参数名} 引用；只能由字母、数字和下划线组成")
        self.p_name_edit.textChanged.connect(self._save_current_param_details)
        id_lbl_row.addWidget(self.p_name_edit, stretch=1)
        id_lbl_row.addWidget(QLabel("标签:"))
        self.p_label_edit = QLineEdit()
        self.p_label_edit.setPlaceholderText("界面显示，如 开始日期")
        self.p_label_edit.setToolTip("【显示标签】在客户端查询面板中展示给操作人员的中文标签")
        self.p_label_edit.textChanged.connect(self._save_current_param_details)
        id_lbl_row.addWidget(self.p_label_edit, stretch=1)
        p_form.addRow("参数标识/标签:", id_lbl_row)

        # 控件类型与必填
        type_row = QHBoxLayout()
        self.p_type_combo = QComboBox()
        types = [
            ('text', '单行文本 (text) - 通用文本输入'),
            ('date', '日期选择 (date) - 格式 yyyy-MM-dd'),
            ('datetime', '日期时间 (datetime) - 格式 yyyy-MM-dd HH:mm:ss'),
            ('number', '数值输入 (number) - 仅限有效数字'),
            ('select', '下拉选择框 (select) - 支持静态候选项与动态SQL'),
            ('radio', '单选按钮组 (radio) - 候选项横向单选'),
            ('textarea', '多行文本框 (textarea) - 适合较长输入'),
            ('checkbox', '复选框 (checkbox) - 选中提交1，未选中提交0'),
            ('hidden', '隐藏参数 (hidden) - 不可见，提交固定默认值')
        ]
        for val, desc in types:
            self.p_type_combo.addItem(desc, val)
        self.p_type_combo.setToolTip("【控件类型】选择该参数在前端界面的展现形式")
        self.p_type_combo.currentIndexChanged.connect(self._on_param_type_changed)
        type_row.addWidget(self.p_type_combo, stretch=2)

        self.p_required_check = QCheckBox("必填项 (required)")
        self.p_required_check.setToolTip("勾选后，若操作员未填入该条件则阻止执行查询")
        self.p_required_check.toggled.connect(self._save_current_param_details)
        type_row.addWidget(self.p_required_check)

        self.p_width_edit = QLineEdit()
        self.p_width_edit.setPlaceholderText("宽度 (如 180px, 25%)")
        self.p_width_edit.setToolTip("【控件宽度】支持像素（如 160px）或百分比（如 30%），留空为自适应")
        self.p_width_edit.textChanged.connect(self._save_current_param_details)
        type_row.addWidget(self.p_width_edit, stretch=1)
        p_form.addRow("控件类型/特性:", type_row)

        # 默认值（带快捷填入按键）
        def_row = QHBoxLayout()
        self.p_default_edit = QLineEdit()
        self.p_default_edit.setPlaceholderText("默认填充值，日期可使用 {today}")
        self.p_default_edit.setToolTip("【默认值】打开表单时的初始值。日期参数可直接输入 {today} 宏自动取当天日期")
        self.p_default_edit.textChanged.connect(self._save_current_param_details)
        def_row.addWidget(self.p_default_edit, stretch=1)

        btn_today = QPushButton("+ {today}")
        btn_today.setStyleSheet("padding: 2px 8px; background: #E6F7FF; color: #0050B3; border: 1px solid #91D5FF; border-radius: 3px;")
        btn_today.setToolTip("快捷填入 {today} 动态当天宏")
        btn_today.clicked.connect(lambda: self.p_default_edit.setText("{today}"))
        def_row.addWidget(btn_today)

        self.p_placeholder_edit = QLineEdit()
        self.p_placeholder_edit.setPlaceholderText("输入框内浅灰提示文字 (placeholder)")
        self.p_placeholder_edit.setToolTip("【提示文字】输入框为空时显示的浅灰引导文本")
        self.p_placeholder_edit.textChanged.connect(self._save_current_param_details)
        def_row.addWidget(self.p_placeholder_edit, stretch=1)
        p_form.addRow("默认值/提示:", def_row)

        # 候选项设置（针对 select / radio）
        opt_row = QHBoxLayout()
        self.p_options_edit = QLineEdit()
        self.p_options_edit.setPlaceholderText("静态候选项（逗号分隔，如：全部,启用,禁用）")
        self.p_options_edit.setToolTip("【静态候选项】以英文逗号分隔的固定列表。若同时配置了 options_sql，将以动态 SQL 结果为准")
        self.p_options_edit.textChanged.connect(self._save_current_param_details)
        opt_row.addWidget(self.p_options_edit, stretch=2)

        self.p_searchable_check = QCheckBox("可输入搜索")
        self.p_searchable_check.setChecked(True)
        self.p_searchable_check.setToolTip("下拉框是否允许操作员直接键入关键词快速过滤选项")
        self.p_searchable_check.toggled.connect(self._save_current_param_details)
        opt_row.addWidget(self.p_searchable_check)

        self.p_allow_custom_check = QCheckBox("允许自定义输入")
        self.p_allow_custom_check.setToolTip("是否允许操作员输入下拉候选列表中不存在的自由文本")
        self.p_allow_custom_check.toggled.connect(self._save_current_param_details)
        opt_row.addWidget(self.p_allow_custom_check)
        p_form.addRow("候选项配置:", opt_row)

        # 动态 SQL 候选项
        self.p_options_sql_edit = QLineEdit()
        self.p_options_sql_edit.setPlaceholderText("动态只读 SELECT 语句，返回一列为值，两列为 值,显示标签 (options_sql)")
        self.p_options_sql_edit.setToolTip("【动态候选 SQL】执行只读 SELECT 查询，用于从数据库字典表中动态加载选项")
        self.p_options_sql_edit.textChanged.connect(self._save_current_param_details)
        p_form.addRow("动态候选 SQL:", self.p_options_sql_edit)

        # options_sql 规范说明黄色提示框
        sql_tip_box = QFrame()
        sql_tip_box.setStyleSheet("QFrame { background-color: #FFFBE6; border: 1px solid #FFE58F; border-radius: 4px; padding: 4px; }")
        st_layout = QVBoxLayout(sql_tip_box)
        st_layout.setContentsMargins(8, 4, 8, 4)
        st_layout.setSpacing(2)
        st_t1 = QLabel("📌 <b>options_sql 规范</b>：仅允许单条只读 SELECT 语句，禁止多语句或分号；始终在默认主库执行。")
        st_t1.setStyleSheet("color: #D48806; font-size: 11px;")
        st_t2 = QLabel("• <b>返回 1 列</b>：该列既作为提交到 SQL 的入参值，也作为下拉显示的文字；<br>• <b>返回 2 列</b>：第 1 列作为提交值，第 2 列作为界面显示名称（如：<code>SELECT DeptCode, DeptName FROM Departments</code>）。")
        st_t2.setStyleSheet("color: #8C6B00; font-size: 11px;")
        st_layout.addWidget(st_t1)
        st_layout.addWidget(st_t2)
        p_form.addRow("", sql_tip_box)

        layout.addWidget(self.param_detail_group)
        return tab

    # ── Tab 2: 报表区块与排版 (Blocks & Layout) ─
    def _create_blocks_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        # 顶部操作指引横幅
        blocks_banner = QFrame()
        blocks_banner.setStyleSheet("QFrame { background-color: #F0F7FF; border: 1px solid #BAE0FF; border-radius: 6px; padding: 4px; }")
        bb_layout = QHBoxLayout(blocks_banner)
        bb_layout.setContentsMargins(10, 6, 10, 6)
        bb_lbl = QLabel("💡 <b>多区块与排版指南</b>：支持多数据源与跨库报表！<b>table</b> 为明细数据表格（支持底部自动合计），<b>cards</b> 为顶部大字 KPI 指标卡。每个区块可独立连接不同数据库。")
        bb_lbl.setStyleSheet("color: #0050B3; font-size: 11px;")
        bb_layout.addWidget(bb_lbl)
        layout.addWidget(blocks_banner)

        splitter = QSplitter(Qt.Vertical)

        # 上半部分：区块清单表格 + 新建按钮
        block_list_grp = QGroupBox("报表区块清单（支持多数据源与指标卡）")
        b_layout = QVBoxLayout(block_list_grp)
        b_layout.setContentsMargins(8, 8, 8, 8)

        btn_bar = QHBoxLayout()
        self.block_add_table_btn = QPushButton("➕ 新增表格区块 (table)")
        self.block_add_table_btn.setStyleSheet("background-color: #0052CC; color: white; font-weight: bold; padding: 4px 10px;")
        self.block_add_table_btn.setToolTip("添加一个明细数据表格区块，可独立配置数据源与底部合计行")
        self.block_add_table_btn.clicked.connect(self._on_block_add_table)
        self.block_add_cards_btn = QPushButton("➕ 新增指标卡 (cards)")
        self.block_add_cards_btn.setStyleSheet("background-color: #00875A; color: white; font-weight: bold; padding: 4px 10px;")
        self.block_add_cards_btn.setToolTip("添加顶部 KPI 指标卡区块，查询返回的首行各字段将自动展示为突出大字卡片")
        self.block_add_cards_btn.clicked.connect(self._on_block_add_cards)
        self.block_del_btn = QPushButton("➖ 删除区块")
        self.block_del_btn.setToolTip("删除当前选中的报表区块（表单必须至少保留一个区块）")
        self.block_del_btn.clicked.connect(self._on_block_delete)
        self.block_up_btn = QPushButton("⬆️ 上移")
        self.block_up_btn.setToolTip("将选中区块向上移动一位")
        self.block_up_btn.clicked.connect(self._on_block_move_up)
        self.block_down_btn = QPushButton("⬇️ 下移")
        self.block_down_btn.setToolTip("将选中区块向下移动一位")
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
        self.b_id_edit.setToolTip("【区块标识】唯一英文标识符，在 [meta] 的 layout 中可用于排版排序")
        self.b_id_edit.textChanged.connect(self._save_current_block_details)
        b_meta_row.addWidget(self.b_id_edit, stretch=1)

        b_meta_row.addWidget(QLabel("标题:"))
        self.b_title_edit = QLineEdit()
        self.b_title_edit.setPlaceholderText("展示标题（如：体检人员明细表）")
        self.b_title_edit.setToolTip("【展示标题】在客户端多Tab切换栏以及导出 Excel 对应工作表(Sheet)时使用的名称")
        self.b_title_edit.textChanged.connect(self._save_current_block_details)
        b_meta_row.addWidget(self.b_title_edit, stretch=2)

        b_meta_row.addWidget(QLabel("类型:"))
        self.b_type_combo = QComboBox()
        self.b_type_combo.addItem("table - 明细表格", "table")
        self.b_type_combo.addItem("cards - 指标汇总卡", "cards")
        self.b_type_combo.setToolTip("【区块类型】\n• table: 展现为多行多列的数据表格，支持底部合计行；\n• cards: 展现为顶部大字 KPI 指标卡片。")
        self.b_type_combo.currentIndexChanged.connect(self._save_current_block_details)
        b_meta_row.addWidget(self.b_type_combo, stretch=1)

        b_meta_row.addWidget(QLabel("数据源:"))
        self.b_ds_combo = QComboBox()
        self.b_ds_combo.setEditable(True)
        self._populate_datasources(self.b_ds_combo)
        self.b_ds_combo.setToolTip("【独立数据源】该区块执行 SQL 所在的数据库连接。默认继承主库 default，可为不同区块指定不同库实现跨库报表")
        self.b_ds_combo.currentTextChanged.connect(self._save_current_block_details)
        b_meta_row.addWidget(self.b_ds_combo, stretch=1)

        bd_layout.addLayout(b_meta_row)

        b_meta_row2 = QHBoxLayout()
        b_meta_row2.addWidget(QLabel("合计规则:"))
        self.b_summary_edit = QLineEdit()
        self.b_summary_edit.setPlaceholderText("auto 或 sum:实收金额,人次; count:体检号; avg:均价")
        self.b_summary_edit.setToolTip("【合计规则】\n• auto：自动识别数值列并累加求和，首列显示「合计 (N条)」；\n• 聚合格式：sum:金额,人次; count:单号; avg:客单价；\n• 留空：跟随表单基本信息中的默认合计规则。")
        self.b_summary_edit.textChanged.connect(self._save_current_block_details)
        b_meta_row2.addWidget(self.b_summary_edit, stretch=2)

        b_meta_row2.addWidget(QLabel("显示宽度:"))
        self.b_width_edit = QLineEdit()
        self.b_width_edit.setPlaceholderText("100% 或 50%")
        self.b_width_edit.setToolTip("【显示宽度】在网页端或并排布局时的宽度占比，桌面端默认占满 100%")
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

    # ── Tab 3: 效果预览 (Live Preview) ──────────
    def _create_preview_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        # 顶部提示条与手动刷新按钮
        top_bar = QHBoxLayout()
        tip_frame = QFrame()
        tip_frame.setStyleSheet("background: #F0F7FF; border: 1px solid #BAE0FF; border-radius: 4px; padding: 2px;")
        tf_layout = QHBoxLayout(tip_frame)
        tf_layout.setContentsMargins(8, 4, 8, 4)
        tip = QLabel("👀 <b>实时运行效果预览</b>（所见即所得：自动根据当前配置的条件、指标卡与区块渲染真实桌面端界面）")
        tip.setStyleSheet("color: #0050B3; font-size: 11px;")
        tf_layout.addWidget(tip)
        top_bar.addWidget(tip_frame, stretch=1)

        self.btn_refresh_preview = QPushButton("🔄 刷新预览")
        self.btn_refresh_preview.setStyleSheet("background-color: #0052CC; color: white; font-weight: bold; padding: 4px 12px; border-radius: 4px;")
        self.btn_refresh_preview.clicked.connect(self._refresh_live_preview)
        top_bar.addWidget(self.btn_refresh_preview)
        layout.addLayout(top_bar)

        # 主滚动预览区
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        self.preview_container = QWidget()
        self.preview_layout = QVBoxLayout(self.preview_container)
        self.preview_layout.setContentsMargins(4, 4, 4, 4)
        self.preview_layout.setSpacing(12)
        scroll.setWidget(self.preview_container)
        layout.addWidget(scroll, stretch=1)

        return tab

    def _refresh_live_preview(self):
        """根据当前参数与区块配置，动态构建预览视图"""
        # 清除现有控件
        while self.preview_layout.count():
            item = self.preview_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

        # 1. 表单标题横幅
        title_text = self.title_edit.text().strip() or (self.form.title if self.form else "未命名表单")
        desc_text = self.desc_edit.text().strip() or "暂无表单描述"
        header_frame = QFrame()
        header_frame.setStyleSheet("background: #F8FAFC; border: 1px solid #E2E8F0; border-radius: 6px; padding: 4px;")
        h_layout = QVBoxLayout(header_frame)
        h_layout.setContentsMargins(10, 8, 10, 8)
        h_layout.setSpacing(2)
        t_lbl = QLabel(f"📑 <b>{title_text}</b>")
        t_lbl.setStyleSheet("font-size: 15px; color: #1E293B;")
        d_lbl = QLabel(f"描述：{desc_text}  |  所属分组：{self.group_combo.currentText().strip() or '默认'}  |  主数据源：{self.datasource_combo.currentText().strip() or 'default'}")
        d_lbl.setStyleSheet("font-size: 11px; color: #64748B;")
        h_layout.addWidget(t_lbl)
        h_layout.addWidget(d_lbl)
        self.preview_layout.addWidget(header_frame)

        # 2. 查询条件工具栏模拟
        params_grp = QGroupBox("🔍 查询条件工具栏 (模拟可交互)")
        p_vbox = QVBoxLayout(params_grp)
        p_vbox.setContentsMargins(10, 8, 10, 8)
        p_vbox.setSpacing(8)

        if not self._params_data:
            empty_lbl = QLabel("（尚未配置任何查询条件，操作员无需输入即可直接执行查询）")
            empty_lbl.setStyleSheet("color: #94A3B8; font-style: italic; padding: 8px;")
            p_vbox.addWidget(empty_lbl)
        else:
            p_grid_frame = QFrame()
            p_grid_layout = QHBoxLayout(p_grid_frame)
            p_grid_layout.setContentsMargins(0, 0, 0, 0)
            p_grid_layout.setSpacing(12)

            for p in self._params_data:
                item_box = QVBoxLayout()
                item_box.setSpacing(2)
                lbl_text = p.label or p.name
                if p.required:
                    lbl_text += " <span style='color:red;'>*</span>"
                l = QLabel(lbl_text)
                l.setStyleSheet("font-size: 11px; color: #334155; font-weight: bold;")
                item_box.addWidget(l)

                ptype = p.ptype or 'text'
                if ptype == 'date':
                    dt = QDateEdit()
                    dt.setCalendarPopup(True)
                    dt.setDate(QDate.currentDate())
                    dt.setMinimumWidth(110)
                    item_box.addWidget(dt)
                elif ptype == 'datetime':
                    dtt = QDateTimeEdit()
                    dtt.setCalendarPopup(True)
                    dtt.setDateTime(QDateTime.currentDateTime())
                    dtt.setMinimumWidth(150)
                    item_box.addWidget(dtt)
                elif ptype == 'select':
                    cb = QComboBox()
                    cb.setMinimumWidth(120)
                    if p.options:
                        cb.addItems(p.options)
                    elif getattr(p, 'options_sql', ''):
                        cb.addItem("（动态 SQL 加载项1）")
                        cb.addItem("（动态 SQL 加载项2）")
                    else:
                        cb.addItem("请选择...")
                    if getattr(p, 'allow_custom', False):
                        cb.setEditable(True)
                    item_box.addWidget(cb)
                elif ptype == 'radio':
                    r_frame = QFrame()
                    r_layout = QHBoxLayout(r_frame)
                    r_layout.setContentsMargins(0, 0, 0, 0)
                    opts = p.options or ['选项A', '选项B']
                    for opt in opts[:3]:
                        rb = QRadioButton(opt)
                        r_layout.addWidget(rb)
                    if opts:
                        first_rb = r_frame.findChild(QRadioButton)
                        if first_rb:
                            first_rb.setChecked(True)
                    item_box.addWidget(r_frame)
                elif ptype == 'checkbox':
                    chk = QCheckBox("启用/勾选")
                    chk.setChecked(p.default in ('1', 'true', 'True', True))
                    item_box.addWidget(chk)
                elif ptype == 'hidden':
                    h_lbl = QLabel(f"(隐藏: {p.default or '空'})")
                    h_lbl.setStyleSheet("color: #94A3B8; font-size: 11px;")
                    item_box.addWidget(h_lbl)
                else:
                    le = QLineEdit()
                    le.setPlaceholderText(p.placeholder or "请输入...")
                    if p.default:
                        le.setText(str(p.default))
                    le.setMinimumWidth(110)
                    item_box.addWidget(le)

                p_grid_layout.addLayout(item_box)

            p_grid_layout.addStretch()

            # 操作按钮模拟
            btn_row = QHBoxLayout()
            btn_row.setSpacing(6)
            btn_query = QPushButton("▶ 查询")
            btn_query.setStyleSheet("background-color: #2563EB; color: white; font-weight: bold; padding: 5px 14px; border-radius: 4px;")
            btn_export = QPushButton("📊 导出 Excel")
            btn_export.setStyleSheet("background-color: #10B981; color: white; font-weight: bold; padding: 5px 12px; border-radius: 4px;")
            btn_reset = QPushButton("↺ 重置")
            btn_reset.setStyleSheet("background-color: #F1F5F9; color: #475569; border: 1px solid #CBD5E1; padding: 5px 10px; border-radius: 4px;")
            btn_row.addWidget(btn_query)
            btn_row.addWidget(btn_export)
            btn_row.addWidget(btn_reset)

            act_box = QVBoxLayout()
            act_box.setSpacing(2)
            act_top_spacer = QLabel("")  # 空白占位以保持与左侧输入框垂直对齐，去除 nbsp
            act_box.addWidget(act_top_spacer)
            act_box.addLayout(btn_row)
            p_grid_layout.addLayout(act_box)

            p_vbox.addWidget(p_grid_frame)

        self.preview_layout.addWidget(params_grp)

        # 3. KPI 指标卡模拟 (若有 btype == 'cards' 的区块)
        cards_blocks = [b for b in self._blocks_data if b.btype == 'cards']
        if cards_blocks:
            cards_grp = QGroupBox("📊 关键指标总览 (模拟 KPI 指标卡)")
            c_vbox = QVBoxLayout(cards_grp)
            c_vbox.setContentsMargins(10, 8, 10, 8)
            cards_flow = QHBoxLayout()
            cards_flow.setSpacing(12)

            palette = [
                {"top": "#2563EB", "num": "#1E3A8A", "bg": "#FFFFFF", "icon": "📊"},
                {"top": "#059669", "num": "#065F46", "bg": "#FFFFFF", "icon": "📈"},
                {"top": "#D97706", "num": "#92400E", "bg": "#FFFFFF", "icon": "🎯"},
                {"top": "#7C3AED", "num": "#5B21B6", "bg": "#FFFFFF", "icon": "💎"},
                {"top": "#0891B2", "num": "#155E75", "bg": "#FFFFFF", "icon": "💡"},
            ]
            sample_cards = [
                ("总体检人次", "1,580 人"),
                ("体检实收总额", "¥ 328,600.00"),
                ("平均客单价", "¥ 207.97"),
                ("综合完成率", "96.8%")
            ]
            for idx, (title, val) in enumerate(sample_cards):
                theme = palette[idx % len(palette)]
                c_box = QFrame()
                c_box.setMinimumWidth(150)
                c_box.setMaximumWidth(280)
                c_box.setStyleSheet(
                    "QFrame {"
                    "  background: " + theme['bg'] + ";"
                    "  border: 1px solid #E2E8F0;"
                    "  border-top: 3px solid " + theme['top'] + ";"
                    "  border-radius: 8px;"
                    "}"
                    "QFrame:hover {"
                    "  border-color: #CBD5E1;"
                    "  border-top: 3px solid " + theme['top'] + ";"
                    "  background: #FFFFFF;"
                    "}"
                )
                c_lay = QVBoxLayout(c_box)
                c_lay.setContentsMargins(14, 10, 14, 10)
                c_lay.setSpacing(6)

                t_row = QHBoxLayout()
                t_row.setSpacing(6)
                icn_lbl = QLabel(theme['icon'])
                icn_lbl.setStyleSheet("font-size: 11px;")
                t = QLabel(title)
                t.setStyleSheet("color: #64748B; font-size: 12px; font-weight: bold;")
                t_row.addWidget(icn_lbl)
                t_row.addWidget(t)
                t_row.addStretch()

                v = QLabel(val)
                v.setStyleSheet("color: " + theme['num'] + "; font-size: 22px; font-weight: bold; font-family: 'Segoe UI', 'Microsoft YaHei', sans-serif;")
                c_lay.addLayout(t_row)
                c_lay.addWidget(v)
                cards_flow.addWidget(c_box)

            cards_flow.addStretch()
            c_vbox.addLayout(cards_flow)
            self.preview_layout.addWidget(cards_grp)

        # 4. 报表表格模拟
        table_blocks = [b for b in self._blocks_data if b.btype != 'cards']
        if not table_blocks:
            table_blocks = [QueryBlock(block_id='main', title='主查询结果', btype='table')]

        tables_grp = QGroupBox("📋 报表数据呈现 (模拟带合计行的数据表)")
        tb_vbox = QVBoxLayout(tables_grp)
        tb_vbox.setContentsMargins(10, 8, 10, 8)

        if len(table_blocks) == 1:
            b = table_blocks[0]
            tb_vbox.addWidget(self._build_mock_table_widget(b))
        else:
            multi_tab = QTabWidget()
            for b in table_blocks:
                multi_tab.addTab(self._build_mock_table_widget(b), b.title or b.id)
            tb_vbox.addWidget(multi_tab)

        self.preview_layout.addWidget(tables_grp)
        self.preview_layout.addStretch()

    def _build_mock_table_widget(self, block):
        container = QWidget()
        c_layout = QVBoxLayout(container)
        c_layout.setContentsMargins(0, 4, 0, 0)
        c_layout.setSpacing(4)

        info_row = QHBoxLayout()
        ds_text = block.datasource or self.datasource_combo.currentText().strip() or 'default'
        sum_text = block.summary_footer or self.meta_summary_edit.text().strip() or '未配置'
        info_lbl = QLabel(f"🔌 数据源: <b>{ds_text}</b>  |  📐 合计规则: <b>{sum_text}</b>")
        info_lbl.setStyleSheet("color: #475569; font-size: 11px;")
        info_row.addWidget(info_lbl)
        info_row.addStretch()
        c_layout.addLayout(info_row)

        table = QTableWidget()
        cols = ["体检号", "姓名", "科室", "检查项目", "应收金额", "实收金额", "登记日期"]
        table.setColumnCount(len(cols))
        table.setHorizontalHeaderLabels(cols)
        table.setRowCount(4)

        mock_rows = [
            ["TJ20260901", "张三", "内科", "入职常规体检", "350.00", "320.00", "2026-09-28"],
            ["TJ20260902", "李四", "外科", "深度全套体检", "880.00", "850.00", "2026-09-28"],
            ["TJ20260903", "王五", "妇科", "专项妇检套餐", "520.00", "500.00", "2026-09-28"],
        ]
        for r, rdata in enumerate(mock_rows):
            for c, val in enumerate(rdata):
                table.setItem(r, c, QTableWidgetItem(val))

        # 合计行 (第 4 行)
        sum_row_idx = 3
        sum_items = ["∑ 合计 (3条)", "", "", "", "1,750.00", "1,670.00", ""]
        for c, val in enumerate(sum_items):
            item = QTableWidgetItem(val)
            item.setBackground(QColor("#F1F5F9"))
            f = item.font()
            f.setBold(True)
            item.setFont(f)
            item.setForeground(QColor("#0F172A"))
            if c in (4, 5):
                item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            table.setItem(sum_row_idx, c, item)

        table.horizontalHeader().setStretchLastSection(True)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        table.setFixedHeight(145)
        c_layout.addWidget(table)
        return container

    # ── Tab 4: 源码模式 (Raw .qry) ─────────────
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

    # ── Tab 5: 使用说明与示例 (Docs & Templates) 
    def _create_docs_tab(self):
        tab = QWidget()
        layout = QHBoxLayout(tab)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)

        # 左侧：主题目录导航
        left_pane = QWidget()
        lp_layout = QVBoxLayout(left_pane)
        lp_layout.setContentsMargins(0, 0, 0, 0)
        lp_layout.setSpacing(6)

        title_lbl = QLabel("📖 <b>说明与模版导航</b>")
        title_lbl.setStyleSheet("color: #0747A6; font-size: 13px;")
        lp_layout.addWidget(title_lbl)

        self.docs_list = QListWidget()
        self.docs_list.setStyleSheet("""
            QListWidget {
                border: 1px solid #DFE1E6;
                border-radius: 4px;
                background-color: #FAFBFC;
                font-size: 12px;
            }
            QListWidget::item {
                padding: 10px 8px;
                border-bottom: 1px solid #EBECF0;
                color: #172B4D;
            }
            QListWidget::item:selected {
                background-color: #DEEBFF;
                color: #0747A6;
                font-weight: bold;
            }
        """)

        topics = [
            "🚀 快速入门 3 步走",
            "🎛️ 9大查询控件说明",
            "🔀 动态下拉 options_sql 规范",
            "🔌 跨库多数据源配置说明",
            "📊 指标卡 (cards) 与合计行",
            "📑 模版一：单表综合统计 (常用)",
            "📑 模版二：跨库多数据源报表",
            "📑 模版三：KPI 经营看板驾驶舱"
        ]
        for t in topics:
            self.docs_list.addItem(t)

        lp_layout.addWidget(self.docs_list)
        left_pane.setFixedWidth(230)
        layout.addWidget(left_pane)

        # 右侧：对应主题的详细图文内容与模版
        self.docs_stack = QStackedWidget()

        # 页面 0: 快速入门
        self.docs_stack.addWidget(self._build_doc_intro())
        # 页面 1: 9大控件说明
        self.docs_stack.addWidget(self._build_doc_controls())
        # 页面 2: options_sql 规范
        self.docs_stack.addWidget(self._build_doc_options_sql())
        # 页面 3: 跨库多数据源
        self.docs_stack.addWidget(self._build_doc_multi_ds())
        # 页面 4: 指标卡与合计行
        self.docs_stack.addWidget(self._build_doc_cards_summary())
        # 页面 5: 模版一
        self.docs_stack.addWidget(self._build_template_page_1())
        # 页面 6: 模版二
        self.docs_stack.addWidget(self._build_template_page_2())
        # 页面 7: 模版三
        self.docs_stack.addWidget(self._build_template_page_3())

        self.docs_list.currentRowChanged.connect(self.docs_stack.setCurrentIndex)
        self.docs_list.setCurrentRow(0)

        layout.addWidget(self.docs_stack, stretch=1)
        return tab

    def _copy_text_to_clipboard(self, text):
        clipboard = QApplication.clipboard()
        clipboard.setText(text.strip())
        QMessageBox.information(self, "复制成功", "模版源码已成功复制到系统剪贴板！可在任意文本编辑器中粘贴使用。")

    def _load_template_to_editor(self, tpl_content):
        reply = QMessageBox.question(
            self, "确认载入模版",
            "载入示例模版将会替换当前编辑器中的全部内容。\n\n是否确认载入？",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            self.editor.setPlainText(tpl_content.strip())
            self._sync_raw_to_visual()
            self.tab_widget.setCurrentWidget(self.preview_tab)
            QMessageBox.information(self, "载入成功", "示例模版已成功载入！已自动切换至「👀 效果预览」标签页查看真实呈现效果。")

    def _build_doc_intro(self):
        page = QWidget()
        l = QVBoxLayout(page)
        l.setContentsMargins(10, 0, 10, 0)
        tb = QTextBrowser()
        tb.setOpenExternalLinks(False)
        tb.setHtml("""
        <h2 style='color:#0747A6;'>🚀 报表开发 3 步快速上手</h2>
        <p style='color:#555;'>DBQuery 系统采用声明式表单引擎（.qry 规范），让您无需编写任何前端界面代码，只需简单配置元数据、查询参数与 SQL 脚本，即可全自动生成美观专业的查询界面。</p>
        <hr color='#E2E8F0'>
        <h3 style='color:#1E293B;'>第一步：在「📋 基本信息」中设定表单属性</h3>
        <ul>
            <li><b>表单标题</b>：界面和导航树显示的中文名称（如：体检人员综合统计分析）；</li>
            <li><b>所属分组</b>：选择或输入新分组名称（保存时系统自动创建文件夹分类归档）；</li>
            <li><b>默认数据源</b>：默认连接主库 <code>default</code>；若需跨库，可在下拉框直接选择。</li>
        </ul>
        <h3 style='color:#1E293B;'>第二步：在「⚙️ 查询条件」中定义操作员输入项</h3>
        <ul>
            <li>点击 <b>➕ 添加参数</b> 按钮；</li>
            <li>设置英文标识（如 <code>start_date</code>）和中文标签（如 <code>开始日期</code>）；</li>
            <li>选择控件类型（单行文本、日期、下拉框、单选等），日期推荐设置默认值为 <code>{today}</code>。</li>
        </ul>
        <h3 style='color:#1E293B;'>第三步：在「📊 报表区块」中编写 SQL 脚本</h3>
        <ul>
            <li>在 SQL 语句中使用 <b>{参数名}</b> 接收用户输入（例如：<code>WHERE RegDate >= '{start_date}'</code>）；</li>
            <li>可点击 SQL 框上方的快捷药丸按钮一键插入参数占位符；</li>
            <li>配置合计规则（填写 <code>auto</code> 即可自动累加所有数字列求和）；</li>
            <li>切换到「👀 效果预览」查看真实渲染，无误后点击右下角「保存」即可！</li>
        </ul>
        """)
        l.addWidget(tb)
        return page

    def _build_doc_controls(self):
        page = QWidget()
        l = QVBoxLayout(page)
        l.setContentsMargins(10, 0, 10, 0)
        tb = QTextBrowser()
        tb.setHtml("""
        <h2 style='color:#0747A6;'>🎛️ 9大查询控件说明表</h2>
        <table border='1' cellspacing='0' cellpadding='6' style='border-collapse:collapse; border-color:#CBD5E1; width:100%; font-size:12px;'>
            <tr style='background-color:#F1F5F9; color:#0F172A;'>
                <th>控件类型 (ptype)</th>
                <th>展现形式</th>
                <th>适用场景与默认值说明</th>
            </tr>
            <tr>
                <td><b>text</b></td>
                <td>单行文本输入框</td>
                <td>适用于单号、姓名、手机号等关键字模糊或精确检索。</td>
            </tr>
            <tr>
                <td><b>date</b></td>
                <td>日期选择器 (yyyy-MM-dd)</td>
                <td>选择具体日期；默认值支持填写 <code>{today}</code> 动态宏取当天。</td>
            </tr>
            <tr>
                <td><b>datetime</b></td>
                <td>日期时间选择器</td>
                <td>精确到秒的开始与截止时间，格式：<code>yyyy-MM-dd HH:mm:ss</code>。</td>
            </tr>
            <tr>
                <td><b>number</b></td>
                <td>数值输入框</td>
                <td>仅允许输入整数或浮点数字，如金额下限、年龄、数量等。</td>
            </tr>
            <tr>
                <td><b>select</b></td>
                <td>下拉单选选择框</td>
                <td>支持静态列表（逗号分隔）或动态 <code>options_sql</code> 从字典表加载；支持输入拼音/文字检索。</td>
            </tr>
            <tr>
                <td><b>radio</b></td>
                <td>单选按钮组</td>
                <td>选项数量较少（2~5个）时使用，如：男/女、有效/无效。</td>
            </tr>
            <tr>
                <td><b>checkbox</b></td>
                <td>复选勾选框</td>
                <td>选中时提交 <code>1</code>，未选中时提交 <code>0</code>。</td>
            </tr>
            <tr>
                <td><b>textarea</b></td>
                <td>多行文本输入框</td>
                <td>大段文本输入，如批量输入多个体检号（每行一个）。</td>
            </tr>
            <tr>
                <td><b>hidden</b></td>
                <td>隐藏参数（无界面）</td>
                <td>用户不可见，但在 SQL 中提交固定的默认值（如系统编号等）。</td>
            </tr>
        </table>
        """)
        l.addWidget(tb)
        return page

    def _build_doc_options_sql(self):
        page = QWidget()
        l = QVBoxLayout(page)
        l.setContentsMargins(10, 0, 10, 0)
        tb = QTextBrowser()
        tb.setHtml("""
        <h2 style='color:#0747A6;'>🔀 动态下拉 options_sql 规范指南</h2>
        <p style='color:#555;'>当需要在下拉框中展示来自数据库表的动态字典数据（如科室列表、开单医生、检查套餐等）时，使用 <code>options_sql</code> 属性。</p>
        <hr color='#E2E8F0'>
        <h3 style='color:#1E293B;'>一、返回列数规范（单列 vs 双列）</h3>
        <ul>
            <li><b>模式 1（单列）：值与显示相同</b><br>
                <code>SELECT DeptName FROM Departments WHERE Active = 1 ORDER BY SortOrder</code><br>
                下拉框中显示的文字即为提交到 SQL 的值。
            </li>
            <li style='margin-top:8px;'><b>模式 2（双列）：第1列为提交值，第2列为显示标签（强烈推荐）</b><br>
                <code>SELECT DeptCode, DeptName FROM Departments WHERE Active = 1 ORDER BY SortOrder</code><br>
                用户在界面看到的是 <code>DeptName</code>（如“内科门诊”），但最终传给 SQL <code>{dept}</code> 的是 <code>DeptCode</code>（如“D01”）。
            </li>
        </ul>
        <h3 style='color:#1E293B;'>二、安全与执行约束</h3>
        <ul>
            <li>必须为<b>只读 SELECT</b> 语句，严禁 INSERT、UPDATE、DELETE、EXEC；</li>
            <li>禁止在末尾加分号 <code>;</code>，严禁拼接多条 SQL 语句；</li>
            <li><code>options_sql</code> 始终连接默认主库执行。</li>
        </ul>
        """)
        l.addWidget(tb)
        return page

    def _build_doc_multi_ds(self):
        page = QWidget()
        l = QVBoxLayout(page)
        l.setContentsMargins(10, 0, 10, 0)
        tb = QTextBrowser()
        tb.setHtml("""
        <h2 style='color:#0747A6;'>🔌 跨库多数据源配置说明</h2>
        <p style='color:#555;'>系统支持一个表单同时汇总展示来自不同数据库、甚至不同服务器的数据（例如：主库查询体检基本信息，检验库查询 LIS 报告结果，财务库查询收费明细）。</p>
        <hr color='#E2E8F0'>
        <h3 style='color:#1E293B;'>一、在 config.ini 中配置命名数据源</h3>
        <pre style='background:#F8FAFC; border:1px solid #E2E8F0; padding:8px; border-radius:4px;'>
[datasource.lis_db]
name = 检验分库LIS
server = 192.168.1.50
port = 1433
database = LisDb
user = sa
password = your_password
db_type = mssql
        </pre>
        <h3 style='color:#1E293B;'>二、在表单中绑定数据源</h3>
        <ul>
            <li>在「基本信息」中，可设置整张表单的 <code>默认数据源</code>；</li>
            <li>在「报表区块」中，每个区块都有独立的 <code>数据源</code> 下拉框。选择 <code>lis_db</code> 后，该区块将直连检验库执行查询；</li>
            <li>客户端将同时并排或多 Tab 切换呈现各库结果，并支持一键导出到同一个 Excel 的不同工作表中！</li>
        </ul>
        """)
        l.addWidget(tb)
        return page

    def _build_doc_cards_summary(self):
        page = QWidget()
        l = QVBoxLayout(page)
        l.setContentsMargins(10, 0, 10, 0)
        tb = QTextBrowser()
        tb.setHtml("""
        <h2 style='color:#0747A6;'>📊 指标卡 (cards) 与合计行 (summary_footer)</h2>
        <hr color='#E2E8F0'>
        <h3 style='color:#1E293B;'>一、顶部大字 KPI 指标卡 (type = cards)</h3>
        <p>适合放置在报表顶部，突出展示核心总额、人次、均价等关键指标：</p>
        <pre style='background:#F8FAFC; border:1px solid #E2E8F0; padding:8px; border-radius:4px;'>
[block.kpi_cards]
title = 核心关键指标
type = cards
datasource = default
sql = SELECT COUNT(*) AS [总体检人次], SUM(PaidFee) AS [实收总额] FROM ExamRecords
        </pre>
        <p>系统自动将查询返回的<b>第一行数据的每个列名和数值</b>渲染为独立的大字 KPI 指标卡片；导出 Excel 时将自动在首个 Sheet「📊 指标总览」以大字卡片输出。</p>
        <h3 style='color:#1E293B;'>二、数据表格底部置底合计行 (summary_footer)</h3>
        <ul>
            <li><b>规则 1：自动对所有数值列求和（最便捷）</b><br>
                <code>summary_footer = auto</code><br>
                表格底端置底显示合计行，首列显示“合计 (N条)”，所有数值列自动累加求和。
            </li>
            <li style='margin-top:8px;'><b>规则 2：按列名指定聚合函数</b><br>
                <code>summary_footer = sum:实收金额,应收金额; count:体检号; avg:客单均价</code><br>
                指定只有特定列参与计算，支持 <code>sum</code>、<code>count</code>、<code>avg</code> 等函数。
            </li>
        </ul>
        """)
        l.addWidget(tb)
        return page

    def _build_template_page_1(self):
        content = u"""[meta]
title = 体检人员综合统计
group = 体检报表
description = 包含日期区间、下拉科室筛选、人员明细及全表自动累加合计
datasource = default
query_type = select
web_enabled = true
summary_footer = auto

[params]
start_date = 开始日期 | date | {today} | required | width=150px
end_date = 结束日期 | date | {today} | required | width=150px
dept = 体检科室 | select:全部,内科,外科,五官科,妇科,检验科 | 全部 | searchable
status = 登记状态 | radio:全部,已登记,已体检,已总检 | 全部
keyword = 检索关键词 | text | | placeholder=输入姓名或体检号

[block.main]
title = 体检明细清单
type = table
datasource = default
summary_footer = auto
sql = 
SELECT 
    t.ExamNo AS [体检编号],
    t.PatientName AS [姓名],
    t.Gender AS [性别],
    t.Age AS [年龄],
    t.DeptName AS [体检科室],
    t.TotalFee AS [应收金额],
    t.PaidFee AS [实收金额],
    t.Status AS [当前状态],
    t.RegDate AS [登记时间]
FROM ExamRecords t
WHERE t.RegDate >= '{start_date} 00:00:00'
  AND t.RegDate <= '{end_date} 23:59:59'
  AND ('{dept}' = '全部' OR t.DeptName = '{dept}')
  AND ('{status}' = '全部' OR t.Status = '{status}')
  AND ('{keyword}' = '' OR t.PatientName LIKE '%{keyword}%' OR t.ExamNo LIKE '%{keyword}%')
ORDER BY t.RegDate DESC
"""
        return self._create_template_widget("📑 模版一：单表综合统计 (最常用标准模版)",
                                           "涵盖日期区间、下拉框、单选项、关键词检索、auto 自动合计等最常用业务场景。",
                                           content)

    def _build_template_page_2(self):
        content = u"""[meta]
title = 跨库综合就诊核对
group = 综合核对
description = 跨库查询：同时汇总 HIS 主库与 LIS 检验分库数据
datasource = default
web_enabled = true
layout = his_info, lis_results

[params]
start_date = 统计日期 | date | {today} | required
exam_no = 体检号/就诊号 | text | | placeholder=输入指定就诊号

[block.his_info]
title = HIS主库就诊信息
type = table
datasource = default
summary_footer = sum:应收金额,实收金额
sql = 
SELECT 
    h.PatientID AS [就诊号],
    h.PatientName AS [姓名],
    h.DoctorName AS [开单医生],
    h.TotalFee AS [应收金额],
    h.PaidFee AS [实收金额],
    h.VisitDate AS [就诊时间]
FROM HIS_Visits h
WHERE h.VisitDate >= '{start_date}'
  AND ('{exam_no}' = '' OR h.PatientID = '{exam_no}')

[block.lis_results]
title = LIS检验分库报告
type = table
datasource = lis_db
summary_footer = count:标本号
sql = 
SELECT 
    l.SampleNo AS [标本号],
    l.PatientID AS [就诊号],
    l.ItemName AS [检验项目],
    l.ResultValue AS [检测结果],
    l.RefRange AS [参考区间],
    l.CheckTime AS [检验时间]
FROM LIS_TestItems l
WHERE l.CheckTime >= '{start_date}'
  AND ('{exam_no}' = '' OR l.PatientID = '{exam_no}')
"""
        return self._create_template_widget("📑 模版二：跨库多数据源联合报表",
                                           "通过不同区块绑定独立数据源，同时查询主库与分库数据并在客户端分页展示。",
                                           content)

    def _build_template_page_3(self):
        content = u"""[meta]
title = 运营经营看板
group = 经营管理
description = 顶部大字突出 KPI 指标卡，底部展示科室明细与自动合计
datasource = default
web_enabled = true
layout = kpi_cards, dept_summary

[params]
start_date = 统计起始 | date | {today} | required
end_date = 统计截止 | date | {today} | required

[block.kpi_cards]
title = 核心经营指标
type = cards
datasource = default
sql = 
SELECT 
    COUNT(DISTINCT ExamNo) AS [总登记人数],
    SUM(TotalFee) AS [应收总额],
    SUM(PaidFee) AS [实收总额],
    CAST(AVG(PaidFee) AS DECIMAL(10,2)) AS [客单价]
FROM ExamRecords
WHERE RegDate >= '{start_date}' AND RegDate <= '{end_date} 23:59:59'

[block.dept_summary]
title = 各科室明细汇总
type = table
datasource = default
summary_footer = sum:人次,实收总额; avg:客单均价
sql = 
SELECT 
    DeptName AS [科室名称],
    COUNT(ExamNo) AS [人次],
    SUM(PaidFee) AS [实收总额],
    CAST(AVG(PaidFee) AS DECIMAL(10,2)) AS [客单均价]
FROM ExamRecords
WHERE RegDate >= '{start_date}' AND RegDate <= '{end_date} 23:59:59'
GROUP BY DeptName
ORDER BY SUM(PaidFee) DESC
"""
        return self._create_template_widget("📑 模版三：KPI 经营看板驾驶舱",
                                           "顶部 cards 区块展示大字 KPI 指标卡，底部 table 区块展示明细报表与合计行。",
                                           content)

    def _create_template_widget(self, title, desc, qry_content):
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(10, 0, 10, 0)
        v.setSpacing(6)

        t_lbl = QLabel(f"<b>{title}</b>")
        t_lbl.setStyleSheet("color: #0747A6; font-size: 13px;")
        d_lbl = QLabel(desc)
        d_lbl.setStyleSheet("color: #555; font-size: 11px;")
        v.addWidget(t_lbl)
        v.addWidget(d_lbl)

        code_box = QPlainTextEdit()
        mono_font = QFont("Courier New", 10)
        mono_font.setStyleHint(QFont.TypeWriter)
        code_box.setFont(mono_font)
        code_box.setReadOnly(True)
        code_box.setPlainText(qry_content.strip())
        code_box.setStyleSheet("background: #F8FAFC; border: 1px solid #CBD5E1; border-radius: 4px;")
        QryHighlighter(code_box.document())
        v.addWidget(code_box, stretch=1)

        b_row = QHBoxLayout()
        btn_copy = QPushButton("📋 复制模版源码")
        btn_copy.setStyleSheet("background-color: #F4F5F7; color: #172B4D; font-weight: bold; padding: 4px 12px; border: 1px solid #DFE1E6; border-radius: 4px;")
        btn_copy.clicked.connect(lambda: self._copy_text_to_clipboard(qry_content))

        btn_load = QPushButton("📥 载入此模版到设计器")
        btn_load.setStyleSheet("background-color: #0052CC; color: white; font-weight: bold; padding: 4px 14px; border-radius: 4px;")
        btn_load.clicked.connect(lambda: self._load_template_to_editor(qry_content))

        b_row.addWidget(btn_copy)
        b_row.addWidget(btn_load)
        b_row.addStretch()
        v.addLayout(b_row)

        return w
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

        current_widget = self.tab_widget.widget(new_index)
        prev_widget = self.tab_widget.widget(self._prev_tab_index) if hasattr(self, '_prev_tab_index') and 0 <= self._prev_tab_index < self.tab_widget.count() else None

        # 无论从哪个可视化Tab切出，先保存当前选中的参数和区块细节
        if prev_widget in (self.meta_tab, self.params_tab, self.blocks_tab):
            self._save_current_param_details()
            self._save_current_block_details()

        # 从源码模式切出到其他Tab
        if prev_widget == self.raw_tab and current_widget != self.raw_tab:
            self._sync_raw_to_visual()
        # 切入源码模式
        elif current_widget == self.raw_tab:
            self._sync_visual_to_raw()
        # 切入区块排版
        elif current_widget == self.blocks_tab:
            self._refresh_quick_param_buttons()
        # 切入效果预览
        elif current_widget == self.preview_tab:
            self._refresh_live_preview()

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
            if hasattr(self, 'tab_widget') and hasattr(self, 'raw_tab') and self.tab_widget.currentWidget() != self.raw_tab:
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
        if hasattr(self, 'tab_widget') and hasattr(self, 'raw_tab') and self.tab_widget.currentWidget() != self.raw_tab:
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
        if hasattr(self, 'tab_widget') and hasattr(self, 'raw_tab') and self.tab_widget.currentWidget() != self.raw_tab:
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
        if hasattr(self, 'tab_widget') and hasattr(self, 'raw_tab') and self.tab_widget.currentWidget() != self.raw_tab:
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
