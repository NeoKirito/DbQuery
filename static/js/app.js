/* DBQuery Web 前端交互：嵌入状态、查询、导出与多标签页导航。 */
var lastQueryResult = null;
var dataTable = null;
var resultGridResizeTimer = null;

function apiPath(path) {
    var base = (window.DBQUERY && window.DBQUERY.apiBase) || '';
    return String(base).replace(/\/$/, '') + path;
}

function redirectToLogin() {
    var target = window.location.pathname + window.location.search;
    window.location.replace(apiPath('/login') + '?next=' + encodeURIComponent(target));
}

$(document).ajaxError(function (event, xhr) {
    if (xhr && xhr.status === 401) {
        redirectToLogin();
    }
});

/* ════════════════════════════════════════════════════════════════════════════
   TabManager：多标签页调度（对齐桌面 EXE 多页签机制）
   ════════════════════════════════════════════════════════════════════════════ */
var TabManager = {
    tabs: {},
    activeTabId: null,
    formsCache: null,
    tabCounter: 0,

    init: function () {
        var self = this;

        // 1. 扫描 DOM 中已存在的标签页
        $('#app-tabbar .tab-item').each(function () {
            var $btn = $(this);
            var tabId = $btn.data('tabId');
            var filePath = $btn.data('filePath') || '';
            var $pane = $('#pane-' + tabId);
            var isWelcome = (tabId === 'tab-welcome');
            var title = $btn.find('.tab-title').text().trim();
            self.tabs[tabId] = {
                tabId: tabId,
                filePath: filePath,
                title: title,
                isWelcome: isWelcome,
                $tabBtn: $btn,
                $pane: $pane,
                dataTable: null,
                lastQueryResult: null,
                formParams: (window.DBQUERY && window.DBQUERY.formParams) || []
            };
            if ($btn.hasClass('active')) {
                self.activeTabId = tabId;
            }
        });

        if (!self.activeTabId && self.tabs['tab-welcome']) {
            self.activeTabId = 'tab-welcome';
        }

        // 2. 标签栏点击切换
        $('#app-tabbar').on('click', '.tab-item', function (e) {
            if ($(e.target).closest('.tab-close').length) {
                return;
            }
            var tabId = $(this).data('tabId');
            if (tabId) self.activateTab(tabId);
        });

        // 3. 标签关闭按钮点击
        $('#app-tabbar').on('click', '.tab-close', function (e) {
            e.preventDefault();
            e.stopPropagation();
            var tabId = $(this).closest('.tab-item').data('tabId');
            if (tabId) self.closeTab(tabId);
        });

        // 4. 拦截报表卡片与侧边栏链接，无刷新在多标签页中打开
        $(document).on('click', '.nav-item-link, .project-card', function (e) {
            var $link = $(this);
            var filePath = $link.data('filePath');
            var href = $link.attr('href') || '';
            if (!filePath && href) {
                var match = href.match(/\/query\/(.+?)(?:\?|#|$)/);
                if (match && match[1]) {
                    try { filePath = decodeURIComponent(match[1]); } catch (ignore) { filePath = match[1]; }
                }
            }
            if (filePath) {
                e.preventDefault();
                self.openReport(filePath);
            }
        });

        // 5. 拦截“返回报表主页”按钮，切换至欢迎页
        $(document).on('click', '.report-home-link', function (e) {
            if (self.tabs['tab-welcome']) {
                e.preventDefault();
                self.activateTab('tab-welcome');
            }
        });
    },

    getActiveTab: function () {
        return this.tabs[this.activeTabId] || null;
    },

    getActivePane: function () {
        var tab = this.getActiveTab();
        if (tab && tab.$pane && tab.$pane.length) return tab.$pane;
        return $('.tab-pane.active').first();
    },

    getLegacyActiveTab: function () {
        var $pane = $('.tab-pane.active').first();
        var tabId = $pane.data('tabId') || 'tab-init';
        return {
            tabId: tabId,
            filePath: $pane.data('filePath') || (window.DBQUERY ? window.DBQUERY.filePath : ''),
            $pane: $pane,
            lastQueryResult: lastQueryResult,
            dataTable: dataTable
        };
    },

    getTabByFilePath: function (filePath) {
        var norm = String(filePath || '').replace(/\\/g, '/');
        for (var id in this.tabs) {
            if (Object.prototype.hasOwnProperty.call(this.tabs, id)) {
                var tab = this.tabs[id];
                if (tab.filePath && String(tab.filePath).replace(/\\/g, '/') === norm) {
                    return tab;
                }
            }
        }
        return null;
    },

    activateTab: function (tabId) {
        var tab = this.tabs[tabId];
        if (!tab) return;
        this.activeTabId = tabId;

        // 切换标签按钮激活状态
        $('#app-tabbar .tab-item').removeClass('active').attr('aria-selected', 'false');
        tab.$tabBtn.addClass('active').attr('aria-selected', 'true');
        if (tab.$tabBtn[0] && tab.$tabBtn[0].scrollIntoView) {
            try {
                tab.$tabBtn[0].scrollIntoView({ behavior: 'smooth', block: 'nearest', inline: 'nearest' });
            } catch (ignore) {
                tab.$tabBtn[0].scrollIntoView(false);
            }
        }

        // 切换标签内容窗格
        $('.tab-pane').removeClass('active').hide();
        tab.$pane.addClass('active').show();

        // 同步全局变量以兼容历史脚本与测试
        dataTable = tab.dataTable;
        lastQueryResult = tab.lastQueryResult;
        if (window.DBQUERY) {
            window.DBQUERY.filePath = tab.filePath;
            window.DBQUERY.formParams = tab.formParams;
        }

        // 激活时重新计算表格列宽
        if (tab.dataTable) {
            window.setTimeout(function () {
                try { tab.dataTable.columns.adjust(); } catch (ignore) {}
            }, 20);
        }

        // 高亮侧边栏对应的报表项
        if (tab.filePath) {
            highlightCurrentForm(tab.filePath);
            $('#project-switcher-trigger .project-switcher-current').text('当前：' + tab.title);
        } else {
            $('.nav-item-link').removeClass('active');
            $('#project-switcher-trigger .project-switcher-current').text('综合查询');
        }

        if (window.DrawerManager) {
            DrawerManager.highlightActiveTab();
        }
    },

    closeTab: function (tabId) {
        var tab = this.tabs[tabId];
        if (!tab || tab.isWelcome) return;

        var tabIds = Object.keys(this.tabs);
        var curIndex = tabIds.indexOf(tabId);
        var nextTabId = 'tab-welcome';
        if (this.activeTabId === tabId) {
            if (curIndex > 0 && tabIds[curIndex - 1]) {
                nextTabId = tabIds[curIndex - 1];
            } else if (curIndex + 1 < tabIds.length && tabIds[curIndex + 1]) {
                nextTabId = tabIds[curIndex + 1];
            }
        }

        if (tab.dataTable) {
            try { tab.dataTable.destroy(); } catch (ignore) {}
            tab.dataTable = null;
        }
        tab.$tabBtn.remove();
        tab.$pane.remove();
        delete this.tabs[tabId];

        if (this.activeTabId === tabId) {
            this.activateTab(nextTabId);
        } else if (window.DrawerManager) {
            DrawerManager.highlightActiveTab();
        }
    },

    openReport: function (filePath) {
        var self = this;
        var existing = self.getTabByFilePath(filePath);
        if (existing) {
            self.activateTab(existing.tabId);
            return;
        }

        self.fetchFormConfig(filePath, function (form) {
            if (!form) {
                window.location.href = preserveEmbedParams(apiPath('/query/' + encodeFilePath(filePath)));
                return;
            }
            self.createReportTab(form);
        });
    },

    fetchFormConfig: function (filePath, callback) {
        var self = this;
        var norm = String(filePath || '').replace(/\\/g, '/');
        if (self.formsCache && self.formsCache[norm]) {
            callback(self.formsCache[norm]);
            return;
        }
        $.get(apiPath('/api/forms'), function (data) {
            self.cacheFormsData(data);
            callback(self.formsCache[norm] || null);
        }).fail(function () {
            callback(null);
        });
    },

    cacheFormsData: function (data) {
        this.rawFormsData = data;
        this.formsCache = {};
        for (var group in data) {
            if (!Object.prototype.hasOwnProperty.call(data, group)) continue;
            var forms = data[group];
            for (var i = 0; i < forms.length; i++) {
                var f = forms[i];
                var fp = String(f.file_path || '').replace(/\\/g, '/');
                this.formsCache[fp] = f;
            }
        }
    },

    createReportTab: function (form) {
        var self = this;
        self.tabCounter++;
        var tabId = 'tab-report-' + self.tabCounter;
        var filePath = form.file_path;

        var $btn = $('<div class="tab-item" role="tab"></div>')
            .attr('id', 'tab-btn-' + tabId)
            .attr('data-tab-id', tabId)
            .attr('data-file-path', filePath)
            .attr('title', form.title)
            .attr('aria-controls', 'pane-' + tabId);

        $btn.html(
            '<svg class="icon tab-icon" aria-hidden="true" viewBox="0 0 24 24"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/><polyline points="10 9 9 9 8 9"/></svg>' +
            '<span class="tab-title">' + esc(form.title) + '</span>' +
            '<button class="tab-close" type="button" title="关闭标签页" aria-label="关闭 ' + esc(form.title) + ' 标签页">' +
            '<svg class="tab-close-icon" viewBox="0 0 12 12" width="10" height="10" aria-hidden="true">' +
            '<path d="M2.5 2.5l7 7M9.5 2.5l-7 7" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/>' +
            '</svg></button>'
        );
        $('#app-tabbar').append($btn);

        var $pane = $('<div class="tab-pane" role="tabpanel"></div>')
            .attr('id', 'pane-' + tabId)
            .attr('data-tab-id', tabId)
            .attr('data-file-path', filePath)
            .attr('aria-labelledby', 'tab-btn-' + tabId);

        var paneHtml = self.renderPaneHtml(form, tabId);
        $pane.html(paneHtml);
        $('#tab-panes-container').append($pane);

        self.tabs[tabId] = {
            tabId: tabId,
            filePath: filePath,
            title: form.title,
            isWelcome: false,
            $tabBtn: $btn,
            $pane: $pane,
            dataTable: null,
            lastQueryResult: null,
            formParams: form.params || []
        };

        initializeDefaultValues($pane);
        initializeSearchableSelects($pane);
        loadDynamicSelectOptions(filePath, form.params || [], $pane);

        self.activateTab(tabId);
    },

    renderPaneHtml: function (form, tabId) {
        var isEmbed = isEmbedMode();
        var homeUrl = isEmbed ? preserveEmbedParams(apiPath('/?embed=1&hide_header=1&sidebar=0')) : apiPath('/');
        var html = '<header class="page-header">';
        html += '<div class="page-heading-left">';
        html += '<a class="report-home-link" href="' + esc(homeUrl) + '" aria-label="返回报表主页" title="返回报表主页">';
        html += '<svg class="icon" aria-hidden="true" viewBox="0 0 24 24"><path d="M15 18l-6-6 6-6"/></svg>';
        html += '<span>返回报表主页</span></a>';
        html += '<div class="page-title-block">';
        html += '<h1 class="page-title">' + esc(form.title) + '</h1>';
        if (form.description) {
            html += '<p class="page-desc">' + esc(form.description) + '</p>';
        }
        html += '</div></div>';

        if (isSidebarHidden()) {
            html += '<div class="project-switcher" id="project-switcher-' + tabId + '">';
            html += '<button class="project-switcher-trigger" type="button" aria-expanded="false" onclick="toggleDynamicProjectSwitcher(this)">';
            html += '<span class="project-switcher-label">查询项目</span>';
            html += '<span class="project-switcher-current">当前：' + esc(form.title) + '</span>';
            html += '<span class="project-switcher-caret" aria-hidden="true">▾</span></button>';
            html += '<div class="project-switcher-panel" hidden>';
            html += '<label class="visually-hidden">搜索查询项目</label>';
            html += '<input type="search" class="project-search" placeholder="搜索查询项目" oninput="filterDynamicProjectSwitcher(this)">';
            html += '<div class="project-menu-tree dynamic-project-menu-tree"></div>';
            html += '</div></div>';
        }
        html += '</header>';

        html += '<section class="business-section conditions-section" aria-labelledby="conditions-heading-' + tabId + '">';
        html += '<div class="section-heading" id="conditions-heading-' + tabId + '">查询条件</div>';
        if (form.params && form.params.length) {
            html += '<div class="params-grid">';
            for (var i = 0; i < form.params.length; i++) {
                html += renderParamHtml(form.params[i], tabId, i + 1);
            }
            html += '</div>';
        }
        html += '<div class="action-bar">';
        html += '<button class="btn btn-primary-action btn-execute" type="button" onclick="executeQuery(\'' + tabId + '\')">';
        html += '<svg class="icon" aria-hidden="true" viewBox="0 0 24 24"><circle cx="11" cy="11" r="6"/><path d="m16 16 4 4"/></svg>';
        html += '<span class="button-text">查询</span></button>';
        html += '<button class="btn btn-reset-action btn-reset" type="button" onclick="resetQueryParams(\'' + tabId + '\')" title="清空并重置为初始默认条件">';
        html += '<svg class="icon" aria-hidden="true" viewBox="0 0 24 24"><path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"/><path d="M3 3v5h5"/></svg>';
        html += '<span class="button-text">重置</span></button>';
        html += '<button class="btn btn-secondary-action btn-export" type="button" onclick="exportExcel(\'' + tabId + '\')" disabled>';
        html += '<svg class="icon" aria-hidden="true" viewBox="0 0 24 24"><path d="M12 3v11m0 0 4-4m-4 4-4-4"/><path d="M5 14v5h14v-5"/></svg>';
        html += '<span class="button-text">导出</span></button>';
        html += '<span class="spinner d-none" aria-label="正在查询"></span>';
        html += '</div></section>';

        html += '<section class="business-section result-section" aria-labelledby="result-heading-' + tabId + '">';
        html += '<div class="section-heading result-heading" id="result-heading-' + tabId + '">';
        html += '<div class="result-heading-left"><span class="result-title">查询结果</span>';
        html += '<span class="result-warning d-none" aria-live="polite"></span></div>';
        html += '<span class="action-status result-status" aria-live="polite"></span></div>';
        html += '<div class="inline-message d-none" role="status"></div>';
        html += '<div class="result-panel">';
        html += '<table class="display result-table" style="width:100%"><thead></thead><tbody></tbody></table>';
        html += '<div class="result-empty">设置查询条件后点击“查询”</div>';
        html += '</div></section>';

        return html;
    }
};

/* ════════════════════════════════════════════════════════════════════════════
   DrawerManager：快捷报表抽屉控制器（平滑滑出/收起，搜索，分组，选报表自动缩小收起）
   ════════════════════════════════════════════════════════════════════════════ */
var DrawerManager = {
    formsData: null,
    isOpen: false,

    init: function () {
        var self = this;
        var $drawer = $('#floating-drawer');
        var $backdrop = $('#drawer-backdrop');
        if (!$drawer.length) return;

        // Esc 快捷键收起抽屉
        $(document).on('keydown', function (e) {
            if (e.key === 'Escape' && self.isOpen) {
                self.close();
            }
        });

        // 监听抽屉内列表项点击：打开对应报表并自动收起抽屉
        $drawer.on('click', '.drawer-item', function (e) {
            e.preventDefault();
            var filePath = $(this).data('filePath');
            if (filePath && window.TabManager) {
                TabManager.openReport(filePath);
                self.close();
            }
        });

        // 抽屉内分组折叠展开
        $drawer.on('click', '.drawer-group-title', function () {
            $(this).closest('.drawer-group').toggleClass('collapsed');
        });

        // 支持 URL 参数 drawer=1 自动展开（便于测试与直达）
        try {
            if (new URLSearchParams(window.location.search).get('drawer') === '1') {
                $drawer.css('transition', 'none');
                self.open();
            }
        } catch (ignore) {}
    },

    toggle: function () {
        if (this.isOpen) {
            this.close();
        } else {
            this.open();
        }
    },

    open: function () {
        var self = this;
        var $drawer = $('#floating-drawer');
        var $backdrop = $('#drawer-backdrop');
        var $toggleBtn = $('#drawer-toggle-btn');
        if (!$drawer.length) return;

        self.isOpen = true;
        $drawer.addClass('active').attr('aria-hidden', 'false');
        $backdrop.addClass('active');
        $toggleBtn.addClass('active').attr('aria-expanded', 'true');

        // 如果尚未渲染过数据，先加载或使用已缓存的表单数据
        if (!self.formsData) {
            if (window.TabManager && window.TabManager.rawFormsData) {
                self.render(window.TabManager.rawFormsData);
            } else {
                $.get(apiPath('/api/forms'), function (data) {
                    if (window.TabManager) TabManager.cacheFormsData(data);
                    self.render(data);
                });
            }
        } else {
            self.highlightActiveTab();
        }

        // 自动聚焦搜索框，提升效率
        window.setTimeout(function () {
            $('#drawer-search-input').trigger('focus');
        }, 150);
    },

    close: function () {
        this.isOpen = false;
        $('#floating-drawer').removeClass('active').attr('aria-hidden', 'true');
        $('#drawer-backdrop').removeClass('active');
        $('#drawer-toggle-btn').removeClass('active').attr('aria-expanded', 'false');
    },

    render: function (data) {
        this.formsData = data || {};
        var $tree = $('#drawer-tree');
        var totalCount = 0;
        var html = '';

        for (var group in data) {
            if (!Object.prototype.hasOwnProperty.call(data, group)) continue;
            var forms = data[group] || [];
            totalCount += forms.length;
            html += '<div class="drawer-group">';
            html += '<div class="drawer-group-title">';
            html += '<span class="drawer-group-arrow" aria-hidden="true">▾</span>';
            html += '<span class="drawer-group-name">' + esc(group) + '</span>';
            html += '<span class="drawer-group-count">' + forms.length + ' 个</span>';
            html += '</div>';
            html += '<div class="drawer-group-items">';

            for (var i = 0; i < forms.length; i++) {
                var form = forms[i];
                var fp = form.file_path || '';
                var isHasDesc = Boolean(form.description);
                html += '<a class="drawer-item" href="javascript:void(0);" data-file-path="' + esc(fp) + '" data-title="' + esc(form.title.toLowerCase()) + '" title="' + esc(form.title) + '">';
                html += '<svg class="icon drawer-item-icon" aria-hidden="true" viewBox="0 0 24 24"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/></svg>';
                html += '<div class="drawer-item-info">';
                html += '<span class="drawer-item-title">' + esc(form.title) + '</span>';
                if (isHasDesc) {
                    html += '<span class="drawer-item-desc">' + esc(form.description) + '</span>';
                }
                html += '</div>';
                html += '<span class="drawer-item-status d-none" data-fp="' + esc(fp) + '">已打开</span>';
                html += '</a>';
            }
            html += '</div></div>';
        }

        if (!totalCount) {
            html = '<div class="drawer-empty-search">暂无可用的 Web 报表</div>';
        }

        $tree.html(html);
        $('#drawer-forms-count').text(totalCount ? (totalCount + ' 个') : '');
        this.highlightActiveTab();
    },

    highlightActiveTab: function () {
        var activeTab = window.TabManager ? TabManager.getActiveTab() : null;
        var activeFp = activeTab ? (activeTab.filePath || '') : '';
        var normActiveFp = String(activeFp).replace(/\\/g, '/');

        var openFps = {};
        if (window.TabManager && window.TabManager.tabs) {
            for (var tid in TabManager.tabs) {
                var tab = TabManager.tabs[tid];
                if (tab.filePath) {
                    openFps[String(tab.filePath).replace(/\\/g, '/')] = true;
                }
            }
        }

        $('#drawer-tree .drawer-item').each(function () {
            var $item = $(this);
            var itemFp = String($item.data('filePath') || '').replace(/\\/g, '/');
            var isCurrentActive = normActiveFp && itemFp === normActiveFp;
            var isAlreadyOpen = openFps[itemFp];

            $item.toggleClass('active', Boolean(isCurrentActive));
            $item.find('.drawer-item-status').toggleClass('d-none', !isAlreadyOpen);
        });
    },

    filter: function (keyword) {
        var text = String(keyword || '').trim().toLowerCase();
        var $wrapper = $('#drawer-search-input').closest('.drawer-search-wrapper');
        $wrapper.find('.drawer-search-clear').toggleClass('d-none', !text);

        var matchCount = 0;
        $('#drawer-tree .drawer-group').each(function () {
            var $grp = $(this);
            var grpMatches = 0;
            $grp.find('.drawer-item').each(function () {
                var $item = $(this);
                var title = String($item.data('title') || '');
                var desc = String($item.find('.drawer-item-desc').text() || '').toLowerCase();
                var matched = !text || title.indexOf(text) >= 0 || desc.indexOf(text) >= 0;
                $item.toggle(matched);
                if (matched) grpMatches++;
            });
            $grp.toggle(grpMatches > 0);
            if (text && grpMatches > 0) {
                $grp.removeClass('collapsed').find('.drawer-group-items').show();
            }
            matchCount += grpMatches;
        });

        var $empty = $('#drawer-search-empty');
        if (text && matchCount === 0) {
            if (!$empty.length) {
                $('#drawer-tree').append('<div class="drawer-empty-search" id="drawer-search-empty">未搜索到匹配的报表</div>');
            } else {
                $empty.show();
            }
        } else {
            $empty.remove();
        }
    },

    clearFilter: function () {
        $('#drawer-search-input').val('');
        this.filter('');
        $('#drawer-search-input').trigger('focus');
    }
};

function renderParamHtml(p, tabId, loopIndex) {
    var fieldId = 'param-' + tabId + '-' + loopIndex;
    var rawDef = p.raw_default !== undefined ? p.raw_default : (p.default || '');
    var resolvedDef = p.default !== undefined ? p.default : '';
    var widthStyle = p.width ? ' style="--param-width: ' + esc(p.width) + ';"' : '';
    var requiredAttr = p.required ? ' required' : '';
    var reqMark = p.required ? '<span class="required-mark" aria-label="必填">*</span>' : '';
    var placeholder = esc(p.placeholder || p.label || '');

    if (p.ptype === 'hidden') {
        var hVal = esc(String(resolvedDef).replace('{today}', ''));
        return '<input type="hidden" class="param-input" data-name="' + esc(p.name) + '" data-default="' + esc(rawDef) + '" value="' + hVal + '">';
    }

    var html = '<div class="param-field' + (p.ptype === 'checkbox' ? ' checkbox-field' : '') + '"' + widthStyle + '>';
    html += '<label for="' + fieldId + '">' + esc(p.label) + reqMark + '</label>';

    if (p.ptype === 'date') {
        var dVal = rawDef === '{today}' ? todayStr() : esc(String(resolvedDef).replace('{today}', ''));
        html += '<input id="' + fieldId + '" type="date" class="param-input" data-name="' + esc(p.name) + '" data-default="' + esc(rawDef) + '" value="' + dVal + '"' + (p.placeholder ? ' placeholder="' + esc(p.placeholder) + '"' : '') + requiredAttr + '>';
    } else if (p.ptype === 'datetime') {
        var dtVal = rawDef === '{today}' ? nowStr() : esc(String(resolvedDef).replace(' ', 'T'));
        html += '<input id="' + fieldId + '" type="datetime-local" step="1" class="param-input" data-name="' + esc(p.name) + '" data-default="' + esc(rawDef) + '" value="' + dtVal + '"' + (p.placeholder ? ' placeholder="' + esc(p.placeholder) + '"' : '') + requiredAttr + '>';
    } else if (p.ptype === 'number') {
        html += '<input id="' + fieldId + '" type="number" class="param-input" data-name="' + esc(p.name) + '" data-default="' + esc(rawDef) + '" value="' + esc(resolvedDef) + '" placeholder="' + (p.placeholder ? esc(p.placeholder) : '请输入数字') + '"' + requiredAttr + '>';
    } else if (p.ptype === 'select') {
        var menuId = 'param-options-' + tabId + '-' + loopIndex;
        html += '<div class="searchable-select" data-name="' + esc(p.name) + '" data-default="' + esc(rawDef) + '" data-required="' + (p.required ? '1' : '0') + '" data-allow-custom="' + (p.allow_custom ? '1' : '0') + '">';
        html += '<div class="searchable-select-control">';
        html += '<input id="' + fieldId + '" type="text" class="searchable-select-input" autocomplete="off" role="combobox" aria-autocomplete="list" aria-expanded="false" aria-controls="' + menuId + '" placeholder="' + (p.placeholder ? esc(p.placeholder) : '输入关键字筛选') + '">';
        html += '<button type="button" class="searchable-select-toggle" tabindex="-1" aria-label="展开候选项">▾</button>';
        html += '</div>';
        html += '<input type="hidden" class="param-input searchable-select-value" data-name="' + esc(p.name) + '" data-default="' + esc(rawDef) + '" value="' + esc(resolvedDef) + '">';
        html += '<div id="' + menuId + '" class="searchable-select-menu" role="listbox" hidden>';
        var items = p.option_items || [];
        for (var i = 0; i < items.length; i++) {
            var opt = items[i];
            var isSel = String(opt.value) === String(resolvedDef);
            html += '<button type="button" class="searchable-select-option" role="option" data-value="' + esc(opt.value) + '" aria-selected="' + (isSel ? 'true' : 'false') + '">' + esc(opt.label) + '</button>';
        }
        html += '</div></div>';
    } else if (p.ptype === 'textarea') {
        var taVal = esc(String(resolvedDef).replace('{today}', ''));
        html += '<textarea id="' + fieldId + '" class="param-input param-textarea" data-name="' + esc(p.name) + '" data-default="' + esc(rawDef) + '" placeholder="' + placeholder + '"' + requiredAttr + '>' + taVal + '</textarea>';
    } else if (p.ptype === 'checkbox') {
        var isChecked = ['1', 'true', 'yes', 'on', '是'].indexOf(String(rawDef).toLowerCase()) >= 0;
        html += '<label class="checkbox-control" for="' + fieldId + '">';
        html += '<input id="' + fieldId + '" type="checkbox" class="param-input" data-name="' + esc(p.name) + '" data-default="' + esc(rawDef) + '" data-checked-value="1" value="1"' + (isChecked ? ' checked' : '') + requiredAttr + '>';
        html += '<span>是</span></label>';
    } else if (p.ptype === 'radio') {
        html += '<div class="radio-group" id="' + fieldId + '" data-default="' + esc(rawDef) + '">';
        var radioItems = p.option_items || [];
        for (var r = 0; r < radioItems.length; r++) {
            var rOpt = radioItems[r];
            var rSel = String(rOpt.value) === String(resolvedDef);
            html += '<label class="radio-control">';
            html += '<input type="radio" class="param-input" data-name="' + esc(p.name) + '" value="' + esc(rOpt.value) + '"' + (rSel ? ' checked' : '') + (p.required && r === 0 ? ' required' : '') + '>';
            html += '<span>' + esc(rOpt.label) + '</span></label>';
        }
        html += '</div>';
    } else {
        var txtVal = esc(String(resolvedDef).replace('{today}', ''));
        html += '<input id="' + fieldId + '" type="text" class="param-input" data-name="' + esc(p.name) + '" data-default="' + esc(rawDef) + '" value="' + txtVal + '" placeholder="' + placeholder + '"' + requiredAttr + '>';
    }

    html += '</div>';
    return html;
}

function toggleDynamicProjectSwitcher(trigger) {
    var $panel = $(trigger).next('.project-switcher-panel');
    var opening = $panel.prop('hidden');
    $panel.prop('hidden', !opening);
    $(trigger).attr('aria-expanded', opening ? 'true' : 'false');
    if (opening) {
        $panel.find('.project-search').trigger('focus');
        if ($panel.find('.dynamic-project-menu-tree:empty').length) {
            $panel.find('.dynamic-project-menu-tree').html($('#form-tree').html() || $('#project-menu-tree').html());
        }
    }
}

function filterDynamicProjectSwitcher(input) {
    var $panel = $(input).closest('.project-switcher-panel');
    filterFormTree($(input).val(), $panel.find('.dynamic-project-menu-tree'));
}

/* ════════════════════════════════════════════════════════════════════════════
   页面初始化与全局事件
   ════════════════════════════════════════════════════════════════════════════ */
$(document).ready(function () {
    TabManager.init();
    DrawerManager.init();
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

function initializeDefaultValues($context) {
    $context = $context || $(document);
    $context.find('.param-input[type="date"]').each(function () {
        var $input = $(this);
        if (!$input.val() && $input.data('default') === '{today}') {
            $input.val(todayStr());
        }
    });
    $context.find('.param-input[type="datetime-local"]').each(function () {
        var $input = $(this);
        if (!$input.val() && $input.data('default') === '{today}') {
            $input.val(nowStr());
        }
    });
}

function initializeSearchableSelects($context) {
    $context = $context || $(document);
    $context.find('.searchable-select').each(function () {
        var $root = $(this);
        if ($root.data('searchableSelect')) return;

        var $input = $root.find('.searchable-select-input');
        var $value = $root.find('.searchable-select-value');
        var $menu = $root.find('.searchable-select-menu');
        var $toggle = $root.find('.searchable-select-toggle');
        var allowCustom = $root.attr('data-allow-custom') === '1';
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
            if ($active[0] && $active[0].scrollIntoView) {
                $active[0].scrollIntoView({block: 'nearest'});
            }
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
            $menu.find('[aria-selected="true"]').attr('aria-selected', 'false');
            if (allowCustom) {
                $value.val($input.val());
            } else {
                $value.val('');
            }
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

function loadDynamicSelectOptions(filePath, formParams, $context) {
    var config = window.DBQUERY || {};
    filePath = filePath || config.filePath;
    var params = formParams || config.formParams || [];
    $context = $context || $(document);

    params.forEach(function (param) {
        if (!param || param.ptype !== 'select' || !param.dynamic_options) return;
        var $root = $context.find('.searchable-select').filter(function () {
            return $(this).data('name') === param.name;
        }).first();
        if (!$root.length) return;
        $.ajax({
            url: apiPath('/api/options'),
            method: 'POST',
            contentType: 'application/json',
            data: JSON.stringify({file_path: filePath, param_name: param.name}),
            success: function (data) {
                var component = $root.data('searchableSelect');
                if (component && component.setOptions) component.setOptions(data.options || []);
                if (data.warning) showToast(data.warning, 'warning');
            },
            error: function () {
                showToast('候选数据加载失败，可刷新重试。', 'warning');
            }
        });
    });
}

function loadFormTree() {
    var $trees = $('#form-tree, #project-menu-tree');
    $.get(apiPath('/api/forms'), function (data) {
        if (window.TabManager) {
            TabManager.cacheFormsData(data);
        }
        var html = buildFormTree(data);
        $trees.html(html);
        highlightCurrentForm();
        if ($('#welcome-quick-links').length) {
            $('#welcome-quick-links').html(buildWelcomeCards(data));
        }
        if (window.DrawerManager) {
            DrawerManager.render(data);
        }
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
            var url = preserveEmbedParams(apiPath('/query/' + encodeFilePath(form.file_path)));
            html += '<a href="' + esc(url) + '" class="nav-item-link' + (form.description ? ' has-desc' : '') + '" data-title="' + esc(form.title.toLowerCase()) + '" data-file-path="' + esc(form.file_path) + '">';
            html += svgIcon('document', 'nav-item-icon') + '<span class="nav-item-content"><span class="nav-item-title">' + esc(form.title) + '</span>';
            if (form.description) html += '<span class="nav-item-desc">' + esc(form.description) + '</span>';
            html += '</span></a>';
        }
        html += '</div></div>';
    }
    return html;
}

function buildWelcomeCards(data) {
    var html = '<section class="business-section project-list-section" aria-labelledby="project-list-heading">';
    html += '<div class="section-heading" id="project-list-heading">';
    html += '<svg class="icon" aria-hidden="true" viewBox="0 0 24 24"><rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/><rect x="14" y="14" width="7" height="7"/><rect x="3" y="14" width="7" height="7"/></svg>';
    html += '<span>查询项目卡片</span></div>';
    html += '<div class="project-list">';
    for (var group in data) {
        if (!Object.prototype.hasOwnProperty.call(data, group)) continue;
        var forms = data[group];
        html += '<div class="project-group">';
        html += '<div class="project-group-title">';
        html += '<span class="group-name">' + esc(group) + '</span>';
        html += '<span class="group-count">' + forms.length + ' 个表单</span></div>';
        for (var i = 0; i < forms.length; i++) {
            var form = forms[i];
            var url = preserveEmbedParams(apiPath('/query/' + encodeFilePath(form.file_path)));
            html += '<a class="project-card" href="' + esc(url) + '" data-file-path="' + esc(form.file_path) + '">';
            html += '<div class="project-card-icon">';
            html += '<svg class="icon" aria-hidden="true" viewBox="0 0 24 24"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/></svg>';
            html += '</div><div class="project-card-info">';
            html += '<strong class="project-card-title">' + esc(form.title) + '</strong>';
            if (form.description) html += '<small class="project-card-desc">' + esc(form.description) + '</small>';
            html += '</div><span class="project-card-badge">打开</span></a>';
        }
        html += '</div>';
    }
    html += '</div></section>';
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

function highlightCurrentForm(filePath) {
    filePath = filePath || (window.DBQUERY ? window.DBQUERY.filePath : '');
    if (!filePath) return;
    var encodedPath = encodeFilePath(filePath);
    var normPath = String(filePath).replace(/\\/g, '/');
    $('.nav-item-link').removeClass('active').each(function () {
        var $link = $(this);
        var linkFp = $link.data('filePath') || '';
        var href = $link.attr('href') || '';
        if ((linkFp && String(linkFp).replace(/\\/g, '/') === normPath) ||
            href.indexOf(encodedPath) >= 0 || href.indexOf(filePath) >= 0) {
            $link.addClass('active');
            $link.closest('.nav-group-items').show();
            $link.closest('.nav-group').find('.nav-group-title').first().removeClass('collapsed');
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
        if (!$(event.target).closest('#project-switcher, .project-switcher').length) {
            $panel.prop('hidden', true);
            $trigger.attr('aria-expanded', 'false');
            $('.project-switcher-panel').prop('hidden', true);
            $('.project-switcher-trigger').attr('aria-expanded', 'false');
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
    $.get(apiPath('/api/test-connection'), function (data) {
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

/**
 * P1-1: 从 searchable-select 组件解析最终提交值。
 */
function resolveSearchableSelectValue($root) {
    return $root.find('.searchable-select-value').val() || '';
}

function collectParams(context) {
    var $ctx = context ? $(context) : (TabManager.getActivePane() || $(document));
    var params = {};
    $ctx.find('.param-input').each(function () {
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

function validateRequiredParams($pane) {
    $pane = $pane || (TabManager.getActivePane() || $(document));
    var valid = true;
    $pane.find('.param-input[required]').each(function () {
        if (!this.checkValidity()) {
            valid = false;
            return false;
        }
    });
    $pane.find('.searchable-select[data-required="1"]').each(function () {
        var $root = $(this);
        if (!resolveSearchableSelectValue($root)) {
            valid = false;
            $root.find('.searchable-select-input').trigger('focus');
            return false;
        }
    });
    if (!valid) {
        showInlineMessage('warning', '请先填写标记为必填的查询条件。', $pane);
    }
    return valid;
}

function setQueryLoading(isLoading, $pane) {
    $pane = $pane || (TabManager.getActivePane() || $(document));
    var $button = $pane.find('#btn-execute, .btn-execute, .btn-primary-action');
    $button.prop('disabled', isLoading);
    $button.find('.button-text').text(isLoading ? '查询中…' : '查询');
    $pane.find('#loading, .spinner').toggleClass('d-none', !isLoading);
    if (isLoading) $pane.find('#btn-export, .btn-export, .btn-secondary-action').prop('disabled', true);
}

function setExportLoading(isLoading, $pane, hasResult) {
    $pane = $pane || (TabManager.getActivePane() || $(document));
    var $button = $pane.find('#btn-export, .btn-export, .btn-secondary-action');
    var disabled = isLoading || !(hasResult || lastQueryResult);
    $button.prop('disabled', disabled);
    $button.find('.button-text').text(isLoading ? '导出中…' : '导出');
}

function resetQueryParams(tabId) {
    var tab = tabId ? TabManager.tabs[tabId] : (TabManager.getActiveTab() || TabManager.getLegacyActiveTab());
    if (!tab || !tab.$pane) return;
    var $pane = tab.$pane;

    // 1. 重置日期
    $pane.find('.param-input[type="date"]').each(function () {
        var $input = $(this);
        var def = $input.data('default');
        $input.val(def === '{today}' ? todayStr() : (def || ''));
    });

    // 2. 重置日期时间
    $pane.find('.param-input[type="datetime-local"]').each(function () {
        var $input = $(this);
        var def = $input.data('default');
        $input.val(def === '{today}' ? nowStr() : (def || '').replace(' ', 'T'));
    });

    // 3. 重置文本框、数字框、多行文本框
    $pane.find('.param-input[type="text"], .param-input[type="number"], textarea.param-input, input[type="hidden"].param-input:not(.searchable-select-value)').each(function () {
        var $input = $(this);
        var def = $input.data('default');
        if (def === undefined || def === null || def === '{today}') def = '';
        $input.val(def);
    });

    // 4. 重置复选框
    $pane.find('.param-input[type="checkbox"]').each(function () {
        var $input = $(this);
        var def = String($input.data('default') || '').toLowerCase();
        var isChecked = ['1', 'true', 'yes', 'on', '是'].indexOf(def) >= 0;
        $input.prop('checked', isChecked);
    });

    // 5. 重置单选框
    $pane.find('.radio-group').each(function () {
        var $group = $(this);
        var def = $group.data('default');
        $group.find('.param-input[type="radio"]').each(function () {
            var $radio = $(this);
            $radio.prop('checked', $radio.val() === String(def));
        });
    });

    // 6. 重置可搜索下拉框
    $pane.find('.searchable-select').each(function () {
        var $root = $(this);
        var $input = $root.find('.searchable-select-input');
        var $value = $root.find('.searchable-select-value');
        var $menu = $root.find('.searchable-select-menu');
        var defVal = $root.data('default');
        if (defVal === undefined || defVal === null) defVal = '';

        $value.val(defVal);
        var $matchingOpt = $menu.find('.searchable-select-option').filter(function () {
            return String($(this).data('value')) === String(defVal);
        }).first();

        if ($matchingOpt.length) {
            $input.val($matchingOpt.text());
            $menu.find('.searchable-select-option').attr('aria-selected', 'false');
            $matchingOpt.attr('aria-selected', 'true');
        } else {
            $input.val(defVal);
            $menu.find('.searchable-select-option').attr('aria-selected', 'false');
        }
    });

    clearInlineMessage($pane);
    clearResultWarning($pane);
    showToast('查询条件已重置为默认值。', 'info');
}

function executeQuery(tabId) {
    var tab = tabId ? TabManager.tabs[tabId] : (TabManager.getActiveTab() || TabManager.getLegacyActiveTab());
    if (!tab || !tab.$pane) return;
    var $pane = tab.$pane;
    var filePath = tab.filePath || (window.DBQUERY ? window.DBQUERY.filePath : '');
    var $btnExecute = $pane.find('#btn-execute, .btn-execute, .btn-primary-action');
    if (!filePath || $btnExecute.prop('disabled')) return;
    if (!validateRequiredParams($pane)) return;

    clearInlineMessage($pane);
    clearResultWarning($pane);
    setQueryLoading(true, $pane);
    $pane.find('#result-empty, .result-empty').hide();
    $pane.find('#status-text, .result-status').text('正在查询，请稍候…');

    var params = collectParams($pane);

    $.ajax({
        url: apiPath('/api/query'),
        method: 'POST',
        contentType: 'application/json',
        data: JSON.stringify({file_path: filePath, params: params}),
        success: function (data) {
            if (data.error) {
                handleQueryFailure(data.error, tab);
                return;
            }
            tab.lastQueryResult = data;
            lastQueryResult = data;
            renderResult(data, tab);
            $pane.find('#status-text, .result-status').text(querySummary(data));
            setExportLoading(false, $pane, true);
            if (data.truncated) {
                setResultWarning('已显示前 ' + data.max_rows + ' 条，请缩小查询范围。', $pane);
            }
        },
        error: function (xhr) {
            getRequestError(xhr, '查询失败，请稍后重试。').then(function (msg) {
                handleQueryFailure(msg, tab);
            });
        },
        complete: function () {
            setQueryLoading(false, $pane);
        }
    });
}

function handleQueryFailure(message, tab) {
    tab = tab || (TabManager.getActiveTab() || TabManager.getLegacyActiveTab());
    var $pane = tab && tab.$pane ? tab.$pane : $(document);
    if (tab) tab.lastQueryResult = null;
    lastQueryResult = null;
    clearResultWarning($pane);
    setExportLoading(false, $pane, false);
    $pane.find('#status-text, .result-status').text('查询未完成');
    $pane.find('#result-empty, .result-empty').text('暂无符合条件的数据').show();
    showInlineMessage('error', message || '查询失败，请稍后重试。', $pane);
}

function querySummary(data) {
    var summary = '共 ' + data.row_count + ' 条记录';
    if (data.col_count) summary += ' · ' + data.col_count + ' 个字段';
    summary += ' · 用时 ' + Number(data.elapsed || 0).toFixed(2) + ' 秒';
    return summary;
}

function renderResult(data, tab) {
    tab = tab || (TabManager ? TabManager.getActiveTab() : null) || TabManager.getLegacyActiveTab();
    var $pane = tab && tab.$pane ? tab.$pane : $(document);
    var $table = $pane.find('#result-table, .result-table').first();

    if (tab && tab.dataTable) {
        try { tab.dataTable.destroy(); } catch (ignore) {}
        tab.dataTable = null;
    } else if (dataTable) {
        try { dataTable.destroy(); } catch (ignore) {}
        dataTable = null;
    }

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

    var dt = $table.DataTable({
        paging: true,
        pageLength: 100,
        lengthMenu: [50, 100, 200, 500, 1000],
        ordering: true,
        searching: true,
        info: true,
        scrollX: true,
        autoWidth: false,
        dom: "<'dt-topbar'<'dt-page-size'l><'dt-filter'f>>" +
            "t" +
            "<'dt-bottombar'<'dt-info'i><'dt-pagination'p>>",
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

    if (tab) {
        tab.dataTable = dt;
    }
    dataTable = dt;
    bindResultGridLayout(tab);
    if (data.row_count) {
        $pane.find('#result-empty, .result-empty').hide();
    } else {
        $pane.find('#result-empty, .result-empty').text('暂无符合条件的数据').show();
    }
}

function exportExcel(tabId) {
    var tab = tabId ? TabManager.tabs[tabId] : (TabManager.getActiveTab() || TabManager.getLegacyActiveTab());
    if (!tab || !tab.$pane) return;
    var $pane = tab.$pane;
    var resultData = tab.lastQueryResult || lastQueryResult;
    var $btnExport = $pane.find('#btn-export, .btn-export, .btn-secondary-action');
    if (!resultData || $btnExport.prop('disabled')) return;

    var filePath = tab.filePath || (window.DBQUERY ? window.DBQUERY.filePath : '');
    setExportLoading(true, $pane, true);
    $pane.find('#status-text, .result-status').text('正在生成导出文件…');

    $.ajax({
        url: apiPath('/api/export'),
        method: 'POST',
        contentType: 'application/json',
        data: JSON.stringify({
            file_path: filePath,
            params: collectParams($pane),
            columns: resultData.columns,
            rows: resultData.rows,
            elapsed: resultData.elapsed
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
            $pane.find('#status-text, .result-status').text('导出文件已生成，正在下载。');
            showToast('导出文件已生成，正在下载。', 'success');
        },
        error: function (xhr) {
            getRequestError(xhr, '导出失败，请稍后重试。').then(function (message) {
                $pane.find('#status-text, .result-status').text('导出未完成');
                showInlineMessage('error', message, $pane);
            });
        },
        complete: function () {
            setExportLoading(false, $pane, true);
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

function showInlineMessage(type, message, $pane) {
    $pane = $pane || (TabManager ? TabManager.getActivePane() : null) || $(document);
    var $message = $pane.find('#result-message, .inline-message').first();
    if (!$message.length) {
        showToast(message, type);
        return;
    }
    $message.removeClass('d-none message-warning message-error message-success')
        .addClass('message-' + type)
        .text(message);
}

function clearInlineMessage($pane) {
    $pane = $pane || (TabManager ? TabManager.getActivePane() : null) || $(document);
    $pane.find('#result-message, .inline-message')
        .addClass('d-none')
        .removeClass('message-warning message-error message-success')
        .text('');
}

function setResultWarning(message, $pane) {
    $pane = $pane || (TabManager ? TabManager.getActivePane() : null) || $(document);
    $pane.find('#result-warning, .result-warning')
        .removeClass('d-none')
        .text(message || '');
}

function clearResultWarning($pane) {
    $pane = $pane || (TabManager ? TabManager.getActivePane() : null) || $(document);
    $pane.find('#result-warning, .result-warning')
        .addClass('d-none')
        .text('');
}

function bindResultGridLayout(tab) {
    $(window).off('resize.resultGridLayout').on('resize.resultGridLayout', function () {
        window.clearTimeout(resultGridResizeTimer);
        resultGridResizeTimer = window.setTimeout(function () {
            var curTab = TabManager ? TabManager.getActiveTab() : null;
            if (curTab && curTab.dataTable) {
                try { curTab.dataTable.columns.adjust(); } catch (ignore) {}
            } else if (dataTable) {
                try { dataTable.columns.adjust(); } catch (ignore) {}
            }
        }, 120);
    });
    window.setTimeout(function () {
        if (tab && tab.dataTable) {
            try { tab.dataTable.columns.adjust(); } catch (ignore) {}
        } else if (dataTable) {
            try { dataTable.columns.adjust(); } catch (ignore) {}
        }
    }, 0);
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

function padZero(num) {
    return ('0' + num).slice(-2);
}

function todayStr() {
    var date = new Date();
    return date.getFullYear() + '-' + padZero(date.getMonth() + 1) + '-' + padZero(date.getDate());
}

function nowStr() {
    var date = new Date();
    return todayStr() + 'T' + padZero(date.getHours()) + ':' + padZero(date.getMinutes());
}
