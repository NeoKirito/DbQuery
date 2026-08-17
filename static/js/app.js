/* DBQuery Web 前端交互：嵌入状态、查询与导出。 */
var lastQueryResult = null;
var dataTable = null;

$(document).ready(function () {
    initializeDefaultValues();
    initializeSearchableSelects();
    loadDynamicSelectOptions();
    restoreSidebarState();
    loadFormTree();
    initializeProjectSwitcher();

    $(document).on('keydown', '.param-input', function (event) {
        if (event.key === 'Enter' && !$(this).is('textarea')) {
            event.preventDefault();
            executeQuery();
        }
    });
});

function isEmbedMode() {
    return $('body').attr('data-embed-mode') === '1';
}

function isSidebarHidden() {
    return $('body').attr('data-sidebar-hidden') === '1';
}

function preserveEmbedParams(url) {
    var target = new URL(url, window.location.origin);
    var current = new URLSearchParams(window.location.search);
    ['hide_header', 'embed', 'sidebar'].forEach(function (key) {
        if (current.get(key) === '1' || (key === 'sidebar' && current.get(key) === '0')) {
            target.searchParams.set(key, current.get(key));
        }
    });
    return target.pathname + (target.search ? target.search : '') + target.hash;
}

function initializeDefaultValues() {
    $('.param-input[type="date"]').each(function () {
        var $input = $(this);
        if (!$input.val() && $input.data('default') === '{today}') {
            $input.val(todayStr());
        }
    });
    $('.param-input[type="datetime-local"]').each(function () {
        var $input = $(this);
        if (!$input.val() && $input.data('default') === '{today}') {
            $input.val(nowStr());
        }
    });
}

function initializeSearchableSelects() {
    $('.searchable-select').each(function () {
        var $root = $(this);
        var $input = $root.find('.searchable-select-input');
        var $value = $root.find('.searchable-select-value');
        var $menu = $root.find('.searchable-select-menu');
        var $toggle = $root.find('.searchable-select-toggle');
        var activeIndex = -1;

        function visibleOptions() {
            return $menu.find('.searchable-select-option:visible');
        }
        function closeMenu() {
            $menu.prop('hidden', true);
            $input.attr('aria-expanded', 'false');
            activeIndex = -1;
            $menu.find('.is-active').removeClass('is-active');
        }
        function setActive(index) {
            var $options = visibleOptions();
            if (!$options.length) return;
            activeIndex = Math.max(0, Math.min(index, $options.length - 1));
            $options.removeClass('is-active');
            var $active = $options.eq(activeIndex).addClass('is-active');
            $active[0].scrollIntoView({block: 'nearest'});
        }
        function openMenu() {
            filterOptions($input.val());
            $menu.prop('hidden', false);
            $input.attr('aria-expanded', 'true');
            if (visibleOptions().length) setActive(0);
        }
        function selectOption($option) {
            if (!$option || !$option.length) return;
            $input.val($option.text());
            $value.val($option.data('value'));
            $menu.find('[aria-selected="true"]').attr('aria-selected', 'false');
            $option.attr('aria-selected', 'true');
            closeMenu();
        }
        function filterOptions(query) {
            var needle = String(query || '').toLowerCase();
            $menu.find('.searchable-select-option').each(function () {
                var text = $(this).text().toLowerCase();
                $(this).toggle(!needle || text.indexOf(needle) >= 0);
            });
            activeIndex = -1;
        }

        $root.data('searchableSelect', {
            setOptions: function (options) {
                var currentValue = $value.val();
                $menu.empty();
                (options || []).forEach(function (option) {
                    var value = option && option.value !== undefined ? String(option.value) : '';
                    var label = option && option.label !== undefined ? String(option.label) : value;
                    if (!value) return;
                    var $option = $('<button type="button" class="searchable-select-option" role="option"></button>');
                    $option.attr('data-value', value).attr('aria-selected', 'false').text(label);
                    $menu.append($option);
                });
                var $selected = $menu.find('.searchable-select-option').filter(function () {
                    return String($(this).data('value')) === String(currentValue);
                }).first();
                if ($selected.length) {
                    selectOption($selected);
                } else {
                    $value.val('');
                    $input.val('');
                }
            }
        });

        var initialValue = $value.val();
        var $initial = $menu.find('.searchable-select-option').filter(function () {
            return String($(this).data('value')) === String(initialValue);
        }).first();
        if ($initial.length) selectOption($initial);

        $input.on('focus', openMenu);
        $input.on('input', function () {
            // 搜索过程中不保留旧 value；必须由用户确认合法候选项。
            $value.val('');
            $menu.find('[aria-selected="true"]').attr('aria-selected', 'false');
            openMenu();
        });
        $input.on('keydown', function (event) {
            var $options;
            if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
                event.preventDefault();
                openMenu();
                $options = visibleOptions();
                if ($options.length) setActive(activeIndex + (event.key === 'ArrowDown' ? 1 : -1));
            } else if (event.key === 'Enter') {
                event.preventDefault();
                $options = visibleOptions();
                if ($options.length) selectOption($options.eq(activeIndex >= 0 ? activeIndex : 0));
            } else if (event.key === 'Escape') {
                event.preventDefault();
                closeMenu();
            }
        });
        $toggle.on('click', function () {
            if ($menu.prop('hidden')) {
                $input.trigger('focus');
            } else {
                closeMenu();
            }
        });
        $menu.on('mousedown', '.searchable-select-option', function (event) {
            event.preventDefault();
            selectOption($(this));
        });
        $(document).on('mousedown', function (event) {
            if (!$(event.target).closest($root).length) closeMenu();
        });
    });
}

function loadDynamicSelectOptions() {
    var config = window.DBQUERY || {};
    var params = config.formParams || [];
    params.forEach(function (param) {
        if (!param || param.ptype !== 'select' || !param.options_sql) return;
        var $root = $('.searchable-select').filter(function () {
            return $(this).data('name') === param.name;
        }).first();
        if (!$root.length) return;
        $.ajax({
            url: '/api/options',
            method: 'POST',
            contentType: 'application/json',
            data: JSON.stringify({file_path: config.filePath, param_name: param.name}),
            success: function (data) {
                var component = $root.data('searchableSelect');
                if (component && component.setOptions) component.setOptions(data.options || []);
                if (data.warning) showToast(data.warning, 'warning');
            },
            error: function () {
                // 静态候选仍保留；数据库细节只记录在服务端日志。
                showToast('候选数据加载失败，可刷新重试。', 'warning');
            }
        });
    });
}

function loadFormTree() {
    var $trees = $('#form-tree, #project-menu-tree');
    if (!$trees.length || $trees.filter(':empty').length === 0) {
        fixFormLinks();
        highlightCurrentForm();
        return;
    }

    $.get('/api/forms', function (data) {
        var html = buildFormTree(data);
        $trees.html(html);
        highlightCurrentForm();
    }).fail(function () {
        showToast('查询项目加载失败，请稍后刷新页面。', 'error');
    });
}

function buildFormTree(data) {
    var html = '';
    for (var group in data) {
        if (!Object.prototype.hasOwnProperty.call(data, group)) continue;
        var forms = data[group];
        html += '<div class="nav-group">';
        html += '<button class="nav-group-title" type="button" onclick="toggleGroup(this)">';
        html += '<span class="arrow" aria-hidden="true">▾</span><span>' + esc(group) + '</span>';
        html += '<span class="count">' + forms.length + '</span></button>';
        html += '<div class="nav-group-items">';
        for (var index = 0; index < forms.length; index++) {
            var form = forms[index];
            var url = preserveEmbedParams('/query/' + encodeFilePath(form.file_path));
            html += '<a href="' + esc(url) + '" class="nav-item-link' + (form.description ? ' has-desc' : '') + '" data-title="' + esc(form.title.toLowerCase()) + '">';
            html += svgIcon('document', 'nav-item-icon') + '<span class="nav-item-content"><span class="nav-item-title">' + esc(form.title) + '</span>';
            if (form.description) html += '<span class="nav-item-desc">' + esc(form.description) + '</span>';
            html += '</span></a>';
        }
        html += '</div></div>';
    }
    return html;
}

function encodeFilePath(filePath) {
    return String(filePath || '').replace(/#/g, '%23');
}

function fixFormLinks() {
    $('.nav-item-link, .project-card').each(function () {
        var $link = $(this);
        var href = $link.attr('href');
        if (!href) return;
        $link.attr('href', preserveEmbedParams(encodeFilePath(href)));
    });
}

function highlightCurrentForm() {
    var filePath = window.DBQUERY ? window.DBQUERY.filePath : '';
    if (!filePath) return;
    var encodedPath = encodeFilePath(filePath);
    $('.nav-item-link').each(function () {
        var href = $(this).attr('href') || '';
        if (href.indexOf(encodedPath) >= 0 || href.indexOf(filePath) >= 0) {
            $(this).addClass('active');
            $(this).closest('.nav-group-items').show();
            $(this).closest('.nav-group').find('.nav-group-title').first().removeClass('collapsed');
        }
    });
}

function toggleGroup(element) {
    var $title = $(element);
    $title.toggleClass('collapsed');
    $title.next('.nav-group-items').toggle();
}

function filterForms() {
    filterFormTree($('#form-search').val(), $('#form-tree'));
}

function filterFormTree(value, $tree) {
    var text = (value || '').toLowerCase();
    $tree.find('.nav-item-link').each(function () {
        var title = $(this).data('title') || '';
        $(this).toggle(!text || title.indexOf(text) >= 0);
    });
    $tree.find('.nav-group').each(function () {
        var $group = $(this);
        $group.toggle(!text || $group.find('.nav-item-link:visible').length > 0);
        if (text) $group.find('.nav-group-items').show();
    });
}

function initializeProjectSwitcher() {
    var $switcher = $('#project-switcher');
    var $trigger = $('#project-switcher-trigger');
    var $panel = $('#project-switcher-panel');
    if (!$switcher.length || !$trigger.length || !$panel.length) return;

    $trigger.on('click', function () {
        var opening = $panel.prop('hidden');
        $panel.prop('hidden', !opening);
        $trigger.attr('aria-expanded', opening ? 'true' : 'false');
        if (opening) $('#project-search').trigger('focus');
    });
    $('#project-search').on('input', function () {
        filterFormTree($(this).val(), $('#project-menu-tree'));
    });
    $(document).on('click', function (event) {
        if (!$(event.target).closest('#project-switcher').length) {
            $panel.prop('hidden', true);
            $trigger.attr('aria-expanded', 'false');
        }
    });
    $(document).on('keydown', function (event) {
        if (event.key === 'Escape' && !$panel.prop('hidden')) {
            $panel.prop('hidden', true);
            $trigger.attr('aria-expanded', 'false').trigger('focus');
        }
    });
}

function restoreSidebarState() {
    if (isSidebarHidden() || !$('#sidebar').length) return;
    try {
        if (window.localStorage.getItem('dbquery-sidebar-collapsed') === '1') {
            $('body').addClass('sidebar-collapsed');
        }
    } catch (ignore) {}
}

function toggleSidebar() {
    if (isSidebarHidden() || !$('#sidebar').length) return;
    $('body').toggleClass('sidebar-collapsed');
    try {
        window.localStorage.setItem(
            'dbquery-sidebar-collapsed',
            $('body').hasClass('sidebar-collapsed') ? '1' : '0'
        );
    } catch (ignore) {}
}

function testConnection() {
    var $dot = $('#conn-dot');
    var $text = $('#conn-text');
    if (!$dot.length) return;
    $dot.attr('class', 'conn-dot conn-testing');
    $text.text('正在检测数据服务');
    $.get('/api/test-connection', function (data) {
        if (data.success) {
            $dot.attr('class', 'conn-dot conn-ok');
            $text.text('数据服务连接正常');
        } else {
            $dot.attr('class', 'conn-dot conn-fail');
            $text.text('数据服务连接异常');
            showToast(data.message || '数据服务连接异常，请稍后重试。', 'error');
        }
    }).fail(function () {
        $dot.attr('class', 'conn-dot conn-fail');
        $text.text('数据服务连接异常');
        showToast('数据服务连接异常，请稍后重试。', 'error');
    });
}

function collectParams() {
    var params = {};
    $('.param-input').each(function () {
        var $input = $(this);
        var name = $input.data('name');
        if (!name) return;
        if ($input.is(':radio')) {
            if ($input.is(':checked')) params[name] = $input.val() || '';
        } else if ($input.is(':checkbox')) {
            params[name] = $input.is(':checked') ? '1' : '0';
        } else {
            params[name] = $input.val() || '';
        }
    });
    return params;
}

function validateRequiredParams() {
    var valid = true;
    $('.param-input[required]').each(function () {
        if (!this.checkValidity()) {
            valid = false;
            return false;
        }
    });
    $('.searchable-select[data-required="1"]').each(function () {
        var $root = $(this);
        if (!$root.find('.searchable-select-value').val()) {
            valid = false;
            $root.find('.searchable-select-input').trigger('focus');
            return false;
        }
    });
    if (!valid) {
        showInlineMessage('warning', '请先填写标记为必填的查询条件。');
    }
    return valid;
}

function setQueryLoading(isLoading) {
    var $button = $('#btn-execute');
    $button.prop('disabled', isLoading);
    $button.find('.button-text').text(isLoading ? '查询中…' : '查询');
    $('#loading').toggleClass('d-none', !isLoading);
    if (isLoading) $('#btn-export').prop('disabled', true);
}

function setExportLoading(isLoading) {
    var $button = $('#btn-export');
    $button.prop('disabled', isLoading || !lastQueryResult);
    $button.find('.button-text').text(isLoading ? '导出中…' : '导出');
}

function executeQuery() {
    var filePath = window.DBQUERY ? window.DBQUERY.filePath : '';
    if (!filePath || $('#btn-execute').prop('disabled')) return;
    if (!validateRequiredParams()) return;

    clearInlineMessage();
    setQueryLoading(true);
    $('#result-empty').hide();
    $('#status-text').text('正在查询，请稍候…');

    $.ajax({
        url: '/api/query',
        method: 'POST',
        contentType: 'application/json',
        data: JSON.stringify({file_path: filePath, params: collectParams()}),
        success: function (data) {
            if (data.error) {
                handleQueryFailure(data.error);
                return;
            }
            lastQueryResult = data;
            renderResult(data);
            $('#status-text').text(querySummary(data));
            setExportLoading(false);
            if (data.truncated) {
                showInlineMessage(
                    'warning',
                    '查询结果较多，当前显示前 ' + data.max_rows + ' 条，请适当缩小查询范围。'
                );
            }
        },
        error: function (xhr) {
            getRequestError(xhr, '查询失败，请稍后重试。').then(handleQueryFailure);
        },
        complete: function () {
            setQueryLoading(false);
        }
    });
}

function handleQueryFailure(message) {
    lastQueryResult = null;
    setExportLoading(false);
    $('#status-text').text('查询未完成');
    $('#result-empty').text('暂无符合条件的数据').show();
    showInlineMessage('error', message || '查询失败，请稍后重试。');
}

function querySummary(data) {
    var summary = '共 ' + data.row_count + ' 条记录';
    if (data.col_count) summary += ' · ' + data.col_count + ' 个字段';
    summary += ' · 用时 ' + Number(data.elapsed || 0).toFixed(2) + ' 秒';
    return summary;
}

function renderResult(data) {
    var $table = $('#result-table');
    if (dataTable) {
        dataTable.destroy();
        dataTable = null;
    }

    // DataTables destroy 后保留或显式恢复标准 table 结构，不能清空整个 table。
    var $thead = $table.children('thead');
    var $tbody = $table.children('tbody');
    if (!$thead.length) {
        $thead = $('<thead id="result-thead"></thead>').appendTo($table);
    }
    if (!$tbody.length) {
        $tbody = $('<tbody id="result-tbody"></tbody>').appendTo($table);
    }
    $thead.empty();
    $tbody.empty();

    var head = '<tr>';
    for (var index = 0; index < data.columns.length; index++) {
        head += '<th>' + esc(data.columns[index]) + '</th>';
    }
    head += '</tr>';
    $thead.html(head);

    var body = '';
    for (var rowIndex = 0; rowIndex < data.rows.length; rowIndex++) {
        body += '<tr>';
        for (var columnIndex = 0; columnIndex < data.rows[rowIndex].length; columnIndex++) {
            var value = data.rows[rowIndex][columnIndex];
            body += '<td>' + (
                value === null || value === undefined
                    ? '<span class="null-value">未填写</span>'
                    : esc(String(value))
            ) + '</td>';
        }
        body += '</tr>';
    }
    $tbody.html(body);

    dataTable = $table.DataTable({
        paging: true,
        pageLength: 100,
        lengthMenu: [50, 100, 200, 500, 1000],
        ordering: true,
        searching: true,
        info: true,
        scrollX: true,
        autoWidth: false,
        language: {
            search: '筛选：',
            lengthMenu: '每页显示 _MENU_ 条',
            info: '显示第 _START_ 至 _END_ 条，共 _TOTAL_ 条',
            infoEmpty: '暂无符合条件的数据',
            infoFiltered: '（从 _MAX_ 条记录中筛选）',
            paginate: {first: '首页', last: '末页', previous: '上一页', next: '下一页'},
            zeroRecords: '暂无符合条件的数据'
        }
    });
    if (data.row_count) {
        $('#result-empty').hide();
    } else {
        $('#result-empty').text('暂无符合条件的数据').show();
    }
}

function exportExcel() {
    if (!lastQueryResult || $('#btn-export').prop('disabled')) return;
    var filePath = window.DBQUERY ? window.DBQUERY.filePath : '';
    setExportLoading(true);
    $('#status-text').text('正在生成导出文件…');

    $.ajax({
        url: '/api/export',
        method: 'POST',
        contentType: 'application/json',
        data: JSON.stringify({
            file_path: filePath,
            params: collectParams(),
            columns: lastQueryResult.columns,
            rows: lastQueryResult.rows,
            elapsed: lastQueryResult.elapsed
        }),
        xhrFields: {responseType: 'blob'},
        success: function (blob, status, xhr) {
            var url = URL.createObjectURL(blob);
            var link = document.createElement('a');
            link.href = url;
            link.download = extractDownloadFileName(xhr) || '查询结果.xlsx';
            document.body.appendChild(link);
            link.click();
            document.body.removeChild(link);
            window.setTimeout(function () { URL.revokeObjectURL(url); }, 1000);
            $('#status-text').text('导出文件已生成，正在下载。');
            showToast('导出文件已生成，正在下载。', 'success');
        },
        error: function (xhr) {
            getRequestError(xhr, '导出失败，请稍后重试。').then(function (message) {
                $('#status-text').text('导出未完成');
                showInlineMessage('error', message);
            });
        },
        complete: function () {
            setExportLoading(false);
        }
    });
}

function getRequestError(xhr, fallback) {
    return new Promise(function (resolve) {
        var response = xhr && xhr.response;
        if (response instanceof Blob) {
            var reader = new FileReader();
            reader.onload = function () {
                try {
                    var data = JSON.parse(reader.result);
                    resolve(data.error || fallback);
                } catch (ignore) {
                    resolve(fallback);
                }
            };
            reader.onerror = function () { resolve(fallback); };
            reader.readAsText(response);
            return;
        }
        try {
            var payload = typeof response === 'string' ? JSON.parse(response) : response;
            resolve((payload && payload.error) || fallback);
        } catch (ignore) {
            resolve(fallback);
        }
    });
}

function extractDownloadFileName(xhr) {
    var disposition = xhr.getResponseHeader('Content-Disposition') || '';
    var utf8Match = disposition.match(/filename\*=UTF-8''([^;]+)/i);
    if (utf8Match && utf8Match[1]) {
        try { return decodeURIComponent(utf8Match[1]); } catch (ignore) {}
    }
    var filenameMatch = disposition.match(/filename="?([^";]+)"?/i);
    return filenameMatch && filenameMatch[1] ? filenameMatch[1] : '';
}

function showInlineMessage(type, message) {
    var $message = $('#result-message');
    if (!$message.length) {
        showToast(message, type);
        return;
    }
    $message.removeClass('d-none message-warning message-error message-success')
        .addClass('message-' + type)
        .text(message);
}

function clearInlineMessage() {
    $('#result-message').addClass('d-none').removeClass('message-warning message-error message-success').text('');
}

function showToast(message, type) {
    var $region = $('#toast-region');
    if (!$region.length || !message) return;
    var $toast = $('<div class="app-toast" role="status"></div>').addClass('toast-' + (type || 'info'));
    $toast.append($('<span></span>').text(message));
    $region.append($toast);
    window.setTimeout(function () {
        $toast.addClass('toast-leaving');
        window.setTimeout(function () { $toast.remove(); }, 180);
    }, 3500);
}

function svgIcon(name, extraClass) {
    var cssClass = 'icon ' + (extraClass || '');
    if (name === 'document') {
        return '<svg class="' + cssClass + '" aria-hidden="true" viewBox="0 0 24 24"><path d="M5 4h14v16H5z"/><path d="M8 8h8M8 12h8M8 16h5"/></svg>';
    }
    return '';
}

function esc(value) {
    return String(value || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

function todayStr() {
    var date = new Date();
    return date.getFullYear() + '-' + String(date.getMonth() + 1).padStart(2, '0') + '-' + String(date.getDate()).padStart(2, '0');
}

function nowStr() {
    var date = new Date();
    return todayStr() + 'T' + String(date.getHours()).padStart(2, '0') + ':' + String(date.getMinutes()).padStart(2, '0');
}
