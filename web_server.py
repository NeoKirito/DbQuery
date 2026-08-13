"""
DBQuery Web 服务。

启动方式：python web_server.py（默认端口 8094）。
"""
import datetime
import logging
import os
import sys
import tempfile
import threading
import time
from urllib.parse import unquote

from flask import Flask, jsonify, render_template, request, send_file
from flask.json.provider import DefaultJSONProvider

if getattr(sys, 'frozen', False):
    # PyInstaller 5 的 onedir 与 PyInstaller 6 的 _internal 布局均可解析。
    BASE_DIR = getattr(sys, '_MEIPASS', os.path.dirname(sys.executable))
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

sys.path.insert(0, BASE_DIR)

from db_manager import DBManager, QueryTimeoutError
from form_parser import FormParser
from core.query_service import build_final_sql, export_to_excel, load_all_forms, serialize_form

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('DBQuery.web')

FORMS_DIR = os.path.join(BASE_DIR, 'forms')


class DBQueryJSONProvider(DefaultJSONProvider):
    """处理 datetime 等非标准 JSON 类型。"""

    def default(self, obj, **kwargs):
        if isinstance(obj, (datetime.datetime, datetime.date)):
            return str(obj)
        if isinstance(obj, bytes):
            return obj.decode('utf-8', errors='replace')
        return super().default(obj, **kwargs)


app = Flask(
    __name__,
    template_folder=os.path.join(BASE_DIR, 'templates'),
    static_folder=os.path.join(BASE_DIR, 'static')
)
app.json_provider_class = DBQueryJSONProvider
app.json = DBQueryJSONProvider(app)


def get_embed_context():
    """统一解析页面级嵌入状态，供所有页面模板复用。"""
    hide_header = request.args.get('hide_header') == '1'
    embed = request.args.get('embed') == '1' or hide_header
    sidebar_arg = request.args.get('sidebar')
    # 嵌入宿主通常已有自己的导航；仅在显式 sidebar=1 时保留 DbQuery 侧栏。
    sidebar_hidden = sidebar_arg == '0' or (embed and sidebar_arg != '1')
    return {
        'embed_mode': embed,
        'hide_header': hide_header or embed,
        'sidebar_hidden': sidebar_hidden,
    }


def error_response(message, status=500, error_type=None):
    """返回一致的 API 错误 JSON，便于前端页内提示。"""
    payload = {'error': message}
    if error_type:
        payload['error_type'] = error_type
    return jsonify(payload), status


def get_form_from_path(file_path):
    """加载并解析请求指定的表单，保持既有相对路径约定。"""
    decoded_path = unquote(file_path or '')
    abs_path = os.path.join(BASE_DIR, decoded_path)
    if not os.path.isfile(abs_path):
        return None, decoded_path, None
    return FormParser.parse_file(abs_path), decoded_path, abs_path


def normalize_rows(rows):
    """将 bytes 转为可读文本；日期由 JSON provider 统一处理。"""
    safe_rows = []
    for row in rows:
        safe_rows.append([
            value.decode('utf-8', errors='replace') if isinstance(value, bytes) else value
            for value in row
        ])
    return safe_rows


def has_missing_required_params(form, params):
    """在服务端重复执行必填校验，防止绕过浏览器端校验。"""
    for param in form.params:
        if not param.required:
            continue
        value = params.get(param.name)
        if param.ptype == 'checkbox':
            if str(value or '') != '1':
                return True
        elif value is None or not str(value).strip():
            return True
    return False


@app.route('/')
def index():
    """首页：表单列表。"""
    page_context = get_embed_context()
    return render_template(
        'index.html', forms_data=load_all_forms(FORMS_DIR), **page_context
    )


@app.route('/query/<path:file_path>')
def query_page(file_path):
    """查询页面。"""
    page_context = get_embed_context()
    try:
        form, decoded_path, _ = get_form_from_path(file_path)
    except Exception as exc:
        logger.exception('表单解析失败: %s', file_path)
        return '查询配置加载失败，请联系管理员。', 500
    if form is None:
        return '查询方案不存在或已停用。', 404
    return render_template(
        'query.html',
        form=serialize_form(form, BASE_DIR),
        file_path=decoded_path,
        **page_context
    )


@app.route('/api/forms')
def api_forms():
    """返回所有表单 JSON。"""
    return jsonify(load_all_forms(FORMS_DIR))


@app.route('/api/test-connection')
def api_test_connection():
    """使用独立连接测试数据库连通性。"""
    try:
        ok, _ = DBManager().test_connection()
        message = '数据服务连接正常' if ok else '数据服务连接异常，请稍后重试。'
        return jsonify({'success': ok, 'message': message})
    except Exception as exc:
        logger.exception('数据库连接测试失败')
        return jsonify({'success': False, 'message': '数据服务连接异常，请稍后重试。'})


@app.route('/api/query', methods=['POST'])
def api_query():
    """执行受超时与行数限制保护的查询。"""
    data = request.get_json(silent=True)
    if not data:
        return error_response('请求信息不完整，请重新操作。', 400)

    file_path = data.get('file_path', '')
    params = data.get('params') or {}
    if not isinstance(params, dict):
        return error_response('查询条件格式不正确，请重新操作。', 400)

    try:
        form, decoded_path, _ = get_form_from_path(file_path)
    except Exception as exc:
        logger.exception('表单解析失败: %s', file_path)
        return error_response('查询配置加载失败，请联系管理员。', 500)
    if form is None:
        return error_response('查询方案不存在或已停用。', 404)
    if has_missing_required_params(form, params):
        return error_response('请填写完整的查询条件。', 400)

    try:
        sql = build_final_sql(form, params)
    except Exception as exc:
        logger.exception('查询条件处理失败: %s', decoded_path)
        return error_response('查询条件处理失败，请联系管理员。', 500)

    # 现有安全检查不可删除、不可削弱。
    safe, reason = FormParser.is_safe_sql(sql, form.query_type)
    if not safe:
        logger.warning('查询配置未通过安全检查: %s; 原因: %s', decoded_path, reason)
        return error_response('当前查询配置无法执行，请联系管理员。', 400)

    db_manager = DBManager()
    web_config = db_manager.get_web_config()
    started_at = time.monotonic()
    try:
        columns, rows, truncated = db_manager.execute_query_limited(
            sql,
            query_timeout=web_config['query_timeout'],
            max_rows=web_config['max_rows'],
            query_type=form.query_type
        )
    except QueryTimeoutError:
        return error_response(
            '查询超时，请缩小查询范围或增加查询条件。', 408, 'timeout'
        )
    except Exception as exc:
        logger.exception('查询执行失败: %s', decoded_path)
        return error_response('数据服务暂时不可用，请稍后重试。', 500)

    safe_rows = normalize_rows(rows)
    return jsonify({
        'columns': columns,
        'rows': safe_rows,
        'elapsed': round(time.monotonic() - started_at, 2),
        'row_count': len(safe_rows),
        'col_count': len(columns),
        'truncated': truncated,
        'max_rows': web_config['max_rows'],
    })


@app.route('/api/export', methods=['POST'])
def api_export():
    """将当前页查询结果导出为带元信息的 Excel 文件。"""
    data = request.get_json(silent=True)
    if not data:
        return error_response('请求信息不完整，请重新操作。', 400)

    file_path = data.get('file_path', '')
    params = data.get('params') or {}
    columns = data.get('columns') or []
    rows = data.get('rows') or []
    if not columns:
        return error_response('暂无可导出的查询结果。', 400)
    if not isinstance(params, dict) or not isinstance(rows, list):
        return error_response('导出信息不完整，请重新操作。', 400)

    form_title = ''
    form_desc = ''
    params_info = []
    final_sql = ''
    elapsed = data.get('elapsed', 0.0)

    try:
        form, _, _ = get_form_from_path(file_path)
        if form is not None:
            form_title = form.title
            form_desc = form.description
            final_sql = build_final_sql(form, params)
            params_info = [
                (param.label, params.get(param.name, ''))
                for param in form.params
            ]
    except Exception:
        logger.warning('导出时无法读取表单元信息: %s', file_path, exc_info=True)

    timestamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    filename = '{}_{}.xlsx'.format(form_title or 'export', timestamp)
    file_descriptor, export_path = tempfile.mkstemp(prefix='dbquery_', suffix='.xlsx')
    os.close(file_descriptor)

    try:
        export_to_excel(
            export_path, columns, rows,
            form_title, form_desc, elapsed, params_info, final_sql
        )
        response = send_file(
            export_path,
            as_attachment=True,
            download_name=filename,
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        )
        return response
    except Exception as exc:
        logger.exception('Excel 导出失败')
        try:
            os.remove(export_path)
        except OSError:
            pass
        return error_response('导出失败，请稍后重试。', 500)
    finally:
        # send_file 返回后仍需要文件；延迟清理避免 Windows 文件锁冲突。
        threading.Timer(30, _remove_file_quietly, args=[export_path]).start()


def _remove_file_quietly(file_path):
    try:
        if os.path.exists(file_path):
            os.remove(file_path)
    except OSError:
        pass


def get_local_ip():
    """获取本机局域网 IP。"""
    import socket
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.connect(('8.8.8.8', 80))
        ip = sock.getsockname()[0]
        sock.close()
        return ip
    except Exception:
        return '127.0.0.1'


if __name__ == '__main__':
    local_ip = get_local_ip()
    logger.info('=' * 50)
    logger.info('DBQuery Web Server starting...')
    logger.info('Forms directory: %s', FORMS_DIR)
    logger.info('Local Access: http://localhost:8094')
    logger.info('Network Access: http://%s:8094', local_ip)
    logger.info('=' * 50)
    app.run(host='0.0.0.0', port=8094, debug=False, threaded=True)
