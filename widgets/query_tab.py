# -*- coding: utf-8 -*-
"""
查询标签页
包含：查询条件区、执行按钮、结果表格、导出功能
"""
import time
import datetime
import logging
import traceback

# 配置日志
logger = logging.getLogger('DBQuery.query_tab')

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QDateEdit, QDateTimeEdit, QComboBox, QGroupBox,
    QTableView, QHeaderView, QAbstractItemView,
    QFileDialog, QMessageBox, QProgressBar, QScrollArea,
    QApplication, QMenu, QFrame, QPlainTextEdit, QCheckBox,
    QRadioButton, QButtonGroup, QCompleter, QTabBar
)
from PyQt5.QtCore import (
    Qt, QThread, pyqtSignal,
    QAbstractTableModel, QModelIndex, QDate, QDateTime
)
from PyQt5.QtGui import QColor, QBrush, QDoubleValidator, QFont

from db_manager import DBManager
from form_parser import FormParser
from core.param_service import (
    OptionsLoadError, ParameterError, RequiredParameterError, load_options,
    merge_options, normalize_params, resolve_default, static_options
)
from core.query_service import build_final_sql, export_to_excel
from core.summary_service import compute_summary, compute_cards


# ──────────────────────────────────────────────
#  自定义 TableModel（内置过滤与底部固定合计行支持）
# ──────────────────────────────────────────────
class ResultTableModel(QAbstractTableModel):
    def __init__(self, columns, rows, summary_spec=None, parent=None):
        super(ResultTableModel, self).__init__(parent)
        self._columns = columns
        self._all_rows = rows  # 保存所有原始数据
        self._rows = rows      # 当前显示的数据（过滤后）
        self._filter_text = ''
        self._filter_col = -1  # -1 表示全部列
        self._summary_spec = str(summary_spec or '').strip()
        self._summary_row = None
        self._summary_dict = {}
        self._recompute_summary()

    def _recompute_summary(self):
        if self._summary_spec and self._columns:
            s_row, s_dict = compute_summary(self._columns, self._rows, self._summary_spec)
            self._summary_row = s_row
            self._summary_dict = s_dict
        else:
            self._summary_row = None
            self._summary_dict = {}

    def rowCount(self, parent=QModelIndex()):
        base = len(self._rows)
        return base + 1 if self._summary_row else base

    def columnCount(self, parent=QModelIndex()):
        return len(self._columns)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None

        row = index.row()
        col = index.column()

        is_summary = (self._summary_row is not None and row == len(self._rows))

        # 边界检查
        if not is_summary:
            if row < 0 or row >= len(self._rows):
                return None
        if col < 0 or col >= len(self._columns):
            return None

        if is_summary:
            val = self._summary_row[col] if col < len(self._summary_row) else ''
            if role == Qt.DisplayRole:
                return str(val) if val is not None else ''
            if role == Qt.FontRole:
                f = QFont()
                f.setBold(True)
                return f
            if role == Qt.BackgroundRole:
                return QBrush(QColor('#EFF6FF'))
            if role == Qt.ForegroundRole:
                return QBrush(QColor('#1E40AF'))
            if role == Qt.TextAlignmentRole:
                if col == 0:
                    return int(Qt.AlignLeft | Qt.AlignVCenter)
                return int(Qt.AlignRight | Qt.AlignVCenter)
            return None

        val = self._rows[row][col]

        if role == Qt.DisplayRole:
            if val is None:
                return 'NULL'
            if isinstance(val, (datetime.datetime, datetime.date)):
                return str(val)
            return str(val)

        if role == Qt.BackgroundRole:
            if row % 2 == 0:
                return QBrush(QColor('#F5F8FF'))

        if role == Qt.ForegroundRole:
            if val is None:
                return QBrush(QColor('#AAAAAA'))

        if role == Qt.TextAlignmentRole:
            if isinstance(val, (int, float)):
                return int(Qt.AlignRight | Qt.AlignVCenter)
            return int(Qt.AlignLeft | Qt.AlignVCenter)

        return None

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role == Qt.DisplayRole:
            if orientation == Qt.Horizontal:
                if 0 <= section < len(self._columns):
                    return self._columns[section]
                return ''
            if self._summary_row and section == len(self._rows):
                return u"∑"
            return str(section + 1)
        return None

    def sort(self, column, order):
        self.layoutAboutToBeChanged.emit()
        reverse = (order == Qt.DescendingOrder)

        def sort_key(row):
            v = row[column]
            if v is None:
                return (1, '')
            return (0, str(v))

        self._rows.sort(key=sort_key, reverse=reverse)
        self.layoutChanged.emit()

    def apply_filter(self, text, col_idx=-1):
        """应用过滤条件"""
        self._filter_text = text.lower() if text else ''
        self._filter_col = col_idx

        self.layoutAboutToBeChanged.emit()

        if not self._filter_text:
            self._rows = self._all_rows[:]
        else:
            self._rows = []
            for row in self._all_rows:
                if self._row_matches(row):
                    self._rows.append(row)

        self._recompute_summary()
        self.layoutChanged.emit()

    def _row_matches(self, row):
        """检查一行是否匹配过滤条件"""
        if self._filter_col >= 0:
            # 搜索指定列
            if self._filter_col < len(row):
                cell = str(row[self._filter_col] or '').lower()
                return self._filter_text in cell
            return False
        else:
            # 搜索全部列
            for val in row:
                cell = str(val or '').lower()
                if self._filter_text in cell:
                    return True
            return False

    def get_filtered_count(self):
        """获取过滤后的行数"""
        return len(self._rows)

    def get_total_count(self):
        """获取总行数"""
        return len(self._all_rows)


# ──────────────────────────────────────────────
#  后台查询线程
# ──────────────────────────────────────────────
class QueryWorker(QThread):
    # 注意：不能命名为 finished，会与 QThread 内置信号冲突导致崩溃
    result_ready       = pyqtSignal(list, list)
    multi_result_ready = pyqtSignal(dict)
    query_error        = pyqtSignal(str)
    query_cancelled    = pyqtSignal()

    def __init__(self, db_manager, sql, query_type='select', form=None, normalized_params=None):
        super(QueryWorker, self).__init__()
        self.db_manager = db_manager
        self.sql        = sql
        self.query_type = query_type
        self.form       = form
        self.normalized_params = normalized_params or {}
        self._cancelled = False

    def cancel(self):
        """请求取消查询（协作式，等待当前 SQL 执行完毕后退出）"""
        self._cancelled = True

    def run(self):
        logger.info("QueryWorker started")
        try:
            blocks = getattr(self.form, 'blocks', []) if self.form else []
            if not blocks:
                columns, rows = self.db_manager.execute_query(self.sql, self.query_type)
                if self._cancelled:
                    self.query_cancelled.emit()
                    return
                self.result_ready.emit(columns, rows)
                self.multi_result_ready.emit({'main': {'columns': columns, 'rows': rows, 'block': None}})
                return

            blocks_results = {}
            primary_cols = None
            primary_rows = None

            for block in blocks:
                if self._cancelled:
                    self.query_cancelled.emit()
                    return
                b_sql = build_final_sql(self.form, self.normalized_params, already_normalized=True, sql_template=block.sql)
                cols, rows = self.db_manager.execute_query(b_sql, self.query_type, datasource=block.datasource)
                blocks_results[block.id] = {
                    'columns': cols,
                    'rows': rows,
                    'block': block
                }
                if block.btype == 'table' and primary_cols is None:
                    primary_cols = cols
                    primary_rows = rows

            if self._cancelled:
                self.query_cancelled.emit()
                return

            if primary_cols is None and blocks:
                first_id = blocks[0].id
                primary_cols = blocks_results[first_id]['columns']
                primary_rows = blocks_results[first_id]['rows']

            self.result_ready.emit(primary_cols or [], primary_rows or [])
            self.multi_result_ready.emit(blocks_results)
        except Exception as e:
            if self._cancelled:
                self.query_cancelled.emit()
                return
            logger.error("QueryWorker error: %s", str(e))
            logger.error(traceback.format_exc())
            self.query_error.emit(str(e))


# ──────────────────────────────────────────────
#  动态候选项加载线程
# ──────────────────────────────────────────────
class OptionsWorker(QThread):
    options_ready = pyqtSignal(str, list)
    options_error = pyqtSignal(str)

    def __init__(self, param):
        super(OptionsWorker, self).__init__()
        self.param = param

    def run(self):
        try:
            # 每次加载使用独立 DBManager 和短生命周期连接，不共享 UI 查询连接。
            options = load_options(self.param, DBManager())
            self.options_ready.emit(self.param.name, options)
        except OptionsLoadError:
            logger.exception('桌面端动态候选加载失败: %s', self.param.name)
            self.options_error.emit(self.param.name)


# ──────────────────────────────────────────────
#  后台 Excel 导出线程
# ──────────────────────────────────────────────
class ExportWorker(QThread):
    export_done  = pyqtSignal(str)   # 成功：文件路径
    export_error = pyqtSignal(str)   # 失败：错误信息

    def __init__(self, path, columns, rows, form_title, form_desc,
                 elapsed, params_info, final_sql, summary_row=None, blocks=None):
        super(ExportWorker, self).__init__()
        self.path         = path
        self.columns      = columns
        self.rows         = rows
        self.form_title   = form_title
        self.form_desc    = form_desc
        self.elapsed      = elapsed
        self.params_info  = params_info
        self.final_sql    = final_sql
        self.summary_row  = summary_row
        self.blocks       = blocks

    def run(self):
        try:
            export_to_excel(
                self.path, self.columns, self.rows,
                self.form_title, self.form_desc,
                self.elapsed, self.params_info, self.final_sql,
                summary_row=self.summary_row, blocks=self.blocks
            )
            self.export_done.emit(self.path)
        except Exception as e:
            self.export_error.emit(str(e))


# ──────────────────────────────────────────────
#  查询标签页主体
# ──────────────────────────────────────────────
class QueryTab(QWidget):

    # 通知主窗口刷新表单列表
    request_reload = pyqtSignal()
    # 通知主窗口：该 tab 对应的表单文件已被修改，需要重新打开
    form_modified  = pyqtSignal(str)   # file_path

    def __init__(self, form, db_manager, forms_dir, parent=None):
        super(QueryTab, self).__init__(parent)
        self.form        = form
        self.db_manager  = db_manager
        self.forms_dir   = forms_dir
        self._param_widgets  = {}   # {param_name: QWidget 或 QButtonGroup}
        self._param_defs     = {param.name: param for param in form.params}
        self._param_options  = {}   # {param_name: [{value, label}, ...]}
        self._option_workers = []
        self._worker         = None
        self._last_columns   = []
        self._last_rows      = []
        self._elapsed        = 0.0
        self._query_start    = 0.0

        self._setup_ui()

    # ── 界面构建 ──────────────────────────────
    def _setup_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 8, 10, 8)
        root.setSpacing(6)

        # 标题行
        title_row = QHBoxLayout()
        title_lbl = QLabel(u"<b>{}</b>".format(self.form.title))
        title_lbl.setStyleSheet("font-size: 15px; font-weight: bold; color: #1E293B;")

        # 查询类型徽标
        type_badge = QLabel(u"⚡ 存储过程" if self.form.query_type == 'exec' else u"📊 查询")
        if self.form.query_type == 'exec':
            type_badge.setStyleSheet(
                "background: #FEF3C7; color: #D97706; font-size: 11px; font-weight: bold;"
                "padding: 2px 8px; border-radius: 4px; border: 1px solid #FDE68A;"
            )
        else:
            type_badge.setStyleSheet(
                "background: #EFF6FF; color: #2563EB; font-size: 11px; font-weight: bold;"
                "padding: 2px 8px; border-radius: 4px; border: 1px solid #BFDBFE;"
            )

        desc_lbl = QLabel(self.form.description or '')
        desc_lbl.setStyleSheet("color: #64748B; font-size: 11px; margin-left: 6px;")

        edit_btn = QPushButton(u"✏️ 编辑表单")
        edit_btn.setFixedWidth(88)
        edit_btn.setStyleSheet(
            "QPushButton {"
            "  background: #FFFFFF; border: 1px solid #CBD5E1; border-radius: 6px;"
            "  color: #475569; font-size: 11px; padding: 4px 8px;"
            "}"
            "QPushButton:hover { background: #EFF6FF; color: #1D4ED8; border-color: #93C5FD; }"
        )
        edit_btn.clicked.connect(self._edit_form)

        title_row.addWidget(title_lbl)
        title_row.addWidget(type_badge)
        title_row.addWidget(desc_lbl)
        title_row.addStretch()
        title_row.addWidget(edit_btn)
        root.addLayout(title_row)

        # 分隔线
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setStyleSheet("color: #E2E8F0;")
        root.addWidget(line)

        # 查询条件区
        if self.form.params:
            params_grp = QGroupBox(u"查询条件")
            params_inner = QHBoxLayout(params_grp)
            params_inner.setSpacing(14)
            self._build_param_widgets(params_inner)

            if len(self.form.params) > 5:
                scroll = QScrollArea()
                scroll.setWidget(params_grp)
                scroll.setWidgetResizable(True)
                scroll.setFixedHeight(100)
                scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
                scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
                root.addWidget(scroll)
            else:
                root.addWidget(params_grp)

        # 操作行
        action_row = QHBoxLayout()

        self.query_btn = QPushButton(u"  🔍 执行查询  ")
        self.query_btn.setStyleSheet(
            "QPushButton {"
            "  background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #2563EB, stop:1 #1D4ED8);"
            "  color: white;"
            "  padding: 6px 20px; border-radius: 6px;"
            "  font-weight: bold; font-size: 13px;"
            "  border: 1px solid #1E40AF;"
            "}"
            "QPushButton:hover  { background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #3B82F6, stop:1 #2563EB); border-color: #1D4ED8; }"
            "QPushButton:pressed{ background: #1E40AF; }"
            "QPushButton:disabled{ background: #94A3B8; border-color: #94A3B8; color: #F1F5F9; }"
        )
        self.query_btn.clicked.connect(self._execute_query)

        self.export_btn = QPushButton(u"📥 导出 Excel")
        self.export_btn.setEnabled(False)
        self.export_btn.setStyleSheet(
            "QPushButton {"
            "  background-color: #FFFFFF; color: #1E293B;"
            "  padding: 5px 16px; border-radius: 6px;"
            "  border: 1px solid #CBD5E1; font-size: 12px;"
            "}"
            "QPushButton:hover:enabled {"
            "  background-color: #ECFDF5; color: #047857; border-color: #10B981; font-weight: bold;"
            "}"
            "QPushButton:pressed:enabled{ background-color: #D1FAE5; }"
            "QPushButton:disabled{ background-color: #F8FAFC; color: #94A3B8; border-color: #E2E8F0; }"
        )
        self.export_btn.clicked.connect(self._export_excel)

        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setFixedWidth(100)
        self.progress.setFixedHeight(20)
        self.progress.hide()

        self.status_lbl = QLabel("")
        self.status_lbl.setStyleSheet("color: #64748B; font-size: 11px;")

        action_row.addWidget(self.query_btn)
        action_row.addWidget(self.export_btn)
        action_row.addWidget(self.progress)
        action_row.addStretch()
        action_row.addWidget(self.status_lbl)
        root.addLayout(action_row)

        # 顶部指标卡片区域
        self.cards_frame = QFrame()
        self.cards_frame.setObjectName("cards_container")
        self.cards_frame.setStyleSheet(
            "QFrame#cards_container { background: transparent; border: none; }"
        )
        self.cards_layout = QHBoxLayout(self.cards_frame)
        self.cards_layout.setContentsMargins(0, 4, 0, 4)
        self.cards_layout.setSpacing(14)
        self.cards_frame.hide()
        root.addWidget(self.cards_frame)

        # 多区块表格切换栏
        self.block_tabs = QTabBar()
        self.block_tabs.setDrawBase(False)
        self.block_tabs.setStyleSheet("""
            QTabBar {
                background: transparent;
                border: none;
            }
            QTabBar::tab {
                background: #EDF2F7;
                color: #4A5568;
                padding: 6px 16px;
                margin-right: 4px;
                border: 1px solid #CBD5E0;
                border-bottom: none;
                border-top-left-radius: 6px;
                border-top-right-radius: 6px;
                font-size: 12px;
                min-width: 90px;
            }
            QTabBar::tab:selected {
                background: #FFFFFF;
                color: #2B6CB0;
                border-color: #BEE3F8;
                border-top: 2px solid #3182CE;
                font-weight: bold;
            }
            QTabBar::tab:hover:!selected {
                background: #E2E8F0;
                color: #2D3748;
            }
        """)
        self.block_tabs.currentChanged.connect(self._on_block_tab_changed)
        self.block_tabs.hide()
        root.addWidget(self.block_tabs)

        # 结果表格
        self.table_view = QTableView()
        self.table_view.setSortingEnabled(True)
        self.table_view.setAlternatingRowColors(True)
        self.table_view.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table_view.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table_view.horizontalHeader().setStretchLastSection(False)
        self.table_view.horizontalHeader().setSectionsMovable(True)
        self.table_view.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.table_view.verticalHeader().setDefaultSectionSize(24)
        self.table_view.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table_view.customContextMenuRequested.connect(self._show_table_menu)
        root.addWidget(self.table_view, stretch=1)

        # 底部过滤行
        filter_row = QHBoxLayout()
        filter_row.addWidget(QLabel(u"结果过滤:"))

        self.filter_edit = QLineEdit()
        self.filter_edit.setPlaceholderText(u"输入关键字快速过滤显示结果…")
        self.filter_edit.setMaximumWidth(280)
        self.filter_edit.textChanged.connect(self._apply_filter)

        self.col_combo = QComboBox()
        self.col_combo.addItem(u"全部列")
        self.col_combo.setMaximumWidth(160)
        self.col_combo.currentIndexChanged.connect(self._apply_filter)

        self.filter_status = QLabel("")
        self.filter_status.setStyleSheet("color: #888; font-size: 11px;")

        filter_row.addWidget(self.filter_edit)
        filter_row.addWidget(self.col_combo)
        filter_row.addStretch()
        filter_row.addWidget(self.filter_status)
        root.addLayout(filter_row)

    def _build_param_widgets(self, layout):
        for param in self.form.params:
            # hidden 参数只保留在公共服务中，不创建可见控件。
            if param.ptype == 'hidden':
                self._param_widgets[param.name] = None
                continue

            lbl = QLabel(param.label + u":")
            lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            default = resolve_default(param)

            if param.ptype == 'date':
                w = QDateEdit()
                w.setCalendarPopup(True)
                w.setDisplayFormat("yyyy-MM-dd")
                self._set_date_control_value(w, default, is_datetime=False)
                w.setMinimumWidth(110)
                if hasattr(w, 'lineEdit') and w.lineEdit():
                    w.lineEdit().returnPressed.connect(self._execute_query)

            elif param.ptype == 'datetime':
                w = QDateTimeEdit()
                w.setCalendarPopup(True)
                w.setDisplayFormat("yyyy-MM-dd HH:mm:ss")
                self._set_date_control_value(w, default, is_datetime=True)
                w.setMinimumWidth(170)
                if hasattr(w, 'lineEdit') and w.lineEdit():
                    w.lineEdit().returnPressed.connect(self._execute_query)

            elif param.ptype == 'number':
                w = QLineEdit()
                w.setPlaceholderText(param.placeholder or u"请输入数字")
                w.setText(default)
                validator = QDoubleValidator(w)
                validator.setNotation(QDoubleValidator.StandardNotation)
                w.setValidator(validator)
                w.setMaximumWidth(120)
                w.returnPressed.connect(self._execute_query)

            elif param.ptype == 'select':
                w = self._create_searchable_combo(param)
                self._param_options[param.name] = static_options(param)
                self._set_combo_options(w, self._param_options[param.name], default)
                if param.options_sql:
                    self._load_dynamic_options(param)

            elif param.ptype == 'textarea':
                w = QPlainTextEdit()
                w.setPlaceholderText(param.placeholder or param.label)
                w.setPlainText(default)
                w.setMinimumWidth(160)
                w.setFixedHeight(54)
                w.installEventFilter(self)

            elif param.ptype == 'checkbox':
                w = QCheckBox(u"是")
                w.setChecked(default.strip().lower() in ('1', 'true', 'yes', 'on', '是'))

            elif param.ptype == 'radio':
                group_widget = QWidget()
                radio_layout = QHBoxLayout(group_widget)
                radio_layout.setContentsMargins(0, 0, 0, 0)
                radio_layout.setSpacing(8)
                w = QButtonGroup(group_widget)
                for index, option in enumerate(static_options(param)):
                    radio = QRadioButton(option['label'])
                    radio.setProperty('param_value', option['value'])
                    radio.setChecked(option['value'] == default)
                    w.addButton(radio, index)
                    radio_layout.addWidget(radio)
                radio_layout.addStretch()
                display_widget = group_widget

            else:
                w = QLineEdit()
                w.setPlaceholderText(param.placeholder or param.label)
                w.setText(default)
                w.setMinimumWidth(120)
                w.returnPressed.connect(self._execute_query)

            self._param_widgets[param.name] = w
            if param.ptype != 'radio':
                display_widget = w

            pair = QHBoxLayout()
            pair.setSpacing(4)
            pair.addWidget(lbl)
            pair.addWidget(display_widget)
            container = QWidget()
            container.setLayout(pair)
            layout.addWidget(container)

        layout.addStretch()

    def _set_date_control_value(self, widget, value, is_datetime=False):
        """让空默认值在 QDate(Edit/TimeEdit) 中保持为空，而不是隐式变成今天。"""
        minimum = QDate(1752, 9, 14)
        widget.setMinimumDate(minimum)
        widget.setSpecialValueText('')
        widget.setProperty('empty_date_value', minimum.toString('yyyy-MM-dd'))
        if is_datetime:
            parsed = QDateTime.fromString(value, 'yyyy-MM-dd HH:mm:ss')
            widget.setMinimumDateTime(QDateTime(minimum, QDateTime.currentDateTime().time()))
            widget.setDateTime(parsed if parsed.isValid() else QDateTime(minimum, QDateTime.currentDateTime().time()))
        else:
            parsed = QDate.fromString(value, 'yyyy-MM-dd')
            widget.setDate(parsed if parsed.isValid() else minimum)

    def _create_searchable_combo(self, param):
        """创建标签搜索、value 提交的不可自由录入下拉框。"""
        combo = QComboBox()
        combo.setEditable(True)
        combo.setInsertPolicy(QComboBox.NoInsert)
        combo.setMinimumWidth(130)
        combo.lineEdit().setPlaceholderText(param.placeholder or u"输入关键字筛选")
        completer = QCompleter(combo.model(), combo)
        completer.setCaseSensitivity(Qt.CaseInsensitive)
        completer.setFilterMode(Qt.MatchContains)
        completer.setCompletionMode(QCompleter.PopupCompletion)
        combo.setCompleter(completer)
        combo.lineEdit().returnPressed.connect(self._execute_query)
        return combo

    def _set_combo_options(self, combo, options, preferred_value=''):
        """按 value/label 写入 QComboBox，保留已选 value 或 .qry 默认值。"""
        existing_value = combo.currentData(Qt.UserRole)
        target_value = existing_value or preferred_value
        combo.blockSignals(True)
        combo.clear()
        for option in merge_options(options):
            combo.addItem(option['label'], option['value'])
        index = combo.findData(target_value, Qt.UserRole)
        if index >= 0:
            combo.setCurrentIndex(index)
        elif combo.count():
            combo.setCurrentIndex(0)
        combo.blockSignals(False)

    def _load_dynamic_options(self, param):
        worker = OptionsWorker(param)
        worker.options_ready.connect(self._on_options_ready)
        worker.options_error.connect(self._on_options_error)
        worker.finished.connect(lambda worker=worker: self._release_option_worker(worker))
        self._option_workers.append(worker)
        worker.start()

    def _release_option_worker(self, worker):
        if worker in self._option_workers:
            self._option_workers.remove(worker)
        worker.deleteLater()

    def _on_options_ready(self, param_name, dynamic_options):
        param = self._param_defs.get(param_name)
        combo = self._param_widgets.get(param_name)
        if param is None or not isinstance(combo, QComboBox):
            return
        self._param_options[param_name] = merge_options(static_options(param), dynamic_options)
        self._set_combo_options(combo, self._param_options[param_name], resolve_default(param))

    def _on_options_error(self, param_name):
        # 静态项已在表单构建时展示，动态失败仅给业务提示，不显示数据库堆栈。
        if hasattr(self, 'status_lbl'):
            self.status_lbl.setText(u"候选数据加载失败，可刷新重试")

    # ── Worker 清理辅助 ──────────────────────
    def _cancel_worker(self):
        """协作式取消 worker：设标志 → 等待 → 回收"""
        if self._worker is None:
            return
        if self._worker.isRunning():
            self._worker.cancel()
            if not self._worker.wait(5000):
                # 超时仍未结束，强杀（最后手段）
                self._worker.terminate()
                self._worker.wait(1000)
        try:
            self._worker.deleteLater()
        except Exception:
            pass
        self._worker = None

    def _on_query_cancelled(self):
        """查询被取消时的 UI 恢复"""
        self._cancel_worker()
        self.query_btn.setEnabled(True)
        self.progress.hide()
        self.status_lbl.setText(u"查询已取消")

    # ── 参数值获取 ────────────────────────────
    def _get_param_values(self):
        """仅采集控件原始值；类型规则统一交给 core.param_service。"""
        vals = {}
        for name, w in self._param_widgets.items():
            if isinstance(w, QDateTimeEdit) and not isinstance(w, QDateEdit):
                date_text = w.date().toString("yyyy-MM-dd")
                vals[name] = '' if date_text == w.property('empty_date_value') else w.dateTime().toString("yyyy-MM-dd HH:mm:ss")
            elif isinstance(w, QDateEdit):
                date_text = w.date().toString("yyyy-MM-dd")
                vals[name] = '' if date_text == w.property('empty_date_value') else date_text
            elif isinstance(w, QComboBox):
                text = w.currentText()
                index = w.currentIndex()
                # 只有标签仍与真实候选相符时提交其 value；否则交给服务拒绝临时搜索词。
                if index >= 0 and text == w.itemText(index):
                    vals[name] = w.itemData(index, Qt.UserRole)
                else:
                    vals[name] = text
            elif isinstance(w, QPlainTextEdit):
                vals[name] = w.toPlainText()
            elif isinstance(w, QCheckBox):
                vals[name] = '1' if w.isChecked() else '0'
            elif isinstance(w, QButtonGroup):
                selected = w.checkedButton()
                vals[name] = selected.property('param_value') if selected else ''
            elif isinstance(w, QLineEdit):
                vals[name] = w.text()
            else:
                vals[name] = None
        return vals

    def _normalized_param_values(self):
        return normalize_params(
            self.form, self._get_param_values(), options_by_name=self._param_options
        )

    def _build_final_sql(self):
        normalized = self._normalized_param_values()
        return build_final_sql(self.form, normalized, already_normalized=True)

    def _focus_param(self, param_name):
        widget = self._param_widgets.get(param_name)
        if isinstance(widget, QButtonGroup):
            widget = widget.checkedButton() or (widget.buttons()[0] if widget.buttons() else None)
        if widget is not None:
            widget.setFocus()

    # ── 执行查询 ──────────────────────────────
    def _execute_query(self):
        logger.info("_execute_query called")
        if self._worker and self._worker.isRunning():
            logger.info("Worker already running, returning")
            return

        try:
            sql = self._build_final_sql()
            logger.info("Built SQL: %s", sql[:200] if sql else "EMPTY")
        except RequiredParameterError as exc:
            self._focus_param(exc.param.name)
            QMessageBox.warning(self, u"请填写查询条件", str(exc))
            return
        except ParameterError as exc:
            QMessageBox.warning(self, u"查询条件", str(exc))
            return
        except Exception as e:
            logger.error("Error building SQL: %s", str(e))
            logger.error(traceback.format_exc())
            QMessageBox.critical(self, u"错误", u"构建 SQL 失败：\n{}".format(str(e)))
            return

        ok, reason = FormParser.is_safe_sql(sql, self.form.query_type)
        if not ok:
            logger.warning("SQL safety check failed: %s", reason)
            QMessageBox.warning(self, u"SQL 安全检查", reason)
            return

        self.query_btn.setEnabled(False)
        self.export_btn.setEnabled(False)
        self.progress.show()
        self.status_lbl.setText(u"查询中…")
        self._query_start = time.time()

        try:
            self._worker = QueryWorker(
                self.db_manager, sql, self.form.query_type,
                form=self.form, normalized_params=self._normalized_param_values()
            )
            self._worker.result_ready.connect(self._on_query_done)
            self._worker.multi_result_ready.connect(self._on_multi_query_done)
            self._worker.query_error.connect(self._on_query_error)
            self._worker.query_cancelled.connect(self._on_query_cancelled)
            logger.info("Starting worker thread")
            self._worker.start()
        except Exception as e:
            logger.error("Error starting worker: %s", str(e))
            logger.error(traceback.format_exc())
            self.query_btn.setEnabled(True)
            self.progress.hide()
            QMessageBox.critical(self, u"错误", u"启动查询线程失败：\n{}".format(str(e)))

    def _on_multi_query_done(self, blocks_results):
        logger.info("_on_multi_query_done called, blocks=%s", list(blocks_results.keys()))
        self._last_blocks_results = blocks_results
        cards_found = []
        for b_id, b_data in blocks_results.items():
            b = b_data.get('block')
            if b and b.btype == 'cards':
                cards = compute_cards(b_data['columns'], b_data['rows'])
                cards_found.extend(cards)

        # 清除现有卡片控件
        while self.cards_layout.count():
            item = self.cards_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

        if cards_found:
            # 丰富优雅的多彩商务主题配色（数值强调色）
            palette = [
                {"num": "#1E40AF"},  # 经典深蓝
                {"num": "#065F46"},  # 翡翠墨绿
                {"num": "#92400E"},  # 暖色琥珀
                {"num": "#5B21B6"},  # 典雅高贵紫
                {"num": "#0E7490"},  # 商务青蓝
            ]
            for idx, card in enumerate(cards_found):
                theme = palette[idx % len(palette)]
                card_box = QFrame()
                card_box.setObjectName("kpiCard")
                card_box.setMinimumWidth(150)
                card_box.setMaximumWidth(280)
                card_box.setStyleSheet("""
                    QFrame#kpiCard {
                        background-color: #FFFFFF;
                        border: 1px solid #E2E8F0;
                        border-radius: 8px;
                    }
                    QFrame#kpiCard:hover {
                        border-color: #CBD5E1;
                        background-color: #FFFFFF;
                    }
                    QLabel {
                        border: none;
                        background: transparent;
                    }
                """)
                c_layout = QVBoxLayout(card_box)
                c_layout.setContentsMargins(16, 12, 16, 12)
                c_layout.setSpacing(6)

                t_lbl = QLabel(card['title'])
                t_lbl.setStyleSheet("color: #64748B; font-size: 13px; font-weight: 500; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'Microsoft YaHei', sans-serif;")

                v_lbl = QLabel(card['formatted'])
                v_lbl.setStyleSheet("color: " + theme['num'] + "; font-size: 22px; font-weight: bold; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Arial, 'Microsoft YaHei', sans-serif;")

                c_layout.addWidget(t_lbl)
                c_layout.addWidget(v_lbl)
                self.cards_layout.addWidget(card_box)
            self.cards_layout.addStretch()
            self.cards_frame.show()
        else:
            self.cards_frame.hide()

        # 处理多表格区块切换
        self._table_blocks = []
        for b_id, b_data in blocks_results.items():
            b = b_data.get('block')
            if b and b.btype == 'table' and b_data.get('columns'):
                self._table_blocks.append((b, b_data))

        self.block_tabs.blockSignals(True)
        # QTabBar 没有 clear() 方法，使用循环 removeTab 清理
        while self.block_tabs.count() > 0:
            self.block_tabs.removeTab(0)
        if len(self._table_blocks) > 1:
            for b, b_data in self._table_blocks:
                tab_title = u"📋 {} ({})".format(b.title or b.id, len(b_data.get('rows', [])))
                self.block_tabs.addTab(tab_title)
            self.block_tabs.setCurrentIndex(0)
            self.block_tabs.show()
        else:
            self.block_tabs.hide()
        self.block_tabs.blockSignals(False)

        # 检查首个表格是否有 summary_footer
        for b in getattr(self.form, 'blocks', []):
            if b.btype == 'table' and b.id in blocks_results:
                b_spec = b.summary_footer or getattr(self.form, 'summary_footer', '')
                if b_spec and hasattr(self, 'table_view') and self.table_view.model():
                    current_model = self.table_view.model()
                    if isinstance(current_model, ResultTableModel) and not current_model._summary_spec:
                        current_model._summary_spec = b_spec
                        current_model._recompute_summary()
                        current_model.layoutChanged.emit()
                break

    def _on_block_tab_changed(self, index):
        if not hasattr(self, '_table_blocks') or index < 0 or index >= len(self._table_blocks):
            return
        b, b_data = self._table_blocks[index]

        # 切换表格前，清空文本过滤输入框
        self.filter_edit.blockSignals(True)
        self.filter_edit.clear()
        self.filter_edit.blockSignals(False)

        b_spec = b.summary_footer or getattr(self.form, 'summary_footer', '')
        self._on_query_done(b_data['columns'], b_data['rows'], summary_spec=b_spec, current_block_title=b.title or b.id)

    def _on_query_done(self, columns, rows, summary_spec=None, current_block_title=None):
        logger.info("_on_query_done called, columns=%s, rows=%d", columns, len(rows))
        self._cancel_worker()

        try:
            self._elapsed = time.time() - self._query_start
            self._last_columns = columns
            self._last_rows    = rows

            self.query_btn.setEnabled(True)
            self.progress.hide()

            # 先清除旧模型，避免冲突
            logger.info("Clearing old model")
            old_model = self.table_view.model()
            self.table_view.setModel(None)
            if old_model:
                try:
                    old_model.deleteLater()
                except Exception as e:
                    logger.error("Error deleting old model: %s", str(e))

            if not columns:
                logger.info("No columns returned, skipping model creation")
                self.status_lbl.setText(u"查询完成，无数据返回 | 耗时 {:.2f}s".format(self._elapsed))
                self.export_btn.setEnabled(False)
                return

            logger.info("Creating ResultTableModel")
            spec = summary_spec if summary_spec is not None else getattr(self.form, 'summary_footer', '')
            model = ResultTableModel(columns, rows, summary_spec=spec)
            # 暂时不使用代理模型，直接使用源模型
            logger.info("Setting table model (direct)")
            self.table_view.setModel(model)

            # 快速自适应列宽：采样前 100 行，避免大数据集卡顿
            logger.info("Resizing columns, count=%d", len(columns))
            self._fast_resize_columns(columns, rows)

            # 更新过滤列下拉
            logger.info("Updating filter combo")
            self.col_combo.blockSignals(True)
            self.col_combo.clear()
            self.col_combo.addItem(u"全部列")
            self.col_combo.addItems(columns)
            self.col_combo.blockSignals(False)
            self.filter_edit.clear()

            block_info = u"  |  当前显示: {}".format(current_block_title) if current_block_title else ""
            self.status_lbl.setText(
                u"共 {} 行，{} 列{}  |  耗时 {:.2f}s".format(
                    len(rows), len(columns), block_info, self._elapsed
                )
            )
            logger.info("_on_query_done completed successfully")
        except Exception as e:
            logger.error("Error in _on_query_done: %s", str(e))
            logger.error(traceback.format_exc())
            self.query_btn.setEnabled(True)
            self.progress.hide()
            QMessageBox.critical(self, u"错误", u"显示查询结果失败：\n{}".format(str(e)))
        self.export_btn.setEnabled(bool(rows))

    def _on_query_error(self, msg):
        logger.info("_on_query_error called: %s", msg)
        self._cancel_worker()

        self.query_btn.setEnabled(True)
        self.progress.hide()
        self.status_lbl.setText(u"查询出错")
        QMessageBox.critical(self, u"查询错误",
                             u"查询执行失败：\n\n{}".format(msg))

    # ── 过滤 ──────────────────────────────────
    def _apply_filter(self):
        model = self.table_view.model()
        if model is None:
            return
        text    = self.filter_edit.text()
        col_idx = self.col_combo.currentIndex() - 1   # -1 = 全部列

        # 使用模型内置的过滤功能
        if hasattr(model, 'apply_filter'):
            model.apply_filter(text, col_idx)

            if text:
                visible = model.get_filtered_count()
                total   = model.get_total_count()
                self.filter_status.setText(
                    u"显示 {}/{} 行".format(visible, total)
                )
            else:
                self.filter_status.setText("")

    # ── 快速列宽（采样前 100 行，避免大数据集卡顿）────
    def _fast_resize_columns(self, columns, rows):
        fm = self.table_view.fontMetrics()
        sample = rows[:100]
        # horizontalAdvance() 是 Qt 5.11+ 推荐 API，旧版用 width() 兜底
        _text_width = getattr(fm, 'horizontalAdvance', None) or fm.width
        for i, col_name in enumerate(columns):
            # 表头宽度
            hdr_w = _text_width(col_name) + 24
            # 数据宽度（采样）
            data_w = 60
            for row in sample:
                if i < len(row):
                    cell_w = _text_width(str(row[i]) if row[i] is not None else 'NULL') + 16
                    if cell_w > data_w:
                        data_w = cell_w
            w = min(max(hdr_w, data_w, 60), 320)
            self.table_view.setColumnWidth(i, w)

    # ── 导出 Excel（后台线程）────────────────────
    def _export_excel(self):
        logger.info("_export_excel called")
        if not self._last_columns:
            return

        default_name = u"{}_{}.xlsx".format(
            self.form.title,
            datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
        )
        path, _ = QFileDialog.getSaveFileName(
            self, u"导出 Excel", default_name,
            u"Excel 文件 (*.xlsx)"
        )
        if not path:
            return

        # 收集导出数据（主线程取，避免跨线程访问 UI）
        model = self.table_view.model()
        summary_row = getattr(model, '_summary_row', None)
        if hasattr(model, 'get_filtered_count') and model.get_filtered_count() < len(self._last_rows):
            export_rows = model._rows[:]
        else:
            export_rows = self._last_rows

        blocks_for_export = []
        if getattr(self, '_last_blocks_results', None):
            for b_id, b_data in self._last_blocks_results.items():
                b = b_data.get('block')
                if not b:
                    continue
                if b.btype == 'table' and b_data.get('columns'):
                    b_summary_spec = b.summary_footer or getattr(self.form, 'summary_footer', '')
                    b_summary_row = None
                    if b_summary_spec:
                        try:
                            from core.summary_service import compute_summary
                            b_summary_row, _ = compute_summary(b_data.get('columns', []), b_data.get('rows', []), b_summary_spec)
                        except Exception:
                            pass
                    blocks_for_export.append({
                        'title': b.title or b.id,
                        'columns': b_data.get('columns', []),
                        'rows': b_data.get('rows', []),
                        'summary_row': b_summary_row,
                        'type': 'table'
                    })
                elif b.btype == 'cards' and b_data.get('columns'):
                    c_list = []
                    try:
                        from core.summary_service import compute_cards
                        c_list = compute_cards(b_data.get('columns', []), b_data.get('rows', []))
                    except Exception:
                        pass
                    blocks_for_export.append({
                        'title': b.title or b.id or u'关键指标',
                        'type': 'cards',
                        'cards': c_list,
                        'columns': b_data.get('columns', []),
                        'rows': b_data.get('rows', [])
                    })

        try:
            param_vals = self._normalized_param_values()
            final_sql = build_final_sql(self.form, param_vals, already_normalized=True)
        except ParameterError as exc:
            QMessageBox.warning(self, u"查询条件", str(exc))
            return
        params_info = [(p.label, param_vals.get(p.name, '')) for p in self.form.params]

        # 禁用按钮，显示进度
        self.export_btn.setEnabled(False)
        self.progress.show()
        self.status_lbl.setText(u"正在导出…")

        self._export_worker = ExportWorker(
            path, self._last_columns, export_rows,
            self.form.title, self.form.description,
            self._elapsed, params_info, final_sql,
            summary_row=summary_row, blocks=blocks_for_export
        )
        self._export_worker.export_done.connect(self._on_export_done)
        self._export_worker.export_error.connect(self._on_export_error)
        self._export_worker.start()

    def _on_export_done(self, path):
        if hasattr(self, '_export_worker'):
            self._export_worker.deleteLater()
            self._export_worker = None
        self.export_btn.setEnabled(True)
        self.progress.hide()
        self.status_lbl.setText(u"导出完成")
        QMessageBox.information(self, u"导出成功",
                                u"文件已保存到：\n{}".format(path))

    def _on_export_error(self, msg):
        if hasattr(self, '_export_worker'):
            self._export_worker.deleteLater()
            self._export_worker = None
        self.export_btn.setEnabled(True)
        self.progress.hide()
        self.status_lbl.setText(u"导出失败")
        QMessageBox.critical(self, u"导出失败",
                             u"导出 Excel 失败：\n\n{}".format(msg))

    # ── 右键菜单 ──────────────────────────────
    def _show_table_menu(self, pos):
        proxy = self.table_view.model()
        if proxy is None:
            return
        menu = QMenu(self)

        idx = self.table_view.indexAt(pos)
        a_copy_cell = None
        cell_data = None
        if idx.isValid():
            cell_data = proxy.data(idx)
            cell_str = '' if cell_data is None else str(cell_data)
            preview = (cell_str[:24] + '...') if len(cell_str) > 24 else cell_str
            a_copy_cell = menu.addAction(u"复制单元格内容 (「{}」)".format(preview))
            menu.addSeparator()

        a_copy     = menu.addAction(u"复制选中行")
        a_copy_hdr = menu.addAction(u"复制选中行（含表头）")
        menu.addSeparator()
        a_copy_all = menu.addAction(u"复制全部数据（含表头）")

        action = menu.exec_(self.table_view.viewport().mapToGlobal(pos))
        if action == a_copy_cell and idx.isValid():
            QApplication.clipboard().setText('' if cell_data is None else str(cell_data))
        elif action == a_copy:
            self._copy_selection(with_header=False)
        elif action == a_copy_hdr:
            self._copy_selection(with_header=True)
        elif action == a_copy_all:
            self._copy_all()

    def eventFilter(self, obj, event):
        if event.type() == QEvent.KeyPress:
            if event.key() in (Qt.Key_Return, Qt.Key_Enter):
                if event.modifiers() & Qt.ControlModifier:
                    self._execute_query()
                    return True
        return super(QueryTab, self).eventFilter(obj, event)

    def _copy_selection(self, with_header=False):
        proxy    = self.table_view.model()
        indices  = self.table_view.selectedIndexes()
        if not indices:
            return
        row_map  = {}
        for idx in indices:
            row_map.setdefault(idx.row(), {})[idx.column()] = proxy.data(idx)
        lines = []
        if with_header:
            # proxy 本身即 ResultTableModel，直接调用 headerData
            lines.append('\t'.join(
                str(proxy.headerData(c, Qt.Horizontal) or '')
                for c in sorted(next(iter(row_map.values())).keys())
            ))
        for r in sorted(row_map):
            lines.append('\t'.join(
                str(row_map[r].get(c, ''))
                for c in sorted(row_map[r])
            ))
        QApplication.clipboard().setText('\n'.join(lines))

    def _copy_all(self):
        if not self._last_columns:
            return
        lines = ['\t'.join(self._last_columns)]
        for row in self._last_rows:
            lines.append('\t'.join(
                '' if v is None else str(v)
                for v in row
            ))
        QApplication.clipboard().setText('\n'.join(lines))

    # ── 编辑表单 ──────────────────────────────
    def _edit_form(self):
        old_path = self.form.file_path
        from widgets.form_editor import FormEditorDialog
        dlg = FormEditorDialog(self.form, self.forms_dir, self)
        if dlg.exec_():
            # 通知主窗口重新加载该表单
            if old_path != self.form.file_path and hasattr(self, 'parent_window') and self.parent_window:
                for i in range(self.parent_window.tab_widget.count() - 1, -1, -1):
                    w = self.parent_window.tab_widget.widget(i)
                    if isinstance(w, QueryTab) and w.form.file_path == old_path:
                        self.parent_window.tab_widget.removeTab(i)
                        break
            self.form_modified.emit(self.form.file_path)

    # ── 窗口关闭事件（清理 worker）─────────────
    def closeEvent(self, event):
        self._cancel_worker()
        for worker in list(self._option_workers):
            if worker.isRunning():
                worker.terminate()
                worker.wait(1000)
            worker.deleteLater()
        self._option_workers = []
        if hasattr(self, '_export_worker') and self._export_worker:
            if self._export_worker.isRunning():
                self._export_worker.terminate()
                self._export_worker.wait(2000)
            self._export_worker.deleteLater()
            self._export_worker = None
        event.accept()
