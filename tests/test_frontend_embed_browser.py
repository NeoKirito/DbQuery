# -*- coding: utf-8 -*-
"""真实 Chromium 保护性烟雾测试；不连接 SQL Server，也不产生截图或浏览器制品。"""
import contextlib
import os
import shutil
import threading
from wsgiref.util import setup_testing_defaults
from unittest.mock import patch

import pytest
from werkzeug.middleware.dispatcher import DispatcherMiddleware
from werkzeug.serving import make_server

import web_server
from form_parser import QueryForm, QueryParam


class BrowserEmbedManager:
    """为真实浏览器路径提供无数据库、可审计的认证和 Embed 配置。"""

    def __init__(self, origin):
        self.origin = origin
        self.authenticate_calls = []

    def get_integration_config(self):
        return {
            'frontend_embed_enabled': True,
            'frontend_embed_allowed_origins': [self.origin],
            'frontend_embed_session_minutes': 60,
            'frame_ancestors': [self.origin],
        }

    def authenticate_user(self, username, password):
        self.authenticate_calls.append((username, password))
        return username == 'browser-user' and password == 'browser-password'


def _browser_form():
    form = QueryForm()
    form.file_path = os.path.join(web_server.FORMS_DIR, 'browser-smoke.qry')
    form.title = '浏览器 Smoke 表单'
    form.description = 'Browser Embed smoke form'
    form.public_id = 'person-detail'
    form.web_enabled = True
    form.query_type = 'select'
    form.sql = "SELECT '{tjh}' AS TJH, '{hidden_value}' AS HiddenValue"
    form.params = [
        QueryParam('tjh', '体检号', 'text', default='', required=True, external_allowed=True),
        QueryParam('hidden_value', '内部值', 'hidden', default='server-only', external_allowed=True),
    ]
    return form


def _host_app(environ, start_response):
    """PEIS-like same-origin host that deliberately owns the generic `session` cookie."""
    setup_testing_defaults(environ)
    if environ.get('PATH_INFO') != '/host':
        start_response('404 Not Found', [('Content-Type', 'text/plain; charset=utf-8')])
        return [b'not found']
    page = b'''<!doctype html><html><head><meta charset="utf-8">
    <script src="/dbquery/static/js/dbquery-embed.js"></script></head>
    <body><main id="host-app"><div id="embed"></div></main></body></html>'''
    start_response('200 OK', [
        ('Content-Type', 'text/html; charset=utf-8'),
        ('Set-Cookie', 'session=PEIS_SESSION_VALUE; Path=/; HttpOnly; SameSite=Lax'),
    ])
    return [page]


@contextlib.contextmanager
def _browser_server():
    app = DispatcherMiddleware(_host_app, {'/dbquery': web_server.app})
    server = make_server('127.0.0.1', 0, app)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield 'http://127.0.0.1:{}'.format(server.server_port)
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


def test_same_origin_subpath_embed_smoke_in_real_chromium():
    """Run the SDK as a host page would: session probe, password exchange, ctx iframe, then scoped logout."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        pytest.skip('Python Playwright is unavailable in this test environment')
    chromium = shutil.which('chromium') or shutil.which('chromium-browser')
    if not chromium:
        pytest.skip('Chromium executable is unavailable in this test environment')

    web_server.app.config.update(
        TESTING=True,
        SECRET_KEY='browser-embed-test-secret',
        SESSION_COOKIE_NAME='dbquery_session',
        SESSION_COOKIE_PATH='/dbquery',
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE='Lax',
        SESSION_COOKIE_SECURE=False,
    )
    form = _browser_form()
    with web_server._INTEGRATION_LOCK:
        web_server._EMBED_CONTEXTS.clear()
    with _browser_server() as origin:
        manager = BrowserEmbedManager(origin)
        with patch('web_server.DBManager', return_value=manager), patch(
                'web_server.FormParser.load_forms_from_dir', return_value={'Browser': [form]}):
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(
                    executable_path=chromium, headless=True, args=['--no-sandbox']
                )
                context = browser.new_context()
                page = context.new_page()
                session_request_headers = []
                page.on('request', lambda req: session_request_headers.append(req.headers)
                        if '/dbquery/api/integration/session' in req.url else None)
                page.goto(origin + '/host', wait_until='networkidle')
                iframe_src = page.evaluate('''async () => {
                    const result = await DBQueryEmbed.mount({
                      el: '#embed', apiBase: '/dbquery', username: 'browser-user',
                      password: 'browser-password', form: 'person-detail',
                      params: {tjh: '202608250001', hidden_value: 'override'}
                    });
                    await new Promise(resolve => result.iframe.addEventListener('load', resolve, {once: true}));
                    return result.iframe.src;
                }''')
                assert '/dbquery/embed/person-detail?' in iframe_src
                assert 'ctx=' in iframe_src
                assert 'tjh=' not in iframe_src
                assert '202608250001' not in iframe_src
                assert 'browser-password' not in iframe_src
                assert page.locator('#embed iframe').count() == 1
                frame = page.frames[-1]
                assert frame.locator('.conditions-section').count() == 1
                assert frame.locator('input.param-input[data-name="tjh"]').input_value() == '202608250001'
                assert 'override' not in frame.content()
                assert 'browser-password' not in page.content()
                assert page.evaluate('Object.keys(localStorage).length + Object.keys(sessionStorage).length') == 0
                # Chromium performs this same-origin GET without a cross-origin allowlist bypass.
                assert session_request_headers
                assert all('origin' not in headers for headers in session_request_headers)

                cookies_after_login = context.cookies()
                assert any(cookie['name'] == 'session' and cookie['value'] == 'PEIS_SESSION_VALUE'
                           for cookie in cookies_after_login)
                assert any(cookie['name'] == 'dbquery_session' and cookie['path'] == '/dbquery'
                           for cookie in cookies_after_login)

                page.evaluate("DBQueryEmbed.logout('/dbquery')")
                cookies_after_logout = context.cookies()
                assert any(cookie['name'] == 'session' and cookie['value'] == 'PEIS_SESSION_VALUE'
                           for cookie in cookies_after_logout)
                assert not any(cookie['name'] == 'dbquery_session' for cookie in cookies_after_logout)
                browser.close()
    assert manager.authenticate_calls == [('browser-user', 'browser-password')]
