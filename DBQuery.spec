# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller 打包配置
Win7 兼容版：自动收集 Universal CRT DLL，无需目标机器安装补丁
"""
import os, glob, sys

block_cipher = None

# ── 收集 Universal CRT DLL（解决 Win7 缺 api-ms-win-*.dll 问题）──
# 这批 DLL 在 Win10/Win11 打包机器上位于以下位置之一：
#   C:\Windows\System32\downlevel\          （推荐，专为下级兼容设计）
#   C:\Program Files (x86)\Windows Kits\10\Redist\ucrt\DLLs\x86\
#   C:\Windows\SysWOW64\downlevel\          （x64 系统上的 32 位版）
#   C:\Windows\System32\                   （兜底）

def _find_ucrt_dlls():
    """搜索 Universal CRT DLL 并返回 PyInstaller binaries 列表"""
    search_dirs = [
        r'C:\Windows\System32\downlevel',
        r'C:\Windows\SysWOW64\downlevel',
        r'C:\Program Files (x86)\Windows Kits\10\Redist\ucrt\DLLs\x86',
        r'C:\Program Files\Windows Kits\10\Redist\ucrt\DLLs\x86',
        # VS 2022 / VS 2019 / VS 2017 安装路径
        r'C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Redist\MSVC',
        r'C:\Program Files (x86)\Microsoft Visual Studio\2019\Community\VC\Redist\MSVC',
        r'C:\Program Files (x86)\Microsoft Visual Studio\2017\Community\VC\Redist\MSVC',
    ]
    # api-ms-win-*.dll 和 ucrtbase.dll
    patterns = ['api-ms-win-*.dll', 'ucrtbase.dll', 'vcruntime*.dll', 'msvcp*.dll']
    found = {}

    for d in search_dirs:
        if not os.path.isdir(d):
            # VS 路径可能有版本子目录，做一层通配
            for sub in glob.glob(d + r'\*\x86\Microsoft.VC*.CRT'):
                if os.path.isdir(sub):
                    d = sub
                    break
            else:
                continue
        for pat in patterns:
            for f in glob.glob(os.path.join(d, pat)):
                name = os.path.basename(f).lower()
                if name not in found:
                    found[name] = f
        if found:
            print("[SPEC] Found {} UCRT DLLs in: {}".format(len(found), d))
            break

    if not found:
        # 最后兜底：从 System32 收集（不一定有 downlevel 版，但总比没有强）
        sys32 = r'C:\Windows\System32'
        for pat in patterns:
            for f in glob.glob(os.path.join(sys32, pat)):
                name = os.path.basename(f).lower()
                if name not in found:
                    found[name] = f
        if found:
            print("[SPEC] Fallback: {} DLLs from System32".format(len(found)))

    result = [(path, '.') for path in found.values()]
    print("[SPEC] Total UCRT/VC DLLs to bundle: {}".format(len(result)))
    return result

ucrt_binaries = _find_ucrt_dlls()

a = Analysis(
    ['app.py'],
    pathex=['.'],
    binaries=ucrt_binaries,   # <── 关键：把 UCRT DLL 打进包
    datas=[
        ('forms', 'forms'),
        ('templates', 'templates'),
        ('static', 'static'),
    ],
    hiddenimports=[
        'pyodbc',
        'openpyxl',
        'openpyxl.cell',
        'openpyxl.cell.cell',
        'openpyxl.workbook',
        'openpyxl.workbook.workbook',
        'openpyxl.worksheet',
        'openpyxl.worksheet.worksheet',
        'openpyxl.styles',
        'openpyxl.styles.fills',
        'openpyxl.styles.fonts',
        'openpyxl.styles.borders',
        'openpyxl.styles.alignment',
        'openpyxl.styles.patterns',
        'openpyxl.utils',
        'openpyxl.utils.cell',
        'openpyxl.writer.excel',
        'openpyxl.descriptors',
        'openpyxl.descriptors.serialisable',
        'PyQt5.QtPrintSupport',
        'configparser',
        # Flask Web 服务依赖
        'flask',
        'flask.json',
        'flask.json.provider',
        'jinja2',
        'werkzeug',
        'werkzeug.serving',
        'werkzeug.debug',
        'markupsafe',
        'itsdangerous',
        'click',
        'core',
        'core.query_service',
        'web_server',
        'main',
    ],
    hookspath=[],
    runtime_hooks=['runtime_hook_win7.py'],   # <── Win7 运行时钩子
    excludes=['tkinter', 'matplotlib', 'numpy', 'pandas', 'scipy'],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='DBQuery',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,          # Win7 必须关闭 UPX
    console=False,
    icon=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='DBQuery',
)
