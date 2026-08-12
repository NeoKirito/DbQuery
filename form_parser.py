# -*- coding: utf-8 -*-
"""
表单解析模块
解析 .qry 文件，提取元信息、查询参数、SQL脚本
"""
import os
import re

# 新建表单时的默认模板内容
TEMPLATE = u"""\
[meta]
title = 新建查询
group = 默认
description = 查询描述（可选）
# type = select    （默认，SELECT 查询）
# type = exec      （存储过程，SQL 以 EXEC 开头）

[params]
# 查询条件配置，格式：
#   参数名 = 显示标签 | 类型 | 默认值
#
# 支持的类型：
#   text          文本输入框
#   date          日期选择（YYYY-MM-DD）
#   datetime      日期时间选择
#   number        数字输入框
#   select:A,B,C  下拉选项（逗号分隔）
#
# 默认值中可用 {today} 代表今日日期
#
# SELECT 模式示例：
# start_date = 开始日期 | date
# end_date   = 结束日期 | date | {today}
# status     = 状态     | select:全部,启用,禁用 | 全部
# keyword    = 关键字   | text
#
# 存储过程模式示例（参数名需与存储过程参数一致）：
# start_date = 开始日期 | date
# end_date   = 结束日期 | date | {today}

[sql]
SELECT TOP 100 *
FROM YourTable
WHERE 1=1
-- 使用参数：AND SomeColumn = '{keyword}'
-- 日期范围：AND CreateDate BETWEEN '{start_date}' AND '{end_date}'
--
-- 存储过程模式示例（取消注释 type = exec 后使用）：
-- EXEC dbo.usp_QueryOrders @StartDate = '{start_date}', @EndDate = '{end_date}'
"""


class QueryParam(object):
    """单个查询参数描述"""
    def __init__(self, name, label, ptype='text', options=None, default=''):
        self.name    = name
        self.label   = label
        self.ptype   = ptype          # text | date | datetime | number | select
        self.options = options or []  # select 时的选项列表
        self.default = default


class QueryForm(object):
    """完整的查询表单"""
    def __init__(self):
        self.title       = ''
        self.description = ''
        self.group       = ''
        self.query_type  = 'select'  # 'select' 或 'exec'（存储过程）
        self.params      = []
        self.sql         = ''
        self.file_path   = ''


class FormParser(object):

    @staticmethod
    def _get_section(content, name):
        """提取指定 section 的内容"""
        pat = r'\[' + name + r'\](.*?)(?=\n\s*\[|\Z)'
        m = re.search(pat, content, re.DOTALL | re.IGNORECASE)
        return m.group(1).strip() if m else ''

    @staticmethod
    def parse_file(file_path):
        form = QueryForm()
        form.file_path = file_path

        with open(file_path, 'r', encoding='utf-8-sig') as f:
            content = f.read()

        # ---- [meta] ----
        for line in FormParser._get_section(content, 'meta').splitlines():
            line = line.strip()
            if not line or line.startswith('#') or line.startswith(';'):
                continue
            if '=' in line:
                k, v = line.split('=', 1)
                k = k.strip().lower()
                v = v.strip()
                if k == 'title':
                    form.title = v
                elif k == 'description':
                    form.description = v
                elif k == 'group':
                    form.group = v
                elif k == 'type':
                    form.query_type = v.lower().strip()

        # 无标题时用文件名
        if not form.title:
            form.title = os.path.splitext(os.path.basename(file_path))[0]

        # 无分组时用父目录名
        if not form.group:
            parent_dir = os.path.basename(os.path.dirname(file_path))
            forms_dir  = os.path.basename(os.path.dirname(os.path.dirname(file_path)))
            form.group = parent_dir if parent_dir.lower() != 'forms' else '默认'

        # ---- [params] ----
        for line in FormParser._get_section(content, 'params').splitlines():
            line = line.strip()
            if not line or line.startswith('#') or line.startswith(';'):
                continue
            if '=' not in line:
                continue
            name, rest = line.split('=', 1)
            name  = name.strip()
            parts = [p.strip() for p in rest.split('|')]

            label   = parts[0] if parts else name
            ptype   = 'text'
            options = []
            default = ''

            if len(parts) >= 2:
                t = parts[1].lower()
                if t.startswith('select:'):
                    ptype   = 'select'
                    options = [x.strip() for x in t[7:].split(',')]
                elif t in ('text', 'date', 'datetime', 'number'):
                    ptype = t
                # 其他未知类型回退到 text

            if len(parts) >= 3:
                default = parts[2]

            form.params.append(QueryParam(name, label, ptype, options, default))

        # ---- [sql] ----
        form.sql = FormParser._get_section(content, 'sql')

        return form

    @staticmethod
    def is_safe_sql(sql, query_type='select'):
        """
        安全检查
        query_type='select'：只允许 SELECT 语句
        query_type='exec'  ：允许 EXEC/EXECUTE 存储过程调用
        返回 (bool, reason_str)
        """
        # 去除注释
        clean = re.sub(r'--[^\n]*', '', sql)
        clean = re.sub(r'/\*.*?\*/', '', clean, flags=re.DOTALL)
        clean = clean.strip()

        if not clean:
            return False, "SQL内容为空"

        # ---- 存储过程模式 ----
        if query_type == 'exec':
            first_word = clean.split()[0].upper()
            if first_word not in ('EXEC', 'EXECUTE'):
                return False, "存储过程模式下，SQL 必须以 EXEC 或 EXECUTE 开头"

            # 存储过程仍需禁止的危险关键字
            blocked_exec = (r'\b(INSERT|UPDATE|DELETE|DROP|CREATE|ALTER|TRUNCATE'
                            r'|XP_|SP_EXECUTESQL)\b')
            m = re.search(blocked_exec, clean, re.IGNORECASE)
            if m:
                return False, "存储过程 SQL 包含禁止的关键字：{}".format(m.group().strip())
            return True, 'OK'

        # ---- SELECT 模式 ----
        tokens = clean.split()
        if not tokens or tokens[0].upper() != 'SELECT':
            return False, "SQL必须以 SELECT 开头，本工具仅允许查询操作"

        blocked = (r'\b(INSERT|UPDATE|DELETE|DROP|CREATE|ALTER|TRUNCATE'
                   r'|EXEC|EXECUTE|XP_|SP_EXECUTESQL|INTO\s+\w+)\b')
        m = re.search(blocked, clean, re.IGNORECASE)
        if m:
            return False, "SQL 包含禁止的关键字：{}".format(m.group().strip())

        return True, 'OK'

    @staticmethod
    def load_forms_from_dir(forms_dir):
        """
        扫描 forms_dir 及其子目录中所有 .qry 文件
        返回 dict: { group_name: [QueryForm, ...] }
        """
        result = {}
        if not os.path.exists(forms_dir):
            os.makedirs(forms_dir)
            return result

        for root, dirs, files in os.walk(forms_dir):
            dirs.sort()
            for fn in sorted(files):
                if fn.lower().endswith('.qry'):
                    path = os.path.join(root, fn)
                    try:
                        form = FormParser.parse_file(path)
                        g = form.group or '默认'
                        result.setdefault(g, []).append(form)
                    except Exception as e:
                        print("[WARN] 加载表单失败 {}: {}".format(path, e))

        return result
