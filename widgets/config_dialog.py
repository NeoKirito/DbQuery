# -*- coding: utf-8 -*-
"""
数据库连接配置对话框
"""
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QGroupBox,
    QLineEdit, QComboBox, QCheckBox, QPushButton, QLabel, QMessageBox,
    QApplication, QSpinBox
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

        integration_grp = QGroupBox("宿主程序无感登录")
        integration_form = QFormLayout(integration_grp)
        integration_form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.integration_enabled_check = QCheckBox("启用受签名的宿主无感登录")
        self.integration_key_edit = QLineEdit()
        self.integration_key_edit.setEchoMode(QLineEdit.Password)
        self.integration_key_edit.setPlaceholderText("生成后仅配置在 DBQuery 和宿主后端；不要放入前端或 URL")
        self.integration_show_key_check = QCheckBox("显示")
        self.integration_show_key_check.toggled.connect(self._toggle_integration_key_visibility)
        generate_key_btn = QPushButton("生成新密钥")
        generate_key_btn.clicked.connect(self._generate_integration_key)
        key_row = QHBoxLayout()
        key_row.addWidget(self.integration_key_edit)
        key_row.addWidget(self.integration_show_key_check)
        key_row.addWidget(generate_key_btn)

        self.integration_ttl_spin = QSpinBox()
        self.integration_ttl_spin.setRange(10, 300)
        self.integration_ttl_spin.setSuffix(" 秒")
        self.integration_skew_spin = QSpinBox()
        self.integration_skew_spin.setRange(10, 300)
        self.integration_skew_spin.setSuffix(" 秒")
        integration_form.addRow("", self.integration_enabled_check)
        integration_form.addRow("共享密钥:", key_row)
        integration_form.addRow("票据有效期:", self.integration_ttl_spin)
        integration_form.addRow("允许时钟偏差:", self.integration_skew_spin)
        integration_hint = QLabel(
            "<small><i>宿主后端用密钥签名后请求短期票据；浏览器仅通过 iframe POST 消费票据。"
            "密钥轮换后，请同步更新宿主后端配置。</i></small>"
        )
        integration_hint.setWordWrap(True)
        integration_form.addRow("", integration_hint)
        layout.addWidget(integration_grp)

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

    def _toggle_integration_key_visibility(self, visible):
        self.integration_key_edit.setEchoMode(
            QLineEdit.Normal if visible else QLineEdit.Password
        )

    def _generate_integration_key(self):
        from db_manager import DBManager
        self.integration_key_edit.setText(DBManager.generate_integration_key())
        self.integration_key_edit.setFocus()
        self.integration_key_edit.selectAll()

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

        integration_cfg = self.db_manager.get_integration_config()
        self.integration_enabled_check.setChecked(bool(integration_cfg.get('enabled')))
        self.integration_key_edit.setText(integration_cfg.get('shared_key', ''))
        self.integration_ttl_spin.setValue(integration_cfg.get('ticket_ttl_seconds', 60))
        self.integration_skew_spin.setValue(integration_cfg.get('max_clock_skew_seconds', 60))

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

    def _build_integration_config(self):
        return {
            'enabled': self.integration_enabled_check.isChecked(),
            'shared_key': self.integration_key_edit.text().strip(),
            'ticket_ttl_seconds': self.integration_ttl_spin.value(),
            'max_clock_skew_seconds': self.integration_skew_spin.value(),
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
        integration_cfg = self._build_integration_config()
        if integration_cfg['enabled'] and len(integration_cfg['shared_key']) < 32:
            QMessageBox.warning(self, "提示", "启用宿主无感登录前，请生成并保存至少 32 个字符的共享密钥")
            return
        self.db_manager.set_db_config(cfg)
        self.db_manager.set_integration_config(integration_cfg)
        self.accept()
