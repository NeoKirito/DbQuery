# -*- coding: utf-8 -*-
"""
DBQuery 统一入口
  双击或 DBQuery.exe          → 桌面版
  DBQuery.exe --web           → Web 版（http://localhost:5000）
  DBQuery.exe --web --port 80 → Web 版指定端口
"""
import sys
import os

# ── 路径设置 ──
if getattr(sys, 'frozen', False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

os.chdir(BASE_DIR)
sys.path.insert(0, BASE_DIR)


def run_desktop():
    """启动桌面版"""
    from main import main
    main()


def run_web(port=5000):
    """启动 Web 版"""
    from web_server import app, logger
    logger.info("Starting web server on port %d", port)
    print()
    print("=" * 50)
    print("  DBQuery Web 服务已启动")
    print("  浏览器访问：http://localhost:{}".format(port))
    print("  按 Ctrl+C 停止")
    print("=" * 50)
    print()
    app.run(host='0.0.0.0', port=port, debug=False, threaded=True)


def main():
    args = sys.argv[1:]

    if '--help' in args or '-h' in args:
        print("DBQuery 数据库查询工具")
        print()
        print("用法：")
        print("  DBQuery.exe              启动桌面版（默认）")
        print("  DBQuery.exe --web        启动 Web 版（http://localhost:5000）")
        print("  DBQuery.exe --web --port 8080  指定端口")
        print("  DBQuery.exe --help       显示帮助")
        return

    if '--web' in args:
        port = 5000
        if '--port' in args:
            try:
                idx = args.index('--port')
                port = int(args[idx + 1])
            except (IndexError, ValueError):
                print("错误：--port 后需要跟端口号，如 --port 8080")
                return
        run_web(port)
    else:
        run_desktop()


if __name__ == '__main__':
    main()
