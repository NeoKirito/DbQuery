"""
表单解析模块。

解析 .qry 文件，提取元信息、查询参数和 SQL 脚本。新增 Web 友好的控件属性
保持可选，旧格式无需修改即可继续使用。
"""
import os
import re
import shutil

TEMPLATE = u"""\
[meta]
title = 新建查询
group = 默认
description = 查询描述（可选）
# type = select    （默认，SELECT 查询）
# type = exec      （存储过程，SQL 以 EXEC 开头）

[params]
# 查询条件配置，格式：
#   参数名 = 显示标签 | 类型 | 默认值 | 可选属性...
#
# 支持的类型：
#   text                    文本输入框
#   date                    日期选择（YYYY-MM-DD）
#   datetime                日期时间选择（YYYY-MM-DD HH:mm:ss）
#   number                  数字输入框
#   select:全部,启用,禁用    下拉选项（逗号分隔；提交 option value）
#   select                  下拉选项可完全由 options_sql 提供
#   textarea                多行文本
#   checkbox                复选框（统一提交 1 或 0）
#   radio:男,女              单选项（提交所选 value）
#   hidden                  不显示，提交配置中的默认值
#
# 可选属性：
#   placeholder=输入关键字
#   required
#   width=220px（或 220、35%、18rem）
#   searchable              select 开启输入筛选（select 默认可搜索）
#   allow_custom=true       允许 select/radio 提交候选项外的值（默认 false）
#   options_sql=SELECT ...  只读动态候选 SQL；一列为 value=label，两列为 value,label
#
# 默认值中可用 {today}：date/text 为 YYYY-MM-DD，datetime 为 YYYY-MM-DD HH:mm:ss。
# 静态和动态 select 候选按 value 保序合并去重，旧格式仍完全兼容。
#
# SELECT 模式示例：
# start_date = 开始日期 | date | {today} | required | width=150
# keyword    = 关键词 | text | | placeholder=姓名、手机号或编号 | width=240px
# remark     = 备注 | textarea | | placeholder=可输入多行备注
# enabled    = 仅启用 | checkbox | 1
# gender     = 性别 | radio:全部,男,女 | 全部
# source     = 来源系统 | hidden | PEIS
# department = 科室 | select:全部 | 全部 | searchable | options_sql=SELECT DISTINCT Department FROM Employee WHERE Department IS NOT NULL ORDER BY Department
# doctor     = 医生 | select | | searchable | options_sql=SELECT DoctorID, DoctorName FROM Doctor WHERE Enabled=1 ORDER BY DoctorName
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


class QueryParam:
    """单个查询参数描述。"""

    def __init__(self, name, label, ptype='text', options=None, default='',
                 placeholder='', required=False, width='', options_sql='',
                 searchable=False, allow_custom=False):
        self.name = name
        self.label = label
        # 保持旧版静态候选项为字符串列表，避免破坏既有调用方。
        self.ptype = ptype
        self.options = options or []
        self.default = default
        self.placeholder = placeholder
        self.required = required
        self.width = width
        self.options_sql = options_sql
        self.searchable = searchable
        self.allow_custom = allow_custom


class QueryForm:
    """完整的查询表单。"""

    def __init__(self):
        self.title = ''
        self.description = ''
        self.group = ''
        self.query_type = 'select'
        self.params = []
        self.sql = ''
        self.file_path = ''


class FormParser:
    _BASIC_TYPES = ('text', 'date', 'datetime', 'number', 'textarea', 'checkbox', 'hidden')
    _WIDTH_PATTERN = re.compile(r'^\d+(?:\.\d+)?(?:px|%|rem|em|vw)?$', re.IGNORECASE)

    @staticmethod
    def _get_section(content, name):
        """提取指定 section 的内容。"""
        pattern = r'\[' + name + r'\](.*?)(?=\n\s*\[|\Z)'
        match = re.search(pattern, content, re.DOTALL | re.IGNORECASE)
        return match.group(1).strip() if match else ''

    @staticmethod
    def _parse_type(raw_type):
        """解析类型及 select/radio 的静态选项；未知类型安全回退 text。"""
        raw_type = (raw_type or 'text').strip()
        lower_type = raw_type.lower()
        if lower_type.startswith('select:'):
            return 'select', [item.strip() for item in raw_type.split(':', 1)[1].split(',') if item.strip()]
        if lower_type == 'select':
            return 'select', []
        if lower_type.startswith('radio:'):
            return 'radio', [item.strip() for item in raw_type.split(':', 1)[1].split(',') if item.strip()]
        if lower_type == 'radio':
            return 'radio', []
        if lower_type in FormParser._BASIC_TYPES:
            return lower_type, []
        return 'text', []

    @staticmethod
    def _normalize_width(value):
        """仅接受常用的安全 CSS 长度，纯数字按 px 处理。"""
        value = (value or '').strip()
        if not value or not FormParser._WIDTH_PATTERN.match(value):
            return ''
        if value.isdigit():
            return value + 'px'
        return value

    @staticmethod
    def _parse_param_attributes(parts):
        """解析属性，保留旧版“首个普通段为默认值”的兼容语义。"""
        default = ''
        placeholder = ''
        required = False
        width = ''
        options_sql = ''
        searchable = False
        allow_custom = False
        default_assigned = False

        for raw_part in parts:
            token = raw_part.strip()
            lower_token = token.lower()
            if lower_token == 'required':
                required = True
                continue
            if lower_token == 'searchable':
                searchable = True
                continue
            if '=' in token:
                key, value = token.split('=', 1)
                key = key.strip().lower()
                value = value.strip()
                if key == 'placeholder':
                    placeholder = value
                    continue
                if key == 'required':
                    required = value.lower() in ('1', 'true', 'yes', 'on', '是')
                    continue
                if key == 'width':
                    width = FormParser._normalize_width(value)
                    continue
                if key == 'options_sql':
                    options_sql = value
                    continue
                if key == 'searchable':
                    searchable = value.lower() in ('1', 'true', 'yes', 'on', '是')
                    continue
                if key == 'allow_custom':
                    allow_custom = value.lower() in ('1', 'true', 'yes', 'on', '是')
                    continue
            if not default_assigned:
                default = token
                default_assigned = True

        return default, placeholder, required, width, options_sql, searchable, allow_custom

    @staticmethod
    def parse_file(file_path):
        form = QueryForm()
        form.file_path = file_path

        with open(file_path, 'r', encoding='utf-8-sig') as form_file:
            content = form_file.read()

        for line in FormParser._get_section(content, 'meta').splitlines():
            line = line.strip()
            if not line or line.startswith('#') or line.startswith(';'):
                continue
            if '=' in line:
                key, value = line.split('=', 1)
                key = key.strip().lower()
                value = value.strip()
                if key == 'title':
                    form.title = value
                elif key == 'description':
                    form.description = value
                elif key == 'group':
                    form.group = value
                elif key == 'type':
                    form.query_type = value.lower().strip()

        if not form.title:
            form.title = os.path.splitext(os.path.basename(file_path))[0]
        if not form.group:
            parent_dir = os.path.basename(os.path.dirname(file_path))
            form.group = parent_dir if parent_dir.lower() != 'forms' else '默认'

        for line in FormParser._get_section(content, 'params').splitlines():
            line = line.strip()
            if not line or line.startswith('#') or line.startswith(';') or '=' not in line:
                continue
            name, rest = line.split('=', 1)
            name = name.strip()
            if not name:
                continue
            parts = [part.strip() for part in rest.split('|')]
            label = parts[0] if parts and parts[0] else name
            raw_type = parts[1] if len(parts) >= 2 else 'text'
            ptype, options = FormParser._parse_type(raw_type)
            (default, placeholder, required, width, options_sql,
             searchable, allow_custom) = FormParser._parse_param_attributes(parts[2:])
            form.params.append(QueryParam(
                name, label, ptype, options, default, placeholder, required, width,
                options_sql, searchable, allow_custom
            ))

        form.sql = FormParser._get_section(content, 'sql')
        return form

    @staticmethod
    def is_safe_sql(sql, query_type='select'):
        """安全检查：SELECT 仅允许查询；exec 仅允许受控存储过程调用。"""
        clean = re.sub(r'--[^\n]*', '', sql)
        clean = re.sub(r'/\*.*?\*/', '', clean, flags=re.DOTALL)
        clean = clean.strip()

        if not clean:
            return False, 'SQL内容为空'

        if query_type == 'exec':
            first_word = clean.split()[0].upper()
            if first_word not in ('EXEC', 'EXECUTE'):
                return False, '存储过程模式下，SQL 必须以 EXEC 或 EXECUTE 开头'
            blocked_exec = (
                r'\b(INSERT|UPDATE|DELETE|DROP|CREATE|ALTER|TRUNCATE|XP_|SP_EXECUTESQL)\b'
            )
            match = re.search(blocked_exec, clean, re.IGNORECASE)
            if match:
                return False, '存储过程 SQL 包含禁止的关键字：{}'.format(match.group().strip())
            return True, 'OK'

        tokens = clean.split()
        if not tokens or tokens[0].upper() != 'SELECT':
            return False, 'SQL必须以 SELECT 开头，本工具仅允许查询操作'

        # 先检测 SELECT INTO（所有 SQL Server 标识符形式）：
        #   INTO TableName / INTO dbo.TableName / INTO [TableName] / INTO [dbo].[TableName]
        #   INTO #TempTable / INTO ##GlobalTempTable
        # 匹配规则：INTO 后（忽略空白）紧跟 #、[ 或普通标识符首字符 \w 即为 SELECT INTO。
        into_match = re.search(r'\bINTO\s+(?:[#\[]|\w)', clean, re.IGNORECASE)
        if into_match:
            return False, 'SQL 包含禁止的 SELECT INTO（禁止写入操作）'

        blocked = (
            r'\b(INSERT|UPDATE|DELETE|DROP|CREATE|ALTER|TRUNCATE|EXEC|EXECUTE|XP_|SP_EXECUTESQL)\b'
        )
        match = re.search(blocked, clean, re.IGNORECASE)
        if match:
            return False, 'SQL 包含禁止的关键字：{}'.format(match.group().strip())
        return True, 'OK'

    @staticmethod
    def ensure_forms_dir(forms_dir):
        """只在 forms 不存在时从随包 defaults/forms 初始化，绝不覆盖现场表单。"""
        if os.path.exists(forms_dir):
            return
        defaults_dir = os.path.join(os.path.dirname(forms_dir), 'defaults', 'forms')
        if os.path.isdir(defaults_dir):
            shutil.copytree(defaults_dir, forms_dir)
        else:
            os.makedirs(forms_dir)

    @staticmethod
    def load_forms_from_dir(forms_dir):
        """扫描 forms_dir 及其子目录中所有 .qry 文件，按分组返回。"""
        result = {}
        FormParser.ensure_forms_dir(forms_dir)

        for root, dirs, files in os.walk(forms_dir):
            dirs.sort()
            for filename in sorted(files):
                if not filename.lower().endswith('.qry'):
                    continue
                path = os.path.join(root, filename)
                try:
                    form = FormParser.parse_file(path)
                    group = form.group or '默认'
                    result.setdefault(group, []).append(form)
                except Exception as exc:
                    print('[WARN] 加载表单失败 {}: {}'.format(path, exc))
        return result
