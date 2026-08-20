# 宿主程序无感登录集成

## Purpose

本协议让宿主程序在用户已登录宿主系统后，**不显示 DBQuery 登录界面**地将用户带入 DBQuery Web/iframe。宿主后端把当前用户的 `czybm` 与密码提交给 DBQuery；DBQuery 按现有 `qx_czyxx` 启用账号规则验证成功后，只返回一个一次性短期票据。浏览器通过 iframe 内的 `POST` 消费票据，DBQuery 再建立 HttpOnly Web 会话。

> 这是**推荐**的接入方式：共享密钥只保存在宿主后端。用户名、密码和共享密钥均不得放入 iframe URL、浏览器 localStorage、浏览器日志或页面源代码；签名接口必须由**宿主后端**调用。

如果宿主没有后端、只能配置浏览器前端，可使用默认关闭且需 Origin 白名单的兼容模式。具体的 EXE 配置与可复制前端代码见 [FRONTEND_INTEGRATION.md](FRONTEND_INTEGRATION.md)。该模式不使用共享密钥，但仅能使用用户本次登录流程中短暂保留于内存的密码，不能把密码写入前端配置或源码。

## Configure DBQuery

在 DBQuery EXE 的“数据库连接配置”中，打开 **宿主程序无感登录** 分组，执行下列步骤。

1. 选中 **启用受签名的宿主无感登录**。
2. 点击 **生成新密钥**，复制完整密钥到宿主后端的机密配置；密钥至少 32 个字符，生成值通常更长。
3. 保持票据有效期为 60 秒、允许时钟偏差为 60 秒，除非两端时间同步条件不同。
4. 点击保存，然后重启 `DBQuery.exe --web`。

配置会保存到仅部署机可访问的 `config.ini`：

```ini
[integration]
enabled = yes
shared_key = <仅保存在 DBQuery 与宿主后端的机密值>
ticket_ttl_seconds = 60
max_clock_skew_seconds = 60
```

密钥轮换后，旧宿主签名立即失败；请同时更新宿主后端并重启 Web 服务。不要将配置文件随发布包、源码或网页分发。

## Step 1: Host backend requests a ticket

宿主后端向 DBQuery 发起 JSON `POST` 请求：

```text
POST https://dbquery.example.internal:8094/api/integration/sso-ticket
Content-Type: application/json
X-DBQuery-Integration-Timestamp: <Unix 时间戳，秒>
X-DBQuery-Integration-Nonce: <每次请求唯一的 UUID 或随机值>
X-DBQuery-Integration-Signature: <hex HMAC-SHA256>
```

请求 JSON：

```json
{
  "username": "当前用户的 czybm",
  "password": "当前用户在 qx_czyxx 中的密码",
  "next": "/query/forms/综合查询/人员查询.qry?embed=1&sidebar=0"
}
```

`next` 只能是 DBQuery 本站以 `/` 开头的路径；外部地址会被忽略并安全回退到首页。

### Signature canonical string

HMAC-SHA256 的原文必须使用 LF（`\n`）分隔，且顺序不能变化：

```text
POST
/api/integration/sso-ticket
{timestamp}
{nonce}
{username}
{password}
```

使用 `shared_key` 的 UTF-8 字节计算 HMAC-SHA256，并把小写十六进制结果放入 `X-DBQuery-Integration-Signature`。

成功响应：

```json
{
  "ticket": "一次性随机票据",
  "expires_in": 60,
  "consume_path": "/sso/consume"
}
```

票据本身不包含密码，只在当前 DBQuery Web 服务进程内保存，并且只能使用一次。每次重试必须生成新的 timestamp、nonce、签名和票据。

## Step 2: Post the ticket into the iframe

宿主服务器取得 ticket 后，渲染以下页面片段。浏览器会自动将票据以 `POST` 提交到 iframe；用户不会看到 DBQuery 登录页。

```html
<iframe name="dbqueryFrame" id="dbqueryFrame" style="width:100%; height:100%; border:0"></iframe>

<form id="dbquerySsoForm"
      method="post"
      target="dbqueryFrame"
      action="https://dbquery.example.internal:8094/sso/consume">
  <input type="hidden" name="ticket" value="服务器刚取得的一次性票据">
</form>
<script>
  document.getElementById('dbquerySsoForm').submit();
</script>
```

不要将 ticket 改为 query string，也不要把 `username`、`password` 或 `shared_key` 放入 HTML、iframe 地址或 JavaScript。iframe 会话建立后，DBQuery 将重定向至 ticket 中的 `next` 表单地址。

## .NET host backend example

以下示例应放在宿主后端控制器、服务层或服务器端页面逻辑中，不能放进浏览器脚本。`sharedKey` 应来自受保护的服务器机密配置。

```csharp
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;

static async Task<string> GetDbQueryTicketAsync(
    HttpClient client,
    string baseUrl,
    string sharedKey,
    string username,
    string password,
    string next)
{
    var timestamp = DateTimeOffset.UtcNow.ToUnixTimeSeconds().ToString();
    var nonce = Guid.NewGuid().ToString("N");
    var canonical = string.Join("\n", new[] {
        "POST", "/api/integration/sso-ticket", timestamp, nonce, username, password
    });
    using var hmac = new HMACSHA256(Encoding.UTF8.GetBytes(sharedKey));
    var signature = Convert.ToHexString(hmac.ComputeHash(Encoding.UTF8.GetBytes(canonical))).ToLowerInvariant();

    using var request = new HttpRequestMessage(
        HttpMethod.Post, baseUrl.TrimEnd('/') + "/api/integration/sso-ticket");
    request.Headers.Add("X-DBQuery-Integration-Timestamp", timestamp);
    request.Headers.Add("X-DBQuery-Integration-Nonce", nonce);
    request.Headers.Add("X-DBQuery-Integration-Signature", signature);
    request.Content = JsonContent.Create(new { username, password, next });

    using var response = await client.SendAsync(request);
    response.EnsureSuccessStatusCode();
    using var document = JsonDocument.Parse(await response.Content.ReadAsStringAsync());
    return document.RootElement.GetProperty("ticket").GetString()!;
}
```

## Security and deployment requirements

| Requirement | Reason |
|---|---|
| 宿主后端与 DBQuery 使用 HTTPS 或受控内网加密通道 | 请求中包含用户密码；HMAC 证明宿主身份但不加密内容。 |
| 宿主后端保管 `shared_key` | 任何拿到该密钥的客户端都可以伪造宿主签名。 |
| 两端系统时钟同步 | 默认只允许 60 秒偏差。 |
| 每次使用新的 nonce | DBQuery 会拒绝已见 nonce，防止签名请求重放。 |
| 通过 iframe POST 消费 ticket | 避免把短期票据放到地址栏、浏览器历史和多数 Web 服务器访问日志中。 |
| DBQuery 与宿主优先部署在同站点 | 浏览器若阻止跨站 iframe Cookie，登录会话无法保留；不要通过关闭认证来规避。 |
| 业务表单显式 `web_enabled = true` | 无感登录只建立身份，不会绕过每张表单的 Web 可见权限。 |

## Error handling

| HTTP / error_type | Meaning | Host action |
|---|---|---|
| `400 invalid_integration_request` | 缺少或不合法的请求字段 | 检查宿主后端调用实现。 |
| `401 expired_integration_request` | timestamp 超出允许偏差 | 同步时间并重新发起新请求。 |
| `401 invalid_integration_credentials` | 当前账号、密码或账号状态无法通过 `qx_czyxx` 验证 | 回到宿主身份处理流程；不要让 DBQuery 显示密码登录页。 |
| `403 integration_not_enabled` | DBQuery 尚未启用或未保存合格的共享密钥 | 在 EXE 配置中启用并保存密钥。 |
| `403 invalid_integration_signature` | 共享密钥或 HMAC 原文不一致 | 检查两端 shared_key、LF 换行与字段顺序。 |
| `409 replayed_integration_request` | nonce 已使用 | 为该次请求生成新的 nonce 和签名。 |
| iframe 显示票据失效 | ticket 已使用、过期或服务重启 | 宿主后端重新申请 ticket 并重新 POST。 |

## Limitations

票据与 nonce 仅驻留在当前 DBQuery 服务进程中；重启服务会立即使未消费票据失效。该设计适用于当前单进程 onedir 部署。若未来部署多个 Web Worker 或多台节点，应把一次性状态迁移至共享缓存，并继续保留短时效与单次消费规则。
