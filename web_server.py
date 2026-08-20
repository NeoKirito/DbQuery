"""
DBQuery Web 服务。

启动方式：python web_server.py（默认端口 8094）。
"""
import datetime
import functools
import hashlib
import hmac
import logging
import os
import secrets
import sys
import tempfile
import threading
import time
from urllib.parse import unquote

from flask import Flask, jsonify, redirect, render_template, request, send_file, session, url_for
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
from core.param_service import (
    OptionsLoadError, ParameterError, RequiredParameterError, load_options,
    normalize_params, static_options
)

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
# 未配置显式环境变量时，每次服务启动生成新的高熵密钥；服务重启后要求重新登录。
# 这避免将会话密钥写入 .qry、模板或前端链接。
app.config.update(
    SECRET_KEY=os.environ.get('DBQUERY_SESSION_SECRET') or secrets.token_urlsafe(32),
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='Lax',
    PERMANENT_SESSION_LIFETIME=datetime.timedelta(hours=8),
)

_LOGIN_LOCK = threading.Lock()
_LOGIN_FAILURES = {}
_LOGIN_LIMIT = 5
_LOGIN_WINDOW_SECONDS = 300

# 宿主无感登录：签名 nonce 与一次性票据仅保存在当前服务进程内。
_INTEGRATION_LOCK = threading.Lock()
_INTEGRATION_NONCES = {}
_INTEGRATION_TICKETS = {}
_INTEGRATION_MAX_BODY_LENGTH = 8192


def _client_key():
    return request.remote_addr or 'unknown'


def _login_allowed():
    now = time.monotonic()
    key = _client_key()
    with _LOGIN_LOCK:
        history = [stamp for stamp in _LOGIN_FAILURES.get(key, []) if now - stamp < _LOGIN_WINDOW_SECONDS]
        _LOGIN_FAILURES[key] = history
        return len(history) < _LOGIN_LIMIT


def _record_login_failure():
    now = time.monotonic()
    key = _client_key()
    with _LOGIN_LOCK:
        history = [stamp for stamp in _LOGIN_FAILURES.get(key, []) if now - stamp < _LOGIN_WINDOW_SECONDS]
        history.append(now)
        _LOGIN_FAILURES[key] = history


def _clear_login_failures():
    with _LOGIN_LOCK:
        _LOGIN_FAILURES.pop(_client_key(), None)


def _safe_next_url(value):
    value = value or ''
    # 仅允许本站相对路径，避免登录成功后被重定向到外部站点。
    return value if value.startswith('/') and not value.startswith('//') else ''


def _integration_canonical_request(timestamp, nonce, username, password):
    """生成宿主与 DBQuery 两端相同的 HMAC 签名原文。"""
    return 'POST\n/api/integration/sso-ticket\n{}\n{}\n{}\n{}'.format(
        timestamp, nonce, username, password
    )


def _purge_integration_state(now=None):
    now = time.time() if now is None else now
    for bucket in (_INTEGRATION_NONCES, _INTEGRATION_TICKETS):
        for key, item in list(bucket.items()):
            expires_at = item if isinstance(item, (int, float)) else item.get('expires_at', 0)
            if expires_at <= now:
                bucket.pop(key, None)


def _integration_error(message, status=403, error_type='integration_authentication_failed'):
    """返回不泄露服务密钥、凭据或数据库细节的集成错误。"""
    return error_response(message, status, error_type)


def _validate_integration_request(data):
    """验证宿主服务身份、时戳、nonce 和 HMAC；返回配置或 None。"""
    if not isinstance(data, dict):
        return None, _integration_error('无感登录请求格式无效。', 400, 'invalid_integration_request')

    username = str(data.get('username') or '').strip()
    password = str(data.get('password') or '')
    timestamp_text = request.headers.get('X-DBQuery-Integration-Timestamp', '')
    nonce = request.headers.get('X-DBQuery-Integration-Nonce', '')
    signature = request.headers.get('X-DBQuery-Integration-Signature', '')
    if (not username or not password or len(username) > 64 or len(password) > 256 or
            not timestamp_text or not nonce or len(nonce) > 128 or not signature):
        return None, _integration_error('无感登录请求无效。', 400, 'invalid_integration_request')

    try:
        timestamp = int(timestamp_text)
    except (TypeError, ValueError):
        return None, _integration_error('无感登录请求已失效。', 401, 'expired_integration_request')

    cfg = DBManager().get_integration_config()
    if not cfg.get('enabled') or len(cfg.get('shared_key', '')) < 32:
        return None, _integration_error('宿主无感登录尚未启用。', 403, 'integration_not_enabled')
    if abs(time.time() - timestamp) > cfg['max_clock_skew_seconds']:
        return None, _integration_error('无感登录请求已失效。', 401, 'expired_integration_request')

    canonical = _integration_canonical_request(timestamp_text, nonce, username, password)
    expected = hmac.new(
        cfg['shared_key'].encode('utf-8'), canonical.encode('utf-8'), hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(expected, signature.lower()):
        return None, _integration_error('无感登录服务身份验证失败。', 403, 'invalid_integration_signature')

    now = time.time()
    with _INTEGRATION_LOCK:
        _purge_integration_state(now)
        if nonce in _INTEGRATION_NONCES:
            return None, _integration_error('无感登录请求已使用。', 409, 'replayed_integration_request')
        _INTEGRATION_NONCES[nonce] = now + cfg['max_clock_skew_seconds']
    return cfg, None


def _issue_integration_ticket(username, next_url, ttl_seconds):
    ticket = secrets.token_urlsafe(32)
    with _INTEGRATION_LOCK:
        _purge_integration_state()
        _INTEGRATION_TICKETS[ticket] = {
            'username': username,
            'next_url': _safe_next_url(next_url) or url_for('index'),
            'expires_at': time.time() + ttl_seconds,
        }
    return ticket


def _consume_integration_ticket(ticket):
    with _INTEGRATION_LOCK:
        _purge_integration_state()
        # pop 使票据天然只能使用一次，即使后续跳转或会话写入失败也不能重放。
        return _INTEGRATION_TICKETS.pop(ticket, None)


def _unauthenticated_response():
    if request.path.startswith('/api/'):
        return error_response('请先登录后再访问查询服务。', 401, 'authentication_required')
    target = request.full_path if request.query_string else request.path
    return redirect(url_for('login', next=_safe_next_url(target)))


def login_required(view):
    """对页面与 API 使用同一会话强制认证。"""
    @functools.wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get('auth_user'):
            return _unauthenticated_response()
        return view(*args, **kwargs)
    return wrapped


@app.after_request
def apply_security_headers(response):
    # 查询页面和 API 不保留在浏览器缓存中，避免登出后从历史缓存读取数据。
    if not request.path.startswith('/static/'):
        response.headers['Cache-Control'] = 'no-store, max-age=0'
        response.headers['Pragma'] = 'no-cache'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['Referrer-Policy'] = 'same-origin'
    return response


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
        'current_user': session.get('auth_user', ''),
        'page_name': 'app',
    }


def error_response(message, status=500, error_type=None):
    """返回一致的 API 错误 JSON，便于前端页内提示。"""
    payload = {'error': message}
    if error_type:
        payload['error_type'] = error_type
    return jsonify(payload), status


def get_form_from_path(file_path):
    """仅加载 Web 明确启用的 forms 内 .qry，拒绝路径穿越和未授权表单。"""
    decoded_path = unquote(file_path or '').replace('\\', '/')
    abs_path = os.path.realpath(os.path.join(BASE_DIR, decoded_path))
    forms_root = os.path.realpath(FORMS_DIR)
    try:
        is_form_path = os.path.commonpath([forms_root, abs_path]) == forms_root
    except ValueError:
        is_form_path = False
    if not is_form_path or not abs_path.lower().endswith('.qry') or not os.path.isfile(abs_path):
        return None, decoded_path, None
    form = FormParser.parse_file(abs_path)
    if not bool(getattr(form, 'web_enabled', False)):
        return None, decoded_path, None
    return form, decoded_path, abs_path


def normalize_rows(rows):
    """将 bytes 转为可读文本；日期由 JSON provider 统一处理。"""
    safe_rows = []
    for row in rows:
        safe_rows.append([
            value.decode('utf-8', errors='replace') if isinstance(value, bytes) else value
            for value in row
        ])
    return safe_rows


def form_options(form, db_manager):
    """加载当前表单所有 select 的 value/label 候选，失败时保留静态项。"""
    options_by_name = {}
    warnings = []
    for param in form.params:
        if param.ptype != 'select':
            continue
        try:
            options_by_name[param.name] = load_options(param, db_manager)
        except OptionsLoadError:
            logger.exception('查询前加载动态候选失败: %s', param.name)
            options_by_name[param.name] = static_options(param)
            warnings.append(param.name)
    return options_by_name, warnings


def _csrf_token():
    token = session.get('csrf_token')
    if not token:
        token = secrets.token_urlsafe(24)
        session['csrf_token'] = token
    return token


@app.route('/api/integration/sso-ticket', methods=['POST'])
def issue_integration_ticket():
    """供宿主后端调用：验证签名与当前操作员凭据后签发一次性短期票据。"""
    if request.content_length is not None and request.content_length > _INTEGRATION_MAX_BODY_LENGTH:
        return _integration_error('无感登录请求过大。', 413, 'invalid_integration_request')
    data = request.get_json(silent=True)
    cfg, failure = _validate_integration_request(data)
    if failure is not None:
        return failure

    username = str(data.get('username') or '').strip()
    password = str(data.get('password') or '')
    if not DBManager().authenticate_user(username, password):
        return _integration_error('无感登录凭据无效。', 401, 'invalid_integration_credentials')

    ticket = _issue_integration_ticket(username, data.get('next'), cfg['ticket_ttl_seconds'])
    logger.info('Issued a one-time host integration ticket')
    return jsonify({
        'ticket': ticket,
        'expires_in': cfg['ticket_ttl_seconds'],
        'consume_path': url_for('consume_integration_ticket'),
    })


@app.route('/sso/consume', methods=['POST'])
def consume_integration_ticket():
    """供宿主页面以 iframe POST 消费短期票据，建立浏览器会话且不显示登录页。"""
    ticket = request.form.get('ticket', '')
    if not ticket or len(ticket) > 256:
        return '宿主登录票据无效，请返回宿主程序重新进入。', 401
    state = _consume_integration_ticket(ticket)
    if not state:
        return '宿主登录票据已失效，请返回宿主程序重新进入。', 401

    session.clear()
    session['auth_user'] = state['username']
    session['auth_source'] = 'host_integration'
    session['csrf_token'] = secrets.token_urlsafe(24)
    session.permanent = True
    logger.info('Consumed a one-time host integration ticket')
    return redirect(state['next_url'])


@app.route('/login', methods=['GET', 'POST'])
def login():
    """Web 与嵌入页共用的账号密码登录入口。"""
    if session.get('auth_user'):
        return redirect(_safe_next_url(request.args.get('next')) or url_for('index'))

    next_url = _safe_next_url(request.values.get('next'))
    error = ''
    if request.method == 'POST':
        if request.form.get('csrf_token', '') != session.get('csrf_token', ''):
            return render_template('login.html', error=u'登录页面已失效，请刷新后重试。',
                                   next_url=next_url, csrf_token=_csrf_token(),
                                   page_name='login'), 400
        if not _login_allowed():
            return render_template('login.html', error=u'登录尝试过于频繁，请稍后再试。',
                                   next_url=next_url, csrf_token=_csrf_token(),
                                   page_name='login'), 429

        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        if DBManager().authenticate_user(username, password):
            session.clear()
            session['auth_user'] = username
            session['csrf_token'] = secrets.token_urlsafe(24)
            session.permanent = True
            _clear_login_failures()
            return redirect(next_url or url_for('index'))

        _record_login_failure()
        error = u'账号、密码无效，账号可能未启用，或数据服务暂不可用。'

    return render_template('login.html', error=error, next_url=next_url,
                           csrf_token=_csrf_token(), page_name='login')


@app.route('/logout', methods=['POST'])
@login_required
def logout():
    if request.form.get('csrf_token', '') != session.get('csrf_token', ''):
        return '请求无效，请刷新页面后重试。', 400
    session.clear()
    return redirect(url_for('login'))


@app.route('/')
@login_required
def index():
    """首页：仅显示已显式允许 Web 访问的表单列表。"""
    page_context = get_embed_context()
    return render_template(
        'index.html', forms_data=load_all_forms(FORMS_DIR, web_only=True),
        csrf_token=_csrf_token(), **page_context
    )


@app.route('/query/<path:file_path>')
@login_required
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
        csrf_token=_csrf_token(),
        **page_context
    )


@app.route('/api/forms')
@login_required
def api_forms():
    """返回已明确授权给 Web 的表单 JSON。"""
    return jsonify(load_all_forms(FORMS_DIR, web_only=True))


@app.route('/api/options', methods=['POST'])
@login_required
def api_options():
    """按表单路径和参数名加载配置中的候选项，绝不接收客户端 SQL。"""
    data = request.get_json(silent=True) or {}
    file_path = data.get('file_path', '')
    param_name = data.get('param_name', '')
    if not isinstance(param_name, str) or not param_name:
        return error_response('查询条件信息不完整，请重新操作。', 400)

    try:
        form, decoded_path, _ = get_form_from_path(file_path)
    except Exception:
        logger.exception('候选项表单解析失败: %s', file_path)
        return error_response('查询配置加载失败，请联系管理员。', 500)
    if form is None:
        return error_response('查询方案不存在或已停用。', 404)

    param = next((item for item in form.params if item.name == param_name), None)
    if param is None or param.ptype != 'select':
        return error_response('查询条件不存在或不支持候选项加载。', 404)

    fallback = static_options(param)
    try:
        options = load_options(param, DBManager())
        return jsonify({'options': options, 'warning': ''})
    except OptionsLoadError:
        logger.exception('动态候选加载失败: %s / %s', decoded_path, param_name)
        # 静态项可继续工作；不给浏览器泄露数据库异常。
        return jsonify({'options': fallback, 'warning': '候选数据加载失败，可刷新重试。'})


@app.route('/api/test-connection')
@login_required
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
@login_required
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

    try:
        db_manager = DBManager()
        options_by_name, option_warnings = form_options(form, db_manager)
        normalized_params = normalize_params(form, params, options_by_name=options_by_name)
        sql = build_final_sql(form, normalized_params, already_normalized=True)
    except RequiredParameterError:
        # 保留既有 Web API 的业务提示，前端和历史集成方均可兼容。
        return error_response('请填写完整的查询条件。', 400)
    except ParameterError as exc:
        return error_response(str(exc), 400)
    except Exception:
        logger.exception('查询条件处理失败: %s', decoded_path)
        return error_response('查询条件处理失败，请联系管理员。', 500)

    # 现有安全检查不可删除、不可削弱。
    safe, reason = FormParser.is_safe_sql(sql, form.query_type)
    if not safe:
        logger.warning('查询配置未通过安全检查: %s; 原因: %s', decoded_path, reason)
        return error_response('当前查询配置无法执行，请联系管理员。', 400)

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
        'option_warnings': option_warnings,
    })


@app.route('/api/export', methods=['POST'])
@login_required
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
            normalized_params = normalize_params(form, params)
            final_sql = build_final_sql(form, normalized_params, already_normalized=True)
            params_info = [
                (param.label, normalized_params.get(param.name, ''))
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
