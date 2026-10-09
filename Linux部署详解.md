# yikeUIAuto 在 Linux（腾讯云 CVM）上的部署详解

> 对象：腾讯云 CVM `ins-cyr2wnwk`，CentOS 7.9，1 核 2G（标准型 S5 同代）。
> 部署目录：`/opt/yikeui`，Django 项目在 `web/`，用内置虚拟环境 `venv`。
> 本文档所有内容均来自服务器真实 `systemctl` / `ps` / 配置文件核对，不是凭记忆。

---

## 0. 先给你一张"全景图"——一个请求是怎么跑起来的

```
                          ┌─────────────────────────────────────────────┐
   浏览器 / 外部用户       │              腾讯云 CVM  (Linux)             │
   (yikeui.ekwing.com     │                                             │
    或 172.20.5.14)       │   ① nginx  :80  (反向代理 + 静态文件 + gzip) │
        │  HTTP :80       │        │   /static/ 直接发文件               │
        │ ───────────────▶ │        │   /        转发给 127.0.0.1:8000    │
        │                 │        ▼                                    │
        │                 │   ② gunicorn  :8000  (WSGI 应用服务器)       │
        │                 │        master 1 个  +  worker 2 个          │
        │                 │        │                                    │
        │                 │        ▼                                    │
        │                 │   ③ Django 4.2   (你的 Web 平台代码)         │
        │                 │        │  执行用例时开后台线程                │
        │                 │        │      │                             │
        │                 │        │      ▼                             │
        │                 │        │   ④ 本地 headless Chromium         │
        │                 │        │      (chromedriver 126 驱动)        │
        │                 │        ▼                                    │
        │                 │   ⑤ MySQL 8.0  :3306  (独立 systemd 服务)   │
        │ ◀────────────────│                                             │
        │   返回 HTML/JSON │   swap 2G 补足内存 | systemd 管进程自启      │
                          └─────────────────────────────────────────────┘
```

**一句话串起来**：用户访问 80 端口 → nginx 把请求转给 8000 端口的 gunicorn → gunicorn 把请求交给 Django 处理 → Django 读写 MySQL；用例执行时 Django 起后台线程，用本机 Chromium 真正打开浏览器跑测试。

---

## 1. 你的四个疑问，先逐一回答

### 1.1 为什么一条 `systemctl start yikeui` 就能启动？

因为"怎么启动这个 Web 服务"这件事，已经提前写进了一个 **systemd 单元文件**（`/etc/systemd/system/yikeui.service`）。
systemd 是 Linux 的"大管家"（PID 1，开机第一个进程），负责管所有后台服务。

文件里告诉了 systemd 三件事：
- **工作目录**在哪（`WorkingDirectory=/opt/yikeui/web`）
- **启动时执行什么命令**（`ExecStart=...gunicorn ...`）
- **需要哪些环境变量**（`Environment=YIKEUI_DB_xxx ...`）

注册之后，systemd 就"接管"了这个进程，于是你只需要：

```bash
systemctl start   yikeui   # 启动
systemctl restart yikeui   # 重启（改完代码用它让新代码生效）
systemctl stop    yikeui   # 停止
systemctl status  yikeui   # 看状态/日志
```

完全不用每次手敲一长串 `gunicorn yikeui.wsgi:application --bind 0.0.0.0:8000 --workers 2 ...`，
也不用 `nohup ... &` 把进程挂在终端后台。这就是"简化"的本质——**把启动逻辑固化成一份配置，交给系统管家管**。

> 类比：就像 Windows 里把程序注册成"服务"，之后在"服务"面板里点启动/停止即可；或者理解成"把启动命令写进了一个开机自启的快捷方式"。

### 1.2 为什么要写 `/etc/systemd/system/yikeui.service` 这个文件？

生产环境不能像开发时那样 `python manage.py runserver` 前台跑（关掉终端进程就没了）。
写 service 文件是为了获得几个生产必备能力：

| 能力 | 怎么来的 | 不用 service 会怎样 |
|---|---|---|
| **开机自启** | `systemctl enable yikeui` | 服务器重启后服务起不来，得人工登录拉 |
| **崩溃自动拉起** | `Restart=on-failure` | 进程意外挂掉就一直瘫着 |
| **统一管日志** | journald（`journalctl -u yikeui`） | 日志散落、难查 |
| **环境变量集中注入** | `Environment=` 段 | 见下方"关键陷阱" |

**关键陷阱（我们踩过）**：Django 的数据库密码、`ALLOWED_HOSTS`、`SECRET_KEY` 都靠 service 文件里的 `Environment=` 注入，
应用代码里只读环境变量、不写死。如果不用 service、而是自己 `setsid nohup gunicorn ... &` 裸起，
**新进程读不到这些环境变量** → `ALLOWED_HOSTS` 里没有机器内网 IP → 页面直接报 `DisallowedHost` 打不开。
所以**永远用 `systemctl restart yikeui`，不要手工 nohup**。

### 1.3 真实启动命令里 `--workers 2` 为什么是 2？

先看真实命令（就是 service 文件里的 `ExecStart`）：

```
/opt/yikeui/venv/bin/gunicorn yikeui.wsgi:application --bind 0.0.0.0:8000 --workers 2 --timeout 120
```

**gunicorn 的工作模型**：1 个 **master**（主管，负责任务分发、监控、拉起 worker）+ N 个 **worker**（真正处理 HTTP 请求）。
服务器上实测进程：
- `12059` master（1 个）
- `12061`、`12062` worker（2 个）
共 3 个 gunicorn 进程 —— 和 `--workers 2` 完全吻合。

**为什么是 2，不是 1、也不是 4？**
- 业界经验公式：`workers ≈ 2 × CPU核数 + 1`。这台机器是 **1 核**，理论值 3。
- 但这里只有 **2G 内存**，而且执行用例时还要在本机拉起 **headless Chromium**（浏览器非常吃内存）。
  worker 多了会互相抢内存、触发 OOM 被杀。
- 取 2 是个**权衡**：
  - 比 1 好：万一某个 worker 正在跑长用例 / 卡住，另一个还能照常响应 Web 页面，不会"一卡全卡"；
  - 比 3/4 稳：内存够用，不会因为 Chrome + 多 worker 把 2G 撑爆。

另外两个参数：
- `--timeout 120`：单个请求处理超过 120 秒，master 就把它杀掉重启，防止用例执行卡死把 worker 拖垮。
- `--bind 0.0.0.0:8000`：监听所有网卡 8000 端口。外部实际走 nginx:80 → 127.0.0.1:8000，
  但 bind 0.0.0.0 也允许你临时直接 `IP:8000` 访问（只要防火墙没拦）。

### 1.3.1 深入：gunicorn 的 pre-fork 进程模型（它到底怎么干活的）

上面把 gunicorn 当成一个"黑盒"讲了参数。这里拆开看它的**进程模型**，这是理解后面"为什么要多 worker""为什么平滑重启会残留旧进程"的基础。

**(1) 什么是 pre-fork（预分叉）**

启动后，gunicorn 只做一件事：**1 个 master 进程 + 它预先 fork 出来的 N 个 worker 子进程**（N = `--workers`）。
master 自己**不处理任何 HTTP 请求**，专职当"车间主任"；worker 才是流水线上的"工人"，每个工人独立处理请求。

**(2) 两个角色的职责**

| 角色 | 干啥 | 关键细节 |
|---|---|---|
| **master** | 绑定 8000 端口、fork 出 worker、盯着 worker 健康、接收信号（HUP/TERM） | 它持有 **listening socket**（监听套接字）；崩溃 = 整个服务挂，但 systemd 会拉起它 |
| **worker** | 真正 accept 连接、调用 Django 的 WSGI app、返回响应 | 处理完一个请求才接下一个（默认 sync 同步模型）；**崩溃只影响自己**，master 会补一个新的 |

**(3) 请求是怎么进到 worker 的（重点：共享 socket）**

master 在启动时 `bind()` + `listen()` 创建好监听套接字，然后 `fork()` 出 worker。
**fork 出的子进程会继承同一个 listening socket 文件描述符**。
于是多个 worker 共用这一个"门"：新连接进来时，由**操作系统内核**决定把它交给哪个空闲 worker 去 `accept`（现代内核已解决好"惊群"问题，不会全被吵醒）。
这就是为什么图里写"共享 listening socket（fork 时继承）"——worker 之间没有各自的端口，它们共用 master 开的那个。

**(4) 为什么要多个 worker（而不用 1 个）**

- **并发**：1 个同步 worker 同一时刻只能处理 1 个请求。本项目的用例执行可能要几十秒（开浏览器跑测试），期间这个 worker 被占着；有第 2 个 worker，页面/API 请求才不会被堵死。
- **隔离**：某个 worker 因为用例异常崩溃，另一个照常服务，master 再补一个，用户几乎无感。
- **代价**：每个 worker 都是一份 Python 进程 + Django 代码常驻内存，所以 worker 越多越吃内存——这正是本项目只敢给 2 个的根因（详见 1.3 的内存权衡）。

**(5) 两种"重启 worker"的机制（对应你踩过的两个坑）**

- **平滑重启（收到 `HUP` 信号）**：master 先 fork 一批**新** worker，再让**旧** worker 把手头请求跑完就优雅退出。理想情况下连接不中断。
  ⚠️ 坑点：如果旧 worker 卡在某个长用例迟迟不结束（超过 `timeout` 之前），它就不会退出——这正是一部分"残留旧 worker"的来源；用 `systemctl restart` 是 master 整体退出、最干净。
- **超时重启（超过 `--timeout 120`）**：某个 worker 处理一个请求超过 120 秒，master 直接把它**杀掉并补一个新的**，防止一个卡死的用例把整个 worker 拖垮、连累其他请求。

> 一句话：**gunicorn = 一个不干活的主管(master) + 一群干活的工人(worker)，工人共用主管开的"门"(socket)；主管负责招人、盯人、换人，工人崩了不影响整体。**

### 1.4 Linux 的 MySQL 是已经单独起了吗？

**是的，MySQL 是一个完全独立的 systemd 服务，自己开机自启，和 yikeui 解耦。**

实测：
```
mysqld.service   enabled    # 已设开机自启
mysqld:          active     # 正在运行
mysql  Ver 8.0.46 for Linux (MySQL Community Server - GPL)
```

- `yikeui.service` 里有一行 `After=network.target mysqld.service`，意思是"**等 MySQL 起来之后我再启动**"，
  这只是声明**启动顺序**，并不负责拉起 MySQL（没加 `Requires=`/`Wants=`）。
- 数据库用 `127.0.0.1:3306`，账号 `root / 123456`，库名 `yikeui`（字符集 utf8mb4），
  这些连接信息通过 service 的 `YIKEUI_DB_*` 环境变量传给 Django，Django 的 `settings.py` 读环境变量连库。

> 也就是说：MySQL = 独立服务；yikeui（gunicorn+Django）= 另一个服务；nginx = 第三个服务。
> 三者各管各的，由 systemd 统一编排启动顺序。

### 1.5 nginx 反向代理：怎么实现的、为什么需要（重点）

**它到底"代理"了什么？**
把 nginx 想成**餐厅前台/接待**：顾客（浏览器）只跟前台打交道，前台再把需求转给后厨（Django/gunicorn）。
顾客不知道后厨在哪、有几个、叫什么。这就是"反向代理"——代理的是**服务端**，对外隐藏了真实后端。
（对比"正向代理"：代理的是**客户端**，比如公司上网代理/VPN，帮你访问外部网站。两者方向相反，所以叫反向。）

**为什么要多加这一层？（直接让 gunicorn 对外不行吗）**
gunicorn 本身也能直接对外（它已经 `bind 0.0.0.0:8000`）。但生产环境加 nginx，是因为它擅长 gunicorn 不擅长的事：

| 作用 | 说明 |
|---|---|
| **统一端口** | 用户只访问标准的 80（浏览器默认），不用记 `:8000`；将来加 HTTPS 用 443，nginx 统一做 TLS，Django 不用管证书 |
| **静态文件加速** | `/static/` 下的 CSS/JS/图片由 nginx 直接读磁盘发回（C 语言实现，极快），**不进 Python**。Django 处理这些纯属浪费 worker 资源 |
| **gzip 压缩** | 自动压缩文本响应，省带宽、加快加载 |
| **大文件/上传缓冲** | `client_max_body_size 50m` 支持上传较大的 Excel 等，nginx 先缓冲再交给后端 |
| **解耦与稳定** | gunicorn 重启/崩溃时，nginx 仍在线（返回 502 或快速恢复），不直接把后端暴露给公网 |
| **可扩展** | 将来若 gunicorn 开多机/多端口，nginx 一行配置就能做负载均衡 |

**它具体怎么实现的（服务器真实配置）**
文件 `/etc/nginx/conf.d/yikeui.conf`，核心就两段"路由规则"：

```nginx
server {
    listen 80 default_server;
    server_name yikeui.ekwing.com 172.20.5.14;   # 命中这些域名/IP 的请求才归我处理

    # 规则一：静态文件 —— 直接读磁盘，不进 Django
    location /static/ {
        alias /opt/yikeui/web/staticfiles/;       # 文件在磁盘的这个目录
        expires 1y;                               # 浏览器缓存一年
    }

    # 规则二：其余所有请求 —— 转发给本机 8000 端口的 gunicorn
    location / {
        proxy_pass http://127.0.0.1:8000;         # 后端在同一台机器，用回环地址转发
        proxy_set_header Host $host;              # 把原始域名带给 Django
        proxy_set_header X-Real-IP $remote_addr;  # 真实客户端 IP
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme; # 用的是 http 还是 https
    }
}
```

**一条请求进来后 nginx 干的事**：
1. 看域名/IP 是否匹配 `server_name`；
2. 看路径：以 `/static/` 开头 → 直接去 `/opt/yikeui/web/staticfiles/` 找文件发回，**到此结束**，Django 完全不知情；
3. 其他路径（如 `/cases/`、`/runs/3/`）→ 通过 `proxy_pass` 原样转发给 `127.0.0.1:8000` 的 gunicorn；
4. `proxy_set_header` 那几行是把"顾客真实信息"（原始域名、真实 IP、协议）写进请求头带过去，
   否则 Django 看到的永远是 nginx 的地址，会生成错误链接、CSRF 校验失败、日志查不到真实用户。

> 一句话：**nginx 像分流器——静态资源走"捷径"直接出，动态请求才交给 Python 处理；对外只露 80，对内用回环地址保护后端。**

---

## 2. 完整部署流程（从零到能跑）

下面按"做一次全新部署"的顺序列，每一步标注**用到什么中间件 / 为什么**。

### 第 1 步：准备操作系统与基础环境
- 系统：CentOS 7.9（glibc 2.17），**1 核 2G**。
- 之所以要关心规格：1c2g 是最小配，跑 Django + 浏览器测试偏紧，所以后面才有 swap、worker=2 这些补救。
- 中间件：操作系统自带 `systemd`（进程管家）、`yum`（包管理）。

### 第 2 步：加 2G swap（弥补内存不足）
- 因为 2G 物理内存不够 headless Chromium 顺畅运行，加一块 2G 交换分区：
  ```
  fallocate -l 2G /swapfile
  chmod 600 /swapfile
  mkswap /swapfile
  swapon /swapfile
  echo '/swapfile swap swap defaults 0 0' >> /etc/fstab   # 开机自动挂载
  ```
- 实测：`swapon --show` 显示 `/swapfile 2G`，已写入 fstab。

### 第 3 步：安装并配置 MySQL 8.0（独立服务）
- 安装 MySQL 8.0 社区版，初始化后它自己就是一个 systemd 服务：
  ```
  systemctl enable --now mysqld      # 开机自启 + 立即启动
  ```
- 建库：`CREATE DATABASE yikeui CHARACTER SET utf8mb4;`
- 账号：`root / 123456`（与 Windows 本地保持一致，方便迁移）。
- 角色：持久化存储（用例、步骤、数据、执行记录、用户等全在这）。

### 第 4 步：准备 Python 虚拟环境
- 在 `/opt/yikeui/venv` 建独立 venv，避免和系统 Python 混：
  ```
  python3 -m venv /opt/yikeui/venv
  /opt/yikeui/venv/bin/pip install -r requirements.txt
  ```
- requirements 里含：`Django==4.2`、`gunicorn`、`selenium==3.141`、`openpyxl`、`PyMySQL`、`whitenoise` 等。
- 角色：提供隔离的 Python 运行时，gunicorn 用它来跑 Django。

### 第 5 步：部署代码到 `/opt/yikeui`
- 把项目整体放到 `/opt/yikeui`（Django 在 `web/` 子目录，应用入口 `web/yikeui/wsgi.py`）。
- Web 平台结构：
  - `web/cases/`：用例 / 步骤 / 数据模型
  - `web/runner/`：执行任务（`TaskRun`）、后台执行引擎、轮询接口
  - `framework/`：关键字驱动执行引擎（被 Django 调用）
  - `tools/`：Linux 版 `chromedriver`（16MB，已 `chmod +x`）

### 第 6 步：把 Django 改成"环境变量驱动"
- 这是为了生产安全：敏感配置不写进代码/文件，由 service 注入。
- `web/yikeui/settings.py` 关键读取（实测）：
  ```python
  SECRET_KEY        = os.environ.get('YIKEUI_SECRET_KEY', '开发默认')
  DEBUG             = os.environ.get('YIKEUI_DEBUG', '1') == '1'   # 生产设 0
  ALLOWED_HOSTS     = ['127.0.0.1','localhost','testserver'] + 环境变量里的 YIKEUI_ALLOWED_HOSTS
  DATABASES['default'] = { HOST: YIKEUI_DB_HOST, USER: YIKEUI_DB_USER,
                           PASSWORD: YIKEUI_DB_PASSWORD, NAME: YIKEUI_DB_NAME, PORT: YIKEUI_DB_PORT }
  STATIC_ROOT       = BASE_DIR / 'staticfiles'   # 生产静态文件收集目录
  ```
- 这些变量最终由 service 文件的 `Environment=` 提供（见第 9 步）。

### 第 7 步：数据库迁移
```
cd /opt/yikeui/web
/opt/yikeui/venv/bin/python manage.py migrate
```
- 把 Django 模型建表到 MySQL。本项目已含迁移 `0001`~`0006`（含 `TaskRun.error_summary`）。

### 第 8 步：安装浏览器驱动（仅 Web 用例需要）
- 因为用例要在 Linux 上真正打开网页，需要无界面（headless）Chromium：
  ```
  yum install chromium chromedriver     # 实测 Chromium 126 + chromedriver 126（版本自动匹配）
  cp /usr/bin/chromedriver /opt/yikeui/tools/chromedriver
  chmod +x /opt/yikeui/tools/chromedriver
  ```
- `framework/browser_engine.py` 的 Linux 分支已加 `--headless --no-sandbox`，用 `executable_path` 指向该驱动。
- **桌面端用例（pywinauto / Teacher.exe）在 Linux 上跑不了**，只能留在本机 Windows 执行——这是范围约束。

### 第 9 步：定义 gunicorn 启动方式（写进 service）
- 启动命令即：
  ```
  /opt/yikeui/venv/bin/gunicorn yikeui.wsgi:application --bind 0.0.0.0:8000 --workers 2 --timeout 120
  ```
- `yikeui.wsgi:application` 是 WSGI 入口（Django 的标准接口，gunicorn 通过它调用你的应用）。

### 第 10 步：写 systemd service 文件并启用
- 文件：`/etc/systemd/system/yikeui.service`（**服务器当前真实内容**）：
  ```ini
  [Unit]
  Description=yikeUIAuto Web Platform
  After=network.target mysqld.service

  [Service]
  Type=simple
  User=root
  WorkingDirectory=/opt/yikeui/web
  Environment=PATH=/opt/yikeui/venv/bin:/usr/local/bin:/usr/bin:/bin
  Environment=YIKEUI_DB_HOST=127.0.0.1
  Environment=YIKEUI_DB_USER=root
  Environment=YIKEUI_DB_PASSWORD=123456
  Environment=YIKEUI_DB_NAME=yikeui
  Environment=YIKEUI_DB_PORT=3306
  Environment=YIKEUI_ALLOWED_HOSTS=127.0.0.1,localhost,172.20.5.14,yikeui.ekwing.com
  Environment=YIKEUI_DEBUG=0
  Environment=YIKEUI_SECRET_KEY=yikeui-internal-9f3a2b7c...（强随机串）
  ExecStart=/opt/yikeui/venv/bin/gunicorn yikeui.wsgi:application --bind 0.0.0.0:8000 --workers 2 --timeout 120
  Restart=on-failure

  [Install]
  WantedBy=multi-user.target
  ```
- 启用：
  ```
  systemctl daemon-reload          # 让 systemd 重新读取改动
  systemctl enable --now yikeui    # 开机自启 + 立即启动
  ```

### 第 11 步：配置 nginx 反向代理 + 静态文件
- 文件：`/etc/nginx/conf.d/yikeui.conf`（**服务器当前真实内容**）：
  ```nginx
  server {
      listen 80 default_server;
      listen [::]:80 default_server;
      server_name yikeui.ekwing.com 172.20.5.14;

      client_max_body_size 50m;
      gzip on; gzip_min_length 1024;
      gzip_types text/plain text/css application/json application/javascript text/xml application/xml image/svg+xml;

      # 静态文件（CSS/JS/图片）由 nginx 直接发，不走 Django，省资源
      location /static/ {
          alias /opt/yikeui/web/staticfiles/;
          expires 1y;
          add_header Cache-Control "public, immutable";
          try_files $uri =404;
      }

      # 其余所有请求转发给 gunicorn
      location / {
          proxy_pass http://127.0.0.1:8000;
          proxy_set_header Host $host;
          proxy_set_header X-Real-IP $remote_addr;
          proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
          proxy_set_header X-Forwarded-Proto $scheme;
      }
  }
  ```
- 启用：
  ```
  nginx -t            # 语法检查
  systemctl enable --now nginx
  ```
- **nginx 的作用**：对外只暴露 80 端口；把 `/static/` 直接当文件发（高效）；把动态请求反代给后端 gunicorn；顺便做 gzip 压缩。
- 注意：生产 `DEBUG=0` 后 Django 不再自己管静态文件，所以必须 `manage.py collectstatic` 把文件收进 `staticfiles/`，再交给 nginx（本项目已通过 whitenoise / nginx 托管）。

### 第 12 步：收尾验证
- 进程：`systemctl is-active yikeui` → `active`；`systemctl is-active nginx mysqld` → 都 active。
- 页面：`curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8000/` → `200`。
- 功能：Web 登录 → 用例列表 → 选一个 Web 用例执行 → 详情页看到执行记录与报告。
- 环境确认：
  ```
  tr '\0' '\n' < /proc/$(pgrep -f "yikeui.wsgi:application"|head -1)/environ | grep YIKEUI_ALLOWED_HOSTS
  ```
  能看到 `172.20.5.14` 即说明 service 注入成功（没丢环境变量）。

---

## 3. 各组件职责速查表

| 组件 | 是什么 | 在本项目干啥 | 怎么管 |
|---|---|---|---|
| **systemd** | Linux 进程管家（init） | 编排开机顺序、自启、崩溃重启 | `systemctl start/restart/status` |
| **nginx** | 高性能 Web 服务器 / 反向代理 | 对外 80 端口、发静态文件、反代到 8000 | `systemctl restart nginx` |
| **gunicorn** | WSGI 应用服务器 | 把 HTTP 请求交给 Django（master+2 worker） | 由 yikeui.service 拉起 |
| **Django 4.2** | Python Web 框架 | 你的平台业务逻辑（用例/执行/报告） | 随 gunicorn 运行 |
| **MySQL 8.0** | 关系型数据库 | 存用例、步骤、数据、执行记录、用户 | `systemctl restart mysqld` |
| **Python venv** | 隔离的 Python 环境 | 提供 Django/gunicorn/selenium 等依赖 | `/opt/yikeui/venv/bin/python` |
| **Chromium + chromedriver** | 无界面浏览器 + 驱动 | 真正打开网页执行 Web 用例 | 系统包 `yum install` |
| **swap 2G** | 交换分区 | 补足 2G 内存，防 OOM | `/swapfile`，写进 fstab |

---

## 4. 常见坑（都是真踩过的）

1. **DisallowedHost 页面打不开**：用 `setsid nohup ... &` 手工起 gunicorn，丢了 service 注入的 `YIKEUI_ALLOWED_HOSTS`。
   → 一律 `systemctl restart yikeui`。
2. **残留旧 worker**：`kill -HUP` 平滑重载后，旧 worker 可能存活很久（实测残留 22h），部分请求仍走旧代码。
   → 查证：`ps -eo pid,etime,cmd | grep "gunicorn yikeui.wsgi"`，所有 worker 的 `etime` 应一致；参差不齐就是有残留，
   先 `kill -9` 老的再 `systemctl restart yikeui`。
3. **内存不足/OOM**：1c2g 跑 Chrome 很容易爆。→ 已加 2G swap，且 gunicorn 只开 2 个 worker。
4. **改 templates/static 不生效**：`--noreload` 下 Django 缓存模板，必须重启 `systemctl restart yikeui`。
5. **静态文件 404（生产）**：`DEBUG=0` 后 Django 不管静态文件，记得 `collectstatic` 并让 nginx 的 `/static/` 指向 `staticfiles/`。

---

## 5. 日常运维速查

```bash
# 启停 / 重启 / 状态（Web 服务）
systemctl restart yikeui
systemctl status  yikeui
journalctl -u yikeui -n 100 --no-pager     # 看 Web 服务日志

# 数据库
systemctl restart mysqld
mysql -uroot -p123456 yikeui               # 连库

# 反向代理
systemctl restart nginx
nginx -t                                  # 改完配置先检查语法

# 改完代码后让生产生效（三步）
cd /opt/yikeui/web
/opt/yikeui/venv/bin/python manage.py migrate      # 若有新迁移
/opt/yikeui/venv/bin/python manage.py collectstatic --noinput   # 若改了静态资源
systemctl restart yikeui

# 健康检查
curl -s -o /dev/null -w "HTTP %{http_code}\n" http://127.0.0.1:8000/
```
