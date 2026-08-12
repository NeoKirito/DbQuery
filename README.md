# 数据库查询工具 (DBQuery)

SQL Server 数据查询桌面工具，支持自定义表单、多标签页查询、导出 Excel。

---

## 目录结构

```
DBQuery/
├── main.py              主程序入口
├── db_manager.py        数据库连接管理
├── form_parser.py       表单文件解析
├── widgets/
│   ├── query_tab.py     查询标签页组件
│   ├── config_dialog.py 数据库配置对话框
│   └── form_editor.py   表单编辑器
├── forms/               表单文件目录（自动扫描）
│   ├── 示例/
│   │   ├── 订单查询.qry
│   │   └── 用户查询.qry
│   └── 系统/
│       └── 数据库表结构.qry
├── config.ini           数据库连接配置（自动生成）
├── requirements.txt     Python 依赖
├── DBQuery.spec         PyInstaller 打包配置
└── build.bat            一键打包脚本
```

---

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 运行程序

```bash
python main.py
```

### 3. 打包为 exe

```bash
build.bat
```
打包结果在 `dist\DBQuery\` 目录，将整个目录复制到目标机器即可。

---

## 系统要求

| 项目 | 要求 |
|------|------|
| Python | 3.8.x（最高支持 Win7 的版本）|
| 操作系统 | Windows 7 及以上 |
| ODBC 驱动 | SQL Server ODBC Driver 11/13/17 |

**安装 ODBC 驱动（目标机器需要）：**
- ODBC Driver 17: https://learn.microsoft.com/sql/connect/odbc/download-odbc-driver-for-sql-server
- 旧版（Win7 兼容）: 搜索 "Microsoft ODBC Driver 11 for SQL Server"

---

## 表单文件格式 (.qry)

表单文件是纯文本，可用记事本编辑，分三个区块：

```ini
[meta]
title       = 订单查询
group       = 销售管理
description = 按日期和客户查询订单

[params]
# 格式: 参数名 = 显示标签 | 类型 | 默认值
start_date    = 开始日期 | date
end_date      = 结束日期 | date | {today}
customer_name = 客户名称 | text
status        = 状态     | select:全部,待处理,已完成 | 全部

[sql]
SELECT TOP 500
    OrderID, OrderDate, CustomerName, Amount, Status
FROM Orders
WHERE OrderDate BETWEEN '{start_date}' AND '{end_date}'
  AND ('{customer_name}' = '' OR CustomerName LIKE '%{customer_name}%')
  AND ('{status}' = '全部' OR Status = '{status}')
ORDER BY OrderDate DESC
```

### 参数类型说明

| 类型 | 说明 |
|------|------|
| `text` | 文本输入框 |
| `date` | 日期选择器（格式：YYYY-MM-DD）|
| `datetime` | 日期时间选择器 |
| `number` | 数字输入框 |
| `select:A,B,C` | 下拉选择框（逗号分隔） |

特殊默认值：`{today}` 在 date/datetime 类型中代表今日。

### 参数在 SQL 中的用法

- 使用 `{参数名}` 引用参数值
- 程序会在执行前将占位符替换为用户输入的值
- 处理"全部"选项的技巧：`('{status}' = '全部' OR Status = '{status}')`

---

## 主要功能

### 界面功能
- 🟢 **连接状态指示灯**：工具栏左侧，绿色=已连接，红色=未连接，灰色=未测试
- **多标签页**：同时打开多个表单查询，可拖动排序
- **表单树**：左侧按分组展示所有表单，支持关键字搜索
- **结果过滤**：查询完成后可在界面内按关键字过滤，支持指定列过滤

### 查询功能
- 自动识别 `[params]` 中的参数，在界面顶部生成输入控件
- 文本框按 Enter 键触发查询
- 支持列排序（点击表头）
- 结果列可拖动调整宽度和顺序
- 右键菜单：复制选中行 / 复制全部（Tab 分隔，可粘贴到 Excel）

### 安全机制
- 只允许执行 `SELECT` 语句
- 自动拦截 `INSERT/UPDATE/DELETE/DROP` 等修改操作
- 配置文件存储密码为明文，建议使用 Windows 身份验证

### 导出 Excel
- 导出当前可见行（已过滤后的结果）
- Sheet1：查询数据（带表头样式、斑马纹、自动列宽、自动筛选）
- Sheet2：查询信息（表单名称、执行时间、查询参数、SQL 语句）

---

## 数据库配置 (config.ini)

程序自动生成，也可手动编辑：

```ini
[database]
server             = 192.168.1.10
port               = 1433
database           = MyDatabase
driver             = ODBC Driver 17 for SQL Server
trusted_connection = no
username           = sa
password           = YourPassword
```

---

## 常见问题

**Q: Win7 上打开 exe 闪退？**  
A: 确认已安装 Visual C++ 2015-2022 Redistributable 和 ODBC 驱动。

**Q: 连接失败提示 "Data source name not found"？**  
A: 在数据库配置中将驱动改为 `SQL Server`（系统内置），或安装对应 ODBC 驱动。

**Q: 中文显示乱码？**  
A: 确认 .qry 文件以 UTF-8 编码保存（记事本另存为时选择 UTF-8）。

**Q: 如何查询多个数据库？**  
A: 在 SQL 中用完整路径：`OtherDB.dbo.TableName`，或修改 config.ini 切换默认库。
