# yikeUIAuto Web 用例管理平台 — 实施方案

> 目标：把 Excel 维护用例改为 Web 页面维护，Excel 里的功能全部在页面上实现，
> 带登录权限，支持一键执行与查看报告。
> 版本：v1（待评审）　日期：2026-09-08

---

## 一、现状盘点（决定方案可行性的关键事实）

### 1.1 用例数据结构

| Sheet | 行数 | 字段 |
|---|---|---|
| `测试用例` | 22 | TCID、用例名称、用例描述、是否需要执行、执行时间、结果 |
| `TestSteps` | 514 | TCID、步骤序号、测试步骤描述、关键字、操作元素定位方式、操作元素定位表达式、操作值、是否需要执行 |
| `TestDatas` | 22 | TCID、CaseId、Runmode、Data_name、Summary、Input1~Input8、verifiedcodeXY、selector1~2、Type、Expression、ExpectedResult、Cycle、ErrMsg、Result、StartTime、RunTime（共 24 列） |
| `keyword_template` | 35 | 关键字清单（代码另实现了 get_win / mouse_click / Close_win，属桌面端，本次不做） |

### 1.2 执行引擎的耦合点（**改造成本低于预期**）

引擎（`framework/keywordsFrameword.py`）对 Excel 的依赖只有两类调用：

- **读：3 处** —— `case_file.get_xls(SuitSheet)`、`cases.get_xls(DataSheet)`、`get_xls(StepSheet, TCID=xxx)`
- **写：8 处** —— `cases.write_data(行, 列, 内容, font, msg)`

写操作用的是 `TestDatas` 单元格里的 `"行,列"` 坐标字符串（`NeedXY` 机制）。

**结论**：只要提供一个**接口相同的 DB 数据源**（`get_xls` 返回同样结构的 dict、`write_data` 按"记录 id + 字段序号"定位），
执行引擎**几乎不用改**。这是整个方案能低风险落地的核心。

### 1.3 已知遗留问题（方案内一并处理）

- 报告引用的 `cdn.bootcss.com` 已停止服务 → 图表加载不出来，样式也受影响。需替换为可用 CDN 或本地化静态资源。
- `keyword_template` 与代码不同步（代码多 3 个桌面端关键字，本次不做）。
- 结果回写依赖 Excel 不被占用（Web 化后此问题自然消失）。

---

## 二、技术选型

### 推荐方案：Django 4.2（LTS）+ SQLite + 服务端渲染

| 维度 | 选择 | 理由 |
|---|---|---|
| 后端框架 | **Django 4.2 LTS** | 你熟悉 Django（ekpms 即 Django 3.2）；自带 auth/ORM/Admin/模板，权限和 CRUD 成本极低；与执行引擎同为 Python，可直接 import，无跨语言调用 |
| 数据库 | **MySQL 8.0** | 与 ekpms 保持一致，便于将来数据打通 |
| 前端 | 服务端模板 + 少量原生 JS | 无需 Node 工具链；步骤表格这类交互用原生 JS 足够；避免引入构建复杂度 |
| 报表查看 | 直接渲染已生成的 HTML | 复用现有 `HTMLTestRunner_cn_echarts2`，不重写报告 |

### MySQL 部署方式：免安装 ZIP 版

原机上的 MySQL 已被卸载（`C:\Program Files\MySQL` 不存在，只剩 `ProgramData` 里的空 data 目录）。
采用**免安装 ZIP 版**，不写系统目录、不依赖安装程序：

```
D:\mysql-8.0\mysql-8.0.36-winx64\     # 解压位置
    bin\mysqld.exe
    data\                              # 数据目录
```

- 初始化：`mysqld --initialize-insecure`（root 初始无密码，随后设置）
- 启动：注册为 Windows 服务（需管理员），失败则退化为 `启动MySQL.bat` 手动启动
- 库名：`yikeui`，字符集 `utf8mb4`

**备选（若你更想要前后端分离）**：FastAPI + Vue3。代价是需要 Node 工具链、两套代码、你自己维护时成本更高。
除非你打算把它做成对外产品，否则不推荐。

---

## 三、架构设计

### 3.1 整体结构

```
浏览器 (yikeui.com)
    │
    ▼
Django Web 应用  ─────────────┐
  ├─ 用例管理（CRUD）          │  ORM
  ├─ 步骤管理（CRUD + 排序）   ├────► 数据库（SQLite / MySQL）
  ├─ 测试数据（CRUD）          │       TestCase / TestStep / TestData / TaskRun
  ├─ 执行控制（一键运行）      │
  └─ 报告查看                  │
                              │
                              ▼
                    数据源适配层 framework/datasource.py
                    ├── Excel 源（现状，保留）
                    └── DB 源（新增，Web 执行时走这条）
                              │
                              ▼
                    执行引擎 keywordsFrameword（基本不改）
                              │
                              ▼
                    Selenium → 报告 HTML → 归档
```

### 3.2 关键点：双轨数据源

新增 `framework/datasource.py`，提供与 `excel_readWrite` 完全相同的接口：

```python
class DbDataSource:
    def get_xls(self, sheet_name, **conditions) -> Iterator[dict]
    def write_data(self, rowno, colno, content, font=None, msg=None)
```

- `get_xls`：从 TestCase / TestStep / TestData 表读出，拼成与 Excel 完全相同的 dict（key 小写）。
  `Result/ErrMsg/StartTime/RunTime` 四个字段仍返回 `"<记录id>,<字段序号>"` 字符串 —— **保持 `NeedXY` 机制不变**。
- `write_data(rowno, colno, ...)`：`rowno` 即记录 id，`colno` 映射回字段名，直接 `UPDATE`。
- 引擎里 `case_file` / `cases` 两个模块级对象改为可注入，默认 Excel、Web 执行时切 DB。

**收益**：Excel 和 Web 两种模式可以并存，现有 22 个用例一条不丢，随时可导出回 Excel。

---

## 四、数据模型

```python
TestCase      # 对应「测试用例」sheet
    tcid            唯一
    name            用例名称
    description     用例描述
    need_run        是否需要执行 (y/n)
    last_run_time   执行时间
    last_result     结果
    created_at / updated_at

TestStep      # 对应 TestSteps，外键 TestCase
    case          FK(TestCase)
    step_no       步骤序号
    description   测试步骤描述
    keyword       关键字
    locate_type   操作元素定位方式
    locate_expr   操作元素定位表达式
    value         操作值
    need_run      是否需要执行
    order         排序号（支持拖拽调整）

TestData      # 对应 TestDatas，外键 TestCase
    case              FK(TestCase)
    case_id / runmode / data_name / summary
    input1 ~ input8
    verifiedcode_xy
    selector1 / selector2
    type / expression / expected_result     # 断言三件套
    cycle            循环次数
    errmsg / result / start_time / run_time # 执行回写字段

TaskRun       # 执行记录（新增，Excel 里没有）
    status        pending / running / passed / failed / error
    case_filter  本次执行的范围（全部 / 指定用例）
    started_at / finished_at / duration
    report_path  报告文件路径
    log_path
    total / passed / failed / error  统计
    triggered_by 执行人
```

---

## 五、页面清单（覆盖 Excel 全部功能）

| 模块 | 页面 | 对应 Excel 能力 | 说明 |
|---|---|---|---|
| 登录 | `/login` | — | 账号密码登录，admin / 123456；未登录跳转 |
| 首页 | `/` | — | 用例总数、最近执行结果、快捷入口 |
| 用例列表 | `/cases` | `测试用例` 表 | 列表、搜索、启停开关（是否需要执行）、批量启停、删除 |
| 用例编辑 | `/cases/<id>` | 同上 | 名称/描述/是否执行 |
| 步骤管理 | `/cases/<id>/steps` | `TestSteps` 表 | 增删改步骤、上下移排序、关键字下拉（带 35 个关键字提示）、定位方式 + 表达式分列填写 |
| 数据管理 | `/cases/<id>/datas` | `TestDatas` 表 | Input1~8、断言三件套（Type/Expression/ExpectedResult）、Cycle、Runmode |
| 关键字参考 | `/keywords` | `keyword_template` | 35 个关键字一览 + 用法说明（页面内置提示，编辑步骤时可查） |
| 执行 | `/run` | — | 选择用例（默认全部启用）→ 一键执行 → 实时进度条 + 日志流 |
| 报告列表 | `/reports` | `reports/` + `BackUP/` | 历史执行记录、状态、耗时 |
| 报告查看 | `/reports/<id>` | `result.html` | 内嵌展示 HTML 报告（**需修复失效 CDN**） |
| Excel 导入 | `/import` | 迁移 | 上传现有 `testdata.xlsx` → 写入数据库（**首次迁移 22 个用例用**） |
| Excel 导出 | `/export` | 备份 | 数据库 → 生成 `testdata.xlsx`，兼容原框架 |
| 用户管理 | `/admin` | — | Django 自带后台，改密码、加用户 |

---

## 六、执行与报告

### 6.1 执行方式：后台线程 + 前端轮询

一个用例要跑 30 秒以上，同步等待会卡死请求。做法：

1. 点击「执行」→ 创建 `TaskRun(status=pending)` → 立刻返回 task_id
2. 起一个后台线程跑执行引擎（数据源切 DB）
3. 前端每 2 秒轮询 `/run/status/<id>` → 显示进度、当前步骤、日志尾部
4. 执行完写入 `TaskRun` 统计 + 报告路径 → 前端跳转报告页

**并发控制**：全局锁，同一时刻只允许 1 个执行任务（避免多个 Chrome 抢资源、也避免写冲突）。
后续若要并发，再引入 Celery + Redis。

### 6.2 两个必须处理的坑

- **Django autoreload 会起两个进程** → 开发时用 `runserver --noreload`，或确保执行只在一个线程里触发
- **报告 CDN 失效**（`cdn.bootcss.com`）→ 替换为可用 CDN（如 `cdn.jsdelivr.net`）或把 echarts/bootstrap 下载到 `static/` 本地引用。
  **推荐本地化**，内网/离线环境也能看

---

## 七、权限与域名

### 7.1 登录权限

- 用 Django 自带 `django.contrib.auth`
- 初始化命令创建超级用户 `admin / 123456`（首次登录后建议改密码）
- 所有业务页面加 `@login_required`；未登录跳 `/login`
- 预留扩展：后续可按「执行权限 / 编辑权限」分组

### 7.2 自定义域名 `yikeui.com`

配置项放 `settings.py`：

```python
SITE_DOMAIN = env('SITE_DOMAIN', default='yikeui.com')
ALLOWED_HOSTS = ['yikeui.com', 'www.yikeui.com', '127.0.0.1', 'localhost']
CSRF_TRUSTED_ORIGINS = ['http://yikeui.com', 'http://127.0.0.1:8000']
```

本地生效两种方式：
1. **改 hosts 文件**（需管理员）：`127.0.0.1  yikeui.com` → 浏览器直接访问 `http://yikeui.com:8000`
2. **仅用 127.0.0.1:8000**，配置留着，将来部署到真域名时改 settings 即可

路由前缀也可配（若将来要挂在某个路径下）：`FORCE_SCRIPT_NAME = '/yikeui'`

---

## 八、目录结构

```
yikeUIAuto/
├── .python3/                  # 项目内置 Python（已有）
├── framework/                 # 执行引擎（基本不动）
│   └── datasource.py          # 【新增】数据源适配层
├── web/                       # 【新增】Django 项目
│   ├── manage.py
│   ├── yikeui/                # settings / urls
│   ├── cases/                 # 用例、步骤、数据、关键字
│   ├── runner/                # 执行控制、任务、报告
│   ├── accounts/              # 登录（可直接用 django.contrib.auth）
│   ├── static/                # echarts / bootstrap 本地化
│   └── templates/
├── Data/testdata.xlsx         # 保留，作为导入源与导出备份
└── 运行测试.bat                # 保留（Excel 模式）
```

---

## 九、实施计划（分期，每期可独立验收）

| 期 | 内容 | 产出 |
|---|---|---|
| **M1 骨架** | Django 项目初始化、登录（admin/123456）、首页、基础布局、hosts/域名配置 | 能登录、看到首页 |
| **M2 用例维护** | 用例/步骤/数据三张表的 CRUD、步骤排序、关键字下拉、Excel 导入（迁移 22 个用例） | Excel 里的功能全部能在页面上做 |
| **M3 执行与报告** | 数据源适配层、一键执行、任务状态轮询、报告列表与查看、修复 CDN | 页面点一下就能跑并看报告 |
| **M4 增强** | 执行历史统计、批量操作、用例复制、导出 Excel、操作日志 | 日常好用 |

建议先做到 **M3**（可用闭环），M4 按实际使用反馈再补。

---

## 十、风险与注意事项

| 风险 | 影响 | 应对 |
|---|---|---|
| 执行引擎与 Django 在同一进程跑 Selenium | 浏览器占用桌面、异常可能带崩进程 | 后台线程 + 异常捕获 + 执行锁；必要时改为独立子进程 |
| 报告 HTML 内嵌 base64 截图，体积大 | 查看时加载慢 | 保留原样；M4 可改存图片文件 |
| 22 个用例迁移后定位表达式可能已失效 | 执行报错 | 迁移只保证数据一致；老旧用例的定位需逐个修（这是业务问题，不是平台问题） |
| `Input1~8`、`selector1~2` 是固定列 | 字段不够灵活 | 保持与 Excel 一致，避免引擎改动；确有需要再扩展 |
| 账号密码写死初始 admin/123456 | 安全风险 | 仅本地/内网使用；首次登录引导改密码 |

---

## 十一、待确认事项（确认后开工）

1. 技术栈：Django 4.2 + SQLite + 服务端渲染（推荐） / 其他
2. 数据库：SQLite（推荐） / MySQL（与 ekpms 一致）
3. Excel 定位：保留导入导出、双轨并存（推荐） / 彻底弃用
4. 执行方式：后台线程 + 轮询（推荐） / 同步等待（页面卡住直到跑完）
5. 是否要我改 hosts 文件让 `yikeui.com` 本地生效（需管理员权限）
