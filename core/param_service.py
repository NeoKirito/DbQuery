# -*- coding: utf-8 -*-
"""查询条件公共服务。

该模块不依赖 PyQt 或 Flask，负责将 .qry 参数定义转换为两个客户端共用的
默认值、候选项和最终参数字典。界面层只负责采集/展示，SQL 构建仅接收这里
规范化后的白名单参数。
"""
import datetime
import logging
import re

from core.sql_safety import normalize_sql_for_safety
from decimal import Decimal, InvalidOperation


logger = logging.getLogger('DBQuery.param_service')

OPTIONS_QUERY_TIMEOUT = 10
OPTIONS_MAX_ROWS = 1000
_TRUE_VALUES = frozenset(('1', 'true', 'yes', 'on', '是'))
_NUMBER_PATTERN = re.compile(r'^[+-]?(?:\d+(?:\.\d*)?|\.\d+)$')
_PLACEHOLDER_PATTERN = re.compile(r'\{([A-Za-z_][A-Za-z0-9_]*)\}')


class ParameterError(ValueError):
    """用户输入或 .qry 参数配置无法被规范化。"""


class RequiredParameterError(ParameterError):
    """必填条件没有获得有效值。"""

    def __init__(self, param):
        self.param = param
        super(RequiredParameterError, self).__init__('请填写查询条件：{}'.format(param.label))


class QueryConfigurationError(ParameterError):
    """.qry 配置与 SQL 占位符不匹配。"""


class OptionsLoadError(ParameterError):
    """动态候选项加载失败，供表现层显示业务化提示。"""


def _string(value):
    return '' if value is None else str(value)


def normalize_option(value, label=None):
    """将静态文本或数据库行统一为 JSON/PyQt 可用的 value/label 结构。"""
    if isinstance(value, dict):
        raw_value = value.get('value')
        raw_label = value.get('label', raw_value)
    elif isinstance(value, (tuple, list)):
        raw_value = value[0] if value else None
        raw_label = value[1] if len(value) > 1 else raw_value
    else:
        raw_value = value
        raw_label = value if label is None else label

    if raw_value is None:
        return None
    value_text = _string(raw_value)
    if not value_text:
        return None
    label_text = _string(raw_label) if raw_label is not None else value_text
    return {'value': value_text, 'label': label_text or value_text}


def merge_options(*option_groups):
    """按 value 保序合并并去重；先出现的 label 保留，保证旧静态项优先。"""
    result = []
    seen_values = set()
    for group in option_groups:
        for raw_option in group or []:
            option = normalize_option(raw_option)
            if option is None or option['value'] in seen_values:
                continue
            seen_values.add(option['value'])
            result.append(option)
    return result


def static_options(param):
    """返回 .qry 中 select/radio 的静态候选项。"""
    return merge_options(getattr(param, 'options', []) or [])


def resolve_default(param, now=None):
    """解析显式默认值及 {today}，确保桌面和 Web 得到相同字符串。"""
    default = _string(getattr(param, 'default', ''))
    if default != '{today}':
        return default

    now = now or datetime.datetime.now()
    ptype = getattr(param, 'ptype', 'text')
    if ptype == 'datetime':
        return now.strftime('%Y-%m-%d %H:%M:%S')
    return now.strftime('%Y-%m-%d')


def _coerce_date(value):
    raw = _string(value).strip()
    if not raw:
        return ''
    try:
        return datetime.datetime.strptime(raw, '%Y-%m-%d').strftime('%Y-%m-%d')
    except ValueError:
        raise ParameterError('查询条件日期格式不正确，应为 yyyy-MM-dd')


def _coerce_datetime(value):
    raw = _string(value).strip()
    if not raw:
        return ''
    candidates = ('%Y-%m-%d %H:%M:%S', '%Y-%m-%dT%H:%M:%S', '%Y-%m-%dT%H:%M')
    for pattern in candidates:
        try:
            return datetime.datetime.strptime(raw, pattern).strftime('%Y-%m-%d %H:%M:%S')
        except ValueError:
            continue
    raise ParameterError('查询条件日期时间格式不正确，应为 yyyy-MM-dd HH:mm:ss')


def _coerce_number(value):
    raw = _string(value).strip()
    if not raw:
        return ''
    if not _NUMBER_PATTERN.match(raw):
        raise ParameterError('查询条件必须是有效数字')
    try:
        Decimal(raw)
    except InvalidOperation:
        raise ParameterError('查询条件必须是有效数字')
    return raw


def _is_blank(value):
    return not _string(value).strip()


def _allowed_values(options):
    return set(option['value'] for option in options or [])


def normalize_value(param, raw_value, options=None, now=None):
    """按参数类型执行唯一的值语义，不负责 required 检查。"""
    ptype = getattr(param, 'ptype', 'text')

    # hidden 只接受 .qry 默认值，不使用来自浏览器或桌面控件的可篡改值。
    if ptype == 'hidden':
        return resolve_default(param, now)
    if raw_value is None:
        raw_value = resolve_default(param, now)

    if ptype == 'checkbox':
        return '1' if _string(raw_value).strip().lower() in _TRUE_VALUES else '0'
    if ptype == 'date':
        return _coerce_date(raw_value)
    if ptype == 'datetime':
        return _coerce_datetime(raw_value)
    if ptype == 'number':
        return _coerce_number(raw_value)

    value = _string(raw_value)
    if ptype in ('select', 'radio'):
        available = options if options is not None else static_options(param)
        allowed = _allowed_values(available)
        allow_custom = bool(getattr(param, 'allow_custom', False))
        if value and allowed and value not in allowed and not allow_custom:
            raise ParameterError('查询条件“{}”必须从候选项中选择'.format(param.label))
        if value and not allowed and not allow_custom and ptype == 'select':
            # 没有加载到可用候选时，禁止把用户临时检索文本拼进 SQL。
            raise ParameterError('查询条件“{}”暂无可用候选项，请刷新后重试'.format(param.label))
    return value


def normalize_params(form, raw_values=None, options_by_name=None, now=None):
    """仅处理 form.params 白名单，统一默认值、类型语义和 required 校验。

    ``raw_values`` 中未定义的键会被丢弃；这使 Web API 无法利用任意参数名替换
    SQL 占位符。``options_by_name`` 可传入已加载的动态候选，避免 UI 与服务端
    对 value/label 的理解分叉。
    """
    raw_values = raw_values if isinstance(raw_values, dict) else {}
    options_by_name = options_by_name or {}
    normalized = {}

    for param in getattr(form, 'params', []) or []:
        supplied = raw_values.get(param.name) if param.name in raw_values else None
        options = options_by_name.get(param.name)
        if options is None and getattr(param, 'ptype', '') in ('select', 'radio'):
            options = static_options(param)
        value = normalize_value(param, supplied, options=options, now=now)

        if getattr(param, 'required', False):
            if getattr(param, 'ptype', '') == 'checkbox':
                if value != '1':
                    raise RequiredParameterError(param)
            elif _is_blank(value):
                raise RequiredParameterError(param)
        normalized[param.name] = value

    return normalized


def ensure_sql_placeholders_resolved(form, sql):
    """拒绝未声明或未替换的 {name}，避免直接把占位符交给数据库。"""
    unresolved = sorted(set(_PLACEHOLDER_PATTERN.findall(sql or '')))
    if unresolved:
        known = set(param.name for param in getattr(form, 'params', []) or [])
        unknown = [name for name in unresolved if name not in known]
        if unknown:
            raise QueryConfigurationError(
                '查询条件配置错误：SQL 使用了未定义参数 {}'.format(', '.join(unknown))
            )
        raise QueryConfigurationError(
            '查询条件配置错误：参数 {} 未能解析'.format(', '.join(unresolved))
        )


def build_sql_with_params(form, normalized_params):
    """基于参数定义白名单替换占位符，保留既有 SQL 单引号转义规则。"""
    from core.query_service import escape_sql_param

    sql = getattr(form, 'sql', '')
    allowed_names = [param.name for param in getattr(form, 'params', []) or []]
    for name in allowed_names:
        if name not in normalized_params:
            continue
        sql = sql.replace('{' + name + '}', escape_sql_param(_string(normalized_params[name])))
    ensure_sql_placeholders_resolved(form, sql)
    return sql


def validate_options_sql(sql):
    """验证动态候选 SQL 为单条只读 SELECT。"""
    from form_parser import FormParser

    clean = normalize_sql_for_safety(sql).strip()
    if clean.endswith(';'):
        clean = clean[:-1].strip()
    if ';' in clean:
        return False, '候选项 SQL 只允许一条 SELECT 语句'
    return FormParser.is_safe_sql(clean, 'select')


def dynamic_options(param, db_manager, timeout=OPTIONS_QUERY_TIMEOUT,
                    max_rows=OPTIONS_MAX_ROWS):
    """使用短生命周期连接加载单个参数的数据库候选项。"""
    options_sql = _string(getattr(param, 'options_sql', '')).strip()
    if not options_sql:
        return []

    safe, reason = validate_options_sql(options_sql)
    if not safe:
        raise OptionsLoadError('候选项 SQL 配置无效：{}'.format(reason))

    try:
        columns, rows, _ = db_manager.execute_query_limited(
            options_sql,
            query_timeout=timeout,
            max_rows=max_rows,
            query_type='select'
        )
    except Exception as exc:
        logger.exception('动态候选项加载失败：%s', getattr(param, 'name', 'unknown'))
        raise OptionsLoadError('候选数据加载失败，可刷新重试') from exc

    if not columns:
        return []
    converted = []
    for row in rows:
        if not row:
            continue
        converted.append((row[0], row[1] if len(row) > 1 else row[0]))
    return merge_options(converted)


def load_options(param, db_manager=None, timeout=OPTIONS_QUERY_TIMEOUT,
                 max_rows=OPTIONS_MAX_ROWS):
    """合并静态和动态候选；调用方可捕获 OptionsLoadError 并继续显示静态项。"""
    static = static_options(param)
    if not getattr(param, 'options_sql', ''):
        return static
    if db_manager is None:
        raise OptionsLoadError('候选数据服务不可用')
    return merge_options(static, dynamic_options(param, db_manager, timeout, max_rows))


def serialize_options(options):
    """返回可安全下发给 Web 的 option 列表。"""
    return merge_options(options)


def sql_placeholders(sql):
    """供测试和保存校验复用的占位符提取器。"""
    return set(_PLACEHOLDER_PATTERN.findall(sql or ''))
