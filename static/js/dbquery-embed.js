/* DBQuery Frontend Embed V1：使用当前宿主凭据建立 DBQuery Session 后嵌入完整工作台。 */
(function (global) {
    'use strict';

    var lastApiBase = null;
    var ERROR_MESSAGES = {
        AUTH_FAILED: '查询工具加载失败',
        ORIGIN_DENIED: '查询工具加载失败',
        NETWORK_ERROR: '查询工具加载失败',
        SESSION_FAILED: '查询工具加载失败',
        LOAD_FAILED: '查询工具加载失败'
    };

    function inferApiBase() {
        var scripts = document.getElementsByTagName('script');
        var script = document.currentScript;
        if (!script) {
            for (var index = scripts.length - 1; index >= 0; index--) {
                if ((scripts[index].src || '').indexOf('/static/js/dbquery-embed.js') >= 0) {
                    script = scripts[index];
                    break;
                }
            }
        }
        if (!script || !script.src) return '';
        var marker = '/static/js/dbquery-embed.js';
        var markerIndex = script.src.indexOf(marker);
        return markerIndex >= 0 ? script.src.slice(0, markerIndex) : '';
    }

    function normalizeApiBase(value) {
        var raw = value === undefined || value === null || value === '' ? inferApiBase() : String(value);
        return raw ? raw.replace(/\/+$/, '') : '';
    }

    function joinUrl(apiBase, path) {
        return (apiBase || '') + path;
    }

    function homeUrl(apiBase) {
        return apiBase ? apiBase + '/' : '/';
    }

    function findContainer(el) {
        if (typeof el === 'string') return document.querySelector(el);
        return el && el.nodeType === 1 ? el : null;
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
        element.textContent = ERROR_MESSAGES[error.code] || '查询工具加载失败';
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
        return fetch(joinUrl(apiBase, path), {
            method: options.method || 'GET',
            mode: 'cors',
            credentials: 'include',
            headers: options.body === undefined ? {} : {'Content-Type': 'application/json'},
            body: options.body === undefined ? undefined : JSON.stringify(options.body)
        }).then(function (response) {
            return response.json().catch(function () { return {}; }).then(function (payload) {
                if (!response.ok) {
                    throw embedError(
                        payload.error_type || (response.status === 403 ? 'ORIGIN_DENIED' : 'NETWORK_ERROR'),
                        payload.error
                    );
                }
                return payload;
            });
        }).catch(function (error) {
            if (error && error.code) throw error;
            throw embedError('NETWORK_ERROR');
        });
    }

    function notifyError(onError, error) {
        if (typeof onError === 'function') {
            try { onError(error); } catch (ignore) {}
        }
        return Promise.reject(error);
    }

    function createIframe(container, apiBase, loading, onReady) {
        return new Promise(function (resolve, reject) {
            var iframe = document.createElement('iframe');
            iframe.className = 'dbquery-embed-frame';
            iframe.title = 'DBQuery';
            iframe.setAttribute('frameborder', '0');
            iframe.style.width = '100%';
            iframe.style.height = '100%';
            iframe.style.border = '0';
            iframe.style.display = 'block';
            iframe.onload = function () {
                if (loading && loading.parentNode) loading.parentNode.removeChild(loading);
                if (onReady) {
                    try { onReady({iframe: iframe}); } catch (ignore) {}
                }
                resolve({iframe: iframe});
            };
            iframe.onerror = function () {
                reject(embedError('LOAD_FAILED'));
            };
            // 认证完成后固定进入完整 DBQuery Web 首页；不传 form、params 或业务条件。
            iframe.src = homeUrl(apiBase);
            container.appendChild(iframe);
        });
    }

    function mount(options) {
        var container = options && findContainer(options.el);
        var invalidOnError = options && options.onError;
        if (!options || typeof options !== 'object' || !container) {
            var invalidError = embedError('SESSION_FAILED');
            displayError(container, invalidError);
            return notifyError(invalidOnError, invalidError);
        }

        var apiBase = normalizeApiBase(options.apiBase);
        var username = String(options.username || '').trim();
        // 仅在当前认证异步链中临时保存；不会写入 URL、DOM、Cookie 或浏览器存储。
        var password = String(options.password || '');
        var onReady = typeof options.onReady === 'function' ? options.onReady : null;
        var onError = typeof options.onError === 'function' ? options.onError : null;
        // 后续 Promise 和 iframe 回调不再保留调用者原始 options（可能含密码）的引用。
        options = null;
        var loading = displayLoading(container);

        // PEIS 已传入本次登录凭据时直接建立 DBQuery Session。不要先做 GET
        // 探测：同源反向代理下浏览器通常不会给 GET 附带 Origin，服务端会按
        // 安全策略返回 403，导致真正的登录请求永远没有机会执行。
        var sessionRequest;
        if (username && password) {
            sessionRequest = request(apiBase, '/api/integration/frontend-login', {
                method: 'POST', body: {username: username, password: password}
            });
        } else {
            // 未传凭据时才复用已有 Session；未登录则给出统一认证错误。
            sessionRequest = request(apiBase, '/api/integration/session', {method: 'GET'})
                .then(function (sessionState) {
                    if (!sessionState.authenticated) throw embedError('AUTH_FAILED');
                    return sessionState;
                });
        }

        return sessionRequest
            .then(function () {
                // 认证完成后 SDK 不再保存或主动持有 password 引用。
                username = '';
                password = '';
                // 根路径以 '/' 作为可恢复的来源值保存，避免 logout 将空字符串重新推断为脚本地址。
                lastApiBase = apiBase || '/';
                return createIframe(container, apiBase, loading, onReady);
            })
            .catch(function (error) {
                username = '';
                password = '';
                displayError(container, error);
                return notifyError(onError, error);
            });
    }

    function logout(options) {
        var source;
        if (typeof options === 'string') {
            source = options;
        } else if (options && Object.prototype.hasOwnProperty.call(options, 'apiBase')) {
            source = options.apiBase;
        } else {
            source = lastApiBase;
        }
        var apiBase = normalizeApiBase(source);
        return request(apiBase, '/api/integration/logout', {method: 'POST'}).then(function (payload) {
            lastApiBase = null;
            return payload;
        });
    }

    global.DBQueryEmbed = {
        mount: mount,
        logout: logout
    };
}(window));
