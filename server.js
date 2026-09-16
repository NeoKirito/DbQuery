import express from 'express';
import session from 'express-session';
import cookieParser from 'cookie-parser';
import ExcelJS from 'exceljs';
import fs from 'fs';
import path from 'path';
import crypto from 'crypto';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const app = express();
const PORT = 3000;
const FORMS_DIR = path.join(__dirname, 'forms');

// ── In-Memory Integration & Embed Session State ──
const embedSessions = new Map();
const integrationTickets = new Map();
const integrationNonces = new Map();

function purgeExpiredSessions() {
  const now = Date.now();
  for (const [token, data] of embedSessions.entries()) {
    if (data.expiresAt <= now) embedSessions.delete(token);
  }
  for (const [ticket, data] of integrationTickets.entries()) {
    if (data.expiresAt <= now) integrationTickets.delete(ticket);
  }
}

// ── Today / Date helpers ──
function getTodayStr() {
  const d = new Date();
  const year = d.getFullYear();
  const month = String(d.getMonth() + 1).padStart(2, '0');
  const day = String(d.getDate()).padStart(2, '0');
  return `${year}-${month}-${day}`;
}

function getNowStr() {
  const d = new Date();
  const date = getTodayStr();
  const hours = String(d.getHours()).padStart(2, '0');
  const minutes = String(d.getMinutes()).padStart(2, '0');
  const seconds = String(d.getSeconds()).padStart(2, '0');
  return `${date} ${hours}:${minutes}:${seconds}`;
}

// ── .qry Form Parser ──
function parseQryFile(filePath) {
  if (!fs.existsSync(filePath)) return null;
  const content = fs.readFileSync(filePath, 'utf-8');
  const lines = content.split(/\r?\n/);

  let currentSection = '';
  const meta = {
    title: path.basename(filePath, '.qry'),
    group: '默认',
    description: '',
    web_enabled: false,
    query_type: 'select'
  };
  const rawParams = [];
  const sqlLines = [];

  for (let rawLine of lines) {
    const line = rawLine.trim();
    if (!line || line.startsWith('#') || line.startsWith('--')) {
      if (currentSection === 'sql' && !rawLine.trim().startsWith('#')) {
        sqlLines.push(rawLine);
      }
      continue;
    }

    if (line.startsWith('[') && line.endsWith(']')) {
      currentSection = line.slice(1, -1).toLowerCase();
      continue;
    }

    if (currentSection === 'meta') {
      const eqIdx = line.indexOf('=');
      if (eqIdx !== -1) {
        const key = line.slice(0, eqIdx).trim().toLowerCase();
        const val = line.slice(eqIdx + 1).trim();
        if (key === 'title') meta.title = val;
        else if (key === 'group') meta.group = val;
        else if (key === 'description') meta.description = val;
        else if (key === 'web_enabled') meta.web_enabled = val.toLowerCase() === 'true';
        else if (key === 'type') meta.query_type = val.toLowerCase();
      }
    } else if (currentSection === 'params') {
      const eqIdx = line.indexOf('=');
      if (eqIdx !== -1) {
        const name = line.slice(0, eqIdx).trim();
        const rest = line.slice(eqIdx + 1).trim();
        const parts = rest.split('|').map(s => s.trim());
        const label = parts[0] || name;
        const ptypeFull = parts[1] || 'text';
        let def = parts[2] || '';
        const extra = parts.slice(3);

        let ptype = ptypeFull;
        let staticOptions = [];
        if (ptypeFull.startsWith('select:')) {
          ptype = 'select';
          staticOptions = ptypeFull.slice(7).split(',').map(s => s.trim()).filter(Boolean);
        } else if (ptypeFull.startsWith('radio:')) {
          ptype = 'radio';
          staticOptions = ptypeFull.slice(6).split(',').map(s => s.trim()).filter(Boolean);
        } else if (ptypeFull === 'select') {
          ptype = 'select';
        }

        let placeholder = '';
        let required = false;
        let width = '';
        let allow_custom = false;
        let dynamic_options = false;

        for (const ext of extra) {
          if (ext.startsWith('placeholder=')) placeholder = ext.slice(12).trim();
          else if (ext === 'required') required = true;
          else if (ext.startsWith('width=')) width = ext.slice(6).trim();
          else if (ext.startsWith('allow_custom=')) allow_custom = ext.slice(13).trim().toLowerCase() === 'true';
          else if (ext.startsWith('options_sql=')) dynamic_options = true;
        }

        let resolvedDefault = def;
        if (def.includes('{today}')) {
          resolvedDefault = ptype === 'datetime' ? getNowStr() : getTodayStr();
        }

        const optionItems = staticOptions.map(opt => ({ value: opt, label: opt }));

        rawParams.push({
          name,
          label,
          ptype,
          options: staticOptions,
          option_items: optionItems,
          default: resolvedDefault,
          raw_default: def,
          placeholder,
          required,
          width,
          dynamic_options,
          searchable: ptype === 'select',
          allow_custom
        });
      }
    } else if (currentSection === 'sql') {
      sqlLines.push(rawLine);
    }
  }

  const relPath = path.relative(__dirname, filePath).replace(/\\/g, '/');

  return {
    ...meta,
    file_path: relPath,
    params: rawParams,
    sql: sqlLines.join('\n')
  };
}

function loadAllForms(webOnly = false) {
  const result = {};
  if (!fs.existsSync(FORMS_DIR)) return result;

  function walk(dir) {
    const entries = fs.readdirSync(dir, { withFileTypes: true });
    for (const entry of entries) {
      const fullPath = path.join(dir, entry.name);
      if (entry.isDirectory()) {
        walk(fullPath);
      } else if (entry.isFile() && entry.name.endsWith('.qry')) {
        const form = parseQryFile(fullPath);
        if (form) {
          if (webOnly && !form.web_enabled) return;
          if (!result[form.group]) result[form.group] = [];
          result[form.group].push(form);
        }
      }
    }
  }

  walk(FORMS_DIR);
  return result;
}

// ── In-Memory Mock Database Datasets ──
const mockUsers = [
  [1, 'admin', '系统管理员', '信息中心', 'admin@example.com', '13800138000', '启用', '2023-01-01 09:00:00', '2026-09-15 10:20:00'],
  [2, 'zhangsan', '张三', '技术部', 'zhangsan@example.com', '13800138001', '启用', '2023-03-15 10:00:00', '2026-09-14 16:30:00'],
  [3, 'lisi', '李四', '销售部', 'lisi@example.com', '13800138002', '启用', '2023-04-10 11:00:00', '2026-09-15 08:45:00'],
  [4, 'wangwu', '王五', '财务部', 'wangwu@example.com', '13800138003', '禁用', '2023-05-20 14:00:00', '2026-08-10 12:00:00'],
  [5, 'zhaoliu', '赵六', '技术部', 'zhaoliu@example.com', '13800138004', '启用', '2023-06-01 15:30:00', '2026-09-15 09:12:00'],
  [6, 'sunqi', '孙七', '客服部', 'sunqi@example.com', '13800138005', '启用', '2023-07-12 16:20:00', '2026-09-13 14:15:00'],
  [7, 'zhouba', '周八', '人事部', 'zhouba@example.com', '13800138006', '禁用', '2023-08-05 10:10:00', '2026-07-22 11:30:00'],
  [8, 'wujiu', '吴九', '销售部', 'wujiu@example.com', '13800138007', '启用', '2023-09-18 13:40:00', '2026-09-15 11:05:00'],
  [9, 'zhengshi', '郑十', '运维部', 'zhengshi@example.com', '13800138008', '启用', '2023-10-09 17:00:00', '2026-09-15 08:30:00'],
  [10, 'qianyi', '钱十一', '市场部', 'qianyi@example.com', '13800138009', '启用', '2023-11-21 09:15:00', '2026-09-15 10:05:00'],
  [11, 'chener', '陈十二', '技术部', 'chener@example.com', '13800138010', '启用', '2023-12-05 13:20:00', '2026-09-14 17:40:00'],
  [12, 'chushi', '楚十三', '财务部', 'chushi@example.com', '13800138011', '启用', '2024-01-15 14:50:00', '2026-09-15 09:50:00']
];

const mockOrders = [
  ['ORD-20260901-001', '2026-09-01', '北京科技有限公司', '企业级数据库授权', 2, 12800, 25600, '已完成'],
  ['ORD-20260902-002', '2026-09-02', '上海网络信息有限公司', '云端数据同步组件', 5, 3600, 18000, '已完成'],
  ['ORD-20260903-003', '2026-09-03', '广州数字传媒有限公司', '高级报表生成插件', 1, 8500, 8500, '待处理'],
  ['ORD-20260905-004', '2026-09-05', '深圳智联科技有限公司', '数据库安全审计模块', 3, 6200, 18600, '已完成'],
  ['ORD-20260907-005', '2026-09-07', '杭州电子商务有限公司', '高并发查询加速器', 2, 15000, 30000, '已完成'],
  ['ORD-20260909-006', '2026-09-09', '成都智谷软件有限公司', '移动端嵌入式查询SDK', 1, 9800, 9800, '待处理'],
  ['ORD-20260911-007', '2026-09-11', '南京恒科实业有限公司', '定制化ETL数据抽取包', 4, 4500, 18000, '已取消'],
  ['ORD-20260912-008', '2026-09-12', '武汉华中数据科技有限公司', '数据库备份容灾方案', 1, 28000, 28000, '已完成'],
  ['ORD-20260914-009', '2026-09-14', '西安秦创信息系统', '企业级数据库授权', 3, 12800, 38400, '待处理'],
  ['ORD-20260915-010', '2026-09-15', '苏州智能制造科技', '高级报表生成插件', 2, 8500, 17000, '待处理']
];

const mockTables = [
  ['dbo', 'Users', 'UserID', 1, 'int', '4', 'NO', '', '用户自增ID主键'],
  ['dbo', 'Users', 'UserName', 2, 'nvarchar', '64', 'NO', '', '登录操作员账号'],
  ['dbo', 'Users', 'FullName', 3, 'nvarchar', '64', 'NO', '', '用户真实姓名'],
  ['dbo', 'Users', 'Department', 4, 'nvarchar', '64', 'YES', '', '所属业务部门'],
  ['dbo', 'Users', 'Email', 5, 'nvarchar', '128', 'YES', '', '工作邮箱'],
  ['dbo', 'Users', 'Phone', 6, 'nvarchar', '32', 'YES', '', '联系电话'],
  ['dbo', 'Users', 'Status', 7, 'tinyint', '1', 'NO', '1', '状态：1启用 0禁用'],
  ['dbo', 'Users', 'CreateTime', 8, 'datetime', '8', 'NO', 'GETDATE()', '创建时间'],
  ['dbo', 'Orders', 'OrderID', 1, 'nvarchar', '32', 'NO', '', '订单唯一流水号'],
  ['dbo', 'Orders', 'OrderDate', 2, 'date', '3', 'NO', '', '客户下单日期'],
  ['dbo', 'Orders', 'CustomerID', 3, 'int', '4', 'NO', '', '关联合同客户ID'],
  ['dbo', 'Orders', 'ProductID', 4, 'int', '4', 'NO', '', '采购产品ID'],
  ['dbo', 'Orders', 'Quantity', 5, 'int', '4', 'NO', '1', '采购产品数量'],
  ['dbo', 'Orders', 'UnitPrice', 6, 'decimal', '9', 'NO', '0', '产品成交单价'],
  ['dbo', 'Orders', 'Status', 7, 'nvarchar', '16', 'NO', '待处理', '订单流转状态'],
  ['dbo', 'qx_czyxx', 'czybm', 1, 'nvarchar', '64', 'NO', '', '操作员唯一编码'],
  ['dbo', 'qx_czyxx', 'pass', 2, 'nvarchar', '128', 'NO', '', '操作员加密密码'],
  ['dbo', 'qx_czyxx', 'czyzt', 3, 'nvarchar', '16', 'NO', '启用', '账号状态'],
  ['dbo', 'qx_czyxx', 'deleted', 4, 'char', '1', 'NO', '0', '逻辑删除标记']
];

// ── Express Middleware Setup ──
app.set('views', path.join(__dirname, 'views'));
app.set('view engine', 'ejs');

app.use(express.urlencoded({ extended: true, limit: '10mb' }));
app.use(express.json({ limit: '10mb' }));
app.use(cookieParser());

const sessionSecret = process.env.DBQUERY_SESSION_SECRET || 'dbquery_secret_key_fixed_production_2026';
app.use(session({
  secret: sessionSecret,
  resave: false,
  saveUninitialized: false,
  cookie: {
    httpOnly: true,
    sameSite: 'lax',
    secure: false,
    maxAge: 8 * 3600 * 1000
  }
}));

// Static Assets
app.use('/static', express.static(path.join(__dirname, 'static')));

// Security Headers & Embed Context Middleware
app.use((req, res, next) => {
  if (!req.path.startsWith('/static/')) {
    res.set('Cache-Control', 'no-store, max-age=0');
    res.set('Pragma', 'no-cache');
  }
  res.set('X-Content-Type-Options', 'nosniff');
  res.set('Referrer-Policy', 'same-origin');
  res.set('Content-Security-Policy', "frame-ancestors 'self' *");

  if (!req.session.csrf_token) {
    req.session.csrf_token = crypto.randomBytes(18).toString('base64url');
  }
  next();
});

// Embed Session Route Handling
app.use((req, res, next) => {
  if (req.path.startsWith('/embed-session/')) {
    const parts = req.path.slice('/embed-session/'.length).split('/');
    const token = parts[0];
    const subPath = '/' + parts.slice(1).join('/');
    purgeExpiredSessions();
    const sessionData = embedSessions.get(token);
    if (sessionData) {
      req.embedUser = sessionData.username;
      req.embedToken = token;
      req.url = subPath;
    }
  }
  next();
});

function getEmbedContext(req) {
  const tokenEmbed = Boolean(req.embedToken);
  const hideHeader = req.query.hide_header === '1';
  const embed = tokenEmbed || req.query.embed === '1' || hideHeader;
  const sidebarArg = req.query.sidebar;
  const sidebarHidden = sidebarArg === '0' || (embed && sidebarArg !== '1');
  const currentUser = req.embedUser || req.session.auth_user || '';

  return {
    embed_mode: embed,
    hide_header: tokenEmbed || hideHeader || embed,
    sidebar_hidden: sidebarHidden,
    current_user: currentUser,
    page_name: 'app',
    csrf_token: req.session.csrf_token,
    script_root: ''
  };
}

function isAuthenticated(req) {
  return Boolean(req.embedUser || req.session.auth_user);
}

function requireAuth(req, res, next) {
  if (!isAuthenticated(req)) {
    if (req.path.startsWith('/api/')) {
      return res.status(401).json({ error: '请先登录后再访问查询服务。', error_type: 'authentication_required' });
    }
    const target = req.originalUrl;
    return res.redirect(`/login?next=${encodeURIComponent(target)}`);
  }
  next();
}

// ── Application Routes ──

// Index Page
app.get('/', requireAuth, (req, res) => {
  const formsData = loadAllForms(true);
  const context = getEmbedContext(req);
  res.render('index', {
    ...context,
    forms_data: formsData
  });
});

// Login Page
app.get('/login', (req, res) => {
  if (isAuthenticated(req)) {
    const nextUrl = req.query.next && req.query.next.startsWith('/') ? req.query.next : '/';
    return res.redirect(nextUrl);
  }
  const nextUrl = req.query.next || '';
  res.render('login', {
    title: '登录综合查询',
    page_name: 'login',
    error: '',
    next_url: nextUrl,
    csrf_token: req.session.csrf_token,
    embed_mode: false,
    sidebar_hidden: false,
    script_root: ''
  });
});

// Process Login
app.post('/login', (req, res) => {
  const { username, password, next } = req.body;
  const nextUrl = next && next.startsWith('/') ? next : '/';

  // Demo accounts check: accept admin, czybm, or any username with password
  if (username && String(username).trim().length > 0 && password && String(password).trim().length > 0) {
    req.session.auth_user = String(username).trim();
    return res.redirect(nextUrl);
  }

  res.status(400).render('login', {
    title: '登录综合查询',
    page_name: 'login',
    error: '账号、密码不能为空。可用演示账号：admin / 123456',
    next_url: nextUrl,
    csrf_token: req.session.csrf_token,
    embed_mode: false,
    sidebar_hidden: false,
    script_root: ''
  });
});

// Logout
app.post('/logout', requireAuth, (req, res) => {
  req.session.destroy(() => {
    res.redirect('/login');
  });
});

// Query Page
app.get('/query/*filePath', requireAuth, (req, res) => {
  const paramPath = req.params.filePath;
  const rawPath = Array.isArray(paramPath) ? paramPath.join('/') : (paramPath || '');
  const decodedPath = decodeURIComponent(rawPath).replace(/\\/g, '/');
  const absPath = path.resolve(__dirname, decodedPath);

  // Security check: must reside inside forms/
  if (!absPath.startsWith(path.resolve(FORMS_DIR)) || !absPath.endsWith('.qry') || !fs.existsSync(absPath)) {
    return res.status(404).send('查询方案不存在或已停用。');
  }

  const form = parseQryFile(absPath);
  if (!form) {
    return res.status(500).send('查询配置加载失败，请联系管理员。');
  }

  const context = getEmbedContext(req);
  res.render('query', {
    ...context,
    form,
    file_path: form.file_path
  });
});

// ── API Endpoints ──

// List Forms
app.get('/api/forms', requireAuth, (req, res) => {
  const forms = loadAllForms(true);
  res.json(forms);
});

// Dynamic / Static Options for Select
app.post('/api/options', requireAuth, (req, res) => {
  const { file_path, param_name } = req.body || {};
  if (!file_path || !param_name) {
    return res.status(400).json({ error: '查询条件信息不完整，请重新操作。' });
  }

  const absPath = path.resolve(__dirname, file_path);
  const form = parseQryFile(absPath);
  if (!form) return res.status(404).json({ error: '查询方案不存在或已停用。' });

  const param = form.params.find(p => p.name === param_name);
  if (!param) return res.status(404).json({ error: '查询条件不存在或不支持候选项加载。' });

  // Return options
  res.json({
    options: param.option_items || [],
    warning: ''
  });
});

// Test DB Connection
app.get('/api/test-connection', requireAuth, (req, res) => {
  res.json({
    success: true,
    message: '数据服务连接正常'
  });
});

// Execute Query
app.post('/api/query', requireAuth, (req, res) => {
  const { file_path, params } = req.body || {};
  if (!file_path) {
    return res.status(400).json({ error: '请求信息不完整，请重新操作。' });
  }

  const absPath = path.resolve(__dirname, file_path);
  const form = parseQryFile(absPath);
  if (!form) {
    return res.status(404).json({ error: '查询方案不存在或已停用。' });
  }

  const userParams = params || {};
  const startTime = Date.now();

  let columns = [];
  let rows = [];

  const formTitle = form.title;

  if (formTitle.includes('Web 快速上手') || form.file_path.includes('Web快速上手')) {
    columns = ['使用说明', '演示输入', '当前数据库时间'];
    rows = [
      [
        '登录成功：当前表单由 web_enabled = true 显式授权给已登录 Web 用户。',
        userParams.keyword || '欢迎使用',
        getNowStr()
      ]
    ];
  } else if (formTitle.includes('用户') || form.file_path.includes('用户查询')) {
    columns = ['用户ID', '登录账号', '姓名', '部门', '邮箱', '电话', '状态', '创建时间', '最后登录'];
    const kw = (userParams.keyword || '').toLowerCase();
    const dept = (userParams.department || '').toLowerCase();
    const status = userParams.status || '全部';

    rows = mockUsers.filter(row => {
      const matchKw = !kw || String(row[1]).toLowerCase().includes(kw) || String(row[2]).toLowerCase().includes(kw);
      const matchDept = !dept || String(row[3]).toLowerCase().includes(dept);
      const matchStatus = status === '全部' || String(row[6]) === status;
      return matchKw && matchDept && matchStatus;
    });
  } else if (formTitle.includes('订单') || form.file_path.includes('订单查询')) {
    columns = ['订单编号', '下单日期', '客户名称', '产品名称', '数量', '单价', '总金额', '状态'];
    const cust = (userParams.customer_name || '').toLowerCase();
    const status = userParams.status || '全部';
    const startDate = userParams.start_date || '1970-01-01';
    const endDate = userParams.end_date || '2099-12-31';

    rows = mockOrders.filter(row => {
      const date = String(row[1]);
      const matchDate = date >= startDate && date <= endDate;
      const matchCust = !cust || String(row[2]).toLowerCase().includes(cust);
      const matchStatus = status === '全部' || String(row[7]) === status;
      return matchDate && matchCust && matchStatus;
    });
  } else if (formTitle.includes('表结构') || formTitle.includes('表信息') || form.file_path.includes('数据库表结构')) {
    columns = ['架构', '表名', '字段名', '字段序号', '数据类型', '长度', '允许空', '默认值', '字段备注'];
    rows = mockTables;
  } else {
    // Generic fallback for any other .qry file
    columns = ['序号', '项目名称', '状态', '更新时间', '备注'];
    rows = [
      [1, form.title, '正常', getNowStr(), '基于本地表单配置执行成功'],
      [2, '示例数据项 A', '已同步', getTodayStr(), '参数匹配: ' + JSON.stringify(userParams)],
      [3, '示例数据项 B', '处理中', getTodayStr(), '数据服务通信正常']
    ];
  }

  const elapsed = ((Date.now() - startTime) / 1000).toFixed(2);

  res.json({
    columns,
    rows,
    elapsed: Number(elapsed),
    row_count: rows.length,
    col_count: columns.length,
    truncated: false,
    max_rows: 5000,
    option_warnings: []
  });
});

// Excel Export
app.post('/api/export', requireAuth, async (req, res) => {
  const { file_path, params, columns, rows, elapsed } = req.body || {};
  if (!columns || !rows) {
    return res.status(400).json({ error: '导出信息不完整，请重新操作。' });
  }

  let formTitle = '数据查询结果';
  let formDesc = '';
  if (file_path) {
    const absPath = path.resolve(__dirname, file_path);
    const form = parseQryFile(absPath);
    if (form) {
      formTitle = form.title;
      formDesc = form.description;
    }
  }

  try {
    const workbook = new ExcelJS.Workbook();
    workbook.creator = 'DBQuery Web';
    workbook.created = new Date();

    // Sheet 1: Query Result Data
    const dataSheet = workbook.addWorksheet(formTitle.slice(0, 30));
    dataSheet.addRow(columns);

    // Style header row
    const headerRow = dataSheet.getRow(1);
    headerRow.font = { bold: true, color: { argb: 'FFFFFFFF' } };
    headerRow.fill = {
      type: 'pattern',
      pattern: 'solid',
      fgColor: { argb: 'FF1A6EB5' }
    };
    headerRow.alignment = { vertical: 'middle', horizontal: 'center' };

    for (const row of rows) {
      dataSheet.addRow(row);
    }

    // Auto-fit column widths
    columns.forEach((col, idx) => {
      let maxLen = String(col).length;
      rows.forEach(r => {
        const val = r[idx];
        if (val !== undefined && val !== null) {
          maxLen = Math.max(maxLen, String(val).length);
        }
      });
      dataSheet.getColumn(idx + 1).width = Math.min(Math.max(maxLen * 2, 12), 40);
    });

    // Sheet 2: Query Info
    const infoSheet = workbook.addWorksheet('查询信息');
    infoSheet.addRow(['查询项目', formTitle]);
    infoSheet.addRow(['项目说明', formDesc || '']);
    infoSheet.addRow(['导出时间', getNowStr()]);
    infoSheet.addRow(['导出记录数', rows.length]);
    infoSheet.addRow(['字段数', columns.length]);
    infoSheet.addRow(['查询耗时', `${elapsed || 0} 秒`]);
    infoSheet.addRow(['', '']);
    infoSheet.addRow(['—— 查询条件 ——', '']);

    if (params && typeof params === 'object') {
      for (const [k, v] of Object.entries(params)) {
        infoSheet.addRow([k, String(v)]);
      }
    }

    infoSheet.getColumn(1).width = 20;
    infoSheet.getColumn(2).width = 50;

    const timestamp = new Date().toISOString().replace(/[-:T]/g, '').slice(0, 14);
    const filename = encodeURIComponent(`${formTitle}_${timestamp}.xlsx`);

    res.setHeader('Content-Type', 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet');
    res.setHeader('Content-Disposition', `attachment; filename="${filename}"`);

    await workbook.xlsx.write(res);
    res.end();
  } catch (err) {
    console.error('Export error:', err);
    res.status(500).json({ error: '导出失败，请稍后重试。' });
  }
});

// ── Host Integration & Embed APIs ──
app.get('/api/integration/session', (req, res) => {
  res.json({ authenticated: isAuthenticated(req) });
});

app.post('/api/integration/frontend-login', (req, res) => {
  const { username, password } = req.body || {};
  if (!username || !password) {
    return res.status(401).json({ error: '账号或密码错误。', error_type: 'AUTH_FAILED' });
  }
  const token = crypto.randomBytes(24).toString('base64url');
  embedSessions.set(token, {
    username: String(username).trim(),
    expiresAt: Date.now() + 60 * 60 * 1000
  });

  const embedPath = `/embed-session/${token}/?embed=1&hide_header=1&sidebar=0`;
  req.session.auth_user = String(username).trim();

  res.json({
    success: true,
    authenticated: true,
    embed_path: embedPath,
    embed_session: token,
    user: { username, display_name: username }
  });
});

app.post('/api/integration/logout', (req, res) => {
  const { embed_session } = req.body || {};
  if (embed_session) embedSessions.delete(embed_session);
  req.session.destroy(() => {
    res.json({ success: true, authenticated: false });
  });
});

app.post('/api/integration/sso-ticket', (req, res) => {
  const { username } = req.body || {};
  const ticket = crypto.randomBytes(24).toString('base64url');
  integrationTickets.set(ticket, {
    username: String(username || 'admin').trim(),
    next_url: '/',
    expiresAt: Date.now() + 60 * 1000
  });
  res.json({
    ticket,
    expires_in: 60,
    consume_path: '/sso/consume'
  });
});

app.post('/sso/consume', (req, res) => {
  const { ticket } = req.body || {};
  purgeExpiredSessions();
  const ticketData = integrationTickets.get(ticket);
  if (!ticketData) {
    return res.status(401).send('宿主登录票据已失效，请返回宿主程序重新进入。');
  }
  integrationTickets.delete(ticket);
  req.session.auth_user = ticketData.username;
  res.redirect(ticketData.next_url || '/');
});

// Start Server
app.listen(PORT, '0.0.0.0', () => {
  console.log(`DBQuery Web Server running at http://0.0.0.0:${PORT}`);
});
