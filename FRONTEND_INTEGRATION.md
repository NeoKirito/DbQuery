# DBQuery 仅前端无密钥无感登录

> **兼容模式（不建议新接入使用）。** 本文档描述历史 `frontend-ticket` → 隐藏 form → `/sso/consume` 流程，接口继续保留以避免破坏已有集成。新的 PEIS 前端应优先使用 README 中的 **DBQuery Frontend Embed V1**：它直接建立 DBQuery Session、提供 `DBQueryEmbed.mount()` 与 `DBQueryEmbed.logout()`，并使用公开 form ID 和 `external_allowed` 参数门控。

## 适用范围

此模式适用于宿主系统**只有浏览器前端配置、没有可保存共享密钥的宿主后端**的情况。宿主页面在自己的用户完成登录后，以该用户本次登录取得的 `czybm` 与密码向 DBQuery 交换一个**一次性、短时有效**的 ticket；随后由隐藏表单将 ticket `POST` 到 iframe，DBQuery 创建会话并直接显示目标表单。

> 这是对“受签名宿主后端”方案的兼容模式。**没有共享密钥不代表不需要任何限制**：必须在 DBQuery 中显式启用，并仅放行宿主页面的精确 Origin。账号密码绝不能写在前端配置文件、HTML、URL、localStorage、sessionStorage、Cookie 或源码中；只能在用户刚完成宿主登录后的内存变量中短暂使用。

如果宿主前端无法取得当前用户本次登录的密码，也没有可调用的宿主后端，那么不能实现真正的无感登录。此时应使用受签名的宿主后端模式，或让用户在 DBQuery 登录页完成登录。

## 管理员一次性配置

在 DBQuery EXE 的“数据库连接配置”窗口，找到 **宿主程序无感登录** 分组并完成下表设置，然后保存、重启 DBQuery Web 服务。

| 设置项 | 填写方式 |
|---|---|
| 启用仅前端无密钥登录（兼容模式） | 勾选。默认不启用。 |
| 允许的前端 Origin | 写宿主页面的 `location.origin`，例如 `https://portal.example.com` 或 `http://127.0.0.1:8080`。多个值以英文逗号分隔。 |
| 票据有效期 | 保持 60 秒；有效范围 10–300 秒。 |
| 共享密钥 | 本模式不需要填写；“受签名的宿主无感登录”也不必勾选。 |

Origin 必须仅包含**协议、主机名和端口**。以下是不同值的处理方式。

| 配置值 | 结果 |
|---|---|
| `https://portal.example.com` | 有效，允许该页面前端调用。 |
| `https://portal.example.com:8443` | 有效，端口必须与宿主页面一致。 |
| `https://portal.example.com/app` | 无效，不允许配置路径。 |
| `*` | 无效，不支持通配符。 |
| `http://dbquery.example.internal:8094` | 通常不应填写；它是 DBQuery 自身而非宿主页面的 Origin。 |

等效的 runtime `config.ini` 配置如下。运行中的正式部署请优先通过 EXE 保存，避免手工修改时覆盖现场数据库连接配置。

```ini
[integration]
frontend_enabled = yes
frontend_allowed_origins = https://portal.example.com
# 与后端签名模式共用，60 秒为推荐值
ticket_ttl_seconds = 60
```

## 前端直接调用

前端只需在宿主登录成功后调用以下函数。`username` 与 `password` 必须来自**本次登录流程的内存值**，不能是写死在页面配置中的值。`next` 必须是 DBQuery 内部、以 `/` 开头的表单路径；它不会接受外站 URL。

```html
<iframe id="dbqueryFrame" name="dbqueryFrame"
        style="width:100%;height:100%;border:0" title="DBQuery"></iframe>
```

```javascript
async function openDbQueryInIframe(options) {
  const dbqueryBaseUrl = options.dbqueryBaseUrl.replace(/\/$/, '');
  const username = String(options.username || '').trim();
  const password = String(options.password || '');
  const next = options.next || '/query/forms/示例/Web快速上手.qry?embed=1&sidebar=0';
  const iframe = document.getElementById(options.iframeId || 'dbqueryFrame');

  if (!username || !password || !iframe) {
    throw new Error('无法建立 DBQuery 会话：缺少当前用户凭据或 iframe。');
  }

  // 不发送任何已有 Cookie；DBQuery 仅用本次 JSON 中的凭据签发一次性 ticket。
  const response = await fetch(dbqueryBaseUrl + '/api/integration/frontend-ticket', {
    method: 'POST',
    mode: 'cors',
    credentials: 'omit',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username: username, password: password, next: next })
  });

  const payload = await response.json().catch(function () { return {}; });
  if (!response.ok) {
    throw new Error(payload.error || 'DBQuery 无感登录失败。');
  }

  // ticket 不放入地址栏；使用一次 POST 后立即从 DOM 删除。
  const form = document.createElement('form');
  form.method = 'post';
  form.action = dbqueryBaseUrl + payload.consume_path;
  form.target = iframe.name;
  form.style.display = 'none';

  const ticketInput = document.createElement('input');
  ticketInput.type = 'hidden';
  ticketInput.name = 'ticket';
  ticketInput.value = payload.ticket;
  form.appendChild(ticketInput);
  document.body.appendChild(form);
  form.submit();
  form.remove();
}
```

宿主登录完成后调用示例：

```javascript
await openDbQueryInIframe({
  dbqueryBaseUrl: 'https://dbquery.example.internal:8094',
  username: currentUser.czybm,
  password: passwordFromThisLoginOnly,
  iframeId: 'dbqueryFrame',
  next: '/query/forms/示例/Web快速上手.qry?embed=1&sidebar=0'
});

// 使用完成后立即清空宿主登录流程中不再需要的密码变量或对象字段。
passwordFromThisLoginOnly = '';
```

接口请求与响应如下，便于不能直接添加 JavaScript 函数的低代码前端按相同规则配置。

```text
POST https://dbquery.example.internal:8094/api/integration/frontend-ticket
Origin: https://portal.example.com
Content-Type: application/json
```

```json
{
  "username": "当前用户的 czybm",
  "password": "当前用户本次登录输入的密码",
  "next": "/query/forms/示例/Web快速上手.qry?embed=1&sidebar=0"
}
```

成功时返回：

```json
{
  "ticket": "一次性随机票据",
  "expires_in": 60,
  "consume_path": "/sso/consume"
}
```

## 行为与安全边界

| 控制项 | 实现行为 |
|---|---|
| 账号验证 | DBQuery 继续用 `qx_czyxx` 的 `czybm`、`pass`、`czyzt='启用'`、`deleted='0'` 进行参数化认证。 |
| 来源白名单 | 浏览器 `Origin` 必须精确匹配 EXE 中配置的一个 Origin；接口不会输出 `Access-Control-Allow-Origin: *`。 |
| 登录限流 | 与普通 DBQuery 登录共用每来源地址 5 次 / 5 分钟的失败限流。 |
| ticket | 只保存在当前 DBQuery 服务进程内；默认 60 秒失效，且 `POST /sso/consume` 后即被删除，无法重用。 |
| iframe | ticket 通过 POST 而不是 URL 传递，不进入地址栏、历史记录或常规访问日志。 |
| 表单可见性 | 登录成功不改变表单权限；只有 `web_enabled = true` 的 `.qry` 可以在 Web 中打开。 |

浏览器的 `Origin` 白名单用于限制正常浏览器页面的跨域读取，**它不是共享密钥**，不能代替宿主后端身份认证。任何能获得用户真实 DBQuery 密码的人仍可像普通用户一样尝试登录。因此必须继续使用 HTTPS 或受控的内网加密通道，并避免在浏览器中保存、记录或复用密码。

宿主页面与 DBQuery 最好部署在同一站点（例如均在 `*.example.com`）。部分浏览器会阻止跨站 iframe Cookie；出现这种情况时请调整同站点部署或浏览器企业策略，不要关闭认证。

## 常见错误

| HTTP / `error_type` | 原因 | 处理方式 |
|---|---|---|
| `403 frontend_integration_not_enabled` | EXE 中没有启用前端无密钥模式，或没有保存有效 Origin。 | 在 EXE 配置中启用并保存精确 Origin，重启 Web 服务。 |
| `403 frontend_integration_origin_denied` | 当前 `location.origin` 与配置不一致。 | 用浏览器控制台执行 `location.origin`，将输出值原样填入 EXE。检查协议、域名和端口。 |
| `400 invalid_frontend_integration_request` | JSON 格式或账号密码字段无效。 | 检查 `Content-Type: application/json` 与参数名。 |
| `401 invalid_frontend_integration_credentials` | 账号、密码、启用状态或数据服务不满足认证规则。 | 回到宿主登录流程处理，不要把密码显示或写入日志。 |
| `429 frontend_integration_rate_limited` | 该来源地址失败次数过多。 | 等待 5 分钟后用正确凭据重试。 |
| iframe 显示 ticket 已失效 | ticket 已被使用、超过有效期，或 DBQuery 已重启。 | 重新调用票据接口，使用新 ticket 再 POST。 |

## 验收清单

| 检查项 | 预期结果 |
|---|---|
| 直接打开 DBQuery 地址 | 仍然显示 DBQuery 登录页。 |
| 打开未启用 `web_enabled` 的 `.qry` | 仍然返回不可访问。 |
| 从已配置的宿主 Origin 调用 | 返回 ticket，iframe 直接进入目标表单。 |
| 从其他 Origin 调用 | 返回 `403 frontend_integration_origin_denied`，不执行数据库账号验证。 |
| 同一个 ticket 重复 POST | 第二次返回 `401`。 |
| 前端源代码与浏览器存储 | 不存在共享密钥、固定账号或固定密码。 |
