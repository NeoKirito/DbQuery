# -*- coding: utf-8 -*-
"""
DBQuery 统一路径解析模块
支持将 exe 与运行库 (dll, pyd) 置于 dist/ 等独立子目录，
而将配置文件 (config.ini)、表单 (forms/)、脚本 (.bat) 及文档置于外层根目录的部署架构。
"""
import sys
import os

def get_exe_dir():
    """获取可执行文件所在目录（打包后为 DBQuery.exe 所在目录；源码模式为源码根目录）"""
    if getattr(sys, 'frozen', False):
        return os.path.abspath(os.path.dirname(sys.executable))
    return os.path.abspath(os.path.dirname(os.path.dirname(__file__)))


def get_app_dir():
    """
    获取程序部署根目录：
    当 DBQuery.exe 位于 dist、dist_final、bin 等子目录时，
    自动将上级目录识别为程序部署根目录（外置 config.ini, forms/, .bat, 文档）。
    若外层无特殊结构，则退回当前 exe 所在目录。
    """
    if not getattr(sys, 'frozen', False):
        return os.path.abspath(os.path.dirname(os.path.dirname(__file__)))

    exe_dir = get_exe_dir()
    parent_dir = os.path.abspath(os.path.dirname(exe_dir))
    dirname = os.path.basename(exe_dir).lower()

    if dirname in ('dist', 'dist_final', 'bin') or \
       os.path.exists(os.path.join(parent_dir, 'config.ini')) or \
       os.path.exists(os.path.join(parent_dir, 'forms')):
        return parent_dir

    return exe_dir


def get_config_path():
    """
    获取 config.ini 路径：
    优先查找部署根目录下的 config.ini；
    若不存在但 exe 所在目录有，则使用 exe 目录；
    默认返回根目录下路径以便新建或保存。
    """
    app_dir = get_app_dir()
    root_config = os.path.join(app_dir, 'config.ini')
    if os.path.exists(root_config):
        return root_config

    exe_config = os.path.join(get_exe_dir(), 'config.ini')
    if os.path.exists(exe_config):
        return exe_config

    return root_config


def get_forms_dir():
    """
    获取 forms 目录路径：
    优先使用根目录下的 forms/ 文件夹；
    若不存在则退回 exe 目录下的 forms/；
    默认返回根目录下的 forms/ 路径。
    """
    app_dir = get_app_dir()
    root_forms = os.path.join(app_dir, 'forms')
    if os.path.isdir(root_forms):
        return root_forms

    exe_forms = os.path.join(get_exe_dir(), 'forms')
    if os.path.isdir(exe_forms):
        return exe_forms

    return root_forms


def get_resource_dir():
    """获取内嵌资源目录（templates, static, defaults 等），随打包二进制文件捆绑在 exe 所在目录"""
    if getattr(sys, 'frozen', False):
        return getattr(sys, '_MEIPASS', get_exe_dir())
    return get_app_dir()


def get_logs_dir():
    """获取日志目录 logs/（位于部署根目录下），自动创建并返回绝对路径"""
    app_dir = get_app_dir()
    logs_dir = os.path.join(app_dir, 'logs')
    try:
        if not os.path.isdir(logs_dir):
            os.makedirs(logs_dir, exist_ok=True)
    except Exception:
        pass
    return logs_dir
