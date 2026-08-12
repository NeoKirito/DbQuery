# -*- coding: utf-8 -*-
"""
DBQuery Web 服务
启动方式：python web_server.py
浏览器访问：http://localhost:5000
"""
import os
import sys
import time
import datetime
import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import unquote

from flask import Flask, render_template, request, jsonify, send_file
from flask.json.provider import DefaultJSONProvider

# ── 路径设置 ──
if getattr(sys, 'frozen', False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

sys.path.insert(0, BASE_DIR)

from db_manager import DBManager
from form_parser import FormParser
from core.query_service import (
    build_final_sql, export_to_excel, serialize_form, load_all_forms
)

# ── 日志 ──
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('DBQuery.web')

# ── 常量 ──
FORMS_DIR = os.path.join(BASE_DIR, 'forms')


# ════════════════════════════════════════
#  JSON 序列化辅助
# ════════════════════════════════════════

class DBQueryJSONProvider(DefaultJSONProvider):
    """处理 datetime 等非标准 JSON 类型"""
    def default(self, obj, **kwargs):
        if isinstance(obj, (datetime.datetime, datetime.date)):
            return str(obj)
        if isinstance(obj, bytes):
            return obj.decode('utf-8', errors='replace')
        return super(DBQueryJSONProvider, self).default(obj, **kwargs)


# ── Flask 应用 ──
app = Flask(__name__,
            template_folder=os.path.join(BASE_DIR, 'templates'),
            static_folder=os.path.join(BASE_DIR, 'static'))
app.json_provider_class = DBQueryJSONProvider
app.json = DBQueryJSONProvider(app)

# ── 全局对象 ──
db_manager = DBManager()
executor = ThreadPoolExecutor(max_workers=4)
db_lock = threading.Lock()  # DBManager 非线程安全，查询时加锁


# ════════════════════════════════════════
#  页面路由
# ════════════════════════════════════════

@app.route('/')
def index():
    """首页 — 表单列表"""
    hide_header = request.args.get('hide_header') == '1'
    forms_data = load_all_forms(FORMS_DIR)
    return render_template('index.html', forms_data=forms_data, hide_header=hide_header)


@app.route('/query/<path:file_path>')
def query_page(file_path):
    """查询页面"""
    hide_header = request.args.get('hide_header') == '1'
    file_path = unquote(file_path)  # 解码 %23 → #
    abs_path = os.path.join(BASE_DIR, file_path)
    if not os.path.isfile(abs_path):
        return "表单不存在", 404
    try:
        form = FormParser.parse_file(abs_path)
        form_data = serialize_form(form, BASE_DIR)
    except Exception as e:
        return "表单解析失败: {}".format(e), 500
    return render_template('query.html', form=form_data, file_path=file_path, hide_header=hide_header)


# ════════════════════════════════════════
#  API 路由
# ════════════════════════════════════════

@app.route('/api/forms')
def api_forms():
    """返回所有表单 JSON"""
    forms_data = load_all_forms(FORMS_DIR)
    return jsonify(forms_data)


@app.route('/api/test-connection')
def api_test_connection():
    """测试数据库连接"""
    try:
        db_manager.load_config()
        ok, msg = db_manager.test_connection()
        return jsonify({'success': ok, 'message': msg})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})


@app.route('/api/query', methods=['POST'])
def api_query():
    """执行查询"""
    data = request.get_json()
    if not data:
        return jsonify({'error': '请求数据为空'}), 400

    file_path = unquote(data.get('file_path', ''))  # 解码 %23 → #
    params = data.get('params', {})

    # 解析表单
    abs_path = os.path.join(BASE_DIR, file_path)
    if not os.path.isfile(abs_path):
        return jsonify({'error': '表单文件不存在: ' + file_path}), 404

    try:
        form = FormParser.parse_file(abs_path)
    except Exception as e:
        return jsonify({'error': '表单解析失败: {}'.format(e)}), 500

    # 构建 SQL
    try:
        sql = build_final_sql(form, params)
    except Exception as e:
        return jsonify({'error': 'SQL 构建失败: {}'.format(e)}), 500

    # 安全检查
    ok, reason = FormParser.is_safe_sql(sql, form.query_type)
    if not ok:
        return jsonify({'error': 'SQL 安全检查未通过: {}'.format(reason)}), 400

    # 执行查询（线程池 + 锁）
    start_time = time.time()
    try:
        with db_lock:
            db_manager.load_config()
            columns, rows = db_manager.execute_query(sql)
        elapsed = time.time() - start_time
    except Exception as e:
        return jsonify({'error': '查询执行失败: {}'.format(e)}), 500

    # 序列化结果（处理 datetime 等类型）
    safe_rows = []
    for row in rows:
        safe_row = []
        for val in row:
            if isinstance(val, (datetime.datetime, datetime.date)):
                safe_row.append(str(val))
            elif isinstance(val, bytes):
                safe_row.append(val.decode('utf-8', errors='replace'))
            else:
                safe_row.append(val)
        safe_rows.append(safe_row)

    return jsonify({
        'columns': columns,
        'rows': safe_rows,
        'elapsed': round(elapsed, 2),
        'row_count': len(safe_rows),
        'col_count': len(columns),
    })


@app.route('/api/export', methods=['POST'])
def api_export():
    """导出 Excel"""
    data = request.get_json()
    if not data:
        return jsonify({'error': '请求数据为空'}), 400

    file_path = unquote(data.get('file_path', ''))  # 解码 %23 → #
    params = data.get('params', {})
    columns = data.get('columns', [])
    rows = data.get('rows', [])

    if not columns:
        return jsonify({'error': '没有可导出的数据'}), 400

    # 解析表单信息
    abs_path = os.path.join(BASE_DIR, file_path)
    form_title = ''
    form_desc = ''
    params_info = []
    final_sql = ''
    elapsed = data.get('elapsed', 0.0)

    if os.path.isfile(abs_path):
        try:
            form = FormParser.parse_file(abs_path)
            form_title = form.title
            form_desc = form.description
            final_sql = build_final_sql(form, params)
            for p in form.params:
                params_info.append((p.label, params.get(p.name, '')))
        except Exception:
            pass

    # 生成文件名
    timestamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    filename = u"{}_{}.xlsx".format(form_title or 'export', timestamp)
    export_path = os.path.join(BASE_DIR, 'temp_' + filename)

    try:
        export_to_excel(
            export_path, columns, rows,
            form_title, form_desc, elapsed, params_info, final_sql
        )
        return send_file(
            export_path,
            as_attachment=True,
            download_name=filename,
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        )
    except Exception as e:
        return jsonify({'error': '导出失败: {}'.format(e)}), 500
    finally:
        # 延迟清理临时文件
        try:
            if os.path.exists(export_path):
                threading.Timer(30, os.remove, args=[export_path]).start()
        except Exception:
            pass


# ════════════════════════════════════════
#  入口
# ════════════════════════════════════════

def get_local_ip():
    """获取本机局域网 IP"""
    import socket
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return '127.0.0.1'

if __name__ == '__main__':
    local_ip = get_local_ip()
    logger.info("=" * 50)
    logger.info("DBQuery Web Server starting...")
    logger.info("Forms directory: %s", FORMS_DIR)
    logger.info("Local Access:  http://localhost:5000")
    logger.info("Network Access: http://%s:5000", local_ip)
    logger.info("=" * 50)
    app.run(host='0.0.0.0', port=5000, debug=False, threaded=True)
