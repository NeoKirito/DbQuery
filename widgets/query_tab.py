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
    QApplication, QMenu, QFrame
)
from PyQt5.QtCore import (
    Qt, QThread, pyqtSignal,
    QAbstractTableModel, QModelIndex, QDate, QDateTime
)
from PyQt5.QtGui import QColor, QBrush

from form_parser import FormParser
from core.query_service import escape_sql_param, build_final_sql, export_to_excel


# ──────────────────────────────────────────────
#  自定义 TableModel（内置过滤支持）
# ──────────────────────────────────────────────
class ResultTableModel(QAbstractTableModel):
    def __init__(self, columns, rows, parent=None):
        super(ResultTableModel, self).__init__(parent)
        self._columns = columns
        self._all_rows = rows  # 保存所有原始数据
        self._rows = rows      # 当前显示的数据（过滤后）
        self._filter_text = ''
        self._filter_col = -1  # -1 表示全部列

    def rowCount(self, parent=QModelIndex()):
        return len(self._rows)

    def columnCount(self, parent=QModelIndex()):
        return len(self._columns)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None

        row = index.row()
        col = index.column()

        # 边界检查
        if row < 0 or row >= len(self._rows):
            return None
        if col < 0 or col >= len(self._columns):
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
    result_ready    = pyqtSignal(list, list)
    query_error     = pyqtSignal(str)
    query_cancelled = pyqtSignal()

    def __init__(self, db_manager, sql):
        super(QueryWorker, self).__init__()
        self.db_manager = db_manager
        self.sql        = sql
        self._cancelled = False

    def cancel(self):
        """请求取消查询（协作式，等待当前 SQL 执行完毕后退出）"""
        self._cancelled = True

    def run(self):
        logger.info("QueryWorker started, sql: %s", self.sql[:100] if self.sql else "EMPTY")
        try:
            columns, rows = self.db_manager.execute_query(self.sql)
            if self._cancelled:
                logger.info("QueryWorker cancelled after query, discarding results")
                self.query_cancelled.emit()
                return
            logger.info("QueryWorker success, columns: %s, rows: %d", columns, len(rows))
            self.result_ready.emit(columns, rows)
        except Exception as e:
            if self._cancelled:
                self.query_cancelled.emit()
                return
            logger.error("QueryWorker error: %s", str(e))
            logger.error(traceback.format_exc())
            self.query_error.emit(str(e))


# ──────────────────────────────────────────────
#  后台 Excel 导出线程
# ──────────────────────────────────────────────
class ExportWorker(QThread):
    export_done  = pyqtSignal(str)   # 成功：文件路径
    export_error = pyqtSignal(str)   # 失败：错误信息

    def __init__(self, path, columns, rows, form_title, form_desc,
                 elapsed, params_info, final_sql):
        super(ExportWorker, self).__init__()
        self.path         = path
        self.columns      = columns
        self.rows         = rows
        self.form_title   = form_title
        self.form_desc    = form_desc
        self.elapsed      = elapsed
        self.params_info  = params_info
        self.final_sql    = final_sql

    def run(self):
        try:
            export_to_excel(
                self.path, self.columns, self.rows,
                self.form_title, self.form_desc,
                self.elapsed, self.params_info, self.final_sql
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
        self._param_widgets  = {}   # {param_name: QWidget}
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
        title_lbl.setStyleSheet("font-size: 14px;")

        desc_lbl = QLabel(self.form.description or '')
        desc_lbl.setStyleSheet("color: #666; font-size: 11px; margin-left: 8px;")

        edit_btn = QPushButton(u"编辑表单")
        edit_btn.setFixedWidth(80)
        edit_btn.clicked.connect(self._edit_form)

        title_row.addWidget(title_lbl)
        title_row.addWidget(desc_lbl)
        title_row.addStretch()
        title_row.addWidget(edit_btn)
        root.addLayout(title_row)

        # 分隔线
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setStyleSheet("color: #DDDDDD;")
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

        self.query_btn = QPushButton(u"  执行查询  ")
        self.query_btn.setStyleSheet(
            "QPushButton {"
            "  background-color: #1a6eb5; color: white;"
            "  padding: 5px 18px; border-radius: 4px;"
            "  font-weight: bold; font-size: 13px;"
            "}"
            "QPushButton:hover  { background-color: #155ea0; }"
            "QPushButton:pressed{ background-color: #0f4a80; }"
            "QPushButton:disabled{ background-color: #9ab3ce; }"
        )
        self.query_btn.clicked.connect(self._execute_query)

        self.export_btn = QPushButton(u"导出 Excel")
        self.export_btn.setEnabled(False)
        self.export_btn.clicked.connect(self._export_excel)

        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setFixedWidth(100)
        self.progress.setFixedHeight(20)
        self.progress.hide()

        self.status_lbl = QLabel("")
        self.status_lbl.setStyleSheet("color: #555; font-size: 11px;")

        action_row.addWidget(self.query_btn)
        action_row.addWidget(self.export_btn)
        action_row.addWidget(self.progress)
        action_row.addStretch()
        action_row.addWidget(self.status_lbl)
        root.addLayout(action_row)

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
        today = QDate.currentDate()

        for param in self.form.params:
            lbl = QLabel(param.label + u":")
            lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

            if param.ptype == 'date':
                w = QDateEdit()
                w.setCalendarPopup(True)
                w.setDisplayFormat("yyyy-MM-dd")
                if param.default == '{today}':
                    w.setDate(today)
                elif param.default:
                    d = QDate.fromString(param.default, "yyyy-MM-dd")
                    w.setDate(d if d.isValid() else today)
                else:
                    w.setDate(today)
                w.setMinimumWidth(110)

            elif param.ptype == 'datetime':
                w = QDateTimeEdit()
                w.setCalendarPopup(True)
                w.setDisplayFormat("yyyy-MM-dd HH:mm:ss")
                w.setDateTime(QDateTime.currentDateTime())
                w.setMinimumWidth(160)

            elif param.ptype == 'number':
                w = QLineEdit()
                w.setPlaceholderText(u"数字")
                w.setText(param.default)
                w.setMaximumWidth(100)

            elif param.ptype == 'select':
                w = QComboBox()
                w.addItems(param.options)
                if param.default in param.options:
                    w.setCurrentText(param.default)
                w.setMinimumWidth(100)

            else:  # text
                w = QLineEdit()
                w.setPlaceholderText(param.label)
                w.setText(param.default if param.default != '{today}' else '')
                w.setMinimumWidth(120)
                w.returnPressed.connect(self._execute_query)

            self._param_widgets[param.name] = w

            pair = QHBoxLayout()
            pair.setSpacing(4)
            pair.addWidget(lbl)
            pair.addWidget(w)
            container = QWidget()
            container.setLayout(pair)
            layout.addWidget(container)

        layout.addStretch()

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
        vals = {}
        for name, w in self._param_widgets.items():
            if isinstance(w, QDateTimeEdit) and not isinstance(w, QDateEdit):
                vals[name] = w.dateTime().toString("yyyy-MM-dd HH:mm:ss")
            elif isinstance(w, QDateEdit):
                vals[name] = w.date().toString("yyyy-MM-dd")
            elif isinstance(w, QComboBox):
                vals[name] = w.currentText()
            elif isinstance(w, QLineEdit):
                vals[name] = w.text()
            else:
                vals[name] = ''
        return vals

    def _build_final_sql(self):
        return build_final_sql(self.form, self._get_param_values())

    # ── 执行查询 ──────────────────────────────
    def _execute_query(self):
        logger.info("_execute_query called")
        if self._worker and self._worker.isRunning():
            logger.info("Worker already running, returning")
            return

        try:
            sql = self._build_final_sql()
            logger.info("Built SQL: %s", sql[:200] if sql else "EMPTY")
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
            self._worker = QueryWorker(self.db_manager, sql)
            self._worker.result_ready.connect(self._on_query_done)
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

    def _on_query_done(self, columns, rows):
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
            model = ResultTableModel(columns, rows)
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

            self.status_lbl.setText(
                u"共 {} 行，{} 列  |  耗时 {:.2f}s".format(
                    len(rows), len(columns), self._elapsed
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
        if hasattr(model, 'get_filtered_count') and model.get_filtered_count() < len(self._last_rows):
            export_rows = model._rows[:]
        else:
            export_rows = self._last_rows

        params_info = []
        param_vals = self._get_param_values()
        for p in self.form.params:
            params_info.append((p.label, param_vals.get(p.name, '')))

        # 禁用按钮，显示进度
        self.export_btn.setEnabled(False)
        self.progress.show()
        self.status_lbl.setText(u"正在导出…")

        self._export_worker = ExportWorker(
            path, self._last_columns, export_rows,
            self.form.title, self.form.description,
            self._elapsed, params_info, self._build_final_sql()
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
        a_copy     = menu.addAction(u"复制选中行")
        a_copy_hdr = menu.addAction(u"复制选中行（含表头）")
        menu.addSeparator()
        a_copy_all = menu.addAction(u"复制全部数据（含表头）")

        action = menu.exec_(self.table_view.viewport().mapToGlobal(pos))
        if action == a_copy:
            self._copy_selection(with_header=False)
        elif action == a_copy_hdr:
            self._copy_selection(with_header=True)
        elif action == a_copy_all:
            self._copy_all()

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
        from widgets.form_editor import FormEditorDialog
        dlg = FormEditorDialog(self.form, self.forms_dir, self)
        if dlg.exec_():
            # 通知主窗口重新加载该表单
            self.form_modified.emit(self.form.file_path)

    # ── 窗口关闭事件（清理 worker）─────────────
    def closeEvent(self, event):
        self._cancel_worker()
        if hasattr(self, '_export_worker') and self._export_worker:
            if self._export_worker.isRunning():
                self._export_worker.terminate()
                self._export_worker.wait(2000)
            self._export_worker.deleteLater()
            self._export_worker = None
        event.accept()
