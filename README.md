# DbQuery

DbQuery 是一个兼容桌面端与 Web 端的 SQL Server 查询工具。Web 端可作为**综合查询**模块嵌入亚创体检系统等业务系统的主内容区，支持 `.qry` 配置化查询、结果筛选和 Excel 导出。

> Web 页面面向业务用户时应使用具体查询项目的业务标题。数据库、SQL、存储过程等技术信息仅保留在服务端日志及独立管理模式中。

## 快速开始

### 桌面端

安装依赖后运行桌面端：

```bash
pip install -r requirements.txt
python main.py
```

Windows 环境可通过 `build.bat` 进行 PyInstaller 打包。目标机器需要安装与系统版本匹配的 SQL Server ODBC 驱动；Windows 7 环境请优先选用兼容的旧版本驱动。

### Web 端

Windows 环境可直接双击 `start_web.bat`。脚本保持使用 **8094** 端口，并通过 `DBQuery.exe --web --port 8094` 启动服务。

```bat
start_web.bat
```

也可以在命令行中启动：

```bat
DBQuery.exe --web
DBQuery.exe --web --port 8094
```

默认访问地址为 `http://localhost:8094/`。启动脚本还会提示局域网访问地址；请按本单位网络与防火墙规范配置访问范围。

桌面端和 Web 端均要求使用 `qx_czyxx` 中 **启用且未删除** 的操作员账号登录。认证通过后才可以查看任何表单、候选项、查询结果和导出数据。

## 嵌入业务系统

Web 端支持在 iframe 中作为宿主系统内容区的一部分使用。所有内部的表单切换和返回链接会保留当前嵌入参数。

| 使用场景 | 示例地址 | 页面行为 |
|---|---|---|
| 隐藏顶部栏（兼容旧调用） | `http://host:8094/?hide_header=1` | 隐藏独立顶栏，进入嵌入式业务界面。 |
| 显式嵌入模式 | `http://host:8094/?embed=1` | 与 `hide_header=1` 一致的嵌入体验，隐藏管理入口与技术类型标识。 |
| 由宿主菜单控制项目 | `http://host:8094/query/forms/示例/用户查询.qry?embed=1&sidebar=0` | 不显示内部侧栏，查询区占满宿主内容区域。 |
| 嵌入模式保留侧栏 | `http://host:8094/query/forms/示例/用户查询.qry?embed=1` | 显示可折叠的“查询项目”侧栏，折叠状态保存在浏览器本地。 |

建议 iframe 容器由宿主系统提供稳定的内容区高度。DbQuery 嵌入模式会使用 iframe 的完整可用高度，并仅使结果区域产生必要的纵向滚动；宽表仍可在结果区域内横向滚动。

嵌入页面与独立访问使用同一个登录页和服务端会话。嵌入页未登录时会显示登录界面；宿主系统不能仅凭 iframe 地址绕过认证。若宿主和 DbQuery 不属于同一站点且浏览器禁止第三方 Cookie，请由部署人员按浏览器安全策略评估，或后续接入企业 SSO，不应在 URL 中传递账号密码。

对于已登录宿主系统的无感 iframe 集成，DBQuery 提供受 HMAC 签名保护的一次性短期票据流程：宿主**后端**验证当前用户后申请票据，浏览器通过 iframe `POST` 消费票据而不显示 DBQuery 登录页。完整配置、签名原文、接口和 .NET 示例见 [HOST_INTEGRATION.md](HOST_INTEGRATION.md)。该流程只建立身份，**不会绕过**下面的 `web_enabled` 表单授权。

### DBQuery Frontend Embed V1

当 PEIS 前端已经在本次登录流程中持有当前用户的账号和密码时，可使用正式的 `DBQueryEmbed` SDK。DBQuery 仍会使用 `qx_czyxx` 独立复核账号、密码、启用和未删除状态；认证成功后只建立 DBQuery 自己的 HttpOnly Session。后续 iframe、查询、动态候选与导出均只使用该 Session，SDK 不会保存密码。

生产部署必须先通过 `config.ini` 的 `[integration]` 显式开启此模式。不要在源码、发布包或浏览器配置中保存任何真实账号、密码或生产域名。

```ini
[integration]
# 默认 no；只有配置了精确 Origin 后才可设为 yes
frontend_embed_enabled = no
# 多个值用英文逗号分隔；不能使用 *、路径或 query string
frontend_embed_allowed_origins = https://peis.example.com
# Embed V1 会话期限，取值 1–1440 分钟
frontend_embed_session_minutes = 60
# iframe 祖先白名单；留空时仅允许 'self'，不能使用 *
frame_ancestors = https://peis.example.com
```

推荐将 DBQuery 通过同域反向代理挂载在 `/dbquery` 下。若代理会设置 `X-Forwarded-Prefix`，需在 DBQuery 服务进程环境中显式设置 `DBQUERY_TRUST_PROXY_PREFIX=true`；若 HTTPS 在反向代理终止，可设置 `DBQUERY_SESSION_COOKIE_SECURE=true`。跨站 iframe Cookie 还会受浏览器 SameSite/第三方 Cookie 策略约束，因此同域部署优先。

原生 JavaScript 的调用只需加载 SDK 并调用 `mount()`：

```html
<script src="/dbquery/static/js/dbquery-embed.js"></script>
<div id="dbquery" style="height: 720px"></div>
<script>
DBQueryEmbed.mount({
  el: '#dbquery',
  username: currentUser.username,
  password: currentUser.password,
  form: 'person-detail',
  params: { tjh: currentTjh },
  apiBase: '/dbquery',
  onReady: function () {},
  onError: function (error) { console.error(error.code); }
});
</script>
```

Vue 中同样只在容器挂载后调用：

```javascript
onMounted(function () {
  DBQueryEmbed.mount({
    el: container.value,
    username: user.username,
    password: user.password,
    form: 'person-detail',
    params: { tjh: currentTjh.value },
    apiBase: '/dbquery'
  });
});
```

`mount()` 返回 Promise，并支持 `AUTH_FAILED`、`ORIGIN_DENIED`、`FORM_NOT_FOUND`、`FORM_NOT_WEB_ENABLED`、`INVALID_PARAM`、`NETWORK_ERROR` 和 `SESSION_FAILED` 错误码。调用 `DBQueryEmbed.logout()` 仅清除 DBQuery 的 Session，**不会**清除 PEIS 自身的账号或密码。

> 密码仅在建立 Session 的首次 HTTPS `POST /api/integration/frontend-login` 中使用。它不会进入 iframe URL、DOM attribute、Cookie、localStorage、sessionStorage 或 SDK 的持久状态。Origin allowlist 只是浏览器接入限制，不构成宿主身份认证。

## 登录与 Web 表单权限

认证 SQL 由程序在服务端参数化执行，等价于：

```sql
SELECT TOP 1 1
FROM qx_czyxx
WHERE czybm = ? AND [pass] = ? AND czyzt = N'启用' AND deleted = '0'
```

账号和密码不会写入 URL、前端脚本、日志或 Web 会话。Web 会话默认为 8 小时，服务重启后要求重新登录；连续失败登录会按客户端地址短时限制，以降低猜测密码风险。

每个 `.qry` 的 `[meta]` 可配置 `web_enabled`：

| 配置 | 行为 |
|---|---|
| 缺省或 `web_enabled = false` | **默认拒绝 Web**。表单仍可在 EXE 中管理和使用，但不会出现在 Web 列表，直接链接和 API 调用也会被拒绝。 |
| `web_enabled = true` | 已登录 Web 用户可查看、加载候选项、执行查询和导出。 |

在 EXE 的“新建表单 / 编辑表单”窗口中，勾选 **允许已登录 Web 用户查看此表单** 即可自动写入该元数据。首次登录后可先运行 `forms/示例/Web快速上手.qry`；它不读取业务表，用于验证登录、表单授权、查询与导出流程。

## Web 查询配置

在 `config.ini` 中可以设置 Web 查询超时与单次返回上限：

```ini
[web]
query_timeout = 60
max_rows = 5000
```

| 配置项 | 默认值 | 说明 |
|---|---:|---|
| `query_timeout` | `60` | 单条查询允许的最长执行时间（秒）。超时后页面会提示缩小查询范围或增加查询条件。 |
| `max_rows` | `5000` | 单次返回到浏览器的最大记录数。服务端会读取 `max_rows + 1` 条以判断截断，避免无限制加载大结果集。 |

旧版 `config.ini` 没有 `[web]` 时可正常启动，并自动采用以上默认值。空值、非法值或非正数也会安全回退至默认值。

## `.qry` 查询项目格式

一个查询项目由 `[meta]`、`[params]` 和 `[sql]` 三部分构成。**既有 `.qry` 无需修改即可继续使用**；新增属性只在配置后生效。

```ini
[meta]
title = 体检人员查询
group = 统计报表
description = 按日期、科室和人员信息查询体检记录
web_enabled = true
id = person-detail
# type = select

[params]
start_date = 开始日期 | date | {today} | required | width=150
end_date = 结束日期 | date | {today} | required | width=150
department = 科室 | select:全部 | 全部 | searchable | options_sql=SELECT DISTINCT Department FROM Employee WHERE Department IS NOT NULL ORDER BY Department
doctor = 医生 | select | | searchable | options_sql=SELECT DoctorID, DoctorName FROM Doctor WHERE Enabled=1 ORDER BY DoctorName
keyword = 关键词 | text | | placeholder=姓名、手机号或编号 | width=240px
# 仅 Embed V1 首次打开时允许宿主预填；hidden 参数永远不能 external_allowed。
# tjh = 体检号 | text | | external_allowed=true
remark = 备注 | textarea | | placeholder=可输入多行查询说明
only_active = 仅查询有效记录 | checkbox | 1
gender = 性别 | radio:全部,男,女 | 全部
source = 来源系统 | hidden | PEIS

[sql]
SELECT TOP 100 *
FROM YourTable
WHERE CreateDate BETWEEN '{start_date}' AND '{end_date}'
  AND Department = '{department}'
  AND DoctorID = '{doctor}'
  AND Name LIKE '%{keyword}%'
```

### 参数类型与统一值语义

| 类型 | 示例 | EXE 与 Web 的一致语义 |
|---|---|---|
| `text` | `keyword = 关键词 | text` | 单行文本。 |
| `textarea` | `remark = 备注 | textarea` | 多行文本。 |
| `date` | `start = 开始日期 | date` | 统一提交 `yyyy-MM-dd`。 |
| `datetime` | `time = 时间 | datetime` | 统一提交 `yyyy-MM-dd HH:mm:ss`。 |
| `number` | `count = 数量 | number` | 仅接受有效数字。 |
| `select:A,B` | `status = 状态 | select:全部,完成` | 可输入包含关键字搜索，查询提交 option 的 `value`。 |
| `select` | `doctor = 医生 | select | | options_sql=SELECT ...` | 可完全由数据库候选项提供，查询提交 `value`。 |
| `checkbox` | `active = 有效 | checkbox | 1` | 始终提交 `1` 或 `0`。 |
| `radio:A,B` | `gender = 性别 | radio:男,女` | 提交所选项的 `value`。 |
| `hidden` | `source = 来源 | hidden | PEIS` | 不显示，始终提交配置默认值。 |

### 默认值与可选属性

| 属性 | 示例 | 说明 |
|---|---|---|
| 默认值 | `| 全部` | 位于类型后的第一个普通值。`{today}` 在 `date/text` 中为当天 `yyyy-MM-dd`，在 `datetime` 中为当前 `yyyy-MM-dd HH:mm:ss`。 |
| `placeholder` | `placeholder=请输入姓名` | 输入框的提示文字。 |
| `required` | `required` 或 `required=true` | 两端均在执行前校验；`checkbox` 必须为 `1`。 |
| `width` | `width=220px`、`width=220`、`width=35%` | 控件宽度；纯数字按 `px` 处理。 |
| `searchable` | `searchable` | 标记可搜索；所有 `select` 已默认启用输入包含匹配。 |
| `allow_custom` | `allow_custom=true` | 默认 `false`。未开启时，临时搜索文字或不存在的候选项不能进入 SQL。 |
| `options_sql` | `options_sql=SELECT DoctorID, DoctorName FROM Doctor` | 只允许单条只读 `SELECT`。一列时为 `value=label`；两列时第一列为 `value`、第二列为 `label`；SQL 永远不下发到浏览器。 |
| `external_allowed` | `external_allowed=true` | 默认 `false`。只有该非 hidden 参数可由 Embed V1 在 iframe 初始打开时预填，且仍经过服务端类型与候选项校验。 |
| `web_enabled`（`[meta]`） | `web_enabled = true` | 默认 `false`；仅明确为 `true` 的表单对已登录 Web 用户开放。 |
| `id`（`[meta]`） | `id = person-detail` | 稳定公开表单 ID，仅允许小写字母、数字、`_`、`-`。Embed V1 从不接受 `.qry` 文件路径。 |

静态 `select:` 候选项与 `options_sql` 返回项可并存，按 **value** 的首次出现顺序合并去重。动态候选加载采用短生命周期连接、10 秒查询超时和最多 1000 项保护；失败时保留静态项，并提示“候选数据加载失败，可刷新重试”。浏览器只接收 `dynamic_options: true` 标记，并只提交表单定位信息与参数名加载候选；`options_sql` 永远保留在服务端，绝不接受客户端提交的候选 SQL。

未知类型、未知属性和不合法宽度会安全忽略或回退为 `text`，不会导致整个查询项目不可用。

## 查询与导出行为

Web 请求使用独立数据库连接，查询结束后会可靠关闭连接。查询出现非超时的短暂驱动错误时会使用新连接重试一次；不会使用全局共享连接或全局查询锁阻塞全部 Web 请求。结果数据的最大返回数量由 `[web] max_rows` 控制。

Excel 导出使用当前已经查询到的结果，并按“查询项目标题_时间戳.xlsx”生成下载文件名。浏览器会从服务端响应中读取真实文件名，以正常支持中文标题；导出失败时页面会显示业务化提示，而不是把服务器异常直接展示给用户。

## 安全边界

`FormParser.is_safe_sql()` 仍保留并持续用于所有 Web 查询请求。`select` 类型仅允许以 `SELECT` 开头的查询，`exec` 类型仅允许受控的存储过程调用；此项改造没有删除或削弱现有检查。

本项目提供基于 `qx_czyxx` 的服务端账号密码认证、HttpOnly 会话、表单 Web 显式授权、登录限流、未认证 API 拦截、后端签名 HMAC 一次性票据集成，以及默认关闭的 Frontend Embed V1。Embed V1 使用精确 Origin allowlist、可配置 CSP `frame-ancestors`、会话期限和可选 Secure Cookie；它不会削弱 SQL 安全检查、`web_enabled` 或 `external_allowed` 门控。项目不内置 TLS 终止、企业身份联邦、最小权限数据库账号或反向代理的现场配置；生产发布前仍须由部署与安全负责人完成 HTTPS、代理信任边界、Cookie 策略和凭据轮换评估。

## 打包与现场升级

`build.bat` 使用 `DBQuery.spec` 生成 PyInstaller onedir 产物。打包配置会包含程序代码、`templates` 和 `static`；构建产物不应携带任何有凭据的现场 `config.ini`。

| 项目 | 现场升级原则 |
|---|---|
| 程序文件 | 使用新 onedir 程序文件替换旧程序文件，并保留回退副本。 |
| `templates` / `static` | 必须随程序同步更新，否则 Web 页面不能使用新控件。 |
| 现场 `forms` | **默认不覆盖**。旧 `.qry` 可原样继续运行；新示例应单独放置或仅在文件不存在时复制。 |
| 现场 `config.ini` | **绝不覆盖**。请保留现场数据库连接与 `[web]` 配置。 |

完成构建后，必须对最终产物而非仅对源码进行冒烟验证：

```bat
DBQuery.exe
DBQuery.exe --web --port 8094
```
