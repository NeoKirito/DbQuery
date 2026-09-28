# -*- coding: utf-8 -*-
"""
汇总与统计指标服务模块。

支持：
1. 表格底部合计行规范解析与多聚合运算（sum, count, avg, min, max, auto）；
2. 聚合结果格式化（千分位、货币与小数处理）；
3. 统计指标卡片（cards）数据提取与呈现转换。
"""
from decimal import Decimal
import re


def parse_summary_spec(spec_str):
    """
    解析 summary_footer 规范字符串。
    
    格式示例：
      - 'sum:金额,人次; count:体检号; avg:客单价'
      - 'auto'
      - 'sum:金额'
    """
    spec = str(spec_str or '').strip()
    if not spec:
        return {'auto': False, 'rules': []}

    if spec.lower() == 'auto':
        return {'auto': True, 'rules': []}

    rules = []
    # 按分号分隔各个统计维度
    groups = [g.strip() for g in spec.split(';') if g.strip()]
    for group in groups:
        if ':' not in group:
            continue
        op_part, cols_part = group.split(':', 1)
        op = op_part.strip().lower()
        if op not in ('sum', 'count', 'avg', 'min', 'max'):
            continue
        cols = [c.strip() for c in cols_part.split(',') if c.strip()]
        if cols:
            rules.append({'op': op, 'cols': cols})

    return {'auto': False, 'rules': rules}


def format_metric_value(val, op=None):
    """格式化统计数值（千分位、保留小数等）。"""
    if val is None or val == '':
        return '-'

    if isinstance(val, int) and not isinstance(val, bool):
        return '{:,}'.format(val)

    if isinstance(val, (float, Decimal)):
        if op == 'count':
            return '{:,}'.format(int(val))
        return '{:,.2f}'.format(float(val))

    # 尝试解析为数字格式化
    val_str = str(val).strip()
    try:
        if '.' in val_str:
            return '{:,.2f}'.format(float(val_str))
        return '{:,}'.format(int(val_str))
    except (ValueError, TypeError):
        return val_str


def _try_parse_num(val):
    if val is None:
        return None
    if isinstance(val, (int, float, Decimal)):
        return float(val)
    val_str = str(val).strip().replace(',', '').replace('¥', '').replace('$', '')
    if not val_str:
        return None
    try:
        return float(val_str)
    except (ValueError, TypeError):
        return None


def compute_summary(columns, rows, spec_str):
    """
    计算数据表格的合计行及摘要结构。

    :param columns: 列名列表，如 ['科室', '人次', '金额']
    :param rows: 数据行列表
    :param spec_str: 合计配置字符串，如 'sum:金额,人次; count:体检号' 或 'auto'
    :return: (summary_row, summary_dict)
             summary_row: 与 columns 长度一致的单元格显示文本列表
             summary_dict: {列名: {'op': op, 'value': raw_val, 'formatted': formatted}}
    """
    col_names = [str(c) for c in (columns or [])]
    total_cols = len(col_names)
    if total_cols == 0:
        return [], {}

    parsed = parse_summary_spec(spec_str)
    is_auto = parsed['auto']
    rules = parsed['rules']

    # 建立 列名 -> 聚合指令 的映射
    col_op_map = {}
    for rule in rules:
        op = rule['op']
        for c in rule['cols']:
            col_op_map[c] = op

    # 若为 auto，自动检测数值列
    if is_auto and rows:
        for ci, col in enumerate(col_names):
            if ci == 0:
                continue
            is_numeric_col = False
            for row in rows:
                if ci < len(row):
                    cell = row[ci]
                    if cell is not None and cell != '':
                        parsed_num = _try_parse_num(cell)
                        if parsed_num is not None:
                            is_numeric_col = True
                        else:
                            is_numeric_col = False
                            break
            if is_numeric_col:
                col_op_map[col] = 'sum'

    summary_row = [''] * total_cols
    summary_dict = {}

    row_count = len(rows or [])
    # 逐列计算
    for ci, col in enumerate(col_names):
        op = col_op_map.get(col)
        if not op:
            continue

        values = []
        for r in rows:
            if ci < len(r):
                values.append(r[ci])

        if op == 'count':
            non_null_count = sum(1 for v in values if v is not None and v != '')
            formatted = format_metric_value(non_null_count, op='count')
            summary_row[ci] = formatted
            summary_dict[col] = {
                'op': 'count',
                'value': non_null_count,
                'formatted': formatted
            }
        elif op in ('sum', 'avg', 'min', 'max'):
            nums = [_try_parse_num(v) for v in values]
            nums = [n for n in nums if n is not None]
            if not nums:
                summary_row[ci] = '-'
                summary_dict[col] = {'op': op, 'value': None, 'formatted': '-'}
                continue

            all_ints = all(
                (isinstance(v, int) and not isinstance(v, bool)) or
                (isinstance(v, str) and '.' not in v and v.replace('-', '').isdigit())
                for v in values if v is not None and v != ''
            )

            if op == 'sum':
                res = sum(nums)
                if all_ints:
                    res = int(res)
            elif op == 'avg':
                res = sum(nums) / len(nums)
            elif op == 'min':
                res = min(nums)
                if all_ints:
                    res = int(res)
            elif op == 'max':
                res = max(nums)
                if all_ints:
                    res = int(res)

            formatted = format_metric_value(res, op=op)
            summary_row[ci] = formatted
            summary_dict[col] = {
                'op': op,
                'value': res,
                'formatted': formatted
            }

    # 第一列处理：若第一列未指定聚合操作，则填充合计标识文本
    first_col = col_names[0] if col_names else ''
    if first_col and first_col not in summary_dict:
        label = u'合计 ({:,}条)'.format(row_count) if row_count > 0 else u'合计'
        summary_row[0] = label
        summary_dict[first_col] = {
            'op': 'label',
            'value': label,
            'formatted': label
        }

    return summary_row, summary_dict


def compute_cards(columns, rows):
    """
    为 type = cards 的区块解析指标卡片数据。
    取第一行结果，将每列解析为卡片对象。
    """
    col_names = [str(c) for c in (columns or [])]
    if not col_names or not rows:
        return []

    first_row = rows[0]
    cards = []
    for ci, col in enumerate(col_names):
        val = first_row[ci] if ci < len(first_row) else None
        formatted = format_metric_value(val)
        cards.append({
            'title': col,
            'value': val,
            'formatted': formatted
        })
    return cards
