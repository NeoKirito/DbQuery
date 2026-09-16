import os
import sys

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QIcon, QPixmap
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QFormLayout, QLineEdit, QLabel, QPushButton,
    QHBoxLayout, QMessageBox
)

from db_manager import DBManager
from widgets.config_dialog import ConfigDialog

if getattr(sys, 'frozen', False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class LoginDialog(QDialog):
    """在桌面主窗口打开前验证 qx_czyxx 启用账号。"""

    def __init__(self, parent=None):
        super(LoginDialog, self).__init__(parent)
        self.db_manager = DBManager()
        self.username = ''
        self.setWindowTitle(u'登录数据库查询工具')
        self.setModal(True)
        self.setFixedWidth(390)

        app_icon_path = os.path.join(BASE_DIR, 'app.ico')
        if not os.path.exists(app_icon_path):
            app_icon_path = os.path.join(BASE_DIR, 'app.png')
        if os.path.exists(app_icon_path):
            self.setWindowIcon(QIcon(app_icon_path))

        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 22)
        layout.setSpacing(12)

        # ── Logo 图标（圆形无背景）──
        logo_path = os.path.join(BASE_DIR, 'app.png')
        if not os.path.exists(logo_path):
            logo_path = os.path.join(BASE_DIR, 'static', 'logo.png')
        if os.path.exists(logo_path):
            logo_lbl = QLabel()
            pix = QPixmap(logo_path).scaled(64, 64, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            logo_lbl.setPixmap(pix)
            logo_lbl.setAlignment(Qt.AlignCenter)
            layout.addWidget(logo_lbl)

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
        cancel_btn.setStyleSheet(u"""
            QPushButton {
                background-color: #FFFFFF;
                color: #4A5568;
                border: 1px solid #CBD5E1;
                border-radius: 4px;
                padding: 5px 14px;
                font-size: 12px;
            }
            QPushButton:hover {
                background-color: #F1F5F9;
                border-color: #94A3B8;
                color: #1E293B;
            }
            QPushButton:pressed {
                background-color: #E2E8F0;
            }
        """)

        login_btn = QPushButton(u'登录')
        login_btn.setDefault(True)
        login_btn.clicked.connect(self._attempt_login)
        login_btn.setStyleSheet(u"""
            QPushButton {
                background-color: #1A6EB5;
                color: #FFFFFF;
                border: 1px solid #145E9C;
                border-radius: 4px;
                padding: 5px 20px;
                font-weight: bold;
                font-size: 12px;
            }
            QPushButton:hover {
                background-color: #145B96;
                border-color: #104A7B;
            }
            QPushButton:pressed {
                background-color: #0F4572;
                border-color: #0C365A;
            }
            QPushButton:disabled {
                background-color: #96BCE0;
                border-color: #96BCE0;
                color: #EBF3FA;
            }
        """)
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
