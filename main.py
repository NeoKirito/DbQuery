# -*- coding: utf-8 -*-
"""
数据库查询工具 — 主窗口
"""
import sys
import os
import logging
import traceback

# 配置日志
log_file = os.path.join(os.path.dirname(sys.executable if getattr(sys, 'frozen', False) else os.path.abspath(__file__)), 'dbquery.log')
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(log_file, encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger('DBQuery.main')

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QSplitter, QTabWidget, QLabel, QPushButton, QToolBar,
    QTreeWidget, QTreeWidgetItem, QMessageBox, QLineEdit,
    QFrame, QSizePolicy, QAction, QTabBar, QInputDialog
)
from PyQt5.QtCore import Qt, QSize, QTimer, QThread, pyqtSignal
from PyQt5.QtGui import QFont, QIcon, QColor

from db_manager import DBManager
from form_parser import FormParser, QueryForm
from widgets.query_tab import QueryTab
from widgets.config_dialog import ConfigDialog
from widgets.form_editor import FormEditorDialog
from widgets.login_dialog import require_desktop_login

# ── 路径常量（exe 和开发模式均有效）──
if getattr(sys, 'frozen', False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

FORMS_DIR = os.path.join(BASE_DIR, 'forms')

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

        self.setWindowTitle(u"数据库查询工具")
        self.setMinimumSize(1000, 680)
        self.resize(1300, 820)

        app_icon_path = os.path.join(BASE_DIR, 'app.ico')
        if not os.path.exists(app_icon_path):
            app_icon_path = os.path.join(BASE_DIR, 'app.png')
        if os.path.exists(app_icon_path):
            self.setWindowIcon(QIcon(app_icon_path))

        self._setup_ui()
        self._load_forms()

        # 启动后自动测试连接（静默）
        QTimer.singleShot(400, lambda: self._test_connection(silent=True))

    # ════════════════════════════════════════
    #  界面构建
    # ════════════════════════════════════════
    def _setup_ui(self):
        # ── 工具栏 ──────────────────────────
        tb = QToolBar(u"主工具栏")
        tb.setMovable(False)
        tb.setIconSize(QSize(16, 16))
        self.addToolBar(tb)

        # 应用名称
        app_lbl = QLabel(u"  📊 数据库查询工具  ")
        app_lbl.setStyleSheet(
            "color: #90BAEE; font-size: 13px; font-weight: bold; letter-spacing: 1px;"
        )
        tb.addWidget(app_lbl)
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

        btn_new       = QPushButton(u"新建表单")
        btn_new_group = QPushButton(u"新建分组")
        btn_refresh   = QPushButton(u"刷新表单")
        btn_new.clicked.connect(lambda: self._new_form())
        btn_new_group.clicked.connect(self._new_group)
        btn_refresh.clicked.connect(self._load_forms)
        tb.addWidget(btn_new)
        tb.addWidget(btn_new_group)
        tb.addWidget(btn_refresh)

        # 右侧弹簧
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        tb.addWidget(spacer)

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
        lv.addWidget(self.search_edit)
        lv.addWidget(self.form_tree)

        # ---- 右侧：标签页 ----
        self.tab_widget = QTabWidget()
        self.tab_widget.setTabsClosable(True)
        self.tab_widget.setDocumentMode(False)
        self.tab_widget.setMovable(True)
        self.tab_widget.tabCloseRequested.connect(self._close_tab)

        # 占位页（无 close 按钮）
        self._welcome = QLabel(
            u"←  双击左侧表单开始查询\n\n右键表单可编辑或删除"
        )
        self._welcome.setAlignment(Qt.AlignCenter)
        self._welcome.setStyleSheet(
            "color: #B0BECE; font-size: 15px; line-height: 2;"
            "background: #F8FAFD;"
        )
        self.tab_widget.addTab(self._welcome, u"欢迎")
        self.tab_widget.tabBar().setTabButton(0, QTabBar.RightSide, None)

        splitter.addWidget(left)
        splitter.addWidget(self.tab_widget)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([210, 1090])

        self.setCentralWidget(splitter)

        # ── 状态栏 ──────────────────────────
        self.statusBar().showMessage(u"就绪")

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
        self._rebuild_tree(self.forms_data)
        total_forms = sum(len(v) for v in self.forms_data.values())
        total_groups = len(self.forms_data)
        self.statusBar().showMessage(u"已加载 {} 个分组，共 {} 个表单".format(total_groups, total_forms))

    def _rebuild_tree(self, data, filter_text=''):
        self.form_tree.clear()
        ft = filter_text.strip().lower()

        for group in sorted(data.keys()):
            forms = data[group]
            matching_forms = [f for f in forms if not ft or ft in f.title.lower()]

            # 搜索过滤：当有搜索词且既无匹配表单、分组名也不匹配搜索词时隐藏
            if ft and not matching_forms and ft not in group.lower():
                continue

            grp_item = QTreeWidgetItem([u"  " + group])
            grp_item.setData(0, Qt.UserRole, None)  # None 表示分组项
            grp_item.setData(0, Qt.UserRole + 1, group)
            grp_item.setForeground(0, QColor('#0055AA'))
            grp_item.setFont(0, QFont('', -1, QFont.Bold))

            if matching_forms:
                for form in matching_forms:
                    child = QTreeWidgetItem([u"    " + form.title])
                    child.setData(0, Qt.UserRole, form)
                    child.setData(0, Qt.UserRole + 1, group)
                    child.setToolTip(0, form.description or form.file_path)
                    grp_item.addChild(child)
            elif not ft:
                # 空分组友好占位提示
                placeholder = QTreeWidgetItem([u"    (空分组 - 双击新建表单)"])
                placeholder.setData(0, Qt.UserRole, '__placeholder__')
                placeholder.setData(0, Qt.UserRole + 1, group)
                placeholder.setForeground(0, QColor('#909399'))
                pfont = placeholder.font(0)
                pfont.setItalic(True)
                placeholder.setFont(0, pfont)
                placeholder.setToolTip(0, u"该分组下暂无表单，双击或右键可在此分组下新建表单")
                grp_item.addChild(placeholder)

            self.form_tree.addTopLevelItem(grp_item)
            grp_item.setExpanded(True)

    def _do_filter_tree(self):
        self._rebuild_tree(self.forms_data, self.search_edit.text())

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
            a_new_grp  = menu.addAction(u"新建分组")
            a_new_form = menu.addAction(u"新建表单")
            menu.addSeparator()
            a_refresh  = menu.addAction(u"刷新表单列表")

            act = menu.exec_(self.form_tree.viewport().mapToGlobal(pos))
            if act == a_new_grp:
                self._new_group()
            elif act == a_new_form:
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
            a_new_grp  = menu.addAction(u"新建分组")
            menu.addSeparator()
            a_rename   = menu.addAction(u"重命名分组")
            a_del_grp  = menu.addAction(u"删除分组")
            menu.addSeparator()
            a_open_dir = menu.addAction(u"打开分组所在目录")

            act = menu.exec_(self.form_tree.viewport().mapToGlobal(pos))
            if act == a_new_form:
                self._new_form(default_group=grp)
            elif act == a_new_grp:
                self._new_group()
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
        dlg = FormEditorDialog(None, FORMS_DIR, parent=self, default_group=default_group)
        if dlg.exec_():
            self._load_forms()
            target_group = getattr(dlg, 'default_group', None)
            if target_group:
                self._select_group_in_tree(target_group)

    def _new_group(self):
        group_name, ok = QInputDialog.getText(
            self, u"新建分组", u"请输入新分组名称（将作为 forms 子目录）："
        )
        if not ok:
            return
        group_name = group_name.strip()
        if not group_name:
            QMessageBox.warning(self, u"提示", u"分组名称不能为空！")
            return
        import re
        if re.search(r'[\\/:*?"<>|]', group_name):
            QMessageBox.warning(self, u"提示", u'分组名称不能包含以下特殊字符：\n\\ / : * ? " < > |')
            return
        group_dir = os.path.join(FORMS_DIR, group_name)
        if os.path.exists(group_dir):
            QMessageBox.information(self, u"提示", u"分组「{}」已存在！".format(group_name))
            self._select_group_in_tree(group_name)
            return
        try:
            os.makedirs(group_dir, exist_ok=True)
            self._load_forms()
            self._select_group_in_tree(group_name)
            self.statusBar().showMessage(u"新建分组「{}」成功".format(group_name), 4000)
            reply = QMessageBox.question(
                self, u"新建分组成功",
                u"分组「{}」已成功创建。\n是否立即在该分组下新建表单？".format(group_name),
                QMessageBox.Yes | QMessageBox.No
            )
            if reply == QMessageBox.Yes:
                self._new_form(default_group=group_name)
        except Exception as e:
            QMessageBox.critical(self, u"创建分组失败", str(e))

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

    def _select_group_in_tree(self, group_name):
        for i in range(self.form_tree.topLevelItemCount()):
            top = self.form_tree.topLevelItem(i)
            if top.data(0, Qt.UserRole + 1) == group_name:
                self.form_tree.setCurrentItem(top)
                top.setExpanded(True)
                self.form_tree.scrollToItem(top)
                break

    def _edit_form_by_path(self, form):
        dlg = FormEditorDialog(form, FORMS_DIR, self)
        if dlg.exec_():
            self._on_form_modified(form.file_path)

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
        app = QApplication(sys.argv)
        app.setStyle('Fusion')
        app_icon_path = os.path.join(BASE_DIR, 'app.ico')
        if not os.path.exists(app_icon_path):
            app_icon_path = os.path.join(BASE_DIR, 'app.png')
        if os.path.exists(app_icon_path):
            app.setWindowIcon(QIcon(app_icon_path))
        logger.info("QApplication created")
    except Exception as e:
        logger.error("Failed to create QApplication: %s", str(e))
        logger.error(traceback.format_exc())
        raise

    # ── 全局样式表（Fusion 风格 + 专业深色工具栏主题）──
    app.setStyleSheet(u"""
/* ── 全局基础 ── */
QWidget {
    font-family: "Microsoft YaHei", "微软雅黑", "SimSun", sans-serif;
    font-size: 12px;
    color: #1A1A2E;
}

/* ── 主窗口 / 对话框 ── */
QMainWindow, QDialog {
    background-color: #F0F2F6;
}

/* ── 工具栏 ── */
QToolBar {
    background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
                                stop:0 #1E3050, stop:1 #162540);
    border: none;
    spacing: 6px;
    padding: 5px 10px;
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
    border-radius: 4px;
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

/* ── 普通按钮 ── */
QPushButton {
    background: #FFFFFF;
    border: 1px solid #C5CDD8;
    border-radius: 4px;
    padding: 4px 12px;
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

/* ── 输入框 ── */
QLineEdit, QTextEdit {
    background: #FFFFFF;
    border: 1px solid #C5CDD8;
    border-radius: 4px;
    padding: 4px 7px;
    selection-background-color: #1A6EB5;
    selection-color: #FFFFFF;
}
QLineEdit:focus, QTextEdit:focus {
    border-color: #1A6EB5;
    background: #FAFCFF;
}

/* ── 日期选择 ── */
QDateEdit, QDateTimeEdit {
    background: #FFFFFF;
    border: 1px solid #C5CDD8;
    border-radius: 4px;
    padding: 3px 6px;
}
QDateEdit:focus, QDateTimeEdit:focus {
    border-color: #1A6EB5;
}
QDateEdit::drop-down, QDateTimeEdit::drop-down {
    border: none;
    width: 20px;
}

/* ── 下拉框 ── */
QComboBox {
    background: #FFFFFF;
    border: 1px solid #C5CDD8;
    border-radius: 4px;
    padding: 3px 6px;
    min-height: 22px;
}
QComboBox:focus {
    border-color: #1A6EB5;
}
QComboBox::drop-down {
    border: none;
    width: 22px;
}
QComboBox QAbstractItemView {
    background: #FFFFFF;
    border: 1px solid #C5CDD8;
    selection-background-color: #1A6EB5;
    selection-color: #FFFFFF;
}

/* ── 分组框 ── */
QGroupBox {
    border: 1px solid #D0D8E4;
    border-radius: 6px;
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
    border: 1px solid #D0D8E4;
    border-radius: 6px;
    outline: none;
}
QTreeWidget::item {
    height: 28px;
    padding-left: 4px;
    border-radius: 3px;
}
QTreeWidget::item:hover {
    background: #EBF3FC;
}
QTreeWidget::item:selected {
    background: #1A6EB5;
    color: #FFFFFF;
}
QTreeWidget::branch {
    background: transparent;
}

/* ── 标签页 ── */
QTabWidget::pane {
    border: 1px solid #D0D8E4;
    border-radius: 0 6px 6px 6px;
    background: #FFFFFF;
    top: -1px;
}
QTabBar::tab {
    background: #E4EAF2;
    border: 1px solid #D0D8E4;
    border-bottom: none;
    padding: 6px 16px;
    margin-right: 2px;
    border-top-left-radius: 5px;
    border-top-right-radius: 5px;
    color: #4A5568;
}
QTabBar::tab:selected {
    background: #FFFFFF;
    color: #1A6EB5;
    font-weight: bold;
    border-bottom: 2px solid #FFFFFF;
}
QTabBar::tab:hover:!selected {
    background: #D4E4F4;
    color: #1A6EB5;
}
QTabBar::close-button {
    subcontrol-position: right;
}

/* ── 结果表格 ── */
QTableView {
    background: #FFFFFF;
    alternate-background-color: #F4F8FF;
    border: 1px solid #D0D8E4;
    border-radius: 4px;
    gridline-color: #E8ECF4;
    selection-background-color: #C8DEFA;
    selection-color: #1A1A2E;
    outline: none;
}
QTableView::item {
    padding: 3px 6px;
    border: none;
}
QTableView::item:selected {
    background: #C8DEFA;
    color: #1A1A2E;
}
QHeaderView {
    background: transparent;
}
QHeaderView::section {
    background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
                                stop:0 #2A4070, stop:1 #1E3050);
    color: #E0ECFF;
    border: none;
    border-right: 1px solid #354E80;
    border-bottom: 2px solid #1A6EB5;
    padding: 5px 8px;
    font-weight: bold;
}
QHeaderView::section:hover {
    background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
                                stop:0 #3A5090, stop:1 #2A4070);
}
QHeaderView::section:checked {
    background: #1A6EB5;
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
    border-radius: 4px;
    text-align: center;
}
QProgressBar::chunk {
    background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
                                stop:0 #1A6EB5, stop:1 #28A0D8);
    border-radius: 3px;
}

/* ── 状态栏 ── */
QStatusBar {
    background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
                                stop:0 #1E3050, stop:1 #162540);
    color: #90AACE;
    font-size: 11px;
    padding: 2px 8px;
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
    border-radius: 4px;
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
""")

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
