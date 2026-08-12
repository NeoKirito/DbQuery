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

## 嵌入业务系统

Web 端支持在 iframe 中作为宿主系统内容区的一部分使用。所有内部的表单切换和返回链接会保留当前嵌入参数。

| 使用场景 | 示例地址 | 页面行为 |
|---|---|---|
| 隐藏顶部栏（兼容旧调用） | `http://host:8094/?hide_header=1` | 隐藏独立顶栏，进入嵌入式业务界面。 |
| 显式嵌入模式 | `http://host:8094/?embed=1` | 与 `hide_header=1` 一致的嵌入体验，隐藏管理入口与技术类型标识。 |
| 由宿主菜单控制项目 | `http://host:8094/query/forms/示例/用户查询.qry?embed=1&sidebar=0` | 不显示内部侧栏，查询区占满宿主内容区域。 |
| 嵌入模式保留侧栏 | `http://host:8094/query/forms/示例/用户查询.qry?embed=1` | 显示可折叠的“查询项目”侧栏，折叠状态保存在浏览器本地。 |

建议 iframe 容器由宿主系统提供稳定的内容区高度。DbQuery 嵌入模式会使用 iframe 的完整可用高度，并仅使结果区域产生必要的纵向滚动；宽表仍可在结果区域内横向滚动。

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

一个查询项目由 `[meta]`、`[params]` 和 `[sql]` 三部分构成。既有格式无需修改即可继续使用。

```ini
[meta]
title = 体检人员查询
group = 统计报表
description = 按日期和人员信息查询体检记录
# type = select

[params]
start_date = 开始日期 | date | {today} | required | width=150
keyword = 关键词 | text | | placeholder=姓名、手机号或编号 | width=240px
status = 状态 | select:全部,已登记,已完成 | 全部
remark = 备注 | textarea | | placeholder=可输入多行查询说明
only_active = 仅查询有效记录 | checkbox | 1
gender = 性别 | radio:全部,男,女 | 全部
source = 来源系统 | hidden | PEIS

[sql]
SELECT TOP 100 *
FROM YourTable
WHERE CreateDate >= '{start_date}'
  AND Name LIKE '%{keyword}%'
```

### 参数类型

| 类型 | 示例 | Web 端表现 | 桌面端兼容策略 |
|---|---|---|---|
| `text` | `keyword = 关键词 | text` | 单行文本框 | 原有行为。 |
| `date` | `start = 开始日期 | date` | 日期选择 | 原有行为。 |
| `datetime` | `time = 时间 | datetime` | 日期时间选择 | 原有行为。 |
| `number` | `count = 数量 | number` | 数字输入框 | 原有行为。 |
| `select:A,B` | `status = 状态 | select:全部,完成` | 下拉选择 | 原有行为。 |
| `textarea` | `remark = 备注 | textarea` | 多行文本框 | 安全回退为可输入的文本控件。 |
| `checkbox` | `active = 有效 | checkbox | 1` | 勾选后提交 `1`，未勾选提交 `0` | 安全回退为可输入的文本控件。 |
| `radio:A,B` | `gender = 性别 | radio:男,女` | 单选项 | 安全回退为可输入的文本控件。 |
| `hidden` | `source = 来源 | hidden | PEIS` | 隐藏参数 | 安全回退为可输入的文本控件。 |

### 可选属性

| 属性 | 示例 | 说明 |
|---|---|---|
| 默认值 | `| 全部` | 位于类型后的第一个普通值；`{today}` 表示当天日期。 |
| `placeholder` | `placeholder=请输入姓名` | 输入框的提示文字。 |
| `required` | `required` 或 `required=true` | Web 端执行查询前要求填写。 |
| `width` | `width=220px`、`width=220`、`width=35%` | Web 端字段宽度；纯数字按 `px` 处理。 |

未知类型、未知属性和不合法宽度会被安全忽略或回退为 `text`，不会导致整个查询项目不可用。

## 查询与导出行为

Web 请求使用独立数据库连接，查询结束后会可靠关闭连接。查询出现非超时的短暂驱动错误时会使用新连接重试一次；不会使用全局共享连接或全局查询锁阻塞全部 Web 请求。结果数据的最大返回数量由 `[web] max_rows` 控制。

Excel 导出使用当前已经查询到的结果，并按“查询项目标题_时间戳.xlsx”生成下载文件名。浏览器会从服务端响应中读取真实文件名，以正常支持中文标题；导出失败时页面会显示业务化提示，而不是把服务器异常直接展示给用户。

## 安全边界

`FormParser.is_safe_sql()` 仍保留并持续用于所有 Web 查询请求。`select` 类型仅允许以 `SELECT` 开头的查询，`exec` 类型仅允许受控的存储过程调用；此项改造没有删除或削弱现有检查。

本项目当前不包含 SSO、Token 鉴权、iframe 来源认证、正式 CSP、HTTPS、最小权限数据库账号或反向代理等生产安全治理。这些项目应在系统正式生产发布前由部署与安全负责人另行评估。

## 打包

`build.bat` 使用 `DBQuery.spec` 调用 PyInstaller。打包配置会整体包含 `forms`、`templates` 和 `static` 目录，因此新增的模板、CSS、JavaScript 和本地 SVG（如有）随 Web 静态资源进入产物。完成打包后请使用以下方式进行实际冒烟验证：

```bat
DBQuery.exe --web --port 8094
```
