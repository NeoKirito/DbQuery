# DBQuery Web 服务 AlwaysUp 托管与健康监听配置指南

本文档指导运维与实施工程师如何将 **DBQuery Web 服务** 配置为 Windows 守护服务（基于 **AlwaysUp** 软件），实现开机自启、后台无窗口静默常驻、服务假死监听探测与秒级故障自愈重启。

---

## 一、为什么旧版启动脚本不能直接加入 AlwaysUp？

1. **异步后台退出问题**：旧版 `启动Web服务.bat` 内部使用了 `start "" DBQuery.exe` 并在 2 秒后退出（`exit /b 0`）。AlwaysUp 会监控启动进程的 PID，当它检测到批处理在 2 秒内退出时，会误认为“服务崩溃”，从而触发无限死循环重启（Restart Storm）。
2. **Session 0 提权交互问题**：旧版脚本包含 UAC 申请管理员权限的交互弹窗，在 Windows 服务 Session 0 无交互桌面的环境中会挂起或直接失败。

**本次升级提供的专属解决方案**：
- **前台常驻守护脚本**：新增根目录下 `AlwaysUp服务启动.bat`，专为服务守护设计，前台阻塞常驻，精准同步服务生命周期，透传退出状态码。
- **开箱即用的健康监听接口**：新增免登录的 `/api/health` 存活探测端点（返回 HTTP 200），完美对接 AlwaysUp 的 **Sanity Check (存活监听)** 功能。
- **智能兼容**：即使在 AlwaysUp 中误选了 `启动Web服务.bat`，脚本也会自动识别 AlwaysUp 环境变量并自动切换为前台常驻服务模式，彻底避免循环重启。

---

## 二、AlwaysUp 详细配置图文指引

### 步骤 1：新建服务
打开 AlwaysUp 主界面，点击菜单栏 **【Application】-> 【Add...】**（或点击左上角的绿色 **+** 号图标）。

### 步骤 2：【General】(常规设置) 选项卡
在弹出的配置对话框中，进入 **General** 选项卡：

| 配置项 | 推荐填写内容 | 说明 |
| :--- | :--- | :--- |
| **Application** | `D:\DBQuery_Deploy\AlwaysUp服务启动.bat` | 浏览选择部署包根目录下的 `AlwaysUp服务启动.bat` <br>*(亦可直接选 `dist\DBQuery.exe`)* |
| **Arguments** | 留空 *(若直接选 exe 则填 `--web`)* | 服务参数 |
| **Working Directory** | `D:\DBQuery_Deploy` | **务必填写部署包根目录**（确保程序能读取 `config.ini` 与 `forms/` 目录） |
| **Name** | `DBQuery Web Server` | Windows 系统服务显示名称 |

---

### 步骤 3：【Sanity Check】(健康存活监听) 选项卡 ⭐核心配置
进入 **Sanity Check** 选项卡，配置针对 Web 服务的周期性探针监听：

1. 勾选 **【Check an HTTP or HTTPS URL】**
2. **URL** 填入：
   ```text
   http://127.0.0.1:6091/api/health
   ```
   *(注：若在 `config.ini` 中修改了 `[web] port`，请对应替换 6091)*
3. **Check every**（监听频率）：建议设置为 `60 seconds`（每分钟探测一次）
4. **Wait up to**（响应超时）：设置为 `10 seconds`
5. **Expected Status Code**（期望返回码）：填入 `200`
6. **If the check fails**（探测失败策略）：勾选 **【Restart the application】**

> **监听作用**：AlwaysUp 会每隔 60 秒向 `http://127.0.0.1:6091/api/health` 发送轻量级心跳请求。一旦 Web 服务发生假死、内存耗尽或未响应，AlwaysUp 将在超时后自动强制重启服务，实现 7×24 小时无人值守自愈。

---

### 步骤 4：【Restart】(自动重启) 选项卡
进入 **Restart** 选项卡：
1. 勾选 **【Whenever the application stops, restart it】**
2. 保持默认的重启延迟（例如 `Wait: 5 seconds`），确保进程异常中断后能立即拉起。

---

### 步骤 5：【Logon】(运行账户) 选项卡
进入 **Logon** 选项卡：
- **普通推荐**：选择默认的 **【In the Local System account】**。
- **特殊权限要求**：若现场数据库需要使用 Windows 集成身份认证（Windows Authentication）访问 SQL Server，请勾选 **【This account】** 并输入具有数据库访问权限的 Windows 用户名和密码。

---

### 步骤 6：保存并启动
点击底部的 **【Save】** 按钮保存服务配置。在 AlwaysUp 主列表中右键点击刚刚创建的 `DBQuery Web Server`，选择 **【Start "DBQuery Web Server"】** 启动服务。服务图标变为绿色即表示运行正常。

---

## 三、现场调试与健康状态验证

部署完成后，可通过以下方式验证监听与服务状态：

### 1. 快速验证存活监听
在部署包的 **`运维工具/`** 目录下，双击运行：
```text
运维工具\检查Web服务健康状态.bat
```
终端将输出：
```text
============================================================================
  正在探测 DBQuery Web 存活状态与监听响应...
  目标地址: http://127.0.0.1:6091/api/health
============================================================================
[OK] DBQuery Web 服务监听正常，HTTP 状态码: 200
[INFO] 响应内容: {"service":"DBQuery Web Server","status":"ok","timestamp":...,"uptime_seconds":...}

[结果] 服务正在正常监听，AlwaysUp Sanity Check 可正常使用此 URL！
```

### 2. 查看服务运行日志
- 访问日志与系统报错位于：`logs/web_YYYY-MM-DD.log`（按天自动滚动保存）。
- AlwaysUp 托管事件日志：在 AlwaysUp 主界面中右键点击该服务 -> **【View Activity Log】**。
