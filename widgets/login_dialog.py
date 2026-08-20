# -*- coding: utf-8 -*-
"""桌面版登录对话框。"""
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QFormLayout, QLineEdit, QLabel, QPushButton,
    QHBoxLayout, QMessageBox
)

from db_manager import DBManager
from widgets.config_dialog import ConfigDialog


class LoginDialog(QDialog):
    """在桌面主窗口打开前验证 qx_czyxx 启用账号。"""

    def __init__(self, parent=None):
        super(LoginDialog, self).__init__(parent)
        self.db_manager = DBManager()
        self.username = ''
        self.setWindowTitle(u'登录数据库查询工具')
        self.setModal(True)
        self.setFixedWidth(390)
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 22)
        layout.setSpacing(12)

        title = QLabel(u'数据库查询工具')
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet('font-size: 20px; font-weight: bold; color: #1A6EB5;')
        subtitle = QLabel(u'请输入已启用的操作员账号和密码')
        subtitle.setAlignment(Qt.AlignCenter)
        subtitle.setStyleSheet('color: #667085;')
        layout.addWidget(title)
        layout.addWidget(subtitle)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.username_edit = QLineEdit()
        self.username_edit.setPlaceholderText(u'账号（czybm）')
        self.username_edit.setClearButtonEnabled(True)
        self.password_edit = QLineEdit()
        self.password_edit.setPlaceholderText(u'密码')
        self.password_edit.setEchoMode(QLineEdit.Password)
        self.password_edit.returnPressed.connect(self._attempt_login)
        form.addRow(u'账号：', self.username_edit)
        form.addRow(u'密码：', self.password_edit)
        layout.addLayout(form)

        self.status_label = QLabel(u'')
        self.status_label.setWordWrap(True)
        self.status_label.setStyleSheet('color: #B42318; min-height: 20px;')
        layout.addWidget(self.status_label)

        actions = QHBoxLayout()
        config_btn = QPushButton(u'数据库连接配置')
        config_btn.clicked.connect(self._open_config)
        actions.addWidget(config_btn)
        actions.addStretch()
        cancel_btn = QPushButton(u'退出')
        cancel_btn.clicked.connect(self.reject)
        login_btn = QPushButton(u'登录')
        login_btn.setDefault(True)
        login_btn.clicked.connect(self._attempt_login)
        actions.addWidget(cancel_btn)
        actions.addWidget(login_btn)
        layout.addLayout(actions)

        self.username_edit.setFocus()

    def _open_config(self):
        dialog = ConfigDialog(self.db_manager, self)
        if dialog.exec_():
            self.db_manager.load_config()
            self.status_label.setStyleSheet('color: #027A48; min-height: 20px;')
            self.status_label.setText(u'数据库连接配置已保存，请使用操作员账号登录。')

    def _attempt_login(self):
        username = self.username_edit.text().strip()
        password = self.password_edit.text()
        if not username or not password:
            self.status_label.setStyleSheet('color: #B42318; min-height: 20px;')
            self.status_label.setText(u'请输入账号和密码。')
            return

        self.status_label.setStyleSheet('color: #667085; min-height: 20px;')
        self.status_label.setText(u'正在验证，请稍候…')
        self.setEnabled(False)
        try:
            authenticated = self.db_manager.authenticate_user(username, password)
        finally:
            self.setEnabled(True)

        if authenticated:
            self.username = username
            self.accept()
            return

        self.password_edit.clear()
        self.password_edit.setFocus()
        self.status_label.setStyleSheet('color: #B42318; min-height: 20px;')
        self.status_label.setText(u'账号、密码无效，账号可能未启用，或数据服务暂不可用。')


def require_desktop_login(parent=None):
    """显示登录框，成功时返回登录账号，取消或失败时返回空字符串。"""
    dialog = LoginDialog(parent)
    if dialog.exec_() == QDialog.Accepted:
        return dialog.username
    return ''
