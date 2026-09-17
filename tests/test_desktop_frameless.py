# -*- coding: utf-8 -*-
import unittest
import sys
import os

from PyQt5.QtWidgets import QApplication
from PyQt5.QtCore import Qt

import main

class TestDesktopFramelessWindow(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance()
        if not cls.app:
            cls.app = QApplication(sys.argv)

    def test_window_is_frameless_and_has_branding_and_controls(self):
        win = main.MainWindow()
        try:
            # 1. 验证无边框标志
            flags = win.windowFlags()
            self.assertTrue(bool(flags & Qt.FramelessWindowHint), "MainWindow should have FramelessWindowHint")

            # 2. 验证品牌区域（Logo 与标题，无 emoji 📊）
            self.assertTrue(hasattr(win, 'brand_widget'))
            self.assertTrue(hasattr(win, 'logo_lbl'))
            self.assertTrue(hasattr(win, 'app_title_lbl'))
            self.assertIn("数据库查询工具", win.app_title_lbl.text())

            # 3. 验证 setWindowTitle 同步更新工具栏标题
            win.setWindowTitle(u"数据库查询工具 - 9999")
            self.assertEqual(win.app_title_lbl.text(), u"数据库查询工具 - 9999")

            # 4. 验证窗口控制按钮
            self.assertTrue(hasattr(win, 'btn_min'))
            self.assertTrue(hasattr(win, 'btn_max'))
            self.assertTrue(hasattr(win, 'btn_close'))
            self.assertEqual(win.btn_min.text(), u"—")
            self.assertEqual(win.btn_max.text(), u"⬜")
            self.assertEqual(win.btn_close.text(), u"✕")

            # 5. 验证最大化状态切换更新按钮提示与文本
            win._toggle_maximize()
            self.assertEqual(win.btn_max.text(), u"🗗" if win.isMaximized() else u"⬜")
            win._toggle_maximize()
        finally:
            win.close()


if __name__ == '__main__':
    unittest.main()
