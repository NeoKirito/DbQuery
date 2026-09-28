# -*- coding: utf-8 -*-
"""
查询服务层 — 桌面版和 Web 版共用的业务逻辑
从 widgets/query_tab.py 中提取，去除 PyQt5 依赖
"""
import os
import datetime
import logging

from form_parser import FormParser
from core.param_service import (
    build_sql_with_params, normalize_params, resolve_default, static_options
)

logger = logging.getLogger('DBQuery.query_service')


# ════════════════════════════════════════
#  SQL 构建
# ════════════════════════════════════════

def escape_sql_param(value):
    """转义参数值中的单引号，防止 SQL 语法错误"""
    return value.replace("'", "''")


def build_final_sql(form, param_values, options_by_name=None, already_normalized=False, sql_template=None):
    """根据表单定义构建最终 SQL。

    只接受 ``form.params`` 中声明的参数名；未知客户端字段不会参与替换。动态
    select 的候选项由调用方通过 ``options_by_name`` 提供，避免将 label 或任意
    搜索词误当成 SQL 参数。
    """
    normalized = param_values if already_normalized else normalize_params(
        form, param_values, options_by_name=options_by_name
    )
    return build_sql_with_params(form, normalized, sql_template=sql_template)


# ════════════════════════════════════════
#  结果数据过滤/排序（纯数据，无 UI 依赖）
# ════════════════════════════════════════

class ResultData:
    """查询结果的纯数据表示，支持过滤和排序"""

    def __init__(self, columns, rows):
        self.columns = columns
        self.rows = rows

    def filter(self, text, col_idx=-1):
        """
        过滤结果
        :param text: 过滤关键字（大小写不敏感）
        :param col_idx: 列索引，-1 表示全部列
        :return: 新的 ResultData
        """
        if not text:
            return ResultData(self.columns, list(self.rows))

        text_lower = text.lower()
        filtered = []
        for row in self.rows:
            if col_idx >= 0:
                if col_idx < len(row):
                    cell = str(row[col_idx] or '').lower()
                    if text_lower in cell:
                        filtered.append(row)
            else:
                for val in row:
                    cell = str(val or '').lower()
                    if text_lower in cell:
                        filtered.append(row)
                        break

        return ResultData(self.columns, filtered)

    def sort(self, col_idx, descending=False):
        """
        排序结果
        :param col_idx: 列索引
        :param descending: 是否降序
        :return: 新的 ResultData
        """
        def sort_key(row):
            v = row[col_idx] if col_idx < len(row) else None
            if v is None:
                return (1, '')
            return (0, str(v))

        sorted_rows = sorted(self.rows, key=sort_key, reverse=descending)
        return ResultData(self.columns, sorted_rows)

    @property
    def row_count(self):
        return len(self.rows)

    @property
    def col_count(self):
        return len(self.columns)


# ════════════════════════════════════════
#  Excel 导出（纯 openpyxl，无 PyQt5）
# ════════════════════════════════════════

def export_to_excel(path, columns, rows, form_title='', form_desc='',
                    elapsed=0.0, params_info=None, final_sql='', summary_row=None, blocks=None):
    """
    将查询结果导出为 Excel 文件
    :param path: 保存路径
    :param columns: 列名列表
    :param rows: 数据行列表
    :param form_title: 表单标题
    :param form_desc: 表单描述
    :param elapsed: 查询耗时（秒）
    :param params_info: [(label, value), ...] 查询参数信息
    :param final_sql: 最终执行的 SQL
    :param summary_row: 底部合计行（可选）
    :param blocks: 多区块数据列表（可选）
    """
    import openpyxl
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    from openpyxl.utils import get_column_letter

    if params_info is None:
        params_info = []

    wb = openpyxl.Workbook()

    # 判定当前主查询结果 (columns) 是否已作为命名区块包含在 blocks 中
    main_already_in_blocks = False
    if blocks:
        for b in blocks:
            if b.get('type') == 'table' and b.get('columns') == columns:
                main_already_in_blocks = True
                break

    # ── Sheet1: 查询结果（仅在非多区块或主表未在区块中重复定义时创建）──
    ws = wb.active
    if ws is None:
        ws = wb.create_sheet()
    first_ws_used = False
    if not main_already_in_blocks:
        ws.title = u"查询结果"
        first_ws_used = True

    hdr_fill  = PatternFill("solid", fgColor="1A6EB5")
    hdr_font  = Font(color="FFFFFF", bold=True, name="微软雅黑", size=10)
    even_fill = PatternFill("solid", fgColor="F8FAFC")
    thin_border = Side(style='thin', color='CBD5E1')
    table_border = Border(left=thin_border, right=thin_border, top=thin_border, bottom=thin_border)
    sum_top_border = Side(style='thin', color='94A3B8')
    sum_bot_border = Side(style='double', color='1A6EB5')
    sum_border = Border(left=thin_border, right=thin_border, top=sum_top_border, bottom=sum_bot_border)

    center      = Alignment(horizontal='center', vertical='center')
    align_left  = Alignment(horizontal='left', vertical='center')
    align_right = Alignment(horizontal='right', vertical='center')

    def _write_table_sheet(target_ws, t_cols, t_rows, t_summary):
        try:
            target_ws.views.sheetView[0].showGridLines = True
        except Exception:
            pass

        target_ws.row_dimensions[1].height = 26

        # 智能判定各列的数据对齐方式（数值右对齐，日期居中，文本左对齐）
        col_alignments = []
        for ci in range(len(t_cols)):
            is_num = True
            is_date = True
            has_data = False
            for r in t_rows[:15]:
                if ci < len(r) and r[ci] is not None and r[ci] != '':
                    has_data = True
                    val = r[ci]
                    if not isinstance(val, (int, float)):
                        try:
                            float(str(val).replace(',', ''))
                        except ValueError:
                            is_num = False
                    if not isinstance(val, (datetime.datetime, datetime.date)):
                        is_date = False
            if has_data and is_num:
                col_alignments.append(align_right)
            elif has_data and is_date:
                col_alignments.append(center)
            else:
                col_alignments.append(align_left)

        # 表头
        for ci, col_name in enumerate(t_cols, 1):
            cell = target_ws.cell(row=1, column=ci, value=col_name)
            cell.fill      = hdr_fill
            cell.font      = hdr_font
            cell.border    = table_border
            cell.alignment = center

        # 数据行
        for ri, row in enumerate(t_rows, 2):
            target_ws.row_dimensions[ri].height = 20
            for ci, val in enumerate(row, 1):
                cell = target_ws.cell(row=ri, column=ci, value=val)
                cell.border    = table_border
                cell.alignment = col_alignments[ci - 1] if ci - 1 < len(col_alignments) else align_left
                if ri % 2 == 0:
                    cell.fill = even_fill

        # 合计行（财务双底线专业样式）
        if t_summary and len(t_summary) == len(t_cols):
            s_ri = len(t_rows) + 2
            target_ws.row_dimensions[s_ri].height = 24
            sum_fill = PatternFill("solid", fgColor="EBF3FC")
            sum_font = Font(color="1A6EB5", bold=True, name="微软雅黑", size=10)
            for ci, val in enumerate(t_summary, 1):
                cell = target_ws.cell(row=s_ri, column=ci, value=val)
                cell.border    = sum_border
                cell.fill      = sum_fill
                cell.font      = sum_font
                if ci == 1:
                    cell.alignment = center
                else:
                    cell.alignment = col_alignments[ci - 1] if ci - 1 < len(col_alignments) else align_right

        # 自适应列宽（考虑中文字符宽度）
        for col_idx in range(1, len(t_cols) + 1):
            col_letter = get_column_letter(col_idx)
            max_len = 0
            for row_idx in range(1, min(len(t_rows) + 2, 102)):
                cell = target_ws.cell(row=row_idx, column=col_idx)
                if cell.value is not None:
                    s = str(cell.value)
                    w = sum(2 if ord(c) > 127 else 1 for c in s)
                    if w > max_len:
                        max_len = w
            target_ws.column_dimensions[col_letter].width = min(max(max_len + 3, 11), 48)

        target_ws.freeze_panes = 'A2'

        # 自动筛选（仅针对数据行）
        try:
            last_col_letter = get_column_letter(len(t_cols))
            last_row = len(t_rows) + 1
            target_ws.auto_filter.ref = "A1:{}{}".format(last_col_letter, last_row)
        except Exception:
            pass

    def _write_cards_sheet(target_ws, sheet_title, cards_list):
        try:
            target_ws.views.sheetView[0].showGridLines = True
        except Exception:
            pass

        # 1. 顶部大标题横幅
        banner_fill = PatternFill("solid", fgColor="1A6EB5")
        banner_font = Font(color="FFFFFF", bold=True, name="微软雅黑", size=13)
        target_ws.merge_cells("A1:H1")
        top_cell = target_ws.cell(row=1, column=1, value=u"📊 " + sheet_title + u" - 核心指标看板")
        top_cell.fill = banner_fill
        top_cell.font = banner_font
        top_cell.alignment = Alignment(horizontal='center', vertical='center')
        target_ws.row_dimensions[1].height = 36

        # 2. 像页面一样渲染【并排大字 KPI 视觉卡片】！
        card_colors = [
            {"val": "1E40AF"},  # 经典深蓝
            {"val": "065F46"},  # 翡翠墨绿
            {"val": "92400E"},  # 暖色琥珀
            {"val": "5B21B6"},  # 典雅高贵紫
            {"val": "0E7490"},  # 商务青蓝
        ]

        t_side_thin = Side(style='thin', color='CBD5E1')

        # 每 4 个卡片一行，每个卡片占 2 列
        for idx, card in enumerate(cards_list):
            theme = card_colors[idx % len(card_colors)]
            c_col = (idx % 4) * 2 + 1  # 1, 3, 5, 7
            c_row = 3 + (idx // 4) * 3 # 3, 6, ...

            col_a = get_column_letter(c_col)
            col_b = get_column_letter(c_col + 1)

            # 卡片标题行 (c_row)
            target_ws.merge_cells("{}{}:{}{}".format(col_a, c_row, col_b, c_row))
            t_cell = target_ws.cell(row=c_row, column=c_col, value=card.get('title', ''))
            t_cell.fill = PatternFill("solid", fgColor="F8FAFC")
            t_cell.font = Font(color="64748B", bold=True, name="微软雅黑", size=10)
            t_cell.alignment = Alignment(horizontal='center', vertical='center')
            for col_i in (c_col, c_col + 1):
                target_ws.cell(row=c_row, column=col_i).border = Border(top=t_side_thin, left=t_side_thin, right=t_side_thin)
            target_ws.row_dimensions[c_row].height = 22

            # 卡片数值行 (c_row + 1)
            target_ws.merge_cells("{}{}:{}{}".format(col_a, c_row + 1, col_b, c_row + 1))
            v_cell = target_ws.cell(row=c_row + 1, column=c_col, value=card.get('formatted', ''))
            v_cell.fill = PatternFill("solid", fgColor="FFFFFF")
            v_cell.font = Font(color=theme['val'], bold=True, name="微软雅黑", size=16)
            v_cell.alignment = Alignment(horizontal='center', vertical='center')
            for col_i in (c_col, c_col + 1):
                target_ws.cell(row=c_row + 1, column=col_i).border = Border(bottom=t_side_thin, left=t_side_thin, right=t_side_thin)
            target_ws.row_dimensions[c_row + 1].height = 32

        # 3. 在卡片下方附上详细指标数据清单
        cards_rows_start = 3 + ((len(cards_list) - 1) // 4 + 1) * 3 + 1
        sub_title = target_ws.cell(row=cards_rows_start - 1, column=1, value=u"📋 指标数据明细对照表")
        sub_title.font = Font(color="1E293B", bold=True, name="微软雅黑", size=11)

        t_hdr_fill = PatternFill("solid", fgColor="E6F2FF")
        t_hdr_font = Font(color="1A6EB5", bold=True, name="微软雅黑", size=10)
        headers = [u"序号", u"指标名称", u"统计数值 (显示格式)", u"原始数值"]
        target_ws.row_dimensions[cards_rows_start].height = 24
        for ci, h_name in enumerate(headers, 1):
            c = target_ws.cell(row=cards_rows_start, column=ci, value=h_name)
            c.fill = t_hdr_fill
            c.font = t_hdr_font
            c.border = table_border
            c.alignment = center

        val_font = Font(color="0F172A", bold=True, name="微软雅黑", size=10.5)
        for idx, card in enumerate(cards_list, 1):
            ri = cards_rows_start + idx
            target_ws.row_dimensions[ri].height = 22
            c1 = target_ws.cell(row=ri, column=1, value=idx)
            c2 = target_ws.cell(row=ri, column=2, value=card.get('title', ''))
            c3 = target_ws.cell(row=ri, column=3, value=card.get('formatted', ''))
            c4 = target_ws.cell(row=ri, column=4, value=card.get('raw', ''))
            for c in (c1, c2, c3, c4):
                c.border = table_border
                c.alignment = align_left
            c1.alignment = center
            c3.font = val_font
            c3.alignment = align_right
            c4.alignment = align_right
            if ri % 2 == 0:
                for c in (c1, c2, c3, c4):
                    c.fill = even_fill

        # 设置列宽
        for col_idx in range(1, 9):
            col_letter = get_column_letter(col_idx)
            target_ws.column_dimensions[col_letter].width = 16

    if not main_already_in_blocks:
        _write_table_sheet(ws, columns, rows, summary_row)

    # 若有多区块（表格或指标卡片），追加各自的工作表
    cards_summary_items = []
    if blocks:
        existing_titles = {ws.title} if first_ws_used else set()
        for b in blocks:
            if b.get('type') == 'cards':
                c_list = b.get('cards') or []
                if not c_list and b.get('columns') and b.get('rows'):
                    from core.summary_service import compute_cards
                    c_list = compute_cards(b.get('columns'), b.get('rows'))
                if c_list:
                    for c in c_list:
                        cards_summary_items.append((c.get('title', ''), str(c.get('formatted', ''))))
                    b_title = (b.get('title') or b.get('id') or u'指标总览').strip()
                    invalid_chars = set(r'[]:*?/') | {'\\'}
                    safe_title = ''.join(c for c in b_title if c not in invalid_chars)[:30]
                    if safe_title not in existing_titles:
                        existing_titles.add(safe_title)
                        if not first_ws_used:
                            cards_ws = ws
                            cards_ws.title = safe_title
                            first_ws_used = True
                        else:
                            cards_ws = wb.create_sheet(title=safe_title)
                        _write_cards_sheet(cards_ws, safe_title, c_list)
            elif b.get('type') == 'table' and b.get('columns'):
                b_title = (b.get('title') or b.get('id') or u'表格').strip()
                # openpyxl 表名最长 31 字符且不可包含某些特殊字符
                invalid_chars = set(r'[]:*?/') | {'\\'}
                safe_title = ''.join(c for c in b_title if c not in invalid_chars)[:30]
                if safe_title in existing_titles:
                    continue
                existing_titles.add(safe_title)
                if not first_ws_used:
                    b_ws = ws
                    b_ws.title = safe_title
                    first_ws_used = True
                else:
                    b_ws = wb.create_sheet(title=safe_title)
                _write_table_sheet(b_ws, b['columns'], b.get('rows', []), b.get('summary_row'))

    # ── Sheet2: 查询信息 ──
    ws2 = wb.create_sheet(u"查询信息")
    info_rows = [
        (u"查询项目",   form_title),
        (u"项目说明",   form_desc or ''),
        (u"查询时间",   datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')),
        (u"导出记录数", len(rows)),
        (u"字段数",     len(columns)),
        (u"查询耗时",   u"{:.2f} 秒".format(elapsed)),
        ('', ''),
        (u"—— 查询条件 ——", ''),
    ]
    info_rows += params_info
    if cards_summary_items:
        info_rows += [('', ''), (u"—— 核心指标汇总 ——", '')]
        info_rows += cards_summary_items

    for r_idx, (k, v) in enumerate(info_rows, 1):
        ws2.cell(row=r_idx, column=1, value=k)
        if v != '':
            ws2.cell(row=r_idx, column=2, value=v)

    ws2.column_dimensions['A'].width = 20
    ws2.column_dimensions['B'].width = 50

    wb.save(path)
    logger.info("Excel exported to: %s", path)


# ════════════════════════════════════════
#  参数值序列化（供 Web API 使用）
# ════════════════════════════════════════

def serialize_form(form, base_dir=None):
    """将 QueryForm 序列化为 dict（JSON 友好）"""
    # 将绝对路径转为相对路径（URL 安全，用正斜杠）
    fp = form.file_path
    if base_dir:
        try:
            fp = os.path.relpath(fp, base_dir)
        except ValueError:
            pass
    fp = fp.replace('\\', '/')

    return {
        'title':       form.title,
        'description': form.description,
        'group':       form.group,
        'order':       getattr(form, 'order', None),
        'group_order': getattr(form, 'group_order', None),
        'query_type':  form.query_type,
        'web_enabled': bool(getattr(form, 'web_enabled', False)),
        'datasource':     getattr(form, 'datasource', 'default'),
        'summary_footer': getattr(form, 'summary_footer', ''),
        'blocks': [
            {
                'id':             b.id,
                'title':          b.title,
                'btype':          b.btype,
                'datasource':     b.datasource,
                'width':          b.width,
                'summary_footer': b.summary_footer,
                'order':          b.order,
            }
            for b in getattr(form, 'blocks', []) or []
        ],
        'file_path':   fp,
        'params': [
            {
                'name':    p.name,
                'label':   p.label,
                'ptype':   p.ptype,
                # 保留旧 options 字段，同时提供 value/label 分离的 option_items。
                'options': p.options,
                'option_items': static_options(p),
                'default': resolve_default(p),
                'raw_default': p.default,
                'placeholder': p.placeholder,
                'required': p.required,
                'width': p.width,
                # 浏览器仅知道是否需要请求服务端加载动态候选；SQL 永不下发。
                'dynamic_options': bool(p.options_sql),
                'searchable': p.searchable or p.ptype == 'select',
                'allow_custom': p.allow_custom,

            }
            for p in form.params
        ],
    }


def load_all_forms(forms_dir, web_only=False, config_path=None):
    """加载所有表单，返回按统一规则排序的分组有序字典 OrderedDict（JSON 友好）。

    ``web_only=True`` 时只返回 [meta] 中明确 ``web_enabled = true`` 的表单。
    默认值保持桌面端兼容：桌面仍可加载和管理全部本地表单。
    """
    from collections import OrderedDict
    raw = FormParser.load_forms_from_dir(forms_dir, config_path=config_path)
    base_dir = os.path.dirname(forms_dir)  # 上级目录，路径相对于它（包含 forms/）
    result = OrderedDict()
    for group, forms in raw.items():
        visible_forms = [
            form for form in forms
            if not web_only or bool(getattr(form, 'web_enabled', False))
        ]
        if visible_forms:
            result[group] = [serialize_form(f, base_dir) for f in visible_forms]
    return result
