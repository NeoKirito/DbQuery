# -*- coding: utf-8 -*-
"""
数据库查询工具 — 主窗口
"""
import sys
import os
import logging
import traceback
import ctypes
from ctypes import wintypes

from core.paths import get_app_dir, get_exe_dir, get_forms_dir, get_logs_dir
from core.logger import setup_logging

BASE_DIR = get_app_dir()
EXE_DIR = get_exe_dir()
FORMS_DIR = get_forms_dir()

# 配置独立按天轮转日志（写入 logs/desktop_YYYY-MM-DD.log）
logger = setup_logging('desktop')


def _global_exception_hook(exctype, value, tb):
    logger.critical("Unhandled desktop exception: %s", value, exc_info=(exctype, value, tb))
    sys.__excepthook__(exctype, value, tb)


sys.excepthook = _global_exception_hook

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QSplitter, QTabWidget, QLabel, QPushButton, QToolBar,
    QTreeWidget, QTreeWidgetItem, QMessageBox, QLineEdit,
    QFrame, QSizePolicy, QAction, QTabBar, QInputDialog, QComboBox
)
from PyQt5.QtCore import Qt, QSize, QTimer, QThread, pyqtSignal, QFileSystemWatcher, QEvent, QPoint, QRectF
from PyQt5.QtGui import QFont, QIcon, QColor, QPixmap, QPainterPath, QRegion

from db_manager import DBManager
from form_parser import FormParser, QueryForm
from widgets.query_tab import QueryTab
from widgets.config_dialog import ConfigDialog
from widgets.form_editor import FormEditorDialog
from widgets.login_dialog import require_desktop_login

# 连接状态常量
STATUS_UNKNOWN  = 0
STATUS_OK       = 1
STATUS_FAIL     = 2
STATUS_TESTING  = 3


# ── 后台连接测试线程 ──
class ConnTestWorker(QThread):
    finished = pyqtSignal(bool, str)

    def __init__(self, db_manager):
        super(ConnTestWorker, self).__init__()
        self.db_manager = db_manager

    def run(self):
        try:
            self.db_manager.load_config()
            ok, msg = self.db_manager.test_connection()
            self.finished.emit(ok, msg)
        except Exception as e:
            self.finished.emit(False, str(e))


class MainWindow(QMainWindow):

    def __init__(self):
        super(MainWindow, self).__init__()
        self.db_manager  = DBManager()
        self.forms_data  = {}   # {group: [QueryForm]}
        self._conn_status = STATUS_UNKNOWN
        self._conn_worker = None
        self._drag_pos = None

        # ── 无边框一体化窗口设置（去除原生白色标题栏）──
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Window)

        self.setWindowTitle(u"数据库查询工具")
        self.setMinimumSize(1000, 680)
        self.resize(1300, 820)

        app_icon_path = os.path.join(BASE_DIR, 'app.png')
        if not os.path.exists(app_icon_path):
            app_icon_path = os.path.join(EXE_DIR, 'app.png')
        if not os.path.exists(app_icon_path):
            app_icon_path = os.path.join(BASE_DIR, 'app.ico')
        if not os.path.exists(app_icon_path):
            app_icon_path = os.path.join(EXE_DIR, 'app.ico')
        self._app_icon_path = app_icon_path
        if os.path.exists(app_icon_path):
            self.setWindowIcon(QIcon(app_icon_path))

        # Windows DWM 阴影扩展
        try:
            hwnd = int(self.winId())
            class MARGINS(ctypes.Structure):
                _fields_ = [
                    ("cxLeftWidth", ctypes.c_int),
                    ("cxRightWidth", ctypes.c_int),
                    ("cyTopHeight", ctypes.c_int),
                    ("cyBottomHeight", ctypes.c_int),
                ]
            margins = MARGINS(1, 1, 1, 1)
            ctypes.windll.dwmapi.DwmExtendFrameIntoClientArea(wintypes.HWND(hwnd), ctypes.byref(margins))
        except Exception:
            pass

        # ── 目录变更实时感知与文件监听器 ──
        self._fs_watcher = QFileSystemWatcher(self)
        self._fs_debounce_timer = QTimer(self)
        self._fs_debounce_timer.setSingleShot(True)
        self._fs_debounce_timer.setInterval(300)
        self._fs_debounce_timer.timeout.connect(self._on_fs_changed_timeout)
        self._fs_watcher.directoryChanged.connect(self._schedule_fs_reload)
        self._fs_watcher.fileChanged.connect(self._schedule_fs_reload)

        self._setup_ui()
        self._load_forms()
        self._apply_window_corners()

        # 启动后自动测试连接（静默）
        QTimer.singleShot(400, lambda: self._test_connection(silent=True))

    # ════════════════════════════════════════
    #  界面构建
    # ════════════════════════════════════════
    def _setup_ui(self):
        # ── 工具栏 ──────────────────────────
        tb = QToolBar(u"主工具栏")
        self.toolbar = tb
        tb.setMovable(False)
        tb.setIconSize(QSize(16, 16))
        tb.installEventFilter(self)
        self.addToolBar(tb)

        # ── 应用 Logo 与标题（替代原绿色 emoji）──
        self.brand_widget = QWidget()
        self.brand_widget.installEventFilter(self)
        brand_layout = QHBoxLayout(self.brand_widget)
        brand_layout.setContentsMargins(2, 0, 8, 0)
        brand_layout.setSpacing(8)

        self.logo_lbl = QLabel()
        self.logo_lbl.installEventFilter(self)
        if getattr(self, '_app_icon_path', None) and os.path.exists(self._app_icon_path):
            pix = QPixmap(self._app_icon_path)
            if not pix.isNull():
                scaled_pix = pix.scaled(20, 20, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                self.logo_lbl.setPixmap(scaled_pix)
                self.logo_lbl.setFixedSize(20, 20)
                brand_layout.addWidget(self.logo_lbl)

        self.app_title_lbl = QLabel(self.windowTitle())
        self.app_title_lbl.setStyleSheet(
            "color: #90BAEE; font-size: 13px; font-weight: bold; letter-spacing: 0.5px;"
        )
        self.app_title_lbl.installEventFilter(self)
        brand_layout.addWidget(self.app_title_lbl)

        tb.addWidget(self.brand_widget)
        tb.addSeparator()

        # 连接状态指示灯
        self.dot_lbl = QLabel(u"●")
        self.dot_lbl.setStyleSheet("font-size: 16px; color: #666688; margin-right: 2px;")
        self.conn_lbl = QLabel(u"未测试")
        self.conn_lbl.setStyleSheet("color: #90AACE; font-size: 12px;")
        self.conn_lbl.setMinimumWidth(55)

        tb.addWidget(self.dot_lbl)
        tb.addWidget(self.conn_lbl)
        tb.addSeparator()

        btn_test = QPushButton(u"测试连接")
        btn_cfg  = QPushButton(u"数据库配置")
        btn_test.clicked.connect(lambda: self._test_connection(silent=False))
        btn_cfg.clicked.connect(self._open_db_config)
        tb.addWidget(btn_test)
        tb.addWidget(btn_cfg)

        tb.addSeparator()

        btn_new     = QPushButton(u"新建表单")
        btn_refresh = QPushButton(u"刷新表单")
        btn_new.clicked.connect(lambda: self._new_form())
        btn_refresh.clicked.connect(self._load_forms)
        tb.addWidget(btn_new)
        tb.addWidget(btn_refresh)

        # 右侧弹簧（用于拖拽窗口）
        self.spacer = QWidget()
        self.spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.spacer.installEventFilter(self)
        tb.addWidget(self.spacer)

        # ── 窗口控制按钮（最小化、最大化/还原、关闭）──
        win_ctrls = QWidget()
        ctrl_layout = QHBoxLayout(win_ctrls)
        ctrl_layout.setContentsMargins(0, 0, 6, 0)
        ctrl_layout.setSpacing(2)

        self.btn_min = QPushButton(u"—")
        self.btn_min.setToolTip(u"最小化")
        self.btn_min.setObjectName("btn_win_min")
        self.btn_min.clicked.connect(self.showMinimized)

        self.btn_max = QPushButton(u"⬜")
        self.btn_max.setToolTip(u"最大化")
        self.btn_max.setObjectName("btn_win_max")
        self.btn_max.clicked.connect(self._toggle_maximize)

        self.btn_close = QPushButton(u"✕")
        self.btn_close.setToolTip(u"关闭")
        self.btn_close.setObjectName("btn_win_close")
        self.btn_close.clicked.connect(self.close)

        for btn in (self.btn_min, self.btn_max, self.btn_close):
            btn.setFixedSize(34, 26)
            btn.setFocusPolicy(Qt.NoFocus)
            ctrl_layout.addWidget(btn)

        tb.addWidget(win_ctrls)

        # ── 主分割布局 ──────────────────────
        splitter = QSplitter(Qt.Horizontal)

        # ---- 左侧：表单树 ----
        left = QWidget()
        left.setMinimumWidth(185)
        left.setMaximumWidth(300)
        left.setStyleSheet("background: #F0F2F6;")
        lv = QVBoxLayout(left)
        lv.setContentsMargins(6, 8, 6, 6)
        lv.setSpacing(6)

        tree_title = QLabel(u"表单列表")
        tree_title.setStyleSheet(
            "color: #1A6EB5; font-weight: bold; font-size: 12px;"
            "padding: 4px 6px; background: #E4EAF2;"
            "border-radius: 4px; border-left: 3px solid #1A6EB5;"
        )

        # 分组筛选下拉框
        group_filter_layout = QHBoxLayout()
        group_filter_lbl = QLabel(u"分组:")
        group_filter_lbl.setStyleSheet("color: #4A5568; font-size: 12px; font-weight: bold;")
        self.group_combo = QComboBox()
        self.group_combo.setToolTip(u"选择分组以快速筛选，或切换查看全部分组")
        self.group_combo.currentIndexChanged.connect(self._on_group_filter_changed)
        group_filter_layout.addWidget(group_filter_lbl)
        group_filter_layout.addWidget(self.group_combo, stretch=1)

        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText(u"搜索表单…")
        self.search_edit.setClearButtonEnabled(True)

        # 搜索防抖：300ms 内停止输入才触发过滤，避免每次按键全量重建树
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(300)
        self._search_timer.timeout.connect(self._do_filter_tree)
        self.search_edit.textChanged.connect(lambda: self._search_timer.start())

        self.form_tree = QTreeWidget()
        self.form_tree.setHeaderHidden(True)
        self.form_tree.setAnimated(True)
        self.form_tree.setIndentation(14)
        self.form_tree.itemDoubleClicked.connect(self._on_tree_double_click)
        self.form_tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.form_tree.customContextMenuRequested.connect(self._tree_context_menu)

        lv.addWidget(tree_title)
        lv.addLayout(group_filter_layout)
        lv.addWidget(self.search_edit)
        lv.addWidget(self.form_tree)

        # ---- 右侧：标签页 ----
        self.tab_widget = QTabWidget()
        self.tab_widget.setTabsClosable(True)
        self.tab_widget.setDocumentMode(False)
        self.tab_widget.setMovable(True)
        self.tab_widget.tabCloseRequested.connect(self._close_tab)

        # 占位页（卡片式指引页，无 close 按钮）
        self._welcome = QWidget()
        self._welcome.setStyleSheet("background: #F8FAFC;")
        w_layout = QVBoxLayout(self._welcome)
        w_layout.setAlignment(Qt.AlignCenter)

        card = QFrame()
        card.setObjectName("welcomeCard")
        card.setFixedWidth(540)
        card.setStyleSheet(
            "QFrame#welcomeCard {"
            "  background: #FFFFFF;"
            "  border: 1px solid #E2E8F0;"
            "  border-radius: 12px;"
            "}"
        )
        card_v = QVBoxLayout(card)
        card_v.setContentsMargins(32, 28, 32, 28)
        card_v.setSpacing(12)

        w_title = QLabel(u"欢迎使用 DBQuery 综合查询系统")
        w_title.setStyleSheet("font-size: 18px; font-weight: bold; color: #1E293B;")
        w_title.setAlignment(Qt.AlignCenter)

        w_sub = QLabel(u"高性能 SQL Server 报表与数据查询桌面客户端")
        w_sub.setStyleSheet("font-size: 12px; color: #64748B; margin-bottom: 4px;")
        w_sub.setAlignment(Qt.AlignCenter)

        card_v.addWidget(w_title)
        card_v.addWidget(w_sub)

        w_sep = QFrame()
        w_sep.setFrameShape(QFrame.HLine)
        w_sep.setStyleSheet("color: #F1F5F9; margin: 4px 0;")
        card_v.addWidget(w_sep)

        tips = [
            (u"📋", u"双击左侧列表中的表单名称，即可快速打开查询标签页"),
            (u"⌨️", u"查询条件输入框支持直接按【回车键】立即执行查询"),
            (u"📊", u"查询结果支持多列即时过滤、点击表头快速升降序排序"),
            (u"📥", u"支持一键无损导出 Excel 表格，后台异步处理不卡顿"),
            (u"🖱️", u"右键表格数据行可快捷复制单元格或整行数据"),
        ]
        for icon, tip_text in tips:
            row = QHBoxLayout()
            row.setSpacing(10)
            ic_lbl = QLabel(icon)
            ic_lbl.setStyleSheet("font-size: 15px;")
            ic_lbl.setFixedWidth(24)
            ic_lbl.setAlignment(Qt.AlignCenter)
            tx_lbl = QLabel(tip_text)
            tx_lbl.setStyleSheet("font-size: 13px; color: #334155; line-height: 1.4;")
            row.addWidget(ic_lbl)
            row.addWidget(tx_lbl, stretch=1)
            card_v.addLayout(row)

        w_layout.addWidget(card)

        self.tab_widget.addTab(self._welcome, u"🏠 首页")
        self.tab_widget.tabBar().setTabButton(0, QTabBar.RightSide, None)

        splitter.addWidget(left)
        splitter.addWidget(self.tab_widget)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([210, 1090])

        self.setCentralWidget(splitter)

        # ── 状态栏 ──────────────────────────
        self.statusBar().showMessage(u"就绪")
        self.status_db_lbl = QLabel(u"🗄️ 数据库: 未测试")
        self.status_db_lbl.setStyleSheet("color: #94A3B8; font-size: 11px; margin-right: 14px;")
        self.status_ver_lbl = QLabel(u"DBQuery 桌面端")
        self.status_ver_lbl.setStyleSheet("color: #64748B; font-size: 11px; margin-right: 8px;")
        self.statusBar().addPermanentWidget(self.status_db_lbl)
        self.statusBar().addPermanentWidget(self.status_ver_lbl)

    def setWindowTitle(self, title):
        super(MainWindow, self).setWindowTitle(title)
        if hasattr(self, 'app_title_lbl'):
            self.app_title_lbl.setText(title)

    def _toggle_maximize(self):
        if self.isMaximized():
            self.showNormal()
            if hasattr(self, 'btn_max'):
                self.btn_max.setText(u"⬜")
                self.btn_max.setToolTip(u"最大化")
        else:
            self.showMaximized()
            if hasattr(self, 'btn_max'):
                self.btn_max.setText(u"🗗")
                self.btn_max.setToolTip(u"向下还原")
        self._apply_window_corners()

    def _apply_window_corners(self):
        """为桌面程序窗口边缘设置圆角（Win11 DWM 系统圆角优先，Win10/Win7 采用窗口区域蒙版剪裁）"""
        if self.isMaximized():
            self.clearMask()
            return

        dwm_rounded = False
        try:
            hwnd = int(self.winId())
            DWMWA_WINDOW_CORNER_PREFERENCE = 33
            DWMWCP_ROUND = 2
            val = ctypes.c_int(DWMWCP_ROUND)
            hr = ctypes.windll.dwmapi.DwmSetWindowAttribute(
                wintypes.HWND(hwnd),
                ctypes.c_uint(DWMWA_WINDOW_CORNER_PREFERENCE),
                ctypes.byref(val),
                ctypes.sizeof(val)
            )
            if hr == 0:
                dwm_rounded = True
        except Exception:
            pass

        if not dwm_rounded:
            path = QPainterPath()
            path.addRoundedRect(QRectF(0, 0, self.width(), self.height()), 8, 8)
            region = QRegion(path.toFillPolygon().toPolygon())
            self.setMask(region)

    def resizeEvent(self, event):
        super(MainWindow, self).resizeEvent(event)
        self._apply_window_corners()

    def showEvent(self, event):
        super(MainWindow, self).showEvent(event)
        self._apply_window_corners()

    def changeEvent(self, event):
        if event.type() == QEvent.WindowStateChange:
            self._apply_window_corners()
            if hasattr(self, 'btn_max'):
                if self.isMaximized():
                    self.btn_max.setText(u"🗗")
                    self.btn_max.setToolTip(u"向下还原")
                else:
                    self.btn_max.setText(u"⬜")
                    self.btn_max.setToolTip(u"最大化")
        super(MainWindow, self).changeEvent(event)

    def eventFilter(self, obj, event):
        # 允许在工具栏空白区、品牌区和占位区拖拽窗口以及双击最大化/还原
        drag_targets = (
            getattr(self, 'toolbar', None),
            getattr(self, 'spacer', None),
            getattr(self, 'brand_widget', None),
            getattr(self, 'app_title_lbl', None),
            getattr(self, 'logo_lbl', None),
        )
        if obj in drag_targets and obj is not None:
            if event.type() == QEvent.MouseButtonPress and event.button() == Qt.LeftButton:
                if not self.isMaximized():
                    self._drag_pos = event.globalPos() - self.frameGeometry().topLeft()
                return True
            elif event.type() == QEvent.MouseMove and event.buttons() == Qt.LeftButton:
                if getattr(self, '_drag_pos', None) is not None and not self.isMaximized():
                    self.move(event.globalPos() - self._drag_pos)
                return True
            elif event.type() == QEvent.MouseButtonRelease:
                self._drag_pos = None
                return True
            elif event.type() == QEvent.MouseButtonDblClick and event.button() == Qt.LeftButton:
                self._toggle_maximize()
                return True
        return super(MainWindow, self).eventFilter(obj, event)

    def nativeEvent(self, eventType, message):
        retval, result = super(MainWindow, self).nativeEvent(eventType, message)
        if eventType == b"windows_generic_MSG" and not self.isMaximized():
            try:
                msg = wintypes.MSG.from_address(int(message))
                if msg.message == 0x0084:  # WM_NCHITTEST
                    x = ctypes.c_short(msg.lParam & 0xFFFF).value
                    y = ctypes.c_short((msg.lParam >> 16) & 0xFFFF).value
                    pt = self.mapFromGlobal(QPoint(x, y))
                    w = 6
                    rect = self.rect()
                    on_left = pt.x() < w
                    on_right = pt.x() > rect.width() - w
                    on_top = pt.y() < w
                    on_bottom = pt.y() > rect.height() - w
                    if on_top and on_left: return True, 13     # HTTOPLEFT
                    if on_top and on_right: return True, 14    # HTTOPRIGHT
                    if on_bottom and on_left: return True, 16  # HTBOTTOMLEFT
                    if on_bottom and on_right: return True, 17 # HTBOTTOMRIGHT
                    if on_left: return True, 10                # HTLEFT
                    if on_right: return True, 11               # HTRIGHT
                    if on_top: return True, 12                 # HTTOP
                    if on_bottom: return True, 15              # HTBOTTOM
            except Exception:
                pass
        return retval, result

    # ════════════════════════════════════════
    #  数据库连接相关
    # ════════════════════════════════════════
    def _update_conn_ui(self, status, msg=''):
        color_map = {
            STATUS_UNKNOWN: '#668899',
            STATUS_OK:      '#2ECC71',
            STATUS_FAIL:    '#E74C3C',
            STATUS_TESTING: '#F5A623',
        }
        text_map = {
            STATUS_UNKNOWN: u'未测试',
            STATUS_OK:      u'已连接',
            STATUS_FAIL:    u'未连接',
            STATUS_TESTING: u'连接中…',
        }
        color = color_map.get(status, '#668899')
        text  = text_map.get(status, '')
        self.dot_lbl.setStyleSheet(
            "font-size: 16px; color: {}; margin-right: 2px;".format(color)
        )
        self.conn_lbl.setStyleSheet(
            "color: {}; font-size: 12px;".format(color)
        )
        self.conn_lbl.setText(text)
        if hasattr(self, 'status_db_lbl'):
            cfg = self.db_manager.get_db_config() if hasattr(self, 'db_manager') else {}
            srv = cfg.get('server', 'localhost')
            db = cfg.get('database', 'master')
            self.status_db_lbl.setText(u"🗄️ 数据库: {}/{} ({})".format(srv, db, text))
            if status == STATUS_OK:
                self.status_db_lbl.setStyleSheet("color: #4ADE80; font-size: 11px; margin-right: 14px;")
            elif status == STATUS_FAIL:
                self.status_db_lbl.setStyleSheet("color: #F87171; font-size: 11px; margin-right: 14px;")
            elif status == STATUS_TESTING:
                self.status_db_lbl.setStyleSheet("color: #FBBF24; font-size: 11px; margin-right: 14px;")
            else:
                self.status_db_lbl.setStyleSheet("color: #94A3B8; font-size: 11px; margin-right: 14px;")
        if msg:
            self.statusBar().showMessage(msg[:120])

    def _test_connection(self, silent=False):
        self._update_conn_ui(STATUS_TESTING)
        self._silent_conn_test = silent

        # 后台线程执行连接测试，避免阻塞 UI 最多 10 秒
        if self._conn_worker and self._conn_worker.isRunning():
            return
        self._conn_worker = ConnTestWorker(self.db_manager)
        self._conn_worker.finished.connect(self._on_conn_test_done)
        self._conn_worker.start()

    def _on_conn_test_done(self, success, msg):
        silent = getattr(self, '_silent_conn_test', True)
        if success:
            self._update_conn_ui(STATUS_OK, u"数据库连接成功")
            if not silent:
                QMessageBox.information(self, u"连接测试", u"数据库连接成功！")
        else:
            self._update_conn_ui(STATUS_FAIL, u"连接失败：" + msg[:80])
            if not silent:
                QMessageBox.warning(self, u"连接测试",
                                    u"连接失败：\n\n{}".format(msg))

    def _open_db_config(self):
        dlg = ConfigDialog(self.db_manager, self)
        if dlg.exec_():
            self._test_connection(silent=False)

    # ════════════════════════════════════════
    #  表单树与分组管理
    # ════════════════════════════════════════
    def _load_forms(self):
        self.forms_data = FormParser.load_forms_from_dir(FORMS_DIR)
        self._update_group_combo()
        self._do_filter_tree()
        self._update_watched_paths()
        total_forms = sum(len(v) for v in self.forms_data.values())
        total_groups = len(self.forms_data)
        self.statusBar().showMessage(u"已加载 {} 个分组，共 {} 个表单".format(total_groups, total_forms))

    def _update_group_combo(self):
        if not hasattr(self, 'group_combo'):
            return
        prev_group = self.group_combo.currentData()
        self.group_combo.blockSignals(True)
        self.group_combo.clear()

        all_count = sum(len(v) for v in self.forms_data.values())
        self.group_combo.addItem(u"📁 全部分组 ({})".format(all_count), userData=None)

        target_idx = 0
        idx = 1
        for grp in self.forms_data.keys():
            count = len(self.forms_data[grp])
            self.group_combo.addItem(u"📁 {} ({})".format(grp, count), userData=grp)
            if prev_group and grp == prev_group:
                target_idx = idx
            idx += 1

        self.group_combo.setCurrentIndex(target_idx)
        self.group_combo.blockSignals(False)

    def _on_group_filter_changed(self, index):
        self._do_filter_tree()

    def _update_watched_paths(self):
        """确保 forms 根目录及其直接子目录都在监听列表中"""
        if not hasattr(self, '_fs_watcher'):
            return
        if not os.path.isdir(FORMS_DIR):
            return
        needed = [os.path.abspath(FORMS_DIR)]
        try:
            for name in os.listdir(FORMS_DIR):
                p = os.path.join(FORMS_DIR, name)
                if os.path.isdir(p) and not name.startswith(('.', '_')):
                    needed.append(os.path.abspath(p))
        except Exception:
            pass

        current = set(os.path.abspath(p) for p in self._fs_watcher.directories())
        for p in needed:
            if p not in current and os.path.exists(p):
                self._fs_watcher.addPath(p)

    def _schedule_fs_reload(self, path=None):
        """文件系统发生变更时防抖触发重新加载"""
        if hasattr(self, '_fs_debounce_timer'):
            self._fs_debounce_timer.start()

    def _on_fs_changed_timeout(self):
        self._load_forms()

    def changeEvent(self, event):
        """当主窗口重新获取焦点时（如从资源管理器粘贴文件夹后切回），自动轻量同步"""
        if event.type() == QEvent.ActivationChange and self.isActiveWindow():
            self._schedule_fs_reload()
        super(MainWindow, self).changeEvent(event)

    def _rebuild_tree(self, data, filter_text='', selected_group=None):
        self.form_tree.clear()
        ft = filter_text.strip().lower()

        for group in data.keys():
            if selected_group is not None and group != selected_group:
                continue

            forms = data[group]
            matching_forms = [f for f in forms if not ft or ft in f.title.lower()]

            # 搜索过滤：当有搜索词且既无匹配表单、分组名也不匹配搜索词时隐藏
            if ft and not matching_forms and ft not in group.lower():
                continue

            grp_item = QTreeWidgetItem([u"📁 " + group])
            grp_item.setData(0, Qt.UserRole, None)  # None 表示分组项
            grp_item.setData(0, Qt.UserRole + 1, group)
            grp_item.setForeground(0, QColor('#1D4ED8'))
            grp_item.setFont(0, QFont('', -1, QFont.Bold))

            if matching_forms:
                for form in matching_forms:
                    icon_prefix = u"⚡ " if form.query_type == 'exec' else u"📄 "
                    child = QTreeWidgetItem([u"  " + icon_prefix + form.title])
                    child.setData(0, Qt.UserRole, form)
                    child.setData(0, Qt.UserRole + 1, group)
                    child.setToolTip(0, form.description or form.file_path)
                    grp_item.addChild(child)
            elif not ft:
                # 空分组友好占位提示
                placeholder = QTreeWidgetItem([u"  ➕ (空分组 - 双击新建表单)"])
                placeholder.setData(0, Qt.UserRole, '__placeholder__')
                placeholder.setData(0, Qt.UserRole + 1, group)
                placeholder.setForeground(0, QColor('#94A3B8'))
                pfont = placeholder.font(0)
                pfont.setItalic(True)
                placeholder.setFont(0, pfont)
                placeholder.setToolTip(0, u"该分组下暂无表单，双击或右键可在此分组下新建表单")
                grp_item.addChild(placeholder)

            self.form_tree.addTopLevelItem(grp_item)
            grp_item.setExpanded(True)

    def _do_filter_tree(self):
        selected_grp = self.group_combo.currentData() if hasattr(self, 'group_combo') else None
        self._rebuild_tree(self.forms_data, self.search_edit.text(), selected_group=selected_grp)

    def _on_tree_double_click(self, item, col):
        if not item:
            return
        role = item.data(0, Qt.UserRole)
        if role == '__placeholder__':
            grp = item.data(0, Qt.UserRole + 1)
            self._new_form(default_group=grp)
            return
        if isinstance(role, QueryForm):
            self._open_form_tab(role)

    def _tree_context_menu(self, pos):
        from PyQt5.QtWidgets import QMenu
        item = self.form_tree.itemAt(pos)
        menu = QMenu(self)

        if not item:
            # 在空白区域点击
            a_new_form = menu.addAction(u"新建表单")
            menu.addSeparator()
            a_refresh  = menu.addAction(u"刷新表单列表")

            act = menu.exec_(self.form_tree.viewport().mapToGlobal(pos))
            if act == a_new_form:
                self._new_form()
            elif act == a_refresh:
                self._load_forms()
            return

        role = item.data(0, Qt.UserRole)
        group_name = item.data(0, Qt.UserRole + 1)

        if role is None or role == '__placeholder__':
            # 点击了分组项或占位符
            grp = group_name or '默认'
            a_new_form = menu.addAction(u"在「{}」下新建表单".format(grp))
            a_new_form.setFont(QFont('', -1, QFont.Bold))
            menu.addSeparator()
            a_rename   = menu.addAction(u"重命名分组")
            a_del_grp  = menu.addAction(u"删除分组")
            menu.addSeparator()
            a_open_dir = menu.addAction(u"打开分组所在目录")

            act = menu.exec_(self.form_tree.viewport().mapToGlobal(pos))
            if act == a_new_form:
                self._new_form(default_group=grp)
            elif act == a_rename:
                self._rename_group(grp)
            elif act == a_del_grp:
                self._delete_group(grp)
            elif act == a_open_dir:
                self._open_group_in_explorer(grp)
            return

        if isinstance(role, QueryForm):
            form = role
            a_open     = menu.addAction(u"打开查询")
            a_open.setFont(QFont('', -1, QFont.Bold))
            a_edit     = menu.addAction(u"编辑表单")
            a_new_form = menu.addAction(u"在「{}」下新建表单".format(form.group))
            menu.addSeparator()
            a_delete   = menu.addAction(u"删除表单")
            menu.addSeparator()
            a_open_dir = menu.addAction(u"打开表单所在目录")

            act = menu.exec_(self.form_tree.viewport().mapToGlobal(pos))
            if act == a_open:
                self._open_form_tab(form)
            elif act == a_edit:
                self._edit_form_by_path(form)
            elif act == a_new_form:
                self._new_form(default_group=form.group)
            elif act == a_delete:
                self._delete_form(form)
            elif act == a_open_dir:
                self._open_group_in_explorer(form.group)

    # ════════════════════════════════════════
    #  标签页管理
    # ════════════════════════════════════════
    def _open_form_tab(self, form):
        # 若已打开则切换过去
        for i in range(self.tab_widget.count()):
            w = self.tab_widget.widget(i)
            if isinstance(w, QueryTab) and w.form.file_path == form.file_path:
                self.tab_widget.setCurrentIndex(i)
                return

        tab = QueryTab(form, self.db_manager, FORMS_DIR, self)
        tab.form_modified.connect(self._on_form_modified)
        idx = self.tab_widget.addTab(tab, form.title)
        # 给标签加 tooltip
        self.tab_widget.setTabToolTip(idx, form.description or form.file_path)
        self.tab_widget.setCurrentIndex(idx)

    def _close_tab(self, index):
        w = self.tab_widget.widget(index)
        if w is self._welcome:
            return  # 不关闭欢迎页
        # 若查询正在运行，提示确认
        if isinstance(w, QueryTab) and w._worker and w._worker.isRunning():
            reply = QMessageBox.question(
                self, u"确认关闭",
                u"查询仍在运行，确定关闭该标签页吗？",
                QMessageBox.Yes | QMessageBox.No
            )
            if reply != QMessageBox.Yes:
                return
            # 协作式取消：设标志让 worker 线程自行结束
            w._cancel_worker()
        self.tab_widget.removeTab(index)

    def _on_form_modified(self, file_path):
        """表单文件被编辑后，关闭旧标签，重新加载并打开新标签"""
        self._load_forms()
        # 找到并关闭旧 tab
        for i in range(self.tab_widget.count() - 1, -1, -1):
            w = self.tab_widget.widget(i)
            if isinstance(w, QueryTab) and w.form.file_path == file_path:
                self.tab_widget.removeTab(i)
                break
        # 重新打开
        try:
            new_form = FormParser.parse_file(file_path, forms_root=FORMS_DIR)
            self._open_form_tab(new_form)
        except Exception as e:
            QMessageBox.warning(self, u"重载失败",
                                u"重新加载表单失败：\n{}".format(e))

    # ════════════════════════════════════════
    #  表单与分组 CRUD
    # ════════════════════════════════════════
    def _new_form(self, default_group=None):
        if default_group is None:
            curr = self.form_tree.currentItem()
            if curr:
                grp = curr.data(0, Qt.UserRole + 1)
                if grp:
                    default_group = grp
            if not default_group and hasattr(self, 'group_combo'):
                default_group = self.group_combo.currentData()
        dlg = FormEditorDialog(None, FORMS_DIR, parent=self, default_group=default_group)
        if dlg.exec_():
            self._load_forms()
            target_group = getattr(dlg, 'saved_group', None) or getattr(dlg, 'default_group', None)
            saved_path = getattr(dlg, 'saved_path', None)
            if target_group:
                self._select_group_in_tree(target_group, file_path=saved_path)

    def _rename_group(self, old_group):
        new_group, ok = QInputDialog.getText(
            self, u"重命名分组",
            u"请输入分组「{}」的新名称：".format(old_group),
            text=old_group
        )
        if not ok or not new_group.strip() or new_group.strip() == old_group:
            return
        new_group = new_group.strip()
        import re
        if re.search(r'[\\/:*?"<>|]', new_group):
            QMessageBox.warning(self, u"提示", u'分组名称不能包含以下特殊字符：\n\\ / : * ? " < > |')
            return
        old_dir = os.path.join(FORMS_DIR, old_group)
        new_dir = os.path.join(FORMS_DIR, new_group)
        if os.path.exists(new_dir):
            QMessageBox.warning(self, u"提示", u"目标分组「{}」已存在！".format(new_group))
            return
        try:
            os.rename(old_dir, new_dir)
            self._load_forms()
            self._select_group_in_tree(new_group)
            self.statusBar().showMessage(u"分组已重命名为「{}」".format(new_group), 4000)
        except Exception as e:
            QMessageBox.critical(self, u"重命名失败", str(e))

    def _delete_group(self, group_name):
        group_dir = os.path.join(FORMS_DIR, group_name)
        if not os.path.exists(group_dir):
            return
        files = [f for f in os.listdir(group_dir) if os.path.isfile(os.path.join(group_dir, f))]
        if files:
            reply = QMessageBox.question(
                self, u"确认删除分组",
                u"分组「{}」下包含 {} 个文件。\n确定要永久删除该分组及其全部表单吗？".format(group_name, len(files)),
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No
            )
        else:
            reply = QMessageBox.question(
                self, u"确认删除分组",
                u"确定要删除空分组「{}」吗？".format(group_name),
                QMessageBox.Yes | QMessageBox.No
            )
        if reply != QMessageBox.Yes:
            return
        try:
            import shutil
            shutil.rmtree(group_dir)
            self._load_forms()
            # 关闭已打开的属于该分组的 tab
            for i in range(self.tab_widget.count() - 1, -1, -1):
                w = self.tab_widget.widget(i)
                if isinstance(w, QueryTab) and getattr(w.form, 'group', '') == group_name:
                    self.tab_widget.removeTab(i)
            self.statusBar().showMessage(u"分组「{}」已删除".format(group_name), 4000)
        except Exception as e:
            QMessageBox.critical(self, u"删除分组失败", str(e))

    def _open_group_in_explorer(self, group_name):
        group_dir = os.path.join(FORMS_DIR, group_name)
        if not os.path.exists(group_dir):
            group_dir = FORMS_DIR
        import subprocess
        try:
            os.startfile(group_dir)
        except Exception:
            subprocess.Popen(['explorer', group_dir])

    def _select_group_in_tree(self, group_name, file_path=None):
        if hasattr(self, 'group_combo'):
            curr_data = self.group_combo.currentData()
            if curr_data and curr_data != group_name:
                idx = self.group_combo.findData(group_name)
                if idx >= 0:
                    self.group_combo.setCurrentIndex(idx)
                else:
                    self.group_combo.setCurrentIndex(0)

        for i in range(self.form_tree.topLevelItemCount()):
            top = self.form_tree.topLevelItem(i)
            if top.data(0, Qt.UserRole + 1) == group_name:
                top.setExpanded(True)
                target_item = top
                if file_path:
                    norm_path = os.path.normpath(file_path).lower()
                    for j in range(top.childCount()):
                        ch = top.child(j)
                        form_obj = ch.data(0, Qt.UserRole)
                        if isinstance(form_obj, QueryForm) and getattr(form_obj, 'file_path', None):
                            if os.path.normpath(form_obj.file_path).lower() == norm_path:
                                target_item = ch
                                break
                self.form_tree.setCurrentItem(target_item)
                self.form_tree.scrollToItem(target_item)
                break

    def _edit_form_by_path(self, form):
        old_path = form.file_path
        dlg = FormEditorDialog(form, FORMS_DIR, self)
        if dlg.exec_():
            if old_path != form.file_path:
                for i in range(self.tab_widget.count() - 1, -1, -1):
                    w = self.tab_widget.widget(i)
                    if isinstance(w, QueryTab) and w.form.file_path == old_path:
                        self.tab_widget.removeTab(i)
                        break
            self._on_form_modified(form.file_path)
            target_group = getattr(dlg, 'saved_group', None) or form.group
            if target_group:
                self._select_group_in_tree(target_group, file_path=form.file_path)

    def _delete_form(self, form):
        reply = QMessageBox.question(
            self, u"确认删除",
            u"确定要删除表单「{}」吗？\n\n文件将被永久删除：\n{}".format(
                form.title, form.file_path
            ),
            QMessageBox.Yes | QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return
        try:
            os.remove(form.file_path)
            self._load_forms()
            # 关闭已打开的同文件 tab
            for i in range(self.tab_widget.count() - 1, -1, -1):
                w = self.tab_widget.widget(i)
                if isinstance(w, QueryTab) and w.form.file_path == form.file_path:
                    self.tab_widget.removeTab(i)
        except Exception as e:
            QMessageBox.critical(self, u"删除失败", str(e))

    # ════════════════════════════════════════
    #  窗口关闭
    # ════════════════════════════════════════
    def closeEvent(self, event):
        # 检查是否有正在运行的查询
        running = []
        for i in range(self.tab_widget.count()):
            w = self.tab_widget.widget(i)
            if isinstance(w, QueryTab) and w._worker and w._worker.isRunning():
                running.append((w.form.title, w))
        if running:
            reply = QMessageBox.question(
                self, u"确认退出",
                u"以下查询仍在运行，确定退出吗？\n\n• {}".format(
                    '\n• '.join([t for t, _ in running])
                ),
                QMessageBox.Yes | QMessageBox.No
            )
            if reply != QMessageBox.Yes:
                event.ignore()
                return
            # 协作式取消：设标志让 worker 线程自行结束，等待超时后再强杀
            for _, w in running:
                w._cancel_worker()
        # 清理连接测试线程
        if self._conn_worker and self._conn_worker.isRunning():
            self._conn_worker.quit()
            self._conn_worker.wait(1000)
            self._conn_worker.deleteLater()
            self._conn_worker = None
        event.accept()


# ── 全局样式表（Fusion 风格 + 专业深色工具栏主题）──
GLOBAL_STYLESHEET = u"""
/* ── 全局基础 ── */
QWidget {
    font-family: "Microsoft YaHei", "微软雅黑", "SimSun", sans-serif;
    font-size: 12px;
    color: #1A1A2E;
}

/* ── 主窗口 / 对话框 ── */
QMainWindow {
    background-color: #F0F2F6;
    border: 1px solid #1E3050;
    border-radius: 8px;
}
QDialog {
    background-color: #F0F2F6;
}

/* ── 工具栏 ── */
QToolBar {
    background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
                                stop:0 #1E3050, stop:1 #162540);
    border: none;
    border-top-left-radius: 8px;
    border-top-right-radius: 8px;
    spacing: 6px;
    padding: 4px 8px;
}
QToolBar QLabel {
    color: #C8D8F0;
    font-size: 12px;
}
QToolBar::separator {
    background: #2E4570;
    width: 1px;
    margin: 4px 4px;
}
QToolBar QPushButton {
    background: transparent;
    color: #D0E4FF;
    border: 1px solid #2E4570;
    border-radius: 6px;
    padding: 4px 12px;
    font-size: 12px;
}
QToolBar QPushButton:hover {
    background: #2A4468;
    border-color: #4A7ABF;
    color: #FFFFFF;
}
QToolBar QPushButton:pressed {
    background: #1A6EB5;
}

/* ── 窗口控制按钮 ── */
QPushButton#btn_win_min, QPushButton#btn_win_max {
    background: transparent;
    color: #C8D8F0;
    border: none;
    border-radius: 6px;
    font-size: 11px;
    font-weight: bold;
    padding: 0;
}
QPushButton#btn_win_min:hover, QPushButton#btn_win_max:hover {
    background: #2A4468;
    color: #FFFFFF;
}
QPushButton#btn_win_close {
    background: transparent;
    color: #C8D8F0;
    border: none;
    border-radius: 6px;
    font-size: 13px;
    font-weight: bold;
    padding: 0;
}
QPushButton#btn_win_close:hover {
    background: #E81123;
    color: #FFFFFF;
}
QPushButton#btn_win_close:pressed {
    background: #BF0F1D;
    color: #FFFFFF;
}

/* ── 普通按钮 ── */
QPushButton {
    background: #FFFFFF;
    border: 1px solid #C5CDD8;
    border-radius: 6px;
    padding: 5px 14px;
    color: #1A1A2E;
}
QPushButton:hover {
    background: #EBF3FC;
    border-color: #1A6EB5;
    color: #1A6EB5;
}
QPushButton:pressed {
    background: #D0E4F7;
    border-color: #1256A0;
}
QPushButton:disabled {
    background: #F0F0F0;
    border-color: #D8D8D8;
    color: #AAAAAA;
}
QPushButton:default {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #2563EB, stop:1 #1D4ED8);
    color: #FFFFFF;
    border: 1px solid #1E40AF;
    font-weight: bold;
}
QPushButton:default:hover {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #3B82F6, stop:1 #2563EB);
    border-color: #1D4ED8;
    color: #FFFFFF;
}
QPushButton:default:pressed {
    background: #1E40AF;
    color: #FFFFFF;
}

/* ── 输入框 ── */
QLineEdit, QTextEdit, QPlainTextEdit {
    background: #FFFFFF;
    border: 1px solid #C5CDD8;
    border-radius: 6px;
    padding: 4px 7px;
    selection-background-color: #1A6EB5;
    selection-color: #FFFFFF;
}
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus {
    border-color: #1A6EB5;
    background: #FAFCFF;
}

/* ── 日期选择 ── */
QDateEdit, QDateTimeEdit {
    background: #FFFFFF;
    border: 1px solid #C5CDD8;
    border-radius: 6px;
    padding: 3px 6px;
}
QDateEdit:focus, QDateTimeEdit:focus {
    border-color: #1A6EB5;
}

/* ── 下拉框 ── */
QComboBox {
    background: #FFFFFF;
    border: 1px solid #C5CDD8;
    border-radius: 6px;
    padding: 3px 6px;
    min-height: 22px;
}
QComboBox:focus {
    border-color: #1A6EB5;
}
QComboBox QAbstractItemView {
    background: #FFFFFF;
    border: 1px solid #C5CDD8;
    border-radius: 6px;
    selection-background-color: #1A6EB5;
    selection-color: #FFFFFF;
}

/* ── 分组框 ── */
QGroupBox {
    border: 1px solid #D0D8E4;
    border-radius: 8px;
    margin-top: 10px;
    padding-top: 12px;
    background: #FFFFFF;
}
QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 12px;
    padding: 0 6px;
    color: #1A6EB5;
    font-weight: bold;
}

/* ── 左侧树形列表 ── */
QTreeWidget {
    background: #FFFFFF;
    border: 1px solid #CBD5E1;
    border-radius: 8px;
    outline: none;
    padding: 2px;
    show-decoration-selected: 0;
    selection-background-color: transparent;
}
QTreeWidget::item {
    height: 30px;
    padding-left: 6px;
    border-radius: 6px;
    margin: 1px 2px;
}
QTreeWidget::item:hover {
    background: #EFF6FF;
    color: #1D4ED8;
}
QTreeWidget::item:selected {
    background: #2563EB;
    color: #FFFFFF;
    font-weight: bold;
}
QTreeWidget::branch {
    background: transparent;
}

/* ── 标签页 ── */
QTabWidget::pane {
    border: 1px solid #CBD5E1;
    border-radius: 0 8px 8px 8px;
    background: #FFFFFF;
    top: -1px;
}
QTabBar::tab {
    background: #E8EEF5;
    border: 1px solid #CBD5E1;
    border-bottom: none;
    padding: 7px 18px;
    margin-right: 3px;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
    color: #475569;
    font-size: 12px;
}
QTabBar::tab:selected {
    background: #FFFFFF;
    color: #1D4ED8;
    font-weight: bold;
    border-top: 3px solid #2563EB;
    border-bottom: 2px solid #FFFFFF;
}
QTabBar::tab:hover:!selected {
    background: #DBEAFE;
    color: #1D4ED8;
}
QTabBar::close-button {
    subcontrol-position: right;
    border-radius: 4px;
}
QTabBar::close-button:hover {
    background: #E2E8F0;
}

/* ── 结果表格 ── */
QTableView {
    background: #FFFFFF;
    alternate-background-color: #F8FAFC;
    border: 1px solid #CBD5E1;
    border-radius: 6px;
    gridline-color: #E2E8F0;
    selection-background-color: #BFDBFE;
    selection-color: #0F172A;
    outline: none;
}
QTableView::item {
    padding: 3px 6px;
    border: none;
}
QTableView::item:selected {
    background: #BFDBFE;
    color: #0F172A;
}
QHeaderView {
    background: transparent;
}
QHeaderView::section {
    background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
                                stop:0 #1E293B, stop:1 #0F172A);
    color: #F1F5F9;
    border: none;
    border-right: 1px solid #334155;
    border-bottom: 2px solid #2563EB;
    padding: 6px 8px;
    font-weight: bold;
    font-size: 12px;
}
QHeaderView::section:hover {
    background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
                                stop:0 #334155, stop:1 #1E293B);
}
QHeaderView::section:checked {
    background: #2563EB;
}

/* ── 滚动条 ── */
QScrollBar:vertical {
    background: #F0F2F6;
    width: 10px;
    border-radius: 5px;
    margin: 0;
}
QScrollBar::handle:vertical {
    background: #B8C4D4;
    border-radius: 5px;
    min-height: 24px;
}
QScrollBar::handle:vertical:hover {
    background: #1A6EB5;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar:horizontal {
    background: #F0F2F6;
    height: 10px;
    border-radius: 5px;
    margin: 0;
}
QScrollBar::handle:horizontal {
    background: #B8C4D4;
    border-radius: 5px;
    min-width: 24px;
}
QScrollBar::handle:horizontal:hover {
    background: #1A6EB5;
}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }

/* ── 进度条 ── */
QProgressBar {
    background: #E4EAF2;
    border: 1px solid #C5CDD8;
    border-radius: 6px;
    text-align: center;
}
QProgressBar::chunk {
    background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
                                stop:0 #1A6EB5, stop:1 #28A0D8);
    border-radius: 5px;
}

/* ── 状态栏 ── */
QStatusBar {
    background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
                                stop:0 #1E3050, stop:1 #162540);
    color: #90AACE;
    font-size: 11px;
    padding: 2px 8px;
    border-bottom-left-radius: 8px;
    border-bottom-right-radius: 8px;
}
QStatusBar::item { border: none; }

/* ── 分割条 ── */
QSplitter::handle {
    background: #D0D8E4;
}
QSplitter::handle:horizontal {
    width: 2px;
}

/* ── 菜单 ── */
QMenu {
    background: #FFFFFF;
    border: 1px solid #C5CDD8;
    border-radius: 6px;
    padding: 4px 0;
}
QMenu::item {
    padding: 6px 24px 6px 16px;
}
QMenu::item:selected {
    background: #EBF3FC;
    color: #1A6EB5;
}
QMenu::separator {
    height: 1px;
    background: #E4EAF2;
    margin: 3px 8px;
}

/* ── 复选框 ── */
QCheckBox::indicator {
    width: 14px;
    height: 14px;
    border: 1px solid #C5CDD8;
    border-radius: 3px;
    background: #FFFFFF;
}
QCheckBox::indicator:checked {
    background: #1A6EB5;
    border-color: #1A6EB5;
}
QCheckBox::indicator:hover {
    border-color: #1A6EB5;
}
"""


# ════════════════════════════════════════
#  程序入口
# ════════════════════════════════════════
def main():
    logger.info("=" * 50)
    logger.info("DBQuery starting...")
    logger.info("Python version: %s", sys.version)
    logger.info("Executable: %s", sys.executable)
    logger.info("Frozen: %s", getattr(sys, 'frozen', False))

    # 高 DPI 支持（Win10/11）
    try:
        QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
        QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps,    True)
        logger.info("High DPI support enabled")
    except Exception as e:
        logger.warning("High DPI support failed: %s", str(e))

    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID('neokirito.dbquery.app.v1')
    except Exception:
        pass

    try:
        app = QApplication(sys.argv)
        app.setStyle('Fusion')
        QApplication.setEffectEnabled(Qt.UI_AnimateCombo, False)
        app_icon_path = os.path.join(BASE_DIR, 'app.ico')
        if not os.path.exists(app_icon_path):
            app_icon_path = os.path.join(EXE_DIR, 'app.ico')
        if not os.path.exists(app_icon_path):
            app_icon_path = os.path.join(BASE_DIR, 'app.png')
        if not os.path.exists(app_icon_path):
            app_icon_path = os.path.join(EXE_DIR, 'app.png')
        if os.path.exists(app_icon_path):
            app.setWindowIcon(QIcon(app_icon_path))
        logger.info("QApplication created")
    except Exception as e:
        logger.error("Failed to create QApplication: %s", str(e))
        logger.error(traceback.format_exc())
        raise

    # 应用全局样式表
    app.setStyleSheet(GLOBAL_STYLESHEET)

    try:
        logger.info("Showing desktop login dialog...")
        authenticated_user = require_desktop_login()
        if not authenticated_user:
            logger.info("Desktop login cancelled or rejected; exiting without opening MainWindow")
            return

        logger.info("Creating MainWindow for authenticated user")
        window = MainWindow()
        window.setWindowTitle(u"数据库查询工具 - {}".format(authenticated_user))
        window.show()
        logger.info("MainWindow shown, entering event loop")
        sys.exit(app.exec_())
    except Exception as e:
        logger.error("Fatal error in main: %s", str(e))
        logger.error(traceback.format_exc())
        raise


if __name__ == '__main__':
    try:
        main()
    except Exception as e:
        logger.critical("Application crashed: %s", str(e))
        logger.critical(traceback.format_exc())
        raise
