/**
 * DBQuery Web 版前端逻辑
 */
var lastQueryResult = null;
var dataTable = null;

// ════════════════════════════════════════
//  初始化
// ════════════════════════════════════════
$(document).ready(function () {
    // 日期默认值
    $('.param-input[type="date"]').each(function () {
        if (!$(this).val()) $(this).val(todayStr());
    });
    $('.param-input[type="datetime-local"]').each(function () {
        if (!$(this).val()) $(this).val(nowStr());
    });

    // 加载侧边栏
    loadFormTree();

    // 回车执行
    $(document).on('keydown', '.param-input', function (e) {
        if (e.key === 'Enter') executeQuery();
    });
});

// ════════════════════════════════════════
//  侧边栏
// ════════════════════════════════════════
function loadFormTree() {
    var $tree = $('#form-tree');
    if (!$tree.length) return;

    // 如果已有静态内容（首页），需要修复链接中的 # 编码
    if ($tree.children().length > 0) {
        fixFormLinks();
        highlightCurrentForm();
        return;
    }

    // 查询页：AJAX 加载
    $.get('/api/forms', function (data) {
        var html = '';
        for (var group in data) {
            var forms = data[group];
            html += '<div class="nav-group">';
            html += '<div class="nav-group-title" onclick="toggleGroup(this)">';
            html += '<span class="arrow">▾</span> ' + esc(group);
            html += ' <span class="count">' + forms.length + '</span>';
            html += '</div><div class="nav-group-items">';
            for (var i = 0; i < forms.length; i++) {
                var f = forms[i];
                var url = '/query/' + encodeFilePath(f.file_path);
                html += '<a href="' + url + '" class="nav-item-link" data-title="' + esc(f.title.toLowerCase()) + '">';
                html += '📄 ' + esc(f.title);
                if (f.description) html += '<span class="nav-item-desc">' + esc(f.description) + '</span>';
                html += '</a>';
            }
            html += '</div></div>';
        }
        $tree.html(html);
        highlightCurrentForm();
    });
}

// 文件路径中的 # 需要编码为 %23，否则被浏览器当作 URL fragment
function encodeFilePath(fp) {
    return fp.replace(/#/g, '%23');
}

// 修复首页静态链接中的 # 问题
function fixFormLinks() {
    $('.nav-item-link').each(function () {
        var href = $(this).attr('href');
        if (href && href.indexOf('#') >= 0) {
            $(this).attr('href', encodeFilePath(href));
        }
    });
}

function highlightCurrentForm() {
    var fp = window.DBQUERY ? window.DBQUERY.filePath : '';
    if (!fp) return;
    var encoded = encodeFilePath(fp);
    $('.nav-item-link').each(function () {
        var href = $(this).attr('href') || '';
        if (href.indexOf(encoded) >= 0 || href.indexOf(fp) >= 0) {
            $(this).addClass('active');
            $(this).closest('.nav-group-items').show()
                .prev('.nav-group-title').removeClass('collapsed');
        }
    });
}

function toggleGroup(el) {
    $(el).toggleClass('collapsed');
    $(el).next('.nav-group-items').slideToggle(150);
}

function filterForms() {
    var text = ($('#form-search').val() || '').toLowerCase();
    $('.nav-item-link').each(function () {
        var title = $(this).data('title') || '';
        $(this).toggle(!text || title.indexOf(text) >= 0);
    });
}

// ════════════════════════════════════════
//  连接测试
// ════════════════════════════════════════
function testConnection() {
    $('#conn-dot').attr('class', 'conn-dot conn-testing');
    $('#conn-text').text('连接中…');
    $.get('/api/test-connection', function (d) {
        if (d.success) {
            $('#conn-dot').attr('class', 'conn-dot conn-ok');
            $('#conn-text').text('已连接');
        } else {
            $('#conn-dot').attr('class', 'conn-dot conn-fail');
            $('#conn-text').text('未连接');
            alert('连接失败：\n\n' + d.message);
        }
    }).fail(function () {
        $('#conn-dot').attr('class', 'conn-dot conn-fail');
        $('#conn-text').text('请求失败');
    });
}

// ════════════════════════════════════════
//  查询执行
// ════════════════════════════════════════
function collectParams() {
    var p = {};
    $('.param-input').each(function () {
        var name = $(this).data('name');
        if (name) p[name] = $(this).val() || '';
    });
    return p;
}

function executeQuery() {
    var fp = window.DBQUERY ? window.DBQUERY.filePath : '';
    if (!fp) return;

    $('#btn-execute').prop('disabled', true);
    $('#btn-export').prop('disabled', true);
    $('#loading').removeClass('d-none');
    $('#result-empty').hide();
    $('#status-text').text('查询中…');

    $.ajax({
        url: '/api/query',
        method: 'POST',
        contentType: 'application/json',
        data: JSON.stringify({ file_path: fp, params: collectParams() }),
        success: function (data) {
            if (data.error) {
                alert('查询错误：\n\n' + data.error);
                $('#status-text').text('查询出错');
                $('#result-empty').show();
            } else {
                renderResult(data);
                $('#status-text').text('共 ' + data.row_count + ' 行，' + data.col_count + ' 列 | 耗时 ' + data.elapsed + 's');
                $('#btn-export').prop('disabled', false);
                lastQueryResult = data;
            }
        },
        error: function (xhr) {
            var msg = '请求失败';
            try { msg = JSON.parse(xhr.responseText).error || msg; } catch (e) {}
            alert('查询错误：\n\n' + msg);
            $('#status-text').text('查询出错');
            $('#result-empty').show();
        },
        complete: function () {
            $('#btn-execute').prop('disabled', false);
            $('#loading').addClass('d-none');
        }
    });
}

// ════════════════════════════════════════
//  结果渲染
// ════════════════════════════════════════
function renderResult(data) {
    if (dataTable) { dataTable.destroy(); $('#result-table').empty(); }

    var thead = '<tr>';
    for (var i = 0; i < data.columns.length; i++)
        thead += '<th>' + esc(data.columns[i]) + '</th>';
    thead += '</tr>';
    $('#result-thead').html(thead);

    var tbody = '';
    for (var r = 0; r < data.rows.length; r++) {
        tbody += '<tr>';
        for (var c = 0; c < data.rows[r].length; c++) {
            var v = data.rows[r][c];
            tbody += '<td>' + (v === null || v === undefined ? '<span style="color:#bbb">NULL</span>' : esc(String(v))) + '</td>';
        }
        tbody += '</tr>';
    }
    $('#result-tbody').html(tbody);

    dataTable = $('#result-table').DataTable({
        paging: true, pageLength: 100,
        lengthMenu: [50, 100, 200, 500, 1000],
        ordering: true, searching: true, info: true,
        scrollX: true, autoWidth: false,
        language: {
            search: "过滤:", lengthMenu: "每页 _MENU_ 行",
            info: "第 _START_ - _END_ 行，共 _TOTAL_ 行",
            infoEmpty: "", infoFiltered: "(从 _MAX_ 行筛选)",
            paginate: { first: "首页", last: "末页", previous: "‹", next: "›" },
            zeroRecords: "无匹配记录"
        }
    });
    $('#result-empty').hide();
}

// ════════════════════════════════════════
//  Excel 导出
// ════════════════════════════════════════
function exportExcel() {
    if (!lastQueryResult) return;
    var fp = window.DBQUERY ? window.DBQUERY.filePath : '';

    $('#btn-export').prop('disabled', true);
    $('#status-text').text('正在导出…');

    $.ajax({
        url: '/api/export', method: 'POST',
        contentType: 'application/json',
        data: JSON.stringify({
            file_path: fp, params: collectParams(),
            columns: lastQueryResult.columns, rows: lastQueryResult.rows,
            elapsed: lastQueryResult.elapsed
        }),
        xhrFields: { responseType: 'blob' },
        success: function (blob) {
            var url = URL.createObjectURL(blob);
            var a = document.createElement('a');
            a.href = url; a.download = 'export.xlsx';
            document.body.appendChild(a); a.click();
            document.body.removeChild(a);
            URL.revokeObjectURL(url);
            $('#status-text').text('导出完成');
        },
        error: function (xhr) {
            var msg = '导出失败';
            try {
                var r = new FileReader();
                r.onload = function () { try { msg = JSON.parse(r.result).error || msg; } catch(e){} alert('导出错误：\n\n' + msg); };
                r.readAsText(xhr.response || xhr.responseText); return;
            } catch(e) {}
            alert('导出错误：\n\n' + msg);
        },
        complete: function () { $('#btn-export').prop('disabled', false); }
    });
}

// ════════════════════════════════════════
//  工具函数
// ════════════════════════════════════════
function esc(s) {
    if (!s) return '';
    return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')
            .replace(/"/g,'&quot;').replace(/'/g,'&#39;');
}
function todayStr() {
    var d = new Date();
    return d.getFullYear() + '-' + String(d.getMonth()+1).padStart(2,'0') + '-' + String(d.getDate()).padStart(2,'0');
}
function nowStr() {
    return todayStr() + 'T' + String(new Date().getHours()).padStart(2,'0') + ':' + String(new Date().getMinutes()).padStart(2,'0');
}
