/* DBQuery Frontend Embed V1：仅使用当前调用的凭据建立 DBQuery Session。 */
(function (global) {
    'use strict';

    var lastApiBase = '';
    var ERROR_MESSAGES = {
        AUTH_FAILED: '账号验证失败',
        ORIGIN_DENIED: '当前页面来源未获 DBQuery 授权',
        FORM_NOT_FOUND: '当前表单不可访问',
        FORM_NOT_WEB_ENABLED: '当前表单不可访问',
        INVALID_PARAM: '嵌入参数无效',
        NETWORK_ERROR: 'DBQuery 加载失败',
        SESSION_FAILED: 'DBQuery 会话建立失败'
    };

    function inferApiBase() {
        var scripts = document.getElementsByTagName('script');
        var script = document.currentScript;
        if (!script) {
            for (var i = scripts.length - 1; i >= 0; i--) {
                if ((scripts[i].src || '').indexOf('/static/js/dbquery-embed.js') >= 0) {
                    script = scripts[i];
                    break;
                }
            }
        }
        if (!script || !script.src) return '';
        var marker = '/static/js/dbquery-embed.js';
        var index = script.src.indexOf(marker);
        return index >= 0 ? script.src.slice(0, index) : '';
    }

    function normalizeApiBase(value) {
        var raw = value === undefined || value === null || value === '' ? inferApiBase() : String(value);
        if (!raw) return '';
        return raw.replace(/\/$/, '');
    }

    function apiUrl(apiBase, path) {
        return apiBase + path;
    }

    function iframeUrl(apiBase, path) {
        var value = String(path || '');
        if (/^https?:\/\//i.test(value)) return value;
        // Flask url_for 在 SCRIPT_NAME 存在时已生成带 /dbquery 前缀的路径。
        if (apiBase && (value === apiBase || value.indexOf(apiBase + '/') === 0)) return value;
        return apiUrl(apiBase, value);
    }

    function findContainer(el) {
        if (typeof el === 'string') return document.querySelector(el);
        if (el && el.nodeType === 1) return el;
        return null;
    }

    function embedError(code, message) {
        var error = new Error(message || ERROR_MESSAGES[code] || ERROR_MESSAGES.NETWORK_ERROR);
        error.code = code || 'NETWORK_ERROR';
        return error;
    }

    function displayError(container, error) {
        if (!container) return;
        container.innerHTML = '';
        var element = document.createElement('div');
        element.className = 'dbquery-embed-status dbquery-embed-error';
        element.setAttribute('role', 'alert');
        element.textContent = ERROR_MESSAGES[error.code] || 'DBQuery 加载失败';
        container.appendChild(element);
    }

    function displayLoading(container) {
        container.innerHTML = '';
        var element = document.createElement('div');
        element.className = 'dbquery-embed-status dbquery-embed-loading';
        element.setAttribute('role', 'status');
        element.textContent = '正在加载查询工具...';
        container.appendChild(element);
        return element;
    }

    function request(apiBase, path, options) {
        return fetch(apiUrl(apiBase, path), {
            method: options.method || 'GET',
            mode: 'cors',
            credentials: 'include',
            headers: options.body === undefined ? {} : {'Content-Type': 'application/json'},
            body: options.body === undefined ? undefined : JSON.stringify(options.body)
        }).then(function (response) {
            return response.json().catch(function () { return {}; }).then(function (payload) {
                if (!response.ok) {
                    throw embedError(payload.error_type || (response.status === 403 ? 'ORIGIN_DENIED' : 'NETWORK_ERROR'),
                                     payload.error);
                }
                return payload;
            });
        }).catch(function (error) {
            if (error && error.code) throw error;
            throw embedError('NETWORK_ERROR');
        });
    }

    function validateOptions(options) {
        if (!options || typeof options !== 'object') throw embedError('SESSION_FAILED', '缺少嵌入配置。');
        if (!findContainer(options.el)) throw embedError('SESSION_FAILED', '未找到嵌入容器。');
        if (!String(options.form || '').trim()) throw embedError('FORM_NOT_FOUND', '缺少表单 ID。');
        if (options.params !== undefined && (!options.params || typeof options.params !== 'object' || Array.isArray(options.params))) {
            throw embedError('INVALID_PARAM');
        }
    }

    function notifyError(onError, error) {
        if (typeof onError === 'function') {
            try { onError(error); } catch (ignore) {}
        }
        return Promise.reject(error);
    }

    function mount(options) {
        try {
            validateOptions(options);
        } catch (error) {
            var invalidContainer = options && findContainer(options.el);
            var invalidOnError = options && options.onError;
            displayError(invalidContainer, error);
            return notifyError(invalidOnError, error);
        }

        var container = findContainer(options.el);
        var apiBase = normalizeApiBase(options.apiBase);
        var username = String(options.username || '').trim();
        // 仅保存至此异步调用链；不会写入 DOM、URL、Cookie 或浏览器存储。
        var password = String(options.password || '');
        var formId = String(options.form).trim();
        var params = options.params || {};
        var onReady = typeof options.onReady === 'function' ? options.onReady : null;
        var onError = typeof options.onError === 'function' ? options.onError : null;
        // 避免 Promise、iframe onload 或错误回调继续持有调用者的原始配置对象。
        options = null;
        var loading = displayLoading(container);

        var flow = request(apiBase, '/api/integration/session', {method: 'GET'})
            .then(function (sessionState) {
                if (sessionState.authenticated) return sessionState;
                if (!username || !password) throw embedError('AUTH_FAILED');
                return request(apiBase, '/api/integration/frontend-login', {
                    method: 'POST', body: {username: username, password: password}
                });
            })
            .then(function () {
                // 登录请求已完成；SDK 不保留凭据引用。
                username = '';
                password = '';
                return request(apiBase, '/api/integration/embed-url', {
                    method: 'POST', body: {form: formId, params: params}
                });
            })
            .then(function (payload) {
                if (!payload.embed_url) throw embedError('SESSION_FAILED');
                lastApiBase = apiBase;
                var iframe = document.createElement('iframe');
                iframe.className = 'dbquery-embed-frame';
                iframe.title = 'DBQuery 查询工具';
                iframe.setAttribute('frameborder', '0');
                iframe.style.width = '100%';
                iframe.style.height = '100%';
                iframe.style.minHeight = '420px';
                iframe.style.border = '0';
                iframe.onload = function () {
                    if (loading && loading.parentNode) loading.parentNode.removeChild(loading);
                    if (onReady) {
                        try { onReady({iframe: iframe}); } catch (ignore) {}
                    }
                };
                // 服务端仅会签发公开表单 ID 和 external_allowed 的业务参数；绝无密码。
                iframe.src = iframeUrl(apiBase, payload.embed_url);
                container.appendChild(iframe);
                return {iframe: iframe};
            });

        return flow.catch(function (error) {
            // 失败时同样释放当前调用中对凭据的引用。
            username = '';
            password = '';
            displayError(container, error);
            return notifyError(onError, error);
        });
    }

    function logout(options) {
        var apiBase = normalizeApiBase(
            typeof options === 'string' ? options : (options && options.apiBase) || lastApiBase
        );
        return request(apiBase, '/api/integration/logout', {method: 'POST'}).then(function (payload) {
            lastApiBase = '';
            return payload;
        });
    }

    global.DBQueryEmbed = {
        mount: mount,
        logout: logout
    };
}(window));
