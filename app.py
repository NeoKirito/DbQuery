# -*- coding: utf-8 -*-
"""
DBQuery 统一入口
  双击或 DBQuery.exe          → 桌面版
  DBQuery.exe --web           → Web 版（http://localhost:8094）
  DBQuery.exe --web --port 80 → Web 版指定端口
"""
import sys
import os

# ── 路径设置 ──
from core.paths import get_app_dir, get_exe_dir

BASE_DIR = get_app_dir()
EXE_DIR = get_exe_dir()

os.chdir(BASE_DIR)
sys.path.insert(0, EXE_DIR)
sys.path.insert(0, BASE_DIR)

try:
    import ctypes
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID('neokirito.dbquery.app.v1')
except Exception:
    pass


def run_desktop():
    """启动桌面版"""
    from main import main
    main()


def run_web(port=8094):
    """启动 Web 版"""
    from web_server import app, logger, get_local_ip
    local_ip = get_local_ip()
    logger.info("Starting web server on port %d", port)
    print()
    print("=" * 50)
    print("  DBQuery Web 服务已启动")
    print("  本地访问：  http://localhost:{}".format(port))
    print("  局域网访问：http://{}:{}".format(local_ip, port))
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
        print("  DBQuery.exe --web        启动 Web 版（http://localhost:8094）")
        print("  DBQuery.exe --web --port 8080  指定端口")
        print("  DBQuery.exe --help       显示帮助")
        return

    if '--web' in args:
        port = 6091
        try:
            from core.paths import get_config_path
            import configparser
            cp = configparser.ConfigParser()
            cp.read(get_config_path(), encoding='utf-8')
            if cp.has_option('web', 'port'):
                port = cp.getint('web', 'port')
        except Exception:
            port = 6091
        if '--port' in args:
            try:
                idx = args.index('--port')
                port = int(args[idx + 1])
            except (IndexError, ValueError):
                print("错误：--port 后需要跟端口号，如 --port 6091")
                return
        run_web(port)
    else:
        run_desktop()


if __name__ == '__main__':
    main()
