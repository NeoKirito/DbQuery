# -*- coding: utf-8 -*-
"""
PyInstaller 运行时钩子 — Win7 兼容
在程序启动最早阶段执行，确保同目录下的 DLL 优先被加载。
解决 Win7 上 api-ms-win-*.dll / ucrtbase.dll 找不到的问题。
"""
import os
import sys

# 将 EXE 所在目录加入 DLL 搜索路径（Win7 默认不这样做）
if sys.platform == 'win32':
    exe_dir = os.path.dirname(sys.executable
                              if getattr(sys, 'frozen', False)
                              else os.path.abspath(__file__))
    # SetDllDirectory：告诉 Windows 优先从我们的目录搜索 DLL
    try:
        import ctypes
        kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel32.SetDllDirectoryW(exe_dir)
    except Exception:
        pass  # 失败也不影响主程序启动

    # 同时把目录加入 PATH，双重保险
    os.environ['PATH'] = exe_dir + os.pathsep + os.environ.get('PATH', '')
