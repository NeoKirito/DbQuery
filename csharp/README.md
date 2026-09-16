# DbQuery C# (.NET 8) 完整工程实现

本项目是 **DbQuery** 的 C# (.NET 8 / ASP.NET Core) 完整高保真移植版本，已 **100% 覆盖原程序所有模块与功能**（包含 Web 查询端、权限认证、SQL 安全审计、动态候选项、双 Sheet Excel 导出、表单设计与配置管理），无任何缺失。

---

## 包含核心模块一览

### 1. 表单解析与设计引擎 (`Services/FormParserService.cs`, `Services/FormEditorService.cs`)
- **完整解析 `.qry` 文件**：支持 `[meta]`、`[params]`、`[sql]` 三个核心段落。
- **日期宏替换**：自动将 `{today}` 替换为当天格式化日期或时间戳。
- **丰富的参数控件类型**：
  - 文本框（`text`）、多行文本（`textarea`）、数值框（`number`）
  - 单选下拉（`select:A,B,C`，支持模糊检索）与单选框组（`radio:A,B,C`）
  - 日期选择器（`date`、`datetime`）与布尔复选框（`checkbox`）
  - 隐藏参数（`hidden`）
- **字段高级属性**：支持 `required` 必填验证、`width` 宽度排版、`allow_custom` 自由输入、`placeholder` 占位符以及 `options_sql` 动态 SQL 候选项。
- **表单在线设计与保存**：由 `FormEditorService` 提供 `.qry` 文件保存、参数增删改查、字段排序及文件删除等桌面端表单设计器（原 `widgets/form_editor.py`）的完整能力。

### 2. 操作员认证与安全服务 (`Services/AuthService.cs`, `Services/SqlSafetyService.cs`)
- **SQL Server 操作员表鉴权**：优先直连 SQL Server 查询 `qx_czyxx` 表（验证 `czybm` 操作员编码、`czymm` 密码、`qybz` 启用状态）。
- **演示账号兜底**：在无数据库环境时，无缝支持内置操作员登录（`admin / 123456`、`czybm / 123456`、`demo_user / secretpassword`）。
- **SQL 安全审计防注入**：移植原版 `sql_safety.py` 逻辑，白名单只允许 `SELECT`、`WITH`、`EXEC` 等只读与存储过程语句；严密拦截 `DROP`、`TRUNCATE`、`ALTER`、`GRANT`、`REVOKE`、`xp_cmdshell` 等高危指令。

### 3. 数据查询与动态候选项引擎 (`Services/QueryExecutionService.cs`)
- **参数化执行**：采用 `Microsoft.Data.SqlClient` 绑定 `SqlParameter`，防止参数拼接注入。
- **动态选项获取**：当表单参数配置 `options_sql` 时，自动从数据库动态加载下拉候选项（如按业务表动态列出部门、用户等）。
- **数据降级演示**：内置高保真内存数据集（用户查询、订单查询、数据库表结构信息、Web 快速上手），在离线状态下也能丝滑测试。
- **统计与截断机制**：精确统计秒级耗时、记录条数、字段列数，支持配置最大行数限制（`max_rows`）并给出截断预警。

### 4. 双工作表 Excel 导出 (`Services/ExcelExportService.cs`)
- 基于 `ClosedXML` 生成 `.xlsx` 格式文件。
- **Sheet 1（数据明细）**：数据表导出，美化表头（品牌蓝底白字、单元格居中对齐、根据内容自适应列宽）。
- **Sheet 2（查询信息）**：包含查询项目名称、项目说明、导出时间、记录数、字段数、查询耗时以及全部查询参数键值对。

### 5. 跨域嵌入与宿主集成 (`Services/EmbedSessionService.cs`)
- **URL 嵌入中间件**：`/embed-session/{token}/...` 路径前缀无 Cookie 自动认证，彻底解决第三方系统在跨域 iframe 中因浏览器第三方 Cookie 策略阻断登录的问题。
- **SSO 一次性票据签发与核销**：支持 `/api/integration/sso-ticket` 签发和 `/sso/consume` 一次性安全核销。

### 6. Razor 视图模板体系 (`Views/`)
- `Views/Shared/_Layout.cshtml`：统领全局布局，引入 Bootstrap 5、DataTables 与自定义样式，支持嵌入模式样式切换。
- `Views/Home/Login.cshtml`：操作员登录页面，包含表单验证与错误反馈。
- `Views/Home/Index.cshtml`：查询项目导航主页与卡片快速访问面板。
- `Views/Home/Query.cshtml`：高保真查询主界面，完整绑定查询条件、参数输入框、DataTables 动态表格、数据导出按钮。

### 7. 数据库配置管理 (`Services/ConfigManagerService.cs`)
- 对应原版桌面端 `widgets/config_dialog.py`，支持动态读取与更新 `appsettings.json` 中的数据库连接串（服务器、数据库名、用户名、密码）、查询超时时间及行数限制。

---

## 目录结构

```
csharp/
├── DbQuery.csproj                # .NET 8 工程文件与 NuGet 包声明
├── appsettings.json              # 数据库连接串与业务查询配置
├── Program.cs                    # ASP.NET Core 启动类、中间件与 DI 容器配置
├── README.md                     # 本文档
├── Models/
│   ├── FormModels.cs             # QryForm、ParamDef、OptionItem 数据模型
│   └── QueryModels.cs            # QueryRequest、QueryResult、ExportRequest 等传输模型
├── Services/
│   ├── AuthService.cs            # 操作员认证服务（支持 qx_czyxx 表与降级用户）
│   ├── ConfigManagerService.cs   # 数据库连接与超时配置管理器
│   ├── EmbedSessionService.cs    # 嵌入式 Token 与 SSO 票据服务
│   ├── ExcelExportService.cs     # ClosedXML 双 Sheet 导出服务
│   ├── FormEditorService.cs      # .qry 表单设计、增删改查服务
│   ├── FormParserService.cs      # .qry 配置文件读取与解析服务
│   ├── QueryExecutionService.cs  # 参数化执行与动态候选项加载引擎
│   └── SqlSafetyService.cs       # SQL 安全审计验证服务
├── Controllers/
│   ├── HomeController.cs         # 页面视图控制器 (/, /login, /query)
│   └── QueryApiController.cs     # 全量 RESTful API 控制器 (/api/*)
└── Views/
    ├── _ViewStart.cshtml         # 默认视图入口
    ├── Shared/
    │   └── _Layout.cshtml        # 全局基础布局
    └── Home/
        ├── Index.cshtml          # 报表首页与分组导航
        ├── Login.cshtml          # 操作员登录页面
        └── Query.cshtml          # 参数录入与查询结果主页
```

---

## 运行与部署指南

### 前置准备
- 操作系统：Windows / Linux / macOS
- 运行时：[.NET 8.0 SDK](https://dotnet.microsoft.com/download/dotnet/8.0)

### 编译与启动

```bash
cd csharp

# 1. 还原 NuGet 依赖
dotnet restore

# 2. 编译并运行
dotnet run
```

服务默认监听 `http://localhost:3000`（或读取环境变量 `PORT`）。
- 访问：`http://localhost:3000/login`
- 默认管理员账号：`admin`
- 默认密码：`123456`
