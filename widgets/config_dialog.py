# -*- coding: utf-8 -*-
"""
数据库连接配置对话框
"""
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QGroupBox,
    QLineEdit, QComboBox, QCheckBox, QPushButton, QLabel, QMessageBox,
    QApplication
)
from PyQt5.QtCore import Qt


class ConfigDialog(QDialog):
    def __init__(self, db_manager, parent=None):
        super(ConfigDialog, self).__init__(parent)
        self.db_manager = db_manager
        self.setWindowTitle("数据库连接配置")
        self.setMinimumWidth(480)
        self.setModal(True)
        self._setup_ui()
        self._load_current()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        grp = QGroupBox("SQL Server 连接参数")
        form = QFormLayout(grp)
        form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        form.setSpacing(8)

        self.server_edit = QLineEdit()
        self.server_edit.setPlaceholderText("如: 192.168.1.10  或  HOST\\SQLEXPRESS")

        self.port_edit = QLineEdit()
        self.port_edit.setPlaceholderText("默认 1433（TCP/IP 端口）")
        self.port_edit.setMaximumWidth(120)

        self.db_edit = QLineEdit()
        self.db_edit.setPlaceholderText("目标数据库名称")

        # 驱动列表
        from db_manager import DBManager
        drivers = DBManager.list_drivers()
        fallback = [
            'ODBC Driver 17 for SQL Server',
            'ODBC Driver 13 for SQL Server',
            'ODBC Driver 11 for SQL Server',
            'SQL Server',
        ]
        all_drivers = list(dict.fromkeys(drivers + fallback))  # 去重保序

        self.driver_combo = QComboBox()
        self.driver_combo.addItems(all_drivers)
        self.driver_combo.setEditable(True)

        self.trusted_check = QCheckBox("使用 Windows 身份验证（Trusted Connection）")
        self.trusted_check.stateChanged.connect(self._toggle_auth)

        self.user_edit = QLineEdit()
        self.user_edit.setPlaceholderText("SQL Server 用户名")

        self.pass_edit = QLineEdit()
        self.pass_edit.setEchoMode(QLineEdit.Password)
        self.pass_edit.setPlaceholderText("密码")

        form.addRow("服务器地址:", self.server_edit)
        form.addRow("端口:", self.port_edit)
        form.addRow("数据库:", self.db_edit)
        form.addRow("驱动程序:", self.driver_combo)
        form.addRow("", self.trusted_check)

        self.user_label = QLabel("用户名:")
        self.pass_label = QLabel("密码:")
        form.addRow(self.user_label, self.user_edit)
        form.addRow(self.pass_label, self.pass_edit)

        layout.addWidget(grp)

        # 提示文本
        hint = QLabel(
            "<small><i>提示：Windows 身份验证无需填写用户名密码，使用当前系统账号登录数据库。</i></small>"
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)

        # 按钮区
        btn_row = QHBoxLayout()
        self.test_btn = QPushButton("测试连接")
        self.test_btn.clicked.connect(self._test)

        save_btn = QPushButton("保存并关闭")
        save_btn.setDefault(True)
        save_btn.clicked.connect(self._save)

        cancel_btn = QPushButton("取消")
        cancel_btn.clicked.connect(self.reject)

        btn_row.addWidget(self.test_btn)
        btn_row.addStretch()
        btn_row.addWidget(save_btn)
        btn_row.addWidget(cancel_btn)
        layout.addLayout(btn_row)

    def _toggle_auth(self, state):
        trusted = (state == Qt.Checked)
        for w in (self.user_edit, self.pass_edit,
                  self.user_label, self.pass_label):
            w.setEnabled(not trusted)

    def _load_current(self):
        cfg = self.db_manager.get_db_config()
        self.server_edit.setText(cfg.get('server', ''))
        self.port_edit.setText(cfg.get('port', '1433'))
        self.db_edit.setText(cfg.get('database', ''))

        driver = cfg.get('driver', '')
        idx = self.driver_combo.findText(driver)
        if idx >= 0:
            self.driver_combo.setCurrentIndex(idx)
        elif driver:
            self.driver_combo.setCurrentText(driver)

        trusted = cfg.get('trusted_connection', 'no').lower() in ('yes', '1', 'true')
        self.trusted_check.setChecked(trusted)
        self.user_edit.setText(cfg.get('username', ''))
        self.pass_edit.setText(cfg.get('password', ''))
        self._toggle_auth(Qt.Checked if trusted else Qt.Unchecked)

    def _build_config_dict(self):
        return {
            'server':             self.server_edit.text().strip(),
            'port':               self.port_edit.text().strip() or '1433',
            'database':           self.db_edit.text().strip(),
            'driver':             self.driver_combo.currentText().strip(),
            'trusted_connection': 'yes' if self.trusted_check.isChecked() else 'no',
            'username':           self.user_edit.text().strip(),
            'password':           self.pass_edit.text(),
        }

    def _test(self):
        cfg = self._build_config_dict()
        self.db_manager.set_db_config(cfg)

        self.test_btn.setEnabled(False)
        self.test_btn.setText("连接中...")
        QApplication.processEvents()

        success, msg = self.db_manager.test_connection()

        self.test_btn.setEnabled(True)
        self.test_btn.setText("测试连接")

        if success:
            QMessageBox.information(self, "连接测试", "连接成功！")
        else:
            QMessageBox.warning(self, "连接测试",
                                "连接失败：\n\n{}".format(msg))

    def _save(self):
        cfg = self._build_config_dict()
        if not cfg['server']:
            QMessageBox.warning(self, "提示", "请填写服务器地址")
            return
        if not cfg['database']:
            QMessageBox.warning(self, "提示", "请填写数据库名称")
            return
        self.db_manager.set_db_config(cfg)
        self.accept()
