"""
数据库连接管理模块。

支持 SQL Server，通过 pyodbc 连接。Web 请求使用短生命周期连接，避免共享
连接和全局锁导致的串行阻塞；桌面端仍可使用 execute_query 兼容接口。
"""
import configparser
import logging
import os
import secrets
import sys

import pyodbc

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
    'username': '',
    'password': ''
}

DEFAULT_WEB_CONFIG = {
    'query_timeout': 60,
    'max_rows': 5000,
}

DEFAULT_INTEGRATION_CONFIG = {
    'enabled': 'no',
    'shared_key': '',
    'ticket_ttl_seconds': '60',
    'max_clock_skew_seconds': '60',
}

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


class QueryTimeoutError(RuntimeError):
    """数据库驱动报告查询超时时抛出。"""


class DBManager:
    """数据库配置与短生命周期查询连接管理器。"""

    def __init__(self):
        # 保留该属性以兼容旧版调用方；Web 查询不再复用它。
        self.connection = None
        self.config = configparser.ConfigParser()
        self.load_config()

    @staticmethod
    def _positive_int(value, default, maximum=None):
        """读取正整数配置，异常、空值或越界时回退默认值。"""
        try:
            parsed = int(str(value).strip())
        except (TypeError, ValueError):
            return default
        if parsed <= 0:
            return default
        if maximum is not None:
            return min(parsed, maximum)
        return parsed

    def load_config(self):
        self.config = configparser.ConfigParser()
        if os.path.exists(CONFIG_PATH):
            self.config.read(CONFIG_PATH, encoding='utf-8')
        if 'database' not in self.config:
            defaults = DEFAULT_DB_CONFIG.copy()
            defaults['driver'] = DBManager.get_best_driver()
            self.config['database'] = defaults
            self.save_config()
        elif not self.config['database'].get('driver', '').strip():
            self.config['database']['driver'] = DBManager.get_best_driver()
            self.save_config()

    def save_config(self):
        with open(CONFIG_PATH, 'w', encoding='utf-8') as config_file:
            self.config.write(config_file)

    def get_db_config(self):
        return dict(self.config['database'])

    def get_web_config(self):
        """返回 Web 查询配置；旧配置文件缺少 [web] 时使用安全默认值。"""
        section = self.config['web'] if self.config.has_section('web') else {}
        return {
            'query_timeout': self._positive_int(
                section.get('query_timeout'), DEFAULT_WEB_CONFIG['query_timeout'], maximum=3600
            ),
            'max_rows': self._positive_int(
                section.get('max_rows'), DEFAULT_WEB_CONFIG['max_rows'], maximum=100000
            ),
        }

    def get_integration_config(self):
        """返回宿主无感登录配置；缺省时功能关闭。"""
        section = self.config['integration'] if self.config.has_section('integration') else {}
        return {
            'enabled': str(section.get('enabled', 'no')).lower() in ('yes', '1', 'true', 'on'),
            'shared_key': section.get('shared_key', '').strip(),
            'ticket_ttl_seconds': self._positive_int(
                section.get('ticket_ttl_seconds'),
                int(DEFAULT_INTEGRATION_CONFIG['ticket_ttl_seconds']), maximum=300
            ),
            'max_clock_skew_seconds': self._positive_int(
                section.get('max_clock_skew_seconds'),
                int(DEFAULT_INTEGRATION_CONFIG['max_clock_skew_seconds']), maximum=300
            ),
        }

    @staticmethod
    def generate_integration_key():
        """生成可配置到宿主后端与 DBQuery 两端的高熵共享密钥。"""
        return secrets.token_urlsafe(48)

    def set_integration_config(self, cfg_dict):
        section = DEFAULT_INTEGRATION_CONFIG.copy()
        section.update({
            'enabled': 'yes' if cfg_dict.get('enabled') else 'no',
            'shared_key': str(cfg_dict.get('shared_key', '')).strip(),
            'ticket_ttl_seconds': str(self._positive_int(
                cfg_dict.get('ticket_ttl_seconds'),
                int(DEFAULT_INTEGRATION_CONFIG['ticket_ttl_seconds']), maximum=300
            )),
            'max_clock_skew_seconds': str(self._positive_int(
                cfg_dict.get('max_clock_skew_seconds'),
                int(DEFAULT_INTEGRATION_CONFIG['max_clock_skew_seconds']), maximum=300
            )),
        })
        self.config['integration'] = section
        self.save_config()

    def set_db_config(self, cfg_dict):
        self.config['database'] = cfg_dict
        self.save_config()
        self.connection = None

    def _build_conn_str(self):
        db = self.config['database']
        driver = db.get('driver', '') or DBManager.get_best_driver()
        server = db.get('server', 'localhost')
        port = db.get('port', '1433').strip()
        database = db.get('database', 'master')
        trusted = db.get('trusted_connection', 'no').lower() in ('yes', '1', 'true')
        server_str = '{},{}'.format(server, port) if port and port != '1433' else server
        if trusted:
            return (
                'DRIVER={{{}}};SERVER={};DATABASE={};Trusted_Connection=yes;'
                .format(driver, server_str, database)
            )
        username = db.get('username', '')
        password = db.get('password', '')
        return (
            'DRIVER={{{}}};SERVER={};DATABASE={};UID={};PWD={};'
            .format(driver, server_str, database, username, password)
        )

    def _open_connection(self, connect_timeout=15):
        """创建一条独立连接；调用者必须负责关闭。"""
        return pyodbc.connect(
            self._build_conn_str(),
            timeout=self._positive_int(connect_timeout, 15, maximum=120)
        )

    def test_connection(self):
        try:
            conn = self._open_connection(connect_timeout=10)
            conn.close()
            return True, '连接成功'
        except Exception as exc:
            return False, str(exc)

    def authenticate_user(self, username, password):
        """使用 qx_czyxx 的启用账号验证登录凭据。

        认证查询始终使用参数绑定，避免将账号或密码拼接到 SQL 中；调用方仅获得
        True/False，不会得到数据库驱动、账号状态或密码字段的细节。
        """
        username = str(username or '').strip()
        password = str(password or '')
        if not username or not password:
            return False

        conn = None
        cursor = None
        try:
            conn = self._open_connection(connect_timeout=10)
            conn.timeout = 10
            cursor = conn.cursor()
            cursor.execute(
                "SELECT TOP 1 1 FROM qx_czyxx "
                "WHERE czybm = ? AND [pass] = ? AND czyzt = ? AND deleted = ?",
                username, password, u'启用', '0'
            )
            return cursor.fetchone() is not None
        except Exception:
            # 不记录底层驱动异常，避免认证日志意外包含连接或凭据细节。
            logger.warning('User authentication failed because the credential service is unavailable')
            return False
        finally:
            self._close_quietly(cursor)
            self._close_quietly(conn)

    @staticmethod
    def _is_timeout_error(exc):
        text = str(exc).lower()
        return 'timeout' in text or 'hyt00' in text or 'hyt01' in text

    @staticmethod
    def _is_transient_connection_error(exc):
        """仅识别可安全重连后重试的 SQL Server 连接/网络错误。"""
        sqlstates = []
        for arg in getattr(exc, 'args', ()):
            if isinstance(arg, tuple) and arg:
                sqlstates.append(str(arg[0]).upper())
            elif isinstance(arg, str):
                sqlstates.append(arg[:5].upper())
        if any(state.startswith('08') for state in sqlstates):
            return True

        text = str(exc).lower()
        transient_markers = (
            'communication link failure',
            'connection reset',
            'connection was forcibly closed',
            'network-related',
            'network error',
            'transport-level error',
        )
        return any(marker in text for marker in transient_markers)

    @staticmethod
    def _close_quietly(resource):
        if resource is None:
            return
        try:
            resource.close()
        except Exception:
            pass

    def _run_limited_query(self, conn, sql, max_rows):
        cursor = None
        try:
            cursor = conn.cursor()
            logger.debug('Executing SQL: %s', sql[:200] if sql else 'EMPTY')
            cursor.execute(sql)
            if cursor.description is None:
                return [], [], False

            columns = [desc[0] for desc in cursor.description]
            fetched = cursor.fetchmany(max_rows + 1)
            truncated = len(fetched) > max_rows
            rows = [list(row) for row in fetched[:max_rows]]
            logger.info(
                'Query success: %d columns, %d rows%s',
                len(columns), len(rows), ' (truncated)' if truncated else ''
            )
            return columns, rows, truncated
        finally:
            self._close_quietly(cursor)

    def execute_query_limited(self, sql, query_timeout=None, max_rows=None, query_type='select'):
        """执行受 Web 限制保护的查询，最多读取 max_rows + 1 行。

        ``pyodbc.connect(timeout=...)`` 只用于登录/连接超时；实际 SQL 执行超时必须在
        创建 cursor 前设置 ``Connection.timeout``。SELECT 仅在明确的连接/网络瞬态错误
        上使用新连接重试一次；EXEC 和查询超时均不自动重试，避免重复执行副作用。
        """
        web_config = self.get_web_config()
        query_timeout = self._positive_int(
            query_timeout, web_config['query_timeout'], maximum=3600
        )
        max_rows = self._positive_int(max_rows, web_config['max_rows'], maximum=100000)
        normalized_type = (query_type or 'select').lower().strip()
        allow_retry = normalized_type == 'select'

        for attempt in range(2):
            conn = None
            try:
                conn = self._open_connection()
                # pyodbc 4.x 的真实查询超时属性属于 Connection，而非 Cursor。
                # 必须在创建 cursor 之前赋值，连接/login timeout 仍由 _open_connection 区分处理。
                conn.timeout = query_timeout
                return self._run_limited_query(conn, sql, max_rows)
            except pyodbc.Error as exc:
                if self._is_timeout_error(exc):
                    logger.warning('Query timed out after %ss: %s', query_timeout, exc)
                    raise QueryTimeoutError('查询超时') from exc
                if allow_retry and attempt == 0 and self._is_transient_connection_error(exc):
                    logger.warning('Transient SELECT connection error; retrying once: %s', exc)
                    continue
                logger.warning(
                    'pyodbc error on %s query attempt %d/2; retry disabled or unsafe: %s',
                    normalized_type, attempt + 1, exc
                )
                raise
            finally:
                self._close_quietly(conn)

        raise RuntimeError('查询执行失败')

    def _run_unlimited_query(self, conn, sql):
        """保留桌面端原有的完整结果读取行为。"""
        cursor = None
        try:
            cursor = conn.cursor()
            logger.debug('Executing desktop SQL: %s', sql[:200] if sql else 'EMPTY')
            cursor.execute(sql)
            if cursor.description is None:
                return [], []
            columns = [desc[0] for desc in cursor.description]
            rows = [list(row) for row in cursor.fetchall()]
            logger.info('Desktop query success: %d columns, %d rows', len(columns), len(rows))
            return columns, rows
        finally:
            self._close_quietly(cursor)

    def execute_query(self, sql, query_type='select'):
        """桌面兼容接口，不套用 Web 行数上限。

        与 Web 的安全原则保持一致：仅 SELECT 在明确的瞬态连接错误时使用新连接
        重试一次；EXEC 和 timeout 绝不自动重试，避免潜在的重复副作用。
        """
        normalized_type = (query_type or 'select').lower().strip()
        allow_retry = normalized_type == 'select'
        last_error = None
        for attempt in range(2):
            conn = None
            try:
                conn = self._open_connection()
                return self._run_unlimited_query(conn, sql)
            except pyodbc.Error as exc:
                last_error = exc
                if self._is_timeout_error(exc):
                    logger.warning('Desktop query timed out; retry disabled: %s', exc)
                    raise QueryTimeoutError('查询超时') from exc
                if allow_retry and attempt == 0 and self._is_transient_connection_error(exc):
                    logger.warning('Transient desktop SELECT connection error; retrying once: %s', exc)
                    continue
                logger.warning(
                    'pyodbc error on desktop %s query attempt %d/2; retry disabled or unsafe: %s',
                    normalized_type, attempt + 1, exc
                )
                raise
            finally:
                self._close_quietly(conn)
        if last_error:
            raise last_error
        raise RuntimeError('查询执行失败')

    @staticmethod
    def list_drivers():
        try:
            all_drivers = pyodbc.drivers()
            sql_drivers = [
                driver for driver in all_drivers
                if 'SQL Server' in driver or 'sqlserver' in driver.lower()
            ]

            def priority(driver):
                try:
                    return _DRIVER_PRIORITY.index(driver)
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
