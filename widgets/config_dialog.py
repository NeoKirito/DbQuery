# -*- coding: utf-8 -*-
"""
数据库连接配置对话框
"""
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QGroupBox,
    QLineEdit, QComboBox, QCheckBox, QPushButton, QLabel, QMessageBox,
    QApplication, QInputDialog
)
from PyQt5.QtCore import Qt
from urllib.parse import urlparse


class ConfigDialog(QDialog):
    def __init__(self, db_manager, parent=None):
        super(ConfigDialog, self).__init__(parent)
        self.db_manager = db_manager
        self.setWindowTitle("数据库连接配置")
        self.setMinimumWidth(500)
        self.setModal(True)
        self._current_ds = 'default'
        self._datasources = {}
        self._deleted_ds = set()
        self._is_switching_ds = False
        self._setup_ui()
        self._load_current()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        # 数据源选择行
        ds_row = QHBoxLayout()
        ds_row.addWidget(QLabel("数据源:"))
        self.ds_combo = QComboBox()
        self.ds_combo.setMinimumWidth(180)
        self.ds_combo.currentIndexChanged.connect(self._on_datasource_changed)

        self.add_ds_btn = QPushButton("新建...")
        self.add_ds_btn.clicked.connect(self._add_datasource)

        self.del_ds_btn = QPushButton("删除")
        self.del_ds_btn.clicked.connect(self._delete_datasource)

        ds_row.addWidget(self.ds_combo)
        ds_row.addWidget(self.add_ds_btn)
        ds_row.addWidget(self.del_ds_btn)
        ds_row.addStretch()
        layout.addLayout(ds_row)

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

        integration_grp = QGroupBox("前端无感登录")
        integration_form = QFormLayout(integration_grp)
        integration_form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.frontend_embed_enabled_check = QCheckBox("启用前端无感登录")
        self.frontend_address_edit = QLineEdit()
        self.frontend_address_edit.setPlaceholderText("如: 192.168.0.39:8080")
        embed_hint = QLabel(
            "<small><i>填写业务前端的 IP 和端口即可，保存后会自动补全 HTTP 协议，并同步所有"
            "前端授权配置。不要填写页面路径或 # 后面的路由；HTTPS 地址请填写完整协议。"
            "</i></small>"
        )
        embed_hint.setWordWrap(True)
        integration_form.addRow("", self.frontend_embed_enabled_check)
        integration_form.addRow("前端 IP:端口:", self.frontend_address_edit)
        integration_form.addRow("", embed_hint)

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

    def _load_current(self):
        if hasattr(self.db_manager, 'get_datasources'):
            raw_datasources = self.db_manager.get_datasources()
            self._datasources = {k: dict(v) for k, v in raw_datasources.items()}
        else:
            self._datasources = {'default': dict(self.db_manager.get_db_config())}

        if 'default' not in self._datasources:
            self._datasources['default'] = dict(self.db_manager.get_db_config())

        self._populate_ds_combo('default')
        self._load_datasource_into_form('default')

        self._integration_cfg = self.db_manager.get_integration_config()
        self.frontend_embed_enabled_check.setChecked(
            bool(self._integration_cfg.get('frontend_embed_enabled'))
        )
        origins = (
            self._integration_cfg.get('frontend_embed_allowed_origins', []) or
            self._integration_cfg.get('frontend_allowed_origins', []) or
            self._integration_cfg.get('frame_ancestors', [])
        )
        if self._integration_cfg.get('frontend_embed_allow_all') or self._integration_cfg.get('frame_ancestors_allow_all'):
            self.frontend_address_edit.setText('*')
        else:
            self.frontend_address_edit.setText(
                self._display_frontend_address(origins[0]) if origins else ''
            )

    def _populate_ds_combo(self, select_id='default'):
        self._is_switching_ds = True
        self.ds_combo.clear()
        self.ds_combo.addItem("默认主库 (default)", "default")
        for ds_id in sorted(self._datasources.keys()):
            if ds_id == 'default':
                continue
            name = self._datasources[ds_id].get('name') or ds_id
            label = "{} [{}]".format(name, ds_id) if name != ds_id else ds_id
            self.ds_combo.addItem(label, ds_id)

        target_index = 0
        for i in range(self.ds_combo.count()):
            if self.ds_combo.itemData(i) == select_id:
                target_index = i
                break
        self.ds_combo.setCurrentIndex(target_index)
        self._is_switching_ds = False

    def _on_datasource_changed(self, index):
        if self._is_switching_ds or index < 0:
            return
        new_ds = self.ds_combo.itemData(index)
        if not new_ds or new_ds == self._current_ds:
            return
        # 保存当前正在编辑的数据源表单内容
        self._datasources[self._current_ds] = self._build_config_dict()
        self._current_ds = new_ds
        self._load_datasource_into_form(new_ds)

    def _load_datasource_into_form(self, ds_id):
        cfg = self._datasources.get(ds_id, {})
        self.server_edit.setText(cfg.get('server', ''))
        self.port_edit.setText(str(cfg.get('port', '1433') or '1433'))
        self.db_edit.setText(cfg.get('database', ''))

        driver = cfg.get('driver', '')
        idx = self.driver_combo.findText(driver)
        if idx >= 0:
            self.driver_combo.setCurrentIndex(idx)
        elif driver:
            self.driver_combo.setCurrentText(driver)

        trusted = str(cfg.get('trusted_connection', 'no')).lower() in ('yes', '1', 'true')
        self.trusted_check.setChecked(trusted)
        self.user_edit.setText(cfg.get('username', ''))
        self.pass_edit.setText(cfg.get('password', ''))
        self._toggle_auth(Qt.Checked if trusted else Qt.Unchecked)

        self.del_ds_btn.setEnabled(ds_id != 'default')

    def _add_datasource(self):
        name, ok = QInputDialog.getText(
            self, "新建数据源", "请输入新数据源标识（英文字母、数字或下划线，例如 lis, his）："
        )
        if not ok or not name:
            return
        ds_id = str(name).strip().lower()
        if not ds_id or ds_id in ('default', 'main', 'database'):
            QMessageBox.warning(self, "提示", "数据源标识无效或已被保留。")
            return
        if ds_id in self._datasources and ds_id not in self._deleted_ds:
            QMessageBox.warning(self, "提示", "数据源 '{}' 已存在。".format(ds_id))
            return
        if ds_id in self._deleted_ds:
            self._deleted_ds.remove(ds_id)

        # 保存当前数据源表单
        self._datasources[self._current_ds] = self._build_config_dict()
        # 初始化新数据源
        self._datasources[ds_id] = {
            'id': ds_id,
            'name': ds_id,
            'server': '',
            'port': '1433',
            'database': '',
            'driver': self.driver_combo.currentText().strip(),
            'trusted_connection': 'no',
            'username': '',
            'password': '',
        }
        self._current_ds = ds_id
        self._populate_ds_combo(select_id=ds_id)
        self._load_datasource_into_form(ds_id)

    def _delete_datasource(self):
        if self._current_ds == 'default':
            return
        ret = QMessageBox.question(
            self, "确认删除",
            "确定要删除数据源 '{}' 吗？".format(self._current_ds),
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )
        if ret != QMessageBox.Yes:
            return
        del_target = self._current_ds
        self._deleted_ds.add(del_target)
        if del_target in self._datasources:
            del self._datasources[del_target]
        self._current_ds = 'default'
        self._populate_ds_combo(select_id='default')
        self._load_datasource_into_form('default')

    @staticmethod
    def _display_frontend_address(origin):
        """HTTP 地址只显示主机和端口，HTTPS 保留协议以免保存时降级。"""
        parsed = urlparse(str(origin or '').strip())
        if parsed.scheme.lower() == 'http' and parsed.netloc:
            return parsed.netloc
        return str(origin or '').strip()

    @staticmethod
    def _frontend_origin(address):
        """把单个“IP/主机:端口”或“*”规范化为可保存的 Origin。"""
        from db_manager import DBManager

        value = str(address or '').strip()
        if value == '*':
            return '*'
        if not value or any(separator in value for separator in (',', ';', '\n')):
            return ''
        candidate = value if '://' in value else 'http://' + value
        origins = DBManager._parse_allowed_origins(candidate)
        if len(origins) != 1:
            return ''
        try:
            parsed = urlparse(origins[0])
            if parsed.port is None:
                return ''
        except ValueError:
            return ''
        return origins[0]

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
        # 旧集成字段不再占用界面，但原值仍会保留，避免升级后破坏已有接入。
        integration_cfg = dict(self._integration_cfg)
        origin = self._frontend_origin(self.frontend_address_edit.text())
        integration_cfg.update({
            'frontend_embed_enabled': self.frontend_embed_enabled_check.isChecked(),
            # 单个前端地址同步给旧前端接口、Embed CORS 和 iframe CSP。
            'frontend_allowed_origins': origin,
            'frontend_embed_allowed_origins': origin,
            'frame_ancestors': origin,
        })
        return integration_cfg

    def _test(self):
        cfg = self._build_config_dict()
        self._datasources[self._current_ds] = cfg
        if self._current_ds == 'default':
            self.db_manager.set_db_config(cfg)
        else:
            if hasattr(self.db_manager, 'set_datasource_config'):
                self.db_manager.set_datasource_config(self._current_ds, cfg)

        self.test_btn.setEnabled(False)
        self.test_btn.setText("连接中...")
        QApplication.processEvents()

        try:
            if hasattr(self.db_manager, 'test_connection'):
                try:
                    success, msg = self.db_manager.test_connection(datasource=self._current_ds)
                except TypeError:
                    success, msg = self.db_manager.test_connection()
            else:
                success, msg = True, 'OK'
        except Exception as exc:
            success, msg = False, str(exc)
        finally:
            self.test_btn.setEnabled(True)
            self.test_btn.setText("测试连接")

        ds_desc = "默认主库" if self._current_ds == 'default' else "数据源 '{}'".format(self._current_ds)
        if success:
            QMessageBox.information(self, "连接测试", "{}连接成功！".format(ds_desc))
        else:
            QMessageBox.warning(self, "连接测试",
                                "{}连接失败：\n\n{}".format(ds_desc, msg))

    def _save(self):
        self._datasources[self._current_ds] = self._build_config_dict()
        default_cfg = self._datasources.get('default', {})
        if not default_cfg.get('server'):
            QMessageBox.warning(self, "提示", "请填写默认主库的服务器地址")
            return
        if not default_cfg.get('database'):
            QMessageBox.warning(self, "提示", "请填写默认主库的数据库名称")
            return
        integration_cfg = self._build_integration_config()
        if integration_cfg.get('frontend_embed_enabled'):
            if not integration_cfg.get('frontend_embed_allowed_origins'):
                QMessageBox.warning(
                    self, "提示",
                    "请填写有效的前端 IP 和端口，例如 192.168.0.39:8080 或 *"
                )
                return

        # 保存默认主库
        self.db_manager.set_db_config(default_cfg)

        # 保存命名数据源
        if hasattr(self.db_manager, 'set_datasource_config'):
            for ds_id, cfg in self._datasources.items():
                if ds_id == 'default':
                    continue
                self.db_manager.set_datasource_config(ds_id, cfg)

        # 删除已标记移除的数据源
        if hasattr(self.db_manager, 'remove_datasource'):
            for ds_id in self._deleted_ds:
                self.db_manager.remove_datasource(ds_id)

        self.db_manager.set_integration_config(integration_cfg)
        self.accept()
