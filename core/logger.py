# -*- coding: utf-8 -*-
"""
DBQuery 统一日志管理模块。

特性：
1. 日志存放于独立 logs/ 目录；
2. 桌面客户端（desktop）与 Web 服务端（web）日志完全隔离；
3. 按天自动轮转（格式：desktop_YYYY-MM-DD.log / web_YYYY-MM-DD.log）；
4. 专为 Windows 24/7 长期运行优化：直接基于日期动态打开输出流，零重命名操作，
   彻底杜绝 Windows 平台 TimedRotatingFileHandler 常见的文件被占用锁死崩溃 (WinError 32)；
5. 自动保留最近 30 天日志并定期清理过期文件；
6. 线程安全。
"""
import datetime
import logging
import os
import re
import sys
import threading

from core.paths import get_logs_dir


class DailyRotatingFileHandler(logging.Handler):
    """
    按自然日无缝切换的日志处理器（Windows 防锁优化版）。
    无需在零点执行脆弱的 os.rename，跨天时自动平滑开启新日期文件。
    """

    def __init__(self, log_dir, app_type='app', retention_days=30, encoding='utf-8'):
        super(DailyRotatingFileHandler, self).__init__()
        self.log_dir = os.path.abspath(log_dir)
        self.app_type = app_type.strip().lower()
        self.retention_days = max(1, int(retention_days))
        self.encoding = encoding
        self._current_date = datetime.date.today().strftime('%Y-%m-%d')
        self._stream = None
        self._lock = threading.RLock()

        os.makedirs(self.log_dir, exist_ok=True)
        self._open_current_stream()
        self._clean_old_logs()

    def _get_filename_for_date(self, date_str):
        return os.path.join(self.log_dir, f"{self.app_type}_{date_str}.log")

    def _open_current_stream(self):
        filename = self._get_filename_for_date(self._current_date)
        try:
            self._stream = open(filename, 'a', encoding=self.encoding, errors='replace')
        except Exception:
            self._stream = None

    def emit(self, record):
        with self._lock:
            try:
                today_str = datetime.date.today().strftime('%Y-%m-%d')
                if today_str != self._current_date:
                    # 跨天切换
                    if self._stream and not self._stream.closed:
                        try:
                            self._stream.flush()
                            self._stream.close()
                        except Exception:
                            pass
                    self._current_date = today_str
                    self._open_current_stream()
                    self._clean_old_logs()

                if self._stream is None or self._stream.closed:
                    self._open_current_stream()

                if self._stream and not self._stream.closed:
                    msg = self.format(record) + '\n'
                    self._stream.write(msg)
                    self._stream.flush()
            except Exception:
                self.handleError(record)

    def _clean_old_logs(self):
        """扫描日志目录并安全清理超出保留期限的历史文件"""
        try:
            pattern = re.compile(rf'^{re.escape(self.app_type)}_(\d{{4}}-\d{{2}}-\d{{2}})\.log$', re.IGNORECASE)
            today = datetime.date.today()
            cutoff = today - datetime.timedelta(days=self.retention_days)

            if not os.path.isdir(self.log_dir):
                return

            for fname in os.listdir(self.log_dir):
                m = pattern.match(fname)
                if not m:
                    continue
                try:
                    file_date = datetime.datetime.strptime(m.group(1), '%Y-%m-%d').date()
                    if file_date < cutoff:
                        old_path = os.path.join(self.log_dir, fname)
                        os.remove(old_path)
                except Exception:
                    pass
        except Exception:
            pass

    def close(self):
        with self._lock:
            if self._stream and not self._stream.closed:
                try:
                    self._stream.flush()
                    self._stream.close()
                except Exception:
                    pass
                self._stream = None
            super(DailyRotatingFileHandler, self).close()


def setup_logging(app_type='desktop', level=None, log_dir=None, console=True):
    """
    配置全局日志体系：
    :param app_type: 'desktop' 或 'web'
    :param level: 日志级别（默认 desktop 为 DEBUG，web 为 INFO）
    :param log_dir: 日志存放目录（缺省自动解析并创建 logs/）
    :param console: 是否同步输出到控制台 stdout
    :return: 对应的根 logger 实例
    """
    app_type = (app_type or 'desktop').lower()
    if level is None:
        level = logging.DEBUG if app_type == 'desktop' else logging.INFO

    if not log_dir:
        log_dir = get_logs_dir()
    else:
        os.makedirs(log_dir, exist_ok=True)

    fmt = '%(asctime)s [%(levelname)s] [%(name)s] %(message)s'
    datefmt = '%Y-%m-%d %H:%M:%S'
    formatter = logging.Formatter(fmt, datefmt=datefmt)

    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    # 移除现有已绑定的旧 Handler（避免热重载或重复调用产生多份重复日志）
    for h in list(root_logger.handlers):
        try:
            h.close()
        except Exception:
            pass
        root_logger.removeHandler(h)

    # 1. 每日文件处理器
    file_handler = DailyRotatingFileHandler(
        log_dir=log_dir,
        app_type=app_type,
        retention_days=30,
        encoding='utf-8'
    )
    file_handler.setLevel(level)
    file_handler.setFormatter(formatter)
    root_logger.addHandler(file_handler)

    # 2. 控制台输出处理器
    if console:
        stream_handler = logging.StreamHandler(sys.stdout)
        stream_handler.setLevel(level)
        stream_handler.setFormatter(formatter)
        root_logger.addHandler(stream_handler)

    logger = logging.getLogger(f"DBQuery.{app_type}")
    logger.info("=== DBQuery %s logging initialized (logs_dir=%s, level=%s) ===",
                app_type.upper(), log_dir, logging.getLevelName(level))
    return logger
