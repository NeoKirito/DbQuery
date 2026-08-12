# -*- coding: utf-8 -*-
"""
数据库连接管理模块
支持 SQL Server，通过 pyodbc 连接
Win7 兼容：自动探测最优 ODBC 驱动
"""
import pyodbc
import configparser
import os
import sys
import logging
import traceback

logger = logging.getLogger('DBQuery.db_manager')

if getattr(sys, 'frozen', False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

CONFIG_PATH = os.path.join(BASE_DIR, 'config.ini')

DEFAULT_DB_CONFIG = {
    'server': 'localhost',
    'port': '1433',
    'database': 'master',
    'driver': '',
    'trusted_connection': 'no',
    'username': 'sa',
    'password': ''
}

# 驱动优先级（高版本优先，Win7/Win10/Win11 均覆盖）
_DRIVER_PRIORITY = [
    'ODBC Driver 18 for SQL Server',
    'ODBC Driver 17 for SQL Server',
    'ODBC Driver 13.1 for SQL Server',
    'ODBC Driver 13 for SQL Server',
    'ODBC Driver 11 for SQL Server',
    'SQL Server Native Client 11.0',
    'SQL Server Native Client 10.0',
    'SQL Server',
]


class DBManager:
    def __init__(self):
        self.connection = None
        self.config = configparser.ConfigParser()
        self.load_config()

    def load_config(self):
        self.config = configparser.ConfigParser()
        if os.path.exists(CONFIG_PATH):
            self.config.read(CONFIG_PATH, encoding='utf-8')
        if 'database' not in self.config:
            defaults = DEFAULT_DB_CONFIG.copy()
            defaults['driver'] = DBManager.get_best_driver()
            self.config['database'] = defaults
            self.save_config()
        else:
            if not self.config['database'].get('driver', '').strip():
                self.config['database']['driver'] = DBManager.get_best_driver()
                self.save_config()

    def save_config(self):
        with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
            self.config.write(f)

    def get_db_config(self):
        return dict(self.config['database'])

    def set_db_config(self, cfg_dict):
        self.config['database'] = cfg_dict
        self.save_config()
        self.connection = None

    def _build_conn_str(self):
        db = self.config['database']
        driver   = db.get('driver', '') or DBManager.get_best_driver()
        server   = db.get('server', 'localhost')
        port     = db.get('port', '1433').strip()
        database = db.get('database', 'master')
        trusted  = db.get('trusted_connection', 'no').lower() in ('yes', '1', 'true')
        server_str = '{},{}'.format(server, port) if port and port != '1433' else server
        if trusted:
            return ("DRIVER={{{}}};SERVER={};DATABASE={};Trusted_Connection=yes;"
                    .format(driver, server_str, database))
        else:
            username = db.get('username', '')
            password = db.get('password', '')
            return ("DRIVER={{{}}};SERVER={};DATABASE={};UID={};PWD={};"
                    .format(driver, server_str, database, username, password))

    def test_connection(self):
        try:
            conn_str = self._build_conn_str()
            conn = pyodbc.connect(conn_str, timeout=10)
            conn.close()
            return True, u"连接成功"
        except Exception as e:
            return False, str(e)

    def _ensure_connection(self):
        if self.connection is None:
            conn_str = self._build_conn_str()
            self.connection = pyodbc.connect(conn_str, timeout=15)

    def validate_connection(self):
        """检查已有连接是否仍然可用"""
        if self.connection is None:
            return False
        try:
            cursor = self.connection.cursor()
            cursor.execute("SELECT 1")
            cursor.fetchone()
            cursor.close()
            return True
        except Exception:
            self.connection = None
            return False

    def _run_query(self, sql):
        cursor = self.connection.cursor()
        logger.debug("Executing SQL: %s", sql[:200] if sql else "EMPTY")
        cursor.execute(sql)
        if cursor.description is None:
            return [], []
        columns = [desc[0] for desc in cursor.description]
        rows = [list(row) for row in cursor.fetchall()]
        logger.info("Query success: %d columns, %d rows", len(columns), len(rows))
        return columns, rows

    def execute_query(self, sql):
        logger.info("execute_query called")
        try:
            if not self.validate_connection():
                self._ensure_connection()
            return self._run_query(sql)
        except pyodbc.Error as e:
            logger.warning("pyodbc.Error (retry): %s", str(e))
            self.connection = None
            self._ensure_connection()
            return self._run_query(sql)
        except Exception as e:
            logger.error("execute_query error: %s", str(e))
            logger.error(traceback.format_exc())
            raise

    @staticmethod
    def list_drivers():
        try:
            all_drivers = pyodbc.drivers()
            sql_drivers = [d for d in all_drivers
                           if 'SQL Server' in d or 'sqlserver' in d.lower()]
            def priority(d):
                try:
                    return _DRIVER_PRIORITY.index(d)
                except ValueError:
                    return len(_DRIVER_PRIORITY)
            return sorted(sql_drivers, key=priority)
        except Exception:
            return []

    @staticmethod
    def get_best_driver():
        available = DBManager.list_drivers()
        for preferred in _DRIVER_PRIORITY:
            if preferred in available:
                return preferred
        if available:
            return available[0]
        return 'SQL Server'
