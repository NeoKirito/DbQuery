# -*- coding: utf-8 -*-
"""
DBQuery 自动化打包与分发同步脚本
部署架构规范：
  - 外部根目录：放运维批处理脚本 (.bat)、配置文件 (config.ini)、表单目录 (forms/)、文档与前端 SDK、程序图标
  - 内部 dist/ 目录：放 DBQuery.exe 及所有依赖 DLL、pyd、PyQt5、Web 模板与静态资源
"""
import os
import sys
import shutil
import zipfile
import ctypes

REPO_DIR = os.path.abspath(os.path.dirname(__file__))
DIST_BUILD = os.path.join(REPO_DIR, "dist", "DBQuery")
ROOT_DIR = os.path.abspath(os.path.dirname(REPO_DIR))

TARGET_DEPLOY = os.path.join(ROOT_DIR, "DBQuery_Deploy")
TARGET_DBQUERY = os.path.join(ROOT_DIR, "DBQuery")
ZIP_DEPLOY = os.path.join(ROOT_DIR, "DBQuery_Deploy.zip")
ZIP_DBQUERY = os.path.join(ROOT_DIR, "DBQuery.zip")


# ── 运维批处理脚本模板 ──
START_DESKTOP_CN = """@echo off
title DBQuery 数据库查询工具
cd /d "%~dp0"
if exist "%~dp0dist\\DBQuery.exe" (
    start "" "%~dp0dist\\DBQuery.exe"
) else (
    start "" "%~dp0DBQuery.exe"
)
"""

START_DESKTOP_EN = """@echo off
title DBQuery Desktop
cd /d "%~dp0"
if exist "%~dp0dist\\DBQuery.exe" (
    start "" "%~dp0dist\\DBQuery.exe"
) else (
    start "" "%~dp0DBQuery.exe"
)
"""

START_WEB_CN = """@echo off
setlocal EnableExtensions
title DBQuery Web 服务
cd /d "%~dp0"

:: 默认服务端口
set "WEB_PORT=8094"

if exist "%~dp0dist\\DBQuery.exe" (
    set "EXE_PATH=%~dp0dist\\DBQuery.exe"
) else if exist "%~dp0dist_final\\DBQuery.exe" (
    set "EXE_PATH=%~dp0dist_final\\DBQuery.exe"
) else if exist "%~dp0DBQuery.exe" (
    set "EXE_PATH=%~dp0DBQuery.exe"
) else (
    set "EXE_PATH=%~dp0dist\\DBQuery.exe"
)
set "PORT_RULE_NAME=DBQuery_Web_%WEB_PORT%"
set "DBQUERY_TRUST_PROXY_PREFIX=true"

:: 检查管理员权限以自动配置 Windows 防火墙
net session >nul 2>&1
if errorlevel 1 (
    echo 正在申请管理员权限以配置 Windows 防火墙并启动服务...
    powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)

echo ================================================
echo   DBQuery Web 服务启动中...
echo ================================================

if not exist "%EXE_PATH%" (
    echo.
    echo 错误: 未找到可执行文件 "%EXE_PATH%"。
    pause
    exit /b 1
)

:: 配置 Windows 防火墙入站规则
echo 正在配置 Windows 防火墙入站规则...
netsh advfirewall firewall delete rule name="dbquery" dir=in >nul 2>&1
netsh advfirewall firewall delete rule name="DBQuery_Web_Access" dir=in >nul 2>&1
netsh advfirewall firewall delete rule name="%PORT_RULE_NAME%" dir=in >nul 2>&1
netsh advfirewall firewall delete rule name="DBQuery Program Allow" dir=in >nul 2>&1

netsh advfirewall firewall add rule name="%PORT_RULE_NAME%" dir=in action=allow protocol=TCP localport=%WEB_PORT% profile=any enable=yes >nul
if errorlevel 1 echo 警告: 添加防火墙端口规则失败。

netsh advfirewall firewall add rule name="DBQuery Program Allow" dir=in action=allow program="%EXE_PATH%" protocol=TCP profile=any enable=yes >nul
if errorlevel 1 echo 警告: 添加防火墙程序规则失败。

echo 防火墙 TCP 端口 %WEB_PORT% 已放行。

:: 获取本机局域网 IP
set "L_IP=127.0.0.1"
for /f "tokens=4" %%a in ('route print -4 ^| findstr /R /C:"^[ ]*0\\.0\\.0\\.0[ ]*0\\.0\\.0\\.0" ^| findstr /V /C:"Default"') do set "L_IP=%%a"

echo.
echo   本机访问: http://localhost:%WEB_PORT%/
echo   局域网:   http://%L_IP%:%WEB_PORT%/
echo.
echo   提示: 嵌入模式可在 URL 附加 ?hide_header=1 或 ?embed=1
echo ================================================
echo.

start "" "%EXE_PATH%" --web --port %WEB_PORT%
echo DBQuery Web 服务已在后台启动成功！

powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Sleep -Seconds 2"
endlocal & exit /b 0
"""

START_WEB_EN = """@echo off
setlocal EnableExtensions
title DBQuery Web Server
cd /d "%~dp0"

set "WEB_PORT=8094"

if exist "%~dp0dist\\DBQuery.exe" (
    set "EXE_PATH=%~dp0dist\\DBQuery.exe"
) else if exist "%~dp0dist_final\\DBQuery.exe" (
    set "EXE_PATH=%~dp0dist_final\\DBQuery.exe"
) else if exist "%~dp0DBQuery.exe" (
    set "EXE_PATH=%~dp0DBQuery.exe"
) else (
    set "EXE_PATH=%~dp0dist\\DBQuery.exe"
)
set "PORT_RULE_NAME=DBQuery_Web_%WEB_PORT%"
set "DBQUERY_TRUST_PROXY_PREFIX=true"

net session >nul 2>&1
if errorlevel 1 (
    echo Requesting administrator privileges to configure Windows Firewall...
    powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)

echo ================================================
echo   DBQuery Web Server Starting...
echo ================================================

if not exist "%EXE_PATH%" (
    echo.
    echo Error: DBQuery.exe not found at "%EXE_PATH%".
    pause
    exit /b 1
)

echo Configuring Windows Firewall...
netsh advfirewall firewall delete rule name="dbquery" dir=in >nul 2>&1
netsh advfirewall firewall delete rule name="DBQuery_Web_Access" dir=in >nul 2>&1
netsh advfirewall firewall delete rule name="%PORT_RULE_NAME%" dir=in >nul 2>&1
netsh advfirewall firewall delete rule name="DBQuery Program Allow" dir=in >nul 2>&1

netsh advfirewall firewall add rule name="%PORT_RULE_NAME%" dir=in action=allow protocol=TCP localport=%WEB_PORT% profile=any enable=yes >nul
netsh advfirewall firewall add rule name="DBQuery Program Allow" dir=in action=allow program="%EXE_PATH%" protocol=TCP profile=any enable=yes >nul
echo Firewall access enabled for TCP port %WEB_PORT%.

set "L_IP=127.0.0.1"
for /f "tokens=4" %%a in ('route print -4 ^| findstr /R /C:"^[ ]*0\\.0\\.0\\.0[ ]*0\\.0\\.0\\.0" ^| findstr /V /C:"Default"') do set "L_IP=%%a"

echo.
echo   Local:   http://localhost:%WEB_PORT%/
echo   Network: http://%L_IP%:%WEB_PORT%/
echo.
echo   Hint: Add ?hide_header=1 or ?embed=1 for embedded mode.
echo ================================================
echo.

start "" "%EXE_PATH%" --web --port %WEB_PORT%
echo Service started in background.

powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Sleep -Seconds 2"
endlocal & exit /b 0
"""

STOP_WEB_CN = """@echo off
setlocal EnableExtensions
title 停止 DBQuery Web 服务
cd /d "%~dp0"

set "WEB_PORT=8094"
if exist "%~dp0dist\\DBQuery.exe" (
    set "EXE_PATH=%~dp0dist\\DBQuery.exe"
) else if exist "%~dp0dist_final\\DBQuery.exe" (
    set "EXE_PATH=%~dp0dist_final\\DBQuery.exe"
) else if exist "%~dp0DBQuery.exe" (
    set "EXE_PATH=%~dp0DBQuery.exe"
) else (
    set "EXE_PATH=%~dp0dist\\DBQuery.exe"
)
set "DBQUERY_EXPECTED_EXE=%EXE_PATH%"

net session >nul 2>&1
if errorlevel 1 (
    echo 正在申请管理员权限以停止服务...
    powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)

echo ================================================
echo   正在停止 DBQuery Web 服务...
echo ================================================

powershell -NoProfile -ExecutionPolicy Bypass -Command "$expected=[IO.Path]::GetFullPath($env:DBQUERY_EXPECTED_EXE); $targets=@(Get-WmiObject Win32_Process | Where-Object { $_.Name -eq 'DBQuery.exe' -and $_.ExecutablePath -and [string]::Equals([IO.Path]::GetFullPath($_.ExecutablePath),$expected,[StringComparison]::OrdinalIgnoreCase) -and $_.CommandLine -match '(?i)(^|\\s)--web(\\s|$)' }); if(-not $targets){ Write-Host 'DBQuery Web 服务未在运行。'; exit 0 }; foreach($target in $targets){ Stop-Process -Id $target.ProcessId -Force -ErrorAction Stop }; Start-Sleep -Milliseconds 500; $remaining=@(Get-WmiObject Win32_Process | Where-Object { $_.Name -eq 'DBQuery.exe' -and $_.ExecutablePath -and [string]::Equals([IO.Path]::GetFullPath($_.ExecutablePath),$expected,[StringComparison]::OrdinalIgnoreCase) -and $_.CommandLine -match '(?i)(^|\\s)--web(\\s|$)' }); if($remaining){ Write-Host '停止服务失败。'; exit 1 }; Write-Host 'DBQuery Web 服务已成功停止。'"
set "STOP_RESULT=%ERRORLEVEL%"

echo.
if /I not "%~1"=="--no-pause" pause
endlocal & exit /b %STOP_RESULT%
"""

STOP_WEB_EN = """@echo off
setlocal EnableExtensions
title Stop DBQuery Web Server
cd /d "%~dp0"

set "WEB_PORT=8094"
if exist "%~dp0dist\\DBQuery.exe" (
    set "EXE_PATH=%~dp0dist\\DBQuery.exe"
) else if exist "%~dp0dist_final\\DBQuery.exe" (
    set "EXE_PATH=%~dp0dist_final\\DBQuery.exe"
) else if exist "%~dp0DBQuery.exe" (
    set "EXE_PATH=%~dp0DBQuery.exe"
) else (
    set "EXE_PATH=%~dp0dist\\DBQuery.exe"
)
set "DBQUERY_EXPECTED_EXE=%EXE_PATH%"

net session >nul 2>&1
if errorlevel 1 (
    echo Requesting administrator privileges to stop DBQuery Web...
    powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)

echo ================================================
echo   Stopping DBQuery Web Server...
echo ================================================

powershell -NoProfile -ExecutionPolicy Bypass -Command "$expected=[IO.Path]::GetFullPath($env:DBQUERY_EXPECTED_EXE); $targets=@(Get-WmiObject Win32_Process | Where-Object { $_.Name -eq 'DBQuery.exe' -and $_.ExecutablePath -and [string]::Equals([IO.Path]::GetFullPath($_.ExecutablePath),$expected,[StringComparison]::OrdinalIgnoreCase) -and $_.CommandLine -match '(?i)(^|\\s)--web(\\s|$)' }); if(-not $targets){ Write-Host 'DBQuery Web is not running.'; exit 0 }; foreach($target in $targets){ Stop-Process -Id $target.ProcessId -Force -ErrorAction Stop }; Start-Sleep -Milliseconds 500; $remaining=@(Get-WmiObject Win32_Process | Where-Object { $_.Name -eq 'DBQuery.exe' -and $_.ExecutablePath -and [string]::Equals([IO.Path]::GetFullPath($_.ExecutablePath),$expected,[StringComparison]::OrdinalIgnoreCase) -and $_.CommandLine -match '(?i)(^|\\s)--web(\\s|$)' }); if($remaining){ Write-Host 'Failed to stop DBQuery Web.'; exit 1 }; Write-Host 'DBQuery Web stopped.'"
set "STOP_RESULT=%ERRORLEVEL%"

echo.
if /I not "%~1"=="--no-pause" pause
endlocal & exit /b %STOP_RESULT%
"""

RESTART_WEB_CN = """@echo off
setlocal EnableExtensions
title 重启 DBQuery Web 服务
cd /d "%~dp0"

net session >nul 2>&1
if errorlevel 1 (
    echo 正在申请管理员权限以重启服务...
    powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)

echo ================================================
echo   正在重启 DBQuery Web 服务...
echo ================================================
echo.

call "%~dp0停止DBQueryWeb服务.bat" --no-pause
if errorlevel 1 (
    echo.
    echo 停止旧服务失败，重启已取消。
    if /I not "%~1"=="--no-pause" pause
    exit /b 1
)

call "%~dp0启动DBQueryWeb服务.bat"
if errorlevel 1 (
    echo.
    echo 启动服务失败。
    if /I not "%~1"=="--no-pause" pause
    exit /b 1
)

echo.
echo DBQuery Web 服务重启成功！
if /I not "%~1"=="--no-pause" pause
endlocal
"""

RESTART_WEB_EN = """@echo off
setlocal EnableExtensions
title Restart DBQuery Web Server
cd /d "%~dp0"

net session >nul 2>&1
if errorlevel 1 (
    echo Requesting administrator privileges to restart DBQuery Web...
    powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)

echo ================================================
echo   Restarting DBQuery Web Server...
echo ================================================
echo.

call "%~dp0stop_web.bat" --no-pause
if errorlevel 1 (
    echo.
    echo Restart cancelled because the old service could not be stopped.
    if /I not "%~1"=="--no-pause" pause
    exit /b 1
)

call "%~dp0start_web.bat"
if errorlevel 1 (
    echo.
    echo Restart failed while starting DBQuery Web.
    if /I not "%~1"=="--no-pause" pause
    exit /b 1
)

echo.
echo DBQuery Web restart completed.
if /I not "%~1"=="--no-pause" pause
endlocal
"""

SHORTCUT_BAT = """@echo off
title 创建桌面快捷方式
cd /d "%~dp0"
echo 正在为当前计算机创建桌面快捷方式...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ws = New-Object -ComObject WScript.Shell; $desktop = [System.Environment]::GetFolderPath('Desktop'); $shortcut = $ws.CreateShortcut((Join-Path $desktop 'DBQuery 数据库查询工具.lnk')); if (Test-Path (Join-Path '%~dp0' 'dist\\DBQuery.exe')) { $shortcut.TargetPath = (Join-Path '%~dp0' 'dist\\DBQuery.exe') } else { $shortcut.TargetPath = (Join-Path '%~dp0' 'DBQuery.exe') }; $shortcut.WorkingDirectory = '%~dp0'; $ico = (Join-Path '%~dp0' 'app.ico'); if (Test-Path $ico) { $shortcut.IconLocation = $ico + ',0' }; $shortcut.Description = 'DBQuery 数据库查询工具'; $shortcut.Save(); Write-Host '桌面快捷方式已成功创建到桌面！'"
echo.
pause
"""

ICON_CACHE_BAT = """@echo off
title 刷新 Windows 图标缓存
echo 正在刷新系统图标缓存...
taskkill /f /im explorer.exe >nul 2>&1
timeout /t 1 /nobreak >nul
powershell -NoProfile -ExecutionPolicy Bypass -Command "$p = Join-Path $env:LOCALAPPDATA 'IconCache.db'; if (Test-Path $p) { Remove-Item -Force $p }"
powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-ChildItem (Join-Path $env:LOCALAPPDATA 'Microsoft\\Windows\\Explorer\\iconcache*.db') -ErrorAction SilentlyContinue | Remove-Item -Force -ErrorAction SilentlyContinue"
start explorer.exe
echo 图标缓存刷新完毕！
timeout /t 2 >nul
"""


def clean_root_obsolete_files(target_dir):
    """
    清理根目录下遗留的旧版二进制、DLL 及运行库目录，确保根目录结构纯净。
    根目录白名单：
      - 目录：dist, forms
      - 文件：config.ini, app.ico, app.png, dbquery-embed.js, *.md, 施工文档, *.bat
    """
    if not os.path.exists(target_dir):
        return

    allowed_dirs = {'dist', 'forms'}
    exact_allowed_files = {
        'config.ini', 'app.ico', 'app.png', 'dbquery-embed.js',
        'readme.md', 'frontend_integration.md', 'host_integration.md',
        '体检系统-dbquery综合查询与报表部署配置施工文档.docx',
        '体检升级-施工升级文档.docx',
        '启动dbquery桌面版.bat', 'start_desktop.bat',
        '启动dbqueryweb服务.bat', 'start_web.bat',
        '停止dbqueryweb服务.bat', 'stop_web.bat',
        '重启dbqueryweb服务.bat', 'restart_web.bat',
        '创建桌面快捷方式.bat', '刷新windows图标缓存.bat'
    }

    for item in list(os.listdir(target_dir)):
        item_path = os.path.join(target_dir, item)
        if os.path.isdir(item_path):
            if item.lower() not in allowed_dirs:
                print(f"    Cleaning obsolete directory: {item}")
                shutil.rmtree(item_path, ignore_errors=True)
        else:
            if item.lower() not in exact_allowed_files:
                print(f"    Cleaning non-whitelisted/obsolete file: {item}")
                try:
                    os.remove(item_path)
                except Exception as e:
                    print(f"    Warning: could not remove {item}: {e}")


def assemble_deployment_folder(target_dir):
    """按照新规范组装部署包"""
    print(f"--> Assembling deployment folder at: {target_dir}")
    os.system("taskkill /f /im DBQuery.exe /t >nul 2>&1")
    os.makedirs(target_dir, exist_ok=True)

    # 0. 备份用户现有 config.ini（若存在）并清理根目录遗留二进制
    saved_config = None
    cfg_dst = os.path.join(target_dir, "config.ini")
    if os.path.isfile(cfg_dst):
        try:
            with open(cfg_dst, "rb") as f:
                saved_config = f.read()
        except Exception:
            pass

    clean_root_obsolete_files(target_dir)

    # 1. 组装内部 dist/ 目录（exe 与运行库）
    inner_dist = os.path.join(target_dir, "dist")
    if os.path.exists(inner_dist):
        shutil.rmtree(inner_dist, ignore_errors=True)
    os.makedirs(inner_dist, exist_ok=True)

    print("    Copying binaries into inner dist/...")
    for item in os.listdir(DIST_BUILD):
        if item.endswith((".log", ".tmp")):
            continue
        src = os.path.join(DIST_BUILD, item)
        dst = os.path.join(inner_dist, item)
        if os.path.isdir(src):
            shutil.copytree(src, dst, ignore=shutil.ignore_patterns("*.pyc", "__pycache__", "*.log", "*.tmp"))
        else:
            shutil.copy2(src, dst)

    # 2. 根目录：forms/ 文件夹
    forms_src = os.path.join(REPO_DIR, "forms")
    forms_dst = os.path.join(target_dir, "forms")
    os.makedirs(forms_dst, exist_ok=True)
    for root, dirs, files in os.walk(forms_src):
        rel = os.path.relpath(root, forms_src)
        dest_d = os.path.join(forms_dst, rel) if rel != "." else forms_dst
        os.makedirs(dest_d, exist_ok=True)
        for f in files:
            if f.endswith(".qry"):
                target_f = os.path.join(dest_d, f)
                if not os.path.exists(target_f):
                    shutil.copy2(os.path.join(root, f), target_f)

    # 3. 根目录：config.ini
    cfg_src = os.path.join(REPO_DIR, "config.ini")
    if saved_config:
        try:
            import configparser
            cp = configparser.ConfigParser()
            cp.read_string(saved_config.decode('utf-8', errors='replace'))
            if not cp.has_section('integration'):
                cp.add_section('integration')
            if cp.get('integration', 'frontend_embed_enabled', fallback='no').lower() not in ('yes', '1', 'true', 'on'):
                cp.set('integration', 'frontend_embed_enabled', 'yes')
            if not cp.get('integration', 'frontend_embed_allowed_origins', fallback='').strip():
                cp.set('integration', 'frontend_embed_allowed_origins', '*')
            if not cp.get('integration', 'frame_ancestors', fallback='').strip():
                cp.set('integration', 'frame_ancestors', '*')
            if cp.get('integration', 'frontend_enabled', fallback='no').lower() not in ('yes', '1', 'true', 'on'):
                cp.set('integration', 'frontend_enabled', 'yes')
            if not cp.get('integration', 'frontend_allowed_origins', fallback='').strip():
                cp.set('integration', 'frontend_allowed_origins', '*')
            with open(cfg_dst, "w", encoding='utf-8') as f:
                cp.write(f)
        except Exception:
            with open(cfg_dst, "wb") as f:
                f.write(saved_config)
    else:
        if os.path.exists(cfg_src) and os.path.abspath(cfg_src) != os.path.abspath(cfg_dst):
            shutil.copy2(cfg_src, cfg_dst)

    # 4. 根目录：图标与资源
    for icon in ["app.ico", "app.png"]:
        src_icon = os.path.join(REPO_DIR, icon)
        dst_icon = os.path.join(target_dir, icon)
        if os.path.exists(src_icon) and os.path.abspath(src_icon) != os.path.abspath(dst_icon):
            shutil.copy2(src_icon, dst_icon)

    # 5. 根目录：文档与前端集成 SDK
    for doc in ["README.md", "FRONTEND_INTEGRATION.md", "HOST_INTEGRATION.md", "dbquery-embed.js"]:
        src_doc = os.path.join(REPO_DIR, doc)
        if not os.path.exists(src_doc):
            src_doc = os.path.join(ROOT_DIR, "DBQuery", doc)
        dst_doc = os.path.join(target_dir, doc)
        if os.path.exists(src_doc) and os.path.abspath(src_doc) != os.path.abspath(dst_doc):
            shutil.copy2(src_doc, dst_doc)

    for docx_name in ["体检系统-DBQuery综合查询与报表部署配置施工文档.docx", "体检升级-施工升级文档.docx"]:
        docx_src = os.path.join(REPO_DIR, docx_name)
        if not os.path.exists(docx_src):
            docx_src = os.path.join(ROOT_DIR, "DBQuery", docx_name)
        if not os.path.exists(docx_src):
            docx_src = os.path.join(ROOT_DIR, docx_name)
        dst_docx = os.path.join(target_dir, docx_name)
        if os.path.exists(docx_src) and os.path.abspath(docx_src) != os.path.abspath(dst_docx):
            shutil.copy2(docx_src, dst_docx)

    # 6. 根目录：全套批处理脚本
    with open(os.path.join(target_dir, "启动DBQuery桌面版.bat"), "w", encoding="gbk") as f:
        f.write(START_DESKTOP_CN)
    with open(os.path.join(target_dir, "start_desktop.bat"), "w", encoding="ascii") as f:
        f.write(START_DESKTOP_EN)

    with open(os.path.join(target_dir, "启动DBQueryWeb服务.bat"), "w", encoding="gbk") as f:
        f.write(START_WEB_CN)
    with open(os.path.join(target_dir, "start_web.bat"), "w", encoding="ascii") as f:
        f.write(START_WEB_EN)

    with open(os.path.join(target_dir, "停止DBQueryWeb服务.bat"), "w", encoding="gbk") as f:
        f.write(STOP_WEB_CN)
    with open(os.path.join(target_dir, "stop_web.bat"), "w", encoding="ascii") as f:
        f.write(STOP_WEB_EN)

    with open(os.path.join(target_dir, "重启DBQueryWeb服务.bat"), "w", encoding="gbk") as f:
        f.write(RESTART_WEB_CN)
    with open(os.path.join(target_dir, "restart_web.bat"), "w", encoding="ascii") as f:
        f.write(RESTART_WEB_EN)

    with open(os.path.join(target_dir, "创建桌面快捷方式.bat"), "w", encoding="gbk") as f:
        f.write(SHORTCUT_BAT)
    with open(os.path.join(target_dir, "刷新Windows图标缓存.bat"), "w", encoding="gbk") as f:
        f.write(ICON_CACHE_BAT)

    # 7. 清理临时日志与缓存
    for root, dirs, files in os.walk(target_dir):
        for f in files:
            if f.endswith((".log", ".tmp", ".pyc")):
                try:
                    os.remove(os.path.join(root, f))
                except Exception:
                    pass
        for d in list(dirs):
            if d == "__pycache__":
                shutil.rmtree(os.path.join(root, d), ignore_errors=True)


def create_zip(zip_path, source_dir, root_folder_name):
    """压缩部署目录，并在 zip 中包含顶层文件夹名称便于规范解压"""
    print(f"--> Compressing {source_dir} to {zip_path}...")
    temp_zip = zip_path + ".tmp"
    if os.path.exists(temp_zip):
        try:
            os.remove(temp_zip)
        except Exception:
            pass

    with zipfile.ZipFile(temp_zip, 'w', zipfile.ZIP_DEFLATED) as zf:
        for root, dirs, files in os.walk(source_dir):
            for file in files:
                if file.endswith((".log", ".tmp", ".pyc")):
                    continue
                full_path = os.path.join(root, file)
                rel_path = os.path.relpath(full_path, source_dir)
                zf.write(full_path, os.path.join(root_folder_name, rel_path))

    if os.path.exists(zip_path):
        try:
            os.remove(zip_path)
        except Exception:
            pass
    os.rename(temp_zip, zip_path)
    sz = os.path.getsize(zip_path)
    print(f"    Created {zip_path} ({sz} bytes, {sz / (1024*1024):.2f} MB)")


def main():
    print("==================================================")
    print("   DBQuery Unified Deployment Packager")
    print("==================================================")

    if not os.path.exists(os.path.join(DIST_BUILD, "DBQuery.exe")):
        print(f"Error: dist/DBQuery/DBQuery.exe not found. Please run PyInstaller first.")
        sys.exit(1)

    # 1. 组装 DBQuery_Deploy（纯净部署包）
    assemble_deployment_folder(TARGET_DEPLOY)
    create_zip(ZIP_DEPLOY, TARGET_DEPLOY, "DBQuery_Deploy")

    # 2. 同步组装 DBQuery（兼容旧路径）
    old_df = os.path.join(TARGET_DBQUERY, "dist_final")
    if os.path.exists(old_df):
        shutil.rmtree(old_df, ignore_errors=True)
    assemble_deployment_folder(TARGET_DBQUERY)
    create_zip(ZIP_DBQUERY, TARGET_DBQUERY, "DBQuery")

    # 3. 刷新 Windows 图标缓存
    try:
        SHCNE_ASSOCCHANGED = 0x08000000
        SHCNF_IDLIST = 0x0000
        ctypes.windll.shell32.SHChangeNotify(SHCNE_ASSOCCHANGED, SHCNF_IDLIST, None, None)
        print("--> Windows Shell icon cache refresh notification sent.")
    except Exception as e:
        print(f"--> Notice: Icon notification skipped: {e}")

    print("==================================================")
    print("   All Deployment Packages Successfully Generated!")
    print("==================================================")


if __name__ == "__main__":
    main()
