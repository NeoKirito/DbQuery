# -*- coding: utf-8 -*-
"""DBQuery 日志模块单元测试。"""
import datetime
import logging
import os
import shutil
import sys
import tempfile
import unittest

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from core.logger import DailyRotatingFileHandler, setup_logging


class LoggerTest(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix='dbquery_test_logs_')

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_daily_rotating_file_handler_creates_file_and_writes(self):
        handler = DailyRotatingFileHandler(self.temp_dir, app_type='desktop', retention_days=30)
        logger = logging.getLogger('test_desktop')
        logger.setLevel(logging.INFO)
        logger.addHandler(handler)

        logger.info("Desktop test log entry 12345")
        handler.close()
        logger.removeHandler(handler)

        today_str = datetime.date.today().strftime('%Y-%m-%d')
        expected_file = os.path.join(self.temp_dir, f"desktop_{today_str}.log")
        self.assertTrue(os.path.exists(expected_file), msg=f"Log file {expected_file} should exist")

        with open(expected_file, 'r', encoding='utf-8') as f:
            content = f.read()
        self.assertIn("Desktop test log entry 12345", content)

    def test_clean_old_logs(self):
        # 预设一个 45 天前的旧日志和一个今天的日志
        old_date = (datetime.date.today() - datetime.timedelta(days=45)).strftime('%Y-%m-%d')
        old_file = os.path.join(self.temp_dir, f"web_{old_date}.log")
        with open(old_file, 'w', encoding='utf-8') as f:
            f.write("old log from 45 days ago\n")

        recent_date = (datetime.date.today() - datetime.timedelta(days=5)).strftime('%Y-%m-%d')
        recent_file = os.path.join(self.temp_dir, f"web_{recent_date}.log")
        with open(recent_file, 'w', encoding='utf-8') as f:
            f.write("recent log from 5 days ago\n")

        handler = DailyRotatingFileHandler(self.temp_dir, app_type='web', retention_days=30)
        handler.close()

        self.assertFalse(os.path.exists(old_file), "超过30天的旧日志应被自动清理")
        self.assertTrue(os.path.exists(recent_file), "未超过30天的日志应被保留")

    def test_setup_logging_separate_namespaces(self):
        desk_logger = setup_logging('desktop', log_dir=self.temp_dir, console=False)
        desk_logger.info("Message for desktop")

        web_logger = setup_logging('web', log_dir=self.temp_dir, console=False)
        web_logger.info("Message for web")

        today_str = datetime.date.today().strftime('%Y-%m-%d')
        desk_file = os.path.join(self.temp_dir, f"desktop_{today_str}.log")
        web_file = os.path.join(self.temp_dir, f"web_{today_str}.log")

        self.assertTrue(os.path.exists(desk_file))
        self.assertTrue(os.path.exists(web_file))


if __name__ == '__main__':
    unittest.main()
